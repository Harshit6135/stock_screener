"""
Percentile Service
==================

Cross-sectionally ranks every active stock by each factor on every Friday
and persists the results to the ``percentile`` table.

What it does
------------
For a given target date (defaults to the latest date with market data):

1. Fetch all closing prices and indicator rows for that date.
2. Pass the data to ``FactorsService.calculate_all_factors()`` which applies
   non-linear transformations (Goldilocks, RSI regime, %B scoring, etc.)
   to produce raw factor scores per stock.
3. Cross-sectionally percentile-rank each factor score across the entire
   stock universe on that date (``percentile_rank(series)`` → 0-100).
4. Write the resulting percentile rows to the ``percentile`` table tagged
   with ``strategy_id`` so multiple strategies can coexist.

Two strategy variants
---------------------
The service supports two strategies, selected via ``strategy_id``:

- ``"strategy1"`` (default) — uses ``StrategyParameters`` and ``FactorsService``
- ``"strategy2"`` — uses ``Strategy2Parameters`` and ``FactorsServiceV2``

Both write to the same ``percentile`` table; the ``strategy_id`` column
distinguishes them for downstream ranking queries.

BUG notes
---------
- BUG-04 fixed: ``metrics_df`` is no longer blanket-filled with 0 before
  factor scoring. ``factors_service`` applies per-column correct defaults.
- BUG-23 fixed: ``generate_percentile(target_date=None)`` now always passes
  a concrete date to the repo; ``None`` would previously cause ambiguous
  DB queries.
"""


pd.set_option("future.no_silent_downcasting", True)

from datetime import date, datetime

from config import Strategy2Parameters, StrategyParameters
from config import setup_logger
from repositories import IndicatorsRepository, MarketDataRepository, PercentileRepository
from services.factors_service import FactorsService, FactorsServiceV2
from utils import percentile_rank

percentile_repo = PercentileRepository()
indicators_repo = IndicatorsRepository()
marketdata_repo = MarketDataRepository()
logger = setup_logger(name="Orchestrator")


