import math
from datetime import date, timedelta

from src.indicators.custom.momentum_quality import (
    momentum_quality_feature_series,
    momentum_quality_features,
)


def test_strategy1_bulk_series_matches_single_date_calculation():
    bars = []
    day = date(2025, 1, 1)
    while len(bars) < 270:
        if day.weekday() < 5:
            index = len(bars)
            close = 100 + index * 0.15 + math.sin(index / 6)
            bars.append(
                {
                    "as_of_date": day.isoformat(),
                    "open": close - 0.4,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 10_000_000 + index * 1000,
                }
            )
        day += timedelta(days=1)

    series = momentum_quality_feature_series(bars)

    assert len(series) == 71
    assert series[bars[-1]["as_of_date"]] == momentum_quality_features(bars)
