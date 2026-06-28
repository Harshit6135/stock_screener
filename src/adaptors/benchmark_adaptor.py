"""
Benchmark Adaptor — Nifty 500 daily close prices via yfinance.
Used by Strategy 2 Mansfield RS calculation.

The adaptor caches results in memory per (start_date, end_date) pair
so repeated calls within the same process incur no network cost.
"""

import pandas as pd

from config import setup_logger

logger = setup_logger(name="BenchmarkAdaptor")

_BENCHMARK_TICKER = "^CNX500"


class BenchmarkAdaptor:
    """Fetches and caches Nifty 500 index close prices from yfinance."""

    _cache: dict = {}

    @classmethod
    def get_nifty500_close(cls, start_date: str, end_date: str) -> pd.Series:
        """Return daily close series for Nifty 500 in the given date range.

        Args:
            start_date: ISO date string, e.g. "2018-01-01"
            end_date:   ISO date string, e.g. "2024-12-31"

        Returns:
            pd.Series indexed by date (DatetimeIndex) with daily close prices.
            Returns an empty Series if download fails.
        """
        key = (start_date, end_date)
        if key in cls._cache:
            return cls._cache[key]

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
                logger.warning(
                    f"yfinance returned empty data for {_BENCHMARK_TICKER} "
                    f"({start_date} → {end_date})"
                )
                return pd.Series(dtype=float)

            series = df["Close"].squeeze()
            series.index = pd.to_datetime(series.index)
            cls._cache[key] = series
            logger.info(
                f"Loaded {len(series)} Nifty 500 rows "
                f"({start_date} → {end_date})"
            )
            return series

        except Exception as e:
            logger.error(f"Failed to fetch benchmark data: {e}")
            return pd.Series(dtype=float)

    @classmethod
    def clear_cache(cls) -> None:
        """Evict all cached benchmark data (useful in long-running processes)."""
        cls._cache.clear()