class PercentileService:
    """
    Multi-Factor Momentum Scorecard for Indian Markets.

    Supports Strategy 1 (default) and Strategy 2 via strategy_id parameter.
    All repo calls are tagged with the strategy_id so rows coexist in the
    same table without collision.
    """

    def __init__(self, strategy_id: str = "strategy1"):
        self.strategy_id = strategy_id
        if strategy_id == "strategy2":
            self.strategy_params = Strategy2Parameters()
            self.factors_service = FactorsServiceV2()
        else:
            self.strategy_params = StrategyParameters()
            self.factors_service = FactorsService()

    def _calculate_percentiles(self, metrics_df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply factor scoring and then cross-sectional percentile ranking.

        Steps
        -----
        1. Call ``factors_service.calculate_all_factors(metrics_df)`` to
           compute raw factor columns (``factor_trend``, ``factor_momentum``,
           ``factor_efficiency``, ``factor_volume``, ``factor_structure``).
        2. For each factor column, apply ``percentile_rank()`` to produce a
           0-100 percentile score across all stocks on this date.
        3. Drop rows where ``tradingsymbol`` is null (data quality guard).

        Parameters
        ----------
        metrics_df : pd.DataFrame
            DataFrame with one row per stock, indicator columns present.

        Returns
        -------
        pd.DataFrame
            Same DataFrame with added ``*_percentile`` columns (0-100).
        """
        metrics_df = self.factors_service.calculate_all_factors(metrics_df)

        factor_cols = {
            "factor_trend": "trend_percentile",
            "factor_momentum": "momentum_percentile",
            "factor_efficiency": "efficiency_percentile",
            "factor_volume": "volume_percentile",
            "factor_structure": "structure_percentile",
        }
        for col, percentile_name in factor_cols.items():
            if col in metrics_df.columns:
                metrics_df[percentile_name] = percentile_rank(metrics_df[col])

        return metrics_df

    def _validate_count(self, indicators_count: int, date, last_percentile_date) -> None:
        """Compare indicator row count vs last percentile date's count."""
        last_percentile_rows = percentile_repo.get_percentiles_by_date(
            last_percentile_date, strategy_id=self.strategy_id
        )
        last_count = len(last_percentile_rows)
        if last_count == 0:
            return

        diff_pct = abs(indicators_count - last_count) / last_count
        logger.info(
            f"Count validation: indicators={indicators_count}, "
            f"last_percentile({last_percentile_date})={last_count}, "
            f"diff={diff_pct:.1%}"
        )
        if diff_pct > 0.05:
            raise ValueError(
                f"Count validation failed for {date}: "
                f"indicators={indicators_count}, "
                f"last_percentile={last_count}, "
                f"diff={diff_pct:.1%} (threshold=5%)"
            )

    def generate_percentile(self, target_date=None):
        """
        Orchestrates the percentile calculation process:
        1. Fetch latest price and indicator data
        2. Construct DataFrames
        3. Calculate percentiles using the selected strategy's factor service
        4. Save to percentile table tagged with strategy_id
        """
        logger.info(f"Starting Percentile Calculation [{self.strategy_id}]...")
        # Resolve target_date early so it is never None further down
        if not target_date:
            target_date = marketdata_repo.get_max_date_from_table()
        date_range = {"start_date": target_date, "end_date": target_date}

        price_data_list = self.query_to_dict(marketdata_repo.get_prices_for_all_stocks(date_range))
        indicators_data_list = self.query_to_dict(
            indicators_repo.get_indicators_for_all_stocks(date_range)
        )

        stocks_df = pd.DataFrame(price_data_list)
        metrics_df = pd.DataFrame(indicators_data_list)
        # BUG-04 fix: do NOT blanket-fill NaN here; factors_service applies
        # per-column correct defaults (e.g. fillna(1) for atr_spike).  A
        # blanket fillna(0) biases factor scores for indicators that are
        # legitimately NaN due to insufficient history.
        metrics_df = metrics_df.infer_objects(copy=False)

        if len(stocks_df) == 0 or len(metrics_df) == 0:
            logger.info("No data found for date: {}".format(target_date))
            return None

        stocks_df["avg_turnover"] = stocks_df["close"] * stocks_df["volume"] / 10000000
        metrics_df = pd.merge(metrics_df, stocks_df, on="tradingsymbol", how="inner")

        # BUG-23 fix: percentile_date is now always a concrete date value
        percentile_date = target_date
        metrics_df["percentile_date"] = percentile_date
        metrics_df["strategy_id"] = self.strategy_id
        metrics_df = self._calculate_percentiles(metrics_df)

        req_cols = [
            "tradingsymbol",
            "percentile_date",
            "strategy_id",
            "close",
            "factor_trend",
            "trend_percentile",
            "factor_momentum",
            "momentum_percentile",
            "factor_efficiency",
            "efficiency_percentile",
            "factor_volume",
            "volume_percentile",
            "factor_structure",
            "structure_percentile",
        ]
        percentile_df = metrics_df[[c for c in req_cols if c in metrics_df.columns]]

        logger.info("Saving percentiles to database...")
        response = percentile_repo.delete(percentile_date, strategy_id=self.strategy_id)
        if response:
            percentile_repo.bulk_insert(percentile_df.to_dict("records"))
        else:
            logger.error(
                "Failed to delete existing percentiles for today, cannot save new percentiles"
            )
            return None
        logger.info(
            f"Saved {len(percentile_df)} percentiles for {percentile_date} [{self.strategy_id}]"
        )
        return True

    def backfill_percentiles(self):
        """
        Generates percentiles for all dates since the last updated date.
        If no percentiles exist, starts from the earliest available market data date.
        """
        last_percentile_date = percentile_repo.get_max_percentile_date(
            strategy_id=self.strategy_id
        )

        if last_percentile_date:
            start_date = last_percentile_date
        else:
            start_date = marketdata_repo.get_min_date_from_table()

        if isinstance(start_date, (datetime, date)):
            start_date = pd.Timestamp(start_date)

        max_date = marketdata_repo.get_max_date_from_table()

        if isinstance(max_date, (datetime, date)):
            max_date = pd.Timestamp(max_date)

        while start_date <= max_date:
            self.generate_percentile(start_date)
            start_date += pd.Timedelta(days=1)

    @staticmethod
    def query_to_dict(results):
        return [{c.name: getattr(row, c.name) for c in row.__table__.columns} for row in results]
