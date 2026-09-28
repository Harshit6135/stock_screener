from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

# Historical Strategy 3 coverage is retained for the retirement audit only.
pytestmark = pytest.mark.skip(reason="Strategy 3 is retired; Task 4.3 remains incomplete until runtime source is removed")

from src.indicators.custom.early_momentum import early_momentum_feature_series


def _bars(count: int, *, scale: float = 1.0) -> list[dict[str, object]]:
    start = date(2023, 1, 1)
    close = 100.0 * scale
    rows = []
    for offset in range(count):
        close *= 1.001 + ((offset % 9) - 4) * 0.00015 * scale
        rows.append({
            "as_of_date": (start + timedelta(days=offset)).isoformat(),
            "open": close * 0.998,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000 + offset * 100,
        })
    return rows


def test_v3_features_are_prefix_invariant() -> None:
    stock, benchmark = _bars(340, scale=1.03), _bars(340)
    prefix = early_momentum_feature_series(stock[:325], benchmark[:325])
    extended = early_momentum_feature_series(stock, benchmark)

    assert prefix
    assert all(extended[day] == values for day, values in prefix.items())


def test_prior20_breakout_excludes_current_bar() -> None:
    stock, benchmark = _bars(317, scale=1.03), _bars(317)
    prior_high = max(float(row["high"]) for row in stock[-21:-1])
    stock[-1]["close"] = prior_high * 1.001
    stock[-1]["high"] = prior_high * 1.50
    stock[-1]["open"] = float(stock[-1]["close"]) * 0.999
    stock[-1]["low"] = float(stock[-1]["close"]) * 0.99

    result = list(early_momentum_feature_series(stock, benchmark).values())[-1]

    assert result["prior20_high"] == pytest.approx(prior_high)
    assert result["prior20_high_cross_ok"] is True


def test_prior_squeeze_excludes_current_percentile() -> None:
    stock, benchmark = _bars(317, scale=1.03), _bars(317)
    baseline = list(early_momentum_feature_series(stock, benchmark).values())[-1]
    stock[-1]["close"] = float(stock[-2]["close"]) * 1.20
    stock[-1]["open"] = float(stock[-1]["close"]) * 0.999
    stock[-1]["high"] = float(stock[-1]["close"]) * 1.01
    stock[-1]["low"] = float(stock[-1]["close"]) * 0.99

    changed = list(early_momentum_feature_series(stock, benchmark).values())[-1]

    assert changed["bbw_percentile_126"] != baseline["bbw_percentile_126"]
    assert changed["bbw_prior10_min_percentile"] == baseline["bbw_prior10_min_percentile"]


def test_skip5_momentum_uses_close_t_minus_5_and_t_minus_68() -> None:
    stock, benchmark = _bars(317, scale=1.03), _bars(317)
    result = list(early_momentum_feature_series(stock, benchmark).values())[-1]

    expected = math.log(float(stock[-6]["close"]) / float(stock[-69]["close"]))
    assert result["momentum_63_skip5"] == pytest.approx(expected)
