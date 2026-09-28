"""The research adapter swaps Supertrend without changing other indicator inputs."""

from datetime import date, timedelta

from src.application.positional_trend import feature_series
from tools.strategy4_supertrend_comparison import pandas_ta_features


def _bars():
    bars = [{"as_of_date": (date(2022, 1, 1) + timedelta(days=i)).isoformat(),
             "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "volume": 2_000_000} for i in range(125)]
    bars[105].update(open=110.0, high=111.0, low=109.0, close=110.0)
    return bars


def test_supertrend_swap_preserves_other_indicators_and_prefix_invariance():
    bars = _bars()
    sessions = [row["as_of_date"] for row in bars]
    base = feature_series(bars, sessions, "A")
    alternate = pandas_ta_features(bars, sessions, "A")
    for before, after in zip(base, alternate, strict=True):
        for key in ("adx14", "atr10", "upper50", "lower20", "adv30", "first_cross"):
            assert before[key] == after[key]
    prefix = pandas_ta_features(bars[:110], sessions[:110], "A")
    assert prefix == [row for row in alternate if row["signal_date"] <= sessions[109]]


def test_absent_stock_day_preserves_pandas_ta_history():
    bars = _bars()
    sessions = [row["as_of_date"] for row in bars]
    without_day = bars[:100] + bars[101:]
    rows = pandas_ta_features(without_day, sessions, "A")
    compact_calendar = [row["as_of_date"] for row in without_day]
    assert rows == pandas_ta_features(without_day, compact_calendar, "A")
    assert any(row["first_cross"] for row in rows)
