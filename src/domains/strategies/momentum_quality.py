"""Momentum-quality factor scoring and eligibility rules."""

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
