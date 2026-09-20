import math
from datetime import date, timedelta

from src.indicators.custom.relative_strength import (
    relative_strength_factors,
    relative_strength_feature_series,
    relative_strength_features,
)


def _histories():
    day = date(2025, 1, 1)
    bars = []
    benchmark = []
    while len(bars) < 270:
        if day.weekday() < 5:
            index = len(bars)
            close = 100 + index * 0.12 + math.sin(index / 5)
            opening = close - 0.3
            bars.append(
                {
                    "as_of_date": day.isoformat(),
                    "open": opening,
                    "high": close + 1,
                    "low": opening - 1,
                    "close": close,
                    "volume": 10_000_000 + index * 1000,
                }
            )
            benchmark.append({"as_of_date": day.isoformat(), "close": 1000 + index * 0.2})
        day += timedelta(days=1)
    return bars, benchmark


def test_strategy2_requires_current_benchmark_and_labels_legacy_proxies():
    bars, benchmark = _histories()
    assert relative_strength_features(bars, benchmark[:-1]) is None
    inputs = relative_strength_features(bars, benchmark)
    assert inputs is not None
    assert inputs["quality_z_score_placeholder"] == 0
    assert inputs["relative_volume_proxy"] == inputs["rvol"]
    factors = relative_strength_factors({"A": inputs, "B": dict(inputs)})
    assert len(factors) == 2
    assert all(0 <= value <= 100 for row in factors.values() for value in row.values())


def test_strategy2_hard_excludes_zero_volume_and_flat_ohlc():
    bars, benchmark = _histories()
    last = bars[-1]
    bars[-1] = {
        **last,
        "open": last["close"],
        "high": last["close"],
        "low": last["close"],
        "volume": 0,
    }
    inputs = relative_strength_features(bars, benchmark)
    assert inputs is not None
    assert inputs["penalty"] == 0
    assert {"zero_volume", "flat_ohlc"} <= set(inputs["penalty_reasons"])


def test_strategy2_bulk_series_matches_single_date_calculation():
    bars, benchmark = _histories()
    series = relative_strength_feature_series(bars, benchmark)

    assert series[bars[-1]["as_of_date"]] == relative_strength_features(bars, benchmark)
    assert bars[-2]["as_of_date"] in relative_strength_feature_series(bars, benchmark[:-1])
