"""Raw momentum-quality indicator series for completed market sessions."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import pandas as pd


def _value(row: pd.Series, name: int, default: float) -> float:
    raw = row[name]
    return float(raw) if pd.notna(raw) and math.isfinite(float(raw)) else default


def average_true_range(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    """The ATR calculation shared by momentum indicators and portfolio stops."""
    previous = frame["close"].shift(1)
    true_range = pd.concat(
        [
            (frame["high"] - frame["low"]),
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


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
    atr = average_true_range(frame)
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
            "flat_ohlc": len({float(latest[field]) for field in ("open", "high", "low", "close")})
            == 1,
            "close": latest_close,
        }
    return output
