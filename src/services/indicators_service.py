"""
Indicators Service
==================

Incrementally calculates technical indicators for all active instruments
and upserts them into the ``indicators`` table.

Two operating modes
-------------------
Default run -- ``calculate_indicators()``
    Processes every instrument in the ``instruments`` table.
    For each symbol the run is incremental: it loads market data only from
    the last recorded indicator date onwards so each call is O(new bars),
    not O(all bars).

Patch run -- ``patch_indicators()``
    Recalculates only the columns listed in ``patch_cols`` for all
    historical dates, starting from the earliest row in ``market_data``.
    Use this when adding a **new** indicator to avoid full recalculation
    of all existing indicators.

Indicator pipeline per symbol
------------------------------
1. ``apply_study(df, last_ind_date)``
   Runs the EMA pandas_ta study first (long lookback, needs full history).
   Then truncates to avoid recalculating unchanged rows.
   Then runs momentum + derived pandas_ta studies on the truncated window.

2. ``_calculate_derived_indicators(df)``
   Adds custom-calculated columns that cannot be expressed as pandas_ta
   studies: price/volume correlation, %B position, EMA slopes, ATR spike,
   distance-from-EMA, risk-adjusted return, RVOL, momentum_3m/6m.

3. Build output rows aligned to ``ALL_INDICATOR_NAMES``.
   Unrecognised columns are dropped so the schema stays consistent.

Configuration
-------------
All study definitions live in ``config/indicators_config.py``:
- ``ema_strategy``      — long EMA calculations (requires full history)
- ``momentum_strategy`` — RSI, PPO, ATR, ROC, Bollinger (shorter lookback)
- ``derived_strategy``  — additional derived indicators via pandas_ta
- ``INDICATOR_REGISTRY`` — column-name to data-type mapping for output
- ``additional_parameters`` — tuning knobs (lookback windows, thresholds)
"""

import time as _time
from typing import List, Optional

import numpy as np
import pandas as pd

pd.set_option("future.no_silent_downcasting", True)

from datetime import timedelta

from adaptors import BenchmarkAdaptor
from config import (
    ALL_INDICATOR_NAMES,
    INDICATOR_REGISTRY,
    STUDY_MAP,
    DerivedIndicator,
    PandasTaIndicator,
    additional_parameters,
    derived_strategy,
    ema_strategy,
    momentum_strategy,
    setup_logger,
)
from repositories import IndicatorsRepository, InstrumentsRepository, MarketDataRepository

instr_repo = InstrumentsRepository()
indicators_repo = IndicatorsRepository()
marketdata_repo = MarketDataRepository()
logger = setup_logger(name="Orchestrator")


