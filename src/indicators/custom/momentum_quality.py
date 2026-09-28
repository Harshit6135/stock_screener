"""Custom momentum/quality feature implementation unavailable as standard TA indicators.

Percentage-based inputs are expressed in percentage points before applying the
documented scoring ranges. This module avoids a runtime dependency on
``pandas_ta``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import pandas as pd

_MOMENTUM_RSI_WEIGHT = 0.60
_MOMENTUM_PPO_WEIGHT = 0.20
_MOMENTUM_PPO_HISTOGRAM_WEIGHT = 0.10
_MOMENTUM_PURE_WEIGHT = 0.10


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


def momentum_quality_indicator_series(
    bars: Sequence[dict[str, Any]],
) -> dict[str, dict[str, object]]:
    """Compute reusable Strategy 1 indicators without applying factor weights."""
    if len(bars) < 200:
        return {}
    frame = pd.DataFrame(bars).sort_values("as_of_date").reset_index(drop=True)
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
    ppo_signal = ppo.ewm(span=9, adjust=False, min_periods=9).mean()
    ppo_histogram = ppo - ppo_signal
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
    ema_slope = (ema50 / ema50.shift(5) - 1) * 100
    ema_distance = (close / ema200 - 1) * 100
    roc20 = (close / close.shift(20) - 1) * 100
    risk_adjusted = roc20 / (atr_value / close).replace(0, float("nan"))
    atr_spike = atr_value / atr_value.rolling(20).mean().replace(0, float("nan"))
    rvol = volume / volume.rolling(20).mean().replace(0, float("nan"))
    price_volume_corr = close.pct_change().rolling(10).corr(volume)
    momentum3 = (close.shift(5) / close.shift(63) - 1) * 100
    momentum6 = (close.shift(5) / close.shift(126) - 1) * 100
    bandwidth_change = (
        bandwidth.fillna(0)
        .pct_change(5)
        .replace([float("inf"), float("-inf")], float("nan"))
        .fillna(0)
    )
    turnover_ema20 = (close * volume).ewm(span=20, adjust=False, min_periods=20).mean()
    output: dict[str, dict[str, object]] = {}
    for i in range(199, len(frame)):
        latest = frame.iloc[i]
        distance = _value(ema_distance, i, 0)
        slope = _value(ema_slope, i, 0)
        rsi_value = _value(rsi_signal, i, 50)
        ppo_value = _value(ppo, i, 0)
        latest_close = float(latest["close"])
        output[str(latest["as_of_date"])] = {
            "ema_50": _value(ema50, i, latest_close),
            "ema_200": _value(ema200, i, latest_close),
            "rsi_14": _value(rsi, i, 50),
            "rsi_signal_ema_3": rsi_value,
            "ppo_12_26_9": ppo_value,
            "ppo_histogram_12_26_9": _value(ppo_histogram, i, 0),
            "atrr_14": _value(atr_value, i, 0),
            "atr_spike": _value(atr_spike, i, 1),
            "risk_adjusted_return": _value(risk_adjusted, i, 0),
            "avg_turnover_ema_20": _value(turnover_ema20, i, 0),
            "ema_50_slope": slope,
            "distance_from_ema_200": distance,
            "momentum_3m": _value(momentum3, i, 0),
            "momentum_6m": _value(momentum6, i, 0),
            "rvol": _value(rvol, i, 1),
            "price_volume_corr": _value(price_volume_corr, i, 0),
            "percent_b": _value(percent_b, i, 0.5),
            "bandwidth_change_5d": _value(bandwidth_change, i, 0),
            "volume": int(latest["volume"]),
            "flat_ohlc": len(
                {float(latest[field]) for field in ("open", "high", "low", "close")}
            )
            == 1,
            "close": latest_close,
        }
    return output


def momentum_quality_from_indicators(values: dict[str, object]) -> dict[str, object]:
    """Apply factor composition and eligibility to cached raw indicators."""
    number = lambda key: float(values[key])
    pure = (number("momentum_3m") + number("momentum_6m")) / 2
    factors = {
        "trend": 0.4 * _goldilocks(number("distance_from_ema_200"))
        + 0.6 * (max(-5, min(5, number("ema_50_slope"))) / 5 * 50 + 50),
        "momentum": _MOMENTUM_RSI_WEIGHT * _rsi_regime(number("rsi_signal_ema_3"))
        + _MOMENTUM_PPO_WEIGHT * (max(-5, min(5, number("ppo_12_26_9"))) / 5 * 50 + 50)
        + _MOMENTUM_PPO_HISTOGRAM_WEIGHT
        * (max(-5, min(5, number("ppo_histogram_12_26_9"))) / 5 * 50 + 50)
        + _MOMENTUM_PURE_WEIGHT * (max(-50, min(50, pure)) / 50 * 50 + 50),
        "efficiency": (max(-5, min(5, number("risk_adjusted_return"))) / 5 * 50 + 50)
        * (0.5 if number("atr_spike") > 2 else 1),
        "volume": 0.7 * (max(0, min(3, number("rvol"))) / 3 * 100)
        + 0.3 * ((max(-1, min(1, number("price_volume_corr"))) + 1) / 2 * 100),
        "structure": 0.5 * _percent_b_score(number("percent_b"))
        + 0.5 * (max(-0.5, min(0.5, number("bandwidth_change_5d"))) / 0.5 * 50 + 50),
    }
    penalty, reasons = 1.0, []
    for condition, multiplier, reason in (
        (number("ema_200") > number("close"), 0.5, "below_ema_200"),
        (number("ema_50") > number("close"), 0.7, "below_ema_50"),
    ):
        if condition:
            penalty *= multiplier
            reasons.append(reason)
    for condition, reason in (
        (number("ema_50") < 50, "penny_stock"),
        (number("avg_turnover_ema_20") < 5_000_000, "low_turnover"),
        (int(values["volume"]) == 0, "zero_volume"),
        (bool(values["flat_ohlc"]), "flat_ohlc"),
    ):
        if condition:
            penalty = 0.0
            reasons.append(reason)
    return {"factors": factors, "indicators": dict(values), "penalty": penalty,
            "penalty_reasons": reasons, "close": number("close")}


def momentum_quality_feature_series(bars: Sequence[dict[str, Any]]) -> dict[str, dict[str, object]]:
    return {day: momentum_quality_from_indicators(values)
            for day, values in momentum_quality_indicator_series(bars).items()}


def momentum_quality_features(bars: Sequence[dict[str, Any]]) -> dict[str, object] | None:
    """Compute Strategy 1 inputs for the final completed session."""
    values = momentum_quality_feature_series(bars)
    return next(reversed(values.values())) if values else None
