"""
Benchmark Adaptor — Nifty 500 daily close prices.
Used by Strategy 2 Mansfield RS calculation.

Primary source : Kite Connect historical_data API (NSE:NIFTY 500, token 268041).
                 Uses kiteconnect directly (no KiteAdaptor overhead).
Fallback source: yfinance (^CNX500) — used only when Kite is unavailable.

Results are cached in-memory per (start_date, end_date) pair so repeated
calls within the same process incur no network cost.
"""

import os
from datetime import datetime
from typing import Optional

import pandas as pd

from config import KITE_CONFIG, setup_logger

logger = setup_logger(name="BenchmarkAdaptor")

# Kite instrument token for NSE Nifty 500 index (NSE:NIFTY 500, type=EQ, token=268041)
# Verified by querying kite.instruments('NSE') → tradingsymbol='NIFTY 500'
_NIFTY500_TOKEN = 268041
_BENCHMARK_TICKER = "^CNX500"  # yfinance fallback ticker

# Kite allows max 400 days per request for 'day' interval
_KITE_MAX_DAYS = 390


class BenchmarkAdaptor:
    """Fetches and caches Nifty 500 index close prices.

    Tries Kite Connect directly first (reliable, no rate limits).
    Falls back to yfinance if Kite is unavailable or returns no data.
    """

    _cache: dict = {}

    @classmethod
    def get_nifty500_close(cls, start_date: str, end_date: str) -> pd.Series:
        """Return daily close series for Nifty 500 in the given date range.

        Args:
            start_date: ISO date string, e.g. "2018-01-01"
            end_date:   ISO date string, e.g. "2024-12-31"

        Returns:
            pd.Series indexed by tz-naive DatetimeIndex with daily close prices.
            Returns an empty Series if all sources fail — callers must guard
            against empty benchmark before computing Mansfield RS.
        """
        key = (start_date, end_date)
        if key in cls._cache:
            return cls._cache[key]

        # ── Primary: Kite Connect ────────────────────────────────────────────
        series = cls._fetch_from_kite(start_date, end_date)

        # ── Fallback: yfinance ───────────────────────────────────────────────
        if series is None or series.empty:
            logger.warning("Kite fetch failed or empty — falling back to yfinance.")
            series = cls._fetch_from_yfinance(start_date, end_date)

        if series is not None and not series.empty:
            cls._cache[key] = series
            logger.info(
                f"Loaded {len(series)} Nifty 500 rows ({start_date} → {end_date})"
            )
            return series

        logger.error("All benchmark sources failed — returning empty Series.")
        return pd.Series(dtype=float)

    @classmethod
    def _get_kite(cls):
        """Return an initialised KiteConnect instance using the saved access token.

        Uses kiteconnect directly — avoids the full KiteAdaptor overhead and
        its browser-based login flow which can block in a server context.
        Returns None if no valid token is found.
        """
        try:
            from kiteconnect import KiteConnect

            api_key = KITE_CONFIG.get("api_key", "")
            if not api_key or api_key == "YOUR_API_KEY":
                logger.warning("Kite API key not configured.")
                return None

            # Resolve access_token.txt relative to project root
            project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            token_path = os.path.join(project_root, "access_token.txt")
            if not os.path.exists(token_path):
                logger.warning(f"access_token.txt not found at {token_path}")
                return None

            with open(token_path) as f:
                access_token = f.read().strip()
            if not access_token:
                logger.warning("access_token.txt is empty.")
                return None

            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(access_token)
            return kite

        except Exception as e:
            logger.error(f"Failed to init KiteConnect: {e}")
            return None

    @classmethod
    def _fetch_from_kite(cls, start_date: str, end_date: str) -> Optional[pd.Series]:
        """Fetch Nifty 500 close prices from Kite Connect historical data API.

        Kite allows max ~400 days per request for daily interval, so we
        chunk the date range automatically.
        """
        try:
            kite = cls._get_kite()
            if kite is None:
                return None

            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")

            all_records = []
            chunk_start = start_dt
            while chunk_start < end_dt:
                chunk_end = min(
                    end_dt,
                    chunk_start.replace(
                        year=chunk_start.year + (_KITE_MAX_DAYS // 365),
                        month=chunk_start.month,
                        day=chunk_start.day,
                    )
                    if (_KITE_MAX_DAYS // 365) > 0
                    else chunk_start,
                )
                # Simple approach: advance by _KITE_MAX_DAYS calendar days
                from datetime import timedelta
                chunk_end = min(end_dt, chunk_start + timedelta(days=_KITE_MAX_DAYS))

                recs = kite.historical_data(
                    instrument_token=_NIFTY500_TOKEN,
                    from_date=chunk_start,
                    to_date=chunk_end,
                    interval="day",
                    continuous=False,
                    oi=False,
                )
                if recs:
                    all_records.extend(recs)
                chunk_start = chunk_end + timedelta(days=1)

            if not all_records:
                logger.warning("Kite returned empty data for Nifty 500.")
                return None

            df = pd.DataFrame(all_records)
            df["date"] = pd.to_datetime(df["date"])
            # Strip timezone (Kite returns IST-offset datetimes) → tz-naive
            if df["date"].dt.tz is not None:
                df["date"] = df["date"].dt.tz_localize(None)
            df["date"] = df["date"].dt.normalize()
            df.set_index("date", inplace=True)
            series = df["close"].sort_index().drop_duplicates()
            logger.info(f"Kite: fetched {len(series)} Nifty 500 rows.")
            return series

        except Exception as e:
            logger.error(f"Kite benchmark fetch failed: {e}")
            return None

    @classmethod
    def _fetch_from_yfinance(cls, start_date: str, end_date: str) -> Optional[pd.Series]:
        """Fallback: fetch Nifty 500 close prices via yfinance."""
        try:
            import yfinance as yf

            df = yf.download(
                _BENCHMARK_TICKER,
                start=start_date,
                end=end_date,
                auto_adjust=True,
                progress=False,
            )
            if df.empty:
                logger.warning(f"yfinance returned empty data for {_BENCHMARK_TICKER}.")
                return None

            close_data = df["Close"]
            if isinstance(close_data, pd.DataFrame):
                close_data = close_data.iloc[:, 0]
            series = close_data.squeeze()
            series.index = pd.to_datetime(series.index).normalize()
            logger.info(f"yfinance: fetched {len(series)} Nifty 500 rows.")
            return series

        except Exception as e:
            logger.error(f"yfinance benchmark fetch failed: {e}")
            return None

    @classmethod
    def clear_cache(cls) -> None:
        """Evict all cached benchmark data (useful in long-running processes)."""
        cls._cache.clear()