class IndicatorsService:
    """
    Technical indicator calculation service.

    Uses module-level repository singletons (``instr_repo``,
    ``indicators_repo``, ``marketdata_repo``) so that all calculations
    within one run share the same DB session.

    All indicator computation is delegated to static helper methods and
    ``pandas_ta`` studies.  The main public methods are:

    - ``calculate_indicators()`` — full incremental run for all symbols
    - ``patch_indicators(patch_cols)`` — backfill specific columns only
    """

    # =========================================================================
    # Static helper calculations (unchanged from original)
    # =========================================================================

    @staticmethod
    def calculate_volume_price_correlation(
        df_close: pd.Series, df_volume: pd.Series, lookback: int = 10
    ) -> pd.Series:
        """
        Rolling Pearson correlation between price returns and volume.

        A high positive value means price increases are accompanied by rising
        volume (trend confirmation). A negative value indicates divergence.

        Parameters
        ----------
        df_close : pd.Series
            Closing prices indexed by date.
        df_volume : pd.Series
            Daily volume indexed by date.
        lookback : int
            Rolling window length in bars (default 10).

        Returns
        -------
        pd.Series
            Rolling correlation values in [-1, 1].
        """
        price_change = df_close.pct_change()
        return price_change.rolling(lookback).corr(df_volume)

    @staticmethod
    def calculate_percent_b(
        df_close: pd.Series, df_upper: pd.Series, df_lower: pd.Series
    ) -> pd.Series:
        """
        Compute Bollinger Band %B: position of price within the band.

        Formula: %B = (Close - Lower) / (Upper - Lower)

        - 0.0 = at lower band (oversold territory)
        - 0.5 = at midline (20-day SMA)
        - 1.0 = at upper band (overbought territory)
        - > 1.0 or < 0.0 = price is outside the bands

        Returns
        -------
        pd.Series
            %B values; NaN where Upper == Lower (degenerate case).
        """
        return (df_close - df_lower) / (df_upper - df_lower)

    @staticmethod
    def calculate_ema_slope(ema: pd.Series, lookback: int = 5) -> pd.Series:
        """
        Fractional rate-of-change of EMA over ``lookback`` bars.

        Formula: slope = (EMA_t - EMA_{t-lookback}) / EMA_{t-lookback}

        A positive slope confirms the trend direction; magnitude reflects
        trend momentum.  Not annualised — raw fractional change.

        Parameters
        ----------
        ema : pd.Series
            EMA values (e.g. EMA_50).
        lookback : int
            Number of bars to look back (default 5 ≈ one trading week).
        """
        slope = (ema - ema.shift(lookback)) / ema.shift(lookback)
        return slope

    @staticmethod
    def calculate_distance_from_ema(df_close: pd.Series, ema: pd.Series) -> pd.Series:
        """
        Fractional distance of closing price above (or below) EMA.

        Formula: (Close - EMA) / EMA

        Positive = price is above EMA (bullish).
        Negative = price is below EMA (bearish).

        Used for Goldilocks scoring: rewards stocks that are 10-35% above
        EMA200 (in the "sweet spot"), penalises over-extended moves.
        """
        return (df_close - ema) / ema

    @staticmethod
    def calculate_atr_spike(atr: pd.Series, lookback: int = 20) -> pd.Series:
        """
        ATR spike ratio: current ATR relative to its recent rolling average.

        Formula: atr_spike = ATR / rolling_mean(ATR, lookback)

        - 1.0 = normal volatility
        - > 1.5 = significantly elevated volatility (soft penalty applied)
        - < 1.0 = contraction (low volatility, possible breakout setup)

        Parameters
        ----------
        lookback : int
            Rolling window for baseline ATR (default 20 bars ≈ one month).
        """
        atr_avg = atr.rolling(window=lookback).mean()
        return atr / atr_avg

    @staticmethod
    def apply_study(df: pd.DataFrame, last_ind_date) -> pd.DataFrame:
        """
        Run all pandas_ta studies on a symbol's OHLCV DataFrame.

        Strategy
        --------
        1. Run ``ema_strategy`` over the full DataFrame (EMA 50/200 need
           200+ bars of history to avoid NaN at the start).
        2. Truncate the DataFrame to ``last_ind_date - truncate_days`` so
           that the heavier ``momentum_strategy`` only runs on recent bars.
        3. Run ``momentum_strategy`` (RSI, PPO, ATR, ROC, Bollinger).
        4. Run ``derived_strategy`` (any additional pandas_ta columns).

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV DataFrame indexed by date.
        last_ind_date : pd.Timestamp
            Last indicator date for this symbol; used for truncation.

        Returns
        -------
        pd.DataFrame
            DataFrame with all indicator columns appended.
        """
        df.ta.study(ema_strategy)
        date_truncate = last_ind_date - timedelta(days=additional_parameters["truncate_days"])
        df = df[df.index >= date_truncate]
        df.ta.study(momentum_strategy)
        df.ta.study(derived_strategy)
        return df

    def _calculate_derived_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute custom indicator columns not available as pandas_ta studies.

        Columns added
        -------------
        price_vol_correlation : float
            Rolling Pearson correlation of price returns vs volume (10 bars).
        percent_b : float
            Bollinger Band %B position (0 = lower band, 1 = upper band).
        ema_50_slope : float
            Rate-of-change of EMA 50 over 5 bars (trend momentum proxy).
        distance_from_ema_200 : float
            (Close - EMA200) / EMA200 — used for Goldilocks scoring.
        distance_from_ema_50 : float
            (Close - EMA50) / EMA50 — supplementary trend position.
        risk_adjusted_return : float
            ROC_20 / (ATRr_14 / Close) — return per unit of normalised risk.
        rvol : float
            Volume / 20-day volume SMA — relative volume.
        atr_spike : float
            ATR / rolling mean ATR (see ``calculate_atr_spike``).
        momentum_3m : float
            (Close[t-5] / Close[t-65]) - 1  (≈ 3-month momentum, skip-1-week).
        momentum_6m : float
            (Close[t-5] / Close[t-130]) - 1 (≈ 6-month momentum, skip-1-week).

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame after ``apply_study()`` has been run; must contain
            EMA columns, Bollinger Band columns, ATRr_14, VOL_SMA_20.

        Returns
        -------
        pd.DataFrame
            Same DataFrame with the derived columns appended in-place.
        """
        df["price_vol_correlation"] = self.calculate_volume_price_correlation(
            df["close"], df["volume"], additional_parameters["vol_price_lookback"]
        )
        df["percent_b"] = self.calculate_percent_b(
            df["close"], df["BBU_20_2.0_2.0"], df["BBL_20_2.0_2.0"]
        )
        df["ema_50_slope"] = self.calculate_ema_slope(
            df["EMA_50"], additional_parameters["ema_slope_lookback"]
        )
        df["distance_from_ema_200"] = self.calculate_distance_from_ema(df["close"], df["EMA_200"])
        df["distance_from_ema_50"] = self.calculate_distance_from_ema(df["close"], df["EMA_50"])
        df["risk_adjusted_return"] = df["ROC_20"] / (df["ATRr_14"] / df["close"])
        df["rvol"] = df["volume"] / df["VOL_SMA_20"]
        df["atr_spike"] = self.calculate_atr_spike(df["ATRr_14"])

        df["momentum_3m"] = (df["close"].shift(5) / df["close"].shift(65)) - 1
        df["momentum_6m"] = (df["close"].shift(5) / df["close"].shift(130)) - 1
        return df

    # =========================================================================
    # Default full incremental run (unchanged behaviour)
    # =========================================================================

    def calculate_indicators(self):
        """Full incremental indicator run for all symbols.

        Identical behaviour to the pre-registry version — processes all
        indicators, incremental by last indicator date per symbol.
        """
        t_total = _time.time()
        logger.info("Starting to update Indicators (API Mode)...")

        logger.info("Fetching Instruments from DB...")
        instruments = instr_repo.get_all_instruments()
        total = len(instruments)

        logger.info(f"Calculating Indicators for {total} Instruments...")
        yesterday = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)

        processed = 0
        skipped = 0
        for i, instr in enumerate(instruments):
            tradingsymbol = instr.tradingsymbol
            instr_token = instr.instrument_token
            exchange = instr.exchange
            log_symb = f"{tradingsymbol} ({instr_token})"
            if (i + 1) % 50 == 0 or i == 0:
                logger.info(f"Progress: {i+1}/{total} ({processed} processed, {skipped} skipped)")
            logger.info(f"Processing {i+1}/{total} {log_symb}...")

            last_data_date = marketdata_repo.get_latest_date_by_symbol(tradingsymbol)
            if last_data_date:
                last_data_date = pd.to_datetime(last_data_date.date)
            else:
                logger.error(f"No market data found for {log_symb}")
                skipped += 1
                continue

            last_ind_date = indicators_repo.get_latest_date_by_symbol(tradingsymbol)
            if last_ind_date:
                last_ind_date = pd.to_datetime(last_ind_date.date)
                if last_ind_date == last_data_date:
                    logger.info(f"Indicators up to date for {log_symb}.")
                    skipped += 1
                    continue
                calc_start_date = last_ind_date - timedelta(
                    days=additional_parameters["ema_200_lookback"]
                )
            else:
                calc_start_date = pd.to_datetime("2000-01-01")
                last_ind_date = calc_start_date

            query_payload = {
                "tradingsymbol": tradingsymbol,
                "start_date": str(calc_start_date.date()),
                "end_date": str(yesterday.date()),
            }
            md_output = marketdata_repo.query(query_payload)
            md_list = [
                {column.name: getattr(row, column.name) for column in row.__table__.columns}
                for row in md_output
            ]

            if len(md_list) < 200:
                logger.error("Less than 200 days data")
                skipped += 1
                continue

            df_for_ind = pd.DataFrame(md_list)
            df_for_ind["date"] = pd.to_datetime(df_for_ind["date"])
            df_for_ind.set_index("date", inplace=True)
            df_for_ind.sort_index(inplace=True)

            logger.info("Calculating indicators...")
            df_for_ind["avg_turnover"] = df_for_ind["close"] * df_for_ind["volume"]
            ind_df = self.apply_study(df_for_ind, last_ind_date)
            try:
                ind_df = self._calculate_derived_indicators(ind_df)
            except Exception as e:
                logger.error(f"Error calculating derived indicators for {log_symb}: {str(e)}")
                skipped += 1
                continue
            ind_df.columns = ind_df.columns.str.lower().str.replace(".0", "", regex=False)
            ind_df = ind_df.drop(
                columns=["open", "high", "low", "close", "volume"], errors="ignore"
            )
            ind_df.reset_index(inplace=True)
            ind_df["tradingsymbol"] = tradingsymbol
            ind_df["exchange"] = exchange

            if last_ind_date:
                next_day = last_ind_date + timedelta(days=1)
                ind_df_filtered = ind_df[ind_df["date"] >= next_day].copy()
            else:
                ind_df_filtered = ind_df.copy()
            if ind_df_filtered.empty:
                logger.info(f"No new data to calculate indicators for {log_symb}")
                skipped += 1
                continue

            ind_df_filtered["date"] = ind_df_filtered["date"].dt.date
            ind_json = ind_df_filtered.to_dict(orient="records")
            indicators_repo.bulk_insert(ind_json)
            processed += 1

        elapsed = _time.time() - t_total
        logger.info(
            f"Indicators updated: {processed} processed, {skipped} skipped, "
            f"{total} total in {elapsed:.1f}s"
        )

    # =========================================================================
    # Patch run — targeted column backfill
    # =========================================================================

    def patch_indicators(
        self,
        indicator_names: Optional[List[str]] = None,
    ) -> dict:
        """Compute and upsert specific indicator columns for all symbols.

        Backfills from the earliest available date in market_data for each
        symbol. Only the requested columns are written — all other columns
        in existing rows are left untouched.

        Args:
            indicator_names: List of registry keys to compute.
                             Defaults to ALL_INDICATOR_NAMES (everything).

        Returns:
            Dict with message and processed/skipped counts.
        """
        if indicator_names is None:
            indicator_names = ALL_INDICATOR_NAMES

        # Validate names
        unknown = [n for n in indicator_names if n not in INDICATOR_REGISTRY]
        if unknown:
            raise ValueError(f"Unknown indicator names: {unknown}. Check INDICATOR_REGISTRY.")

        # Partition into pandas_ta vs derived
        ta_defs: dict = {}
        derived_defs: dict = {}
        for name in indicator_names:
            defn = INDICATOR_REGISTRY[name]
            if isinstance(defn, PandasTaIndicator):
                ta_defs[name] = defn
            elif isinstance(defn, DerivedIndicator):
                derived_defs[name] = defn

        # Group pandas_ta indicators by study_name (run each study only once)
        study_groups: dict = {}
        for name, defn in ta_defs.items():
            study_groups.setdefault(defn.study_name, []).append((name, defn))

        # Load benchmark once if any derived indicator needs it
        benchmark = pd.Series(dtype=float)
        needs_bench = any(v.needs_benchmark for v in derived_defs.values())
        if needs_bench:
            logger.info("Fetching Nifty 500 benchmark data for Mansfield RS...")
            min_date = marketdata_repo.get_min_date_from_table()
            yesterday = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)
            benchmark = BenchmarkAdaptor.get_nifty500_close(
                str(min_date), str(yesterday.date())
            )

        instruments = instr_repo.get_all_instruments()
        total = len(instruments)
        processed = skipped = 0
        t_total = _time.time()

        logger.info(
            f"Patching {len(indicator_names)} indicator(s) for {total} symbols: "
            f"{indicator_names}"
        )

        for i, instr in enumerate(instruments):
            tradingsymbol = instr.tradingsymbol
            exchange = instr.exchange
            if (i + 1) % 50 == 0 or i == 0:
                logger.info(f"Patch progress: {i+1}/{total}")

            # Fetch full OHLCV history (from earliest available)
            md_output = marketdata_repo.query({
                "tradingsymbol": tradingsymbol,
                "start_date": "2000-01-01",
                "end_date": str((pd.Timestamp.now() - pd.Timedelta(days=1)).date()),
            })
            if not md_output:
                skipped += 1
                continue

            md_list = [
                {col.name: getattr(row, col.name) for col in row.__table__.columns}
                for row in md_output
            ]
            if len(md_list) < 252:
                logger.warning(f"Skipping {tradingsymbol}: fewer than 252 rows")
                skipped += 1
                continue

            df = pd.DataFrame(md_list)
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            df.sort_index(inplace=True)
            df["avg_turnover"] = df["close"] * df["volume"]

            result_cols: dict = {}

            # Run pandas_ta studies (grouped — each study runs once)
            for study_name, pairs in study_groups.items():
                study_obj = STUDY_MAP.get(study_name)
                if study_obj is None:
                    logger.warning(f"Study '{study_name}' not in STUDY_MAP, skipping")
                    continue
                try:
                    df.ta.study(study_obj)
                    for ind_name, defn in pairs:
                        raw_col = defn.output_col
                        # Normalise column name to lowercase (matching existing convention)
                        norm_col = raw_col.lower().replace(".0", "")
                        if raw_col in df.columns:
                            result_cols[ind_name] = df[raw_col]
                        elif norm_col in df.columns:
                            result_cols[ind_name] = df[norm_col]
                        else:
                            logger.warning(
                                f"Column '{raw_col}' not found for {tradingsymbol} "
                                f"after running study '{study_name}'"
                            )
                except Exception as e:
                    logger.error(
                        f"Error running study '{study_name}' for {tradingsymbol}: {e}"
                    )

            # Run derived indicators
            # Lowercase all df columns first so deps match registry names
            df.columns = [c.lower().replace(".0", "") for c in df.columns]

            for ind_name, defn in derived_defs.items():
                try:
                    if defn.needs_benchmark:
                        series = defn.fn(df, benchmark=benchmark)
                    else:
                        series = defn.fn(df)
                    result_cols[ind_name] = series
                except Exception as e:
                    logger.error(
                        f"Error computing '{ind_name}' for {tradingsymbol}: {e}"
                    )

            if not result_cols:
                skipped += 1
                continue

            # Build patch records (one per date, PK + requested columns only)
            patch_df = pd.DataFrame(result_cols)
            patch_df.index = df.index  # DatetimeIndex
            patch_df = patch_df.replace([np.inf, -np.inf], np.nan)
            patch_df.reset_index(inplace=True)
            patch_df.rename(columns={"date": "date"}, inplace=True)
            patch_df["tradingsymbol"] = tradingsymbol
            patch_df["exchange"] = exchange
            patch_df["date"] = patch_df["date"].dt.date

            records = patch_df.dropna(subset=list(result_cols.keys()), how="all").to_dict(
                "records"
            )
            if records:
                indicators_repo.bulk_upsert_columns(records, list(result_cols.keys()))
            processed += 1

        elapsed = _time.time() - t_total
        msg = (
            f"Patched {len(indicator_names)} column(s) — "
            f"{processed} symbols processed, {skipped} skipped in {elapsed:.1f}s"
        )
        logger.info(msg)
        return {"message": msg, "processed": processed, "skipped": skipped}
