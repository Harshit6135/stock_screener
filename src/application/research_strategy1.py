"""Reviewed Strategy 1 indicator and factor port from v3 commit dabff59.

The formulas retain v3's units, including its fractional EMA distance and
momentum values. This module avoids a runtime dependency on pandas_ta; parity
against frozen v3 output is tracked separately in the migration ledger.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, cast

import pandas as pd

FACTOR_WEIGHTS = {
    "trend": 0.30,
    "momentum": 0.25,
    "efficiency": 0.20,
    "volume": 0.15,
    "structure": 0.10,
}
FORMULA_REVISION = "strategy1-v4-port-2"


def _goldilocks(distance: float) -> float:
    if distance < 0:
        return 0.0
    if distance <= 10:
        return 70 + distance / 10 * 15
    if distance <= 35:
        return 85 + (distance - 10) / 25 * 15
    if distance <= 50:
        return 100 - (distance - 35) / 15 * 40
    return max(0.0, 60 - (distance - 50) / 50 * 60)


def _rsi_regime(rsi: float) -> float:
    if rsi < 40:
        return 0.0
    if rsi <= 50:
        return (rsi - 40) / 10 * 30
    if rsi <= 70:
        return 30 + (rsi - 50) / 20 * 70
    if rsi <= 85:
        return 100 - (rsi - 70) / 15 * 10
    return max(60.0, 90 - (rsi - 85) / 15 * 30)


def _percent_b_score(value: float) -> float:
    if value < 0.5:
        return 20.0
    if value <= 0.7:
        return 20 + (value - 0.5) / 0.2 * 40
    if value <= 1.1:
        return 60 + (value - 0.7) / 0.4 * 40
    return max(70.0, 100 - (value - 1.1) / 0.5 * 30)


def _value(row: pd.Series, name: int, default: float) -> float:
    raw = row[name]
    return float(raw) if pd.notna(raw) and math.isfinite(float(raw)) else default


def strategy1_factors(bars: Sequence[dict[str, Any]]) -> dict[str, object] | None:
    """Compute v3 Strategy 1 factor inputs for the final completed session."""
    if len(bars) < 200:
        return None
    frame = pd.DataFrame(bars).sort_values("as_of_date")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"]
    ema50 = close.ewm(span=50, adjust=False, min_periods=50).mean()
    ema200 = close.ewm(span=200, adjust=False, min_periods=200).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, float("nan")))
    rsi_signal = rsi.ewm(span=3, adjust=False, min_periods=3).mean()
    fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    ppo = (fast - slow) / slow * 100
    previous = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous).abs(), (low - previous).abs()], axis=1
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    atr_value = atr
    midpoint = close.rolling(20).mean()
    deviation = close.rolling(20).std(ddof=0)
    lower = midpoint - 2 * deviation
    upper = midpoint + 2 * deviation
    bandwidth = (upper - lower) / midpoint * 100
    percent_b = (close - lower) / (upper - lower).replace(0, float("nan"))
    ema_slope = ema50 / ema50.shift(5) - 1
    ema_distance = close / ema200 - 1
    roc20 = (close / close.shift(20) - 1) * 100
    risk_adjusted = roc20 / (atr_value / close).replace(0, float("nan"))
    atr_spike = atr_value / atr_value.rolling(20).mean().replace(0, float("nan"))
    rvol = volume / volume.rolling(20).mean().replace(0, float("nan"))
    price_volume_corr = close.pct_change().rolling(10).corr(volume)
    momentum3 = close.shift(5) / close.shift(63) - 1
    momentum6 = close.shift(5) / close.shift(126) - 1
    bandwidth_change = (
        bandwidth.fillna(0)
        .pct_change(5)
        .replace([float("inf"), float("-inf")], float("nan"))
        .fillna(0)
    )
    turnover_ema20 = (close * volume).ewm(span=20, adjust=False, min_periods=20).mean()
    latest = frame.iloc[-1]
    i = int(cast(Any, latest.name))
    distance = _value(ema_distance, i, 0)
    slope = _value(ema_slope, i, 0)
    rsi_value = _value(rsi_signal, i, 50)
    ppo_value = _value(ppo, i, 0)
    pure_momentum = (_value(momentum3, i, 0) + _value(momentum6, i, 0)) / 2
    risk_value = _value(risk_adjusted, i, 0)
    atr_spike_value = _value(atr_spike, i, 1)
    rvol_value = _value(rvol, i, 1)
    correlation = _value(price_volume_corr, i, 0)
    b_value = _value(percent_b, i, 0.5)
    bw_change = _value(bandwidth_change, i, 0)
    factors = {
        "trend": 0.4 * _goldilocks(distance) + 0.6 * (max(-5, min(5, slope)) / 5 * 50 + 50),
        "momentum": 0.2 * _rsi_regime(rsi_value)
        + 0.2 * (max(-5, min(5, ppo_value)) / 5 * 50 + 50)
        + 0.6 * (max(-50, min(50, pure_momentum)) / 50 * 50 + 50),
        "efficiency": (max(-5, min(5, risk_value)) / 5 * 50 + 50)
        * (0.5 if atr_spike_value > 2 else 1),
        "volume": 0.7 * (max(0, min(3, rvol_value)) / 3 * 100)
        + 0.3 * ((max(-1, min(1, correlation)) + 1) / 2 * 100),
        "structure": 0.5 * _percent_b_score(b_value)
        + 0.5 * (max(-0.5, min(0.5, bw_change)) / 0.5 * 50 + 50),
    }
    latest_close = float(latest["close"])
    latest_volume = int(latest["volume"])
    penalty = 1.0
    reasons: list[str] = []
    if _value(ema200, i, latest_close) > latest_close:
        penalty *= 0.5
        reasons.append("below_ema_200")
    if _value(ema50, i, latest_close) > latest_close:
        penalty *= 0.7
        reasons.append("below_ema_50")
    if _value(ema50, i, latest_close) < 50:
        penalty = 0.0
        reasons.append("penny_stock")
    if _value(turnover_ema20, i, 0) < 5_000_000:
        penalty = 0.0
        reasons.append("low_turnover")
    if latest_volume == 0:
        penalty = 0.0
        reasons.append("zero_volume")
    if len({float(latest[field]) for field in ("open", "high", "low", "close")}) == 1:
        penalty = 0.0
        reasons.append("flat_ohlc")
    return {
        "factors": factors,
        "indicators": {
            "ema_50": _value(ema50, i, latest_close),
            "ema_200": _value(ema200, i, latest_close),
            "rsi_14": _value(rsi, i, 50),
            "rsi_signal_ema_3": rsi_value,
            "ppo_12_26_9": ppo_value,
            "atrr_14": _value(atr_value, i, 0),
            "avg_turnover_ema_20": _value(turnover_ema20, i, 0),
            "momentum_3m": _value(momentum3, i, 0),
            "momentum_6m": _value(momentum6, i, 0),
        },
        "penalty": penalty,
        "penalty_reasons": reasons,
        "close": latest_close,
    }
