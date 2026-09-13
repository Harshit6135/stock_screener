"""Strategy 2 raw indicators and cross-sectional factors from v3 formulas.

The inherited quality input is a constant-zero placeholder, not a fundamental
quality measure. The inherited scaled-turnover input is relative volume, not
float turnover; both are labelled as such in the published feature artifact.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, cast

import pandas as pd

FORMULA_REVISION = "strategy2-v4-port-1"
FACTOR_WEIGHTS = {
    "trend": 0.30,
    "momentum": 0.25,
    "efficiency": 0.20,
    "volume": 0.15,
    "structure": 0.10,
}


def _finite(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(cast(Any, value))
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def strategy2_indicators(
    bars: Sequence[dict[str, Any]], benchmark: Sequence[dict[str, Any]]
) -> dict[str, object] | None:
    """Compute latest v3-style S2 inputs; require a same-day Kite benchmark."""
    if len(bars) < 253 or len(benchmark) < 200:
        return None
    frame = pd.DataFrame(bars).sort_values("as_of_date").reset_index(drop=True)
    benchmark_frame = pd.DataFrame(benchmark).sort_values("as_of_date")
    if frame.iloc[-1]["as_of_date"] != benchmark_frame.iloc[-1]["as_of_date"]:
        return None
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"]
    benchmark_close = pd.to_numeric(benchmark_frame["close"], errors="raise")
    benchmark_by_date = pd.Series(
        benchmark_close.to_numpy(), index=benchmark_frame["as_of_date"].to_numpy()
    )
    aligned_benchmark = benchmark_by_date.reindex(frame["as_of_date"], method="ffill")
    aligned_benchmark.index = frame.index
    if aligned_benchmark.isna().any():
        return None

    ema50 = close.ewm(span=50, adjust=False, min_periods=50).mean()
    ema200 = close.ewm(span=200, adjust=False, min_periods=200).mean()
    ema_slope = ema50 / ema50.shift(5) - 1
    ema_distance = close / ema200 - 1
    fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    ppo = (fast - slow) / slow * 100
    log_return = (close / close.shift(1)).map(math.log, na_action="ignore")
    sigma_annual = log_return.rolling(252).std() * math.sqrt(252)
    momentum_6m = close.shift(5) / close.shift(126) - 1
    norm_momentum = (
        (close.shift(5) / close.shift(126)).map(math.log, na_action="ignore")
        + (close.shift(5) / close.shift(252)).map(math.log, na_action="ignore")
    ) / (2 * sigma_annual.replace(0, float("nan")))
    relative_price = close / aligned_benchmark - 1
    mansfield = relative_price / relative_price.rolling(200).mean().replace(0, float("nan")) - 1

    daily_return = close.pct_change()
    downside = (daily_return - 0.06 / 252).clip(upper=0)
    downside_std = downside.rolling(252).std() * math.sqrt(252)
    sortino = (daily_return.rolling(252).mean() * 252 - 0.06) / downside_std.replace(
        0, float("nan")
    )
    previous = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous).abs(), (low - previous).abs()], axis=1
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    atr_spike = atr / atr.rolling(20).mean().replace(0, float("nan"))
    volume_sma20 = volume.rolling(20).mean()
    rvol = volume / volume_sma20.replace(0, float("nan"))
    # The v3 "scaled_turnover" formula simplifies to volume / SMA(volume).
    # Preserve its actual behavior while exposing its honest name.
    relative_volume_proxy = rvol
    log_price_volume_corr = log_return.rolling(20).corr(volume)
    midpoint = close.rolling(20).mean()
    deviation = close.rolling(20).std(ddof=0)
    lower = midpoint - 2 * deviation
    upper = midpoint + 2 * deviation
    bandwidth = (upper - lower) / midpoint * 100
    bandwidth_change = (bandwidth - bandwidth.shift(5)) / bandwidth.shift(5).replace(
        0, float("nan")
    )
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, float("nan")))

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    smoothed_tr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / smoothed_tr
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / smoothed_tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
    adx = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    turnover_ema20 = (close * volume).ewm(span=20, adjust=False, min_periods=20).mean()
    latest = frame.iloc[-1]
    i = len(frame) - 1
    required = (norm_momentum, sortino, ema200, adx, turnover_ema20)
    if any(not math.isfinite(_finite(series.iloc[i], float("nan"))) for series in required):
        return None
    reasons: list[str] = []
    if _finite(ema50.iloc[i]) < 50:
        reasons.append("penny_stock")
    if _finite(turnover_ema20.iloc[i]) < 500_000_000:
        reasons.append("low_turnover")
    if int(latest["volume"]) == 0:
        reasons.append("zero_volume")
    if len({float(latest[field]) for field in ("open", "high", "low", "close")}) == 1:
        reasons.append("flat_ohlc")
    return {
        "distance_from_ema_200": _finite(ema_distance.iloc[i]),
        "ema_50_slope": _finite(ema_slope.iloc[i]),
        "mansfield_rs": _finite(mansfield.iloc[i]),
        "nse_norm_momentum": _finite(norm_momentum.iloc[i]),
        "ppo_12_26_9": _finite(ppo.iloc[i]),
        "momentum_6m": _finite(momentum_6m.iloc[i]),
        "sortino_ratio": _finite(sortino.iloc[i]),
        "atr_spike": _finite(atr_spike.iloc[i], 1),
        "rvol": _finite(rvol.iloc[i], 1),
        "relative_volume_proxy": _finite(relative_volume_proxy.iloc[i], 0.5),
        "scaled_turnover": _finite(relative_volume_proxy.iloc[i], 0.5),
        "log_price_vol_corr": _finite(log_price_volume_corr.iloc[i]),
        "bandwidth_change_5d": _finite(bandwidth_change.iloc[i]),
        "rsi_14": _finite(rsi.iloc[i], 50),
        "adx_14": _finite(adx.iloc[i], 25),
        "avg_turnover_ema_20": _finite(turnover_ema20.iloc[i]),
        "quality_z_score_placeholder": 0.0,
        "penalty": 0.0 if reasons else 1.0,
        "penalty_reasons": reasons,
    }


def strategy2_factors(
    inputs: dict[str, dict[str, object]],
) -> dict[str, dict[str, float]]:
    """Apply v3 cross-sectional normalizations and per-stock factor weights."""
    frame = pd.DataFrame.from_dict(inputs, orient="index")
    distance = frame["distance_from_ema_200"]
    momentum = frame["nse_norm_momentum"]
    distance_sigma = distance.std()
    momentum_sigma = momentum.std()
    distance_z = (
        (distance - distance.mean()) / distance_sigma if distance_sigma > 0 else distance * 0
    )
    momentum_z = (
        (momentum - momentum.mean()) / momentum_sigma if momentum_sigma > 0 else momentum * 0
    )
    results: dict[str, dict[str, float]] = {}
    for key, row in frame.iterrows():
        symbol = str(key)
        slope = _finite(row["ema_50_slope"])
        mrs = _finite(row["mansfield_rs"])
        ppo = _finite(row["ppo_12_26_9"])
        pure = _finite(row["momentum_6m"])
        sortino = _finite(row["sortino_ratio"])
        atr_spike = _finite(row["atr_spike"], 1)
        rvol = _finite(row["rvol"], 1)
        proxy = _finite(row["relative_volume_proxy"], 0.5)
        corr = _finite(row["log_price_vol_corr"])
        bw_change = _finite(row["bandwidth_change_5d"])
        rsi = _finite(row["rsi_14"], 50)
        results[symbol] = {
            "trend": 0.70 * (_clip(slope, -5, 5) / 5 * 50 + 50)
            + 0.30 * ((_clip(_finite(distance_z.loc[symbol]), -2, 2) + 2) / 4 * 100),
            "momentum": 0.40 * (_clip(mrs, -2, 2) / 2 * 50 + 50)
            + 0.30 * (_clip(_finite(momentum_z.loc[symbol]), -3, 3) / 3 * 50 + 50)
            + 0.20 * (_clip(ppo, -5, 5) / 5 * 50 + 50)
            + 0.10 * (_clip(pure, -50, 50) / 50 * 50 + 50),
            "efficiency": 0.70 * (_clip(sortino, -5, 5) / 5 * 50 + 50)
            + 0.30 * (50 if atr_spike > 2 else 100),
            "volume": 0.40 * (_clip(rvol, 0, 3) / 3 * 100)
            + 0.30 * ((1 - _clip(proxy, 0, 1)) * 100)
            + 0.30 * ((_clip(corr, -1, 1) + 1) / 2 * 100),
            "structure": 0.50 * 50
            + 0.30 * (_clip(bw_change, -0.5, 0.5) / 0.5 * 50 + 50)
            + 0.20 * _clip(rsi, 0, 100),
        }
    return results
