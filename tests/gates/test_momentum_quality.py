import math
from datetime import date, timedelta

import pytest

from src.domains.strategies.momentum_quality import _goldilocks, _rsi_regime
from src.gates.momentum_quality import momentum_quality_feature_series, momentum_quality_features


def test_momentum_bulk_series_matches_single_date_calculation():
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


def test_momentum_uses_percentage_units_and_revised_momentum_mix():
    bars = []
    day = date(2024, 1, 1)
    while len(bars) < 270:
        if day.weekday() < 5:
            index = len(bars)
            close = 100 * (1.0015**index) + math.sin(index / 8)
            bars.append(
                {
                    "as_of_date": day.isoformat(),
                    "open": close - 0.2,
                    "high": close + 0.8,
                    "low": close - 0.8,
                    "close": close,
                    "volume": 5_000_000 + index * 2000,
                }
            )
        day += timedelta(days=1)

    latest = momentum_quality_features(bars)
    assert latest is not None
    indicators = latest["indicators"]
    factors = latest["factors"]
    distance = float(indicators["distance_from_ema_200"])
    slope = float(indicators["ema_50_slope"])
    rsi = float(indicators["rsi_signal_ema_3"])
    ppo = float(indicators["ppo_12_26_9"])
    ppo_histogram = float(indicators["ppo_histogram_12_26_9"])
    pure = (float(indicators["momentum_3m"]) + float(indicators["momentum_6m"])) / 2

    assert distance > 1
    assert slope > 0.1
    assert factors["trend"] == pytest.approx(
        0.4 * _goldilocks(distance) + 0.6 * (max(-5, min(5, slope)) / 5 * 50 + 50)
    )
    assert factors["momentum"] == pytest.approx(
        0.6 * _rsi_regime(rsi)
        + 0.2 * (max(-5, min(5, ppo)) / 5 * 50 + 50)
        + 0.1 * (max(-5, min(5, ppo_histogram)) / 5 * 50 + 50)
        + 0.1 * (max(-50, min(50, pure)) / 50 * 50 + 50)
    )
