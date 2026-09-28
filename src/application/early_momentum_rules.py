"""Serializable, versioned selection rules for Strategy 3 research."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any

from src.platform_kernel import DomainValidationError


@dataclass(frozen=True)
class EarlyMomentumRules:
    version: int = 1
    residual_top_fraction: float = 0.20
    volume_minimum: float = 1.50
    extension_maximum: float = 2.50
    squeeze_threshold: float = 0.25
    squeeze_mode: str = "current"
    trigger: str = "bb_cross"
    close_location_minimum: float | None = None
    max_daily_move_atr: float | None = None
    ranking_factor: str = "residual_score"
    benchmark_regime_required: bool = False
    adv30_minimum: float | None = None
    low_volume_proxy_required: bool = False
    round_trip_cost_bps: float = 50.0
    risk_fraction: float = 0.01
    position_cap_fraction: float = 0.10
    participation_fraction: float = 0.01

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_RULES = EarlyMomentumRules()
V4_RULES = EarlyMomentumRules(version=2, squeeze_mode="prior_session",
                              adv30_minimum=100_000_000.0,
                              low_volume_proxy_required=True)


def parse_rules(value: object | None) -> EarlyMomentumRules:
    if value is None:
        return DEFAULT_RULES
    if isinstance(value, EarlyMomentumRules):
        rules = value
    elif isinstance(value, dict):
        expected = set(DEFAULT_RULES.to_dict())
        unknown = set(value) - expected
        if unknown:
            raise DomainValidationError(
                f"Strategy 3 rules contain unknown fields: {', '.join(sorted(unknown))}"
            )
        try:
            rules = EarlyMomentumRules(**value)
        except TypeError as exc:
            raise DomainValidationError("Strategy 3 rules are invalid") from exc
    else:
        raise DomainValidationError("Strategy 3 rules must be a JSON object")
    if isinstance(rules.version, bool) or not isinstance(rules.version, int) or rules.version not in {1, 2}:
        raise DomainValidationError(f"unsupported Strategy 3 rules version: {rules.version}")
    numeric = {
        "residual_top_fraction": rules.residual_top_fraction,
        "volume_minimum": rules.volume_minimum,
        "extension_maximum": rules.extension_maximum,
        "squeeze_threshold": rules.squeeze_threshold,
        "round_trip_cost_bps": rules.round_trip_cost_bps,
        "risk_fraction": rules.risk_fraction,
        "position_cap_fraction": rules.position_cap_fraction,
        "participation_fraction": rules.participation_fraction,
    }
    optional_numeric = {
        "close_location_minimum": rules.close_location_minimum,
        "max_daily_move_atr": rules.max_daily_move_atr,
        "adv30_minimum": rules.adv30_minimum,
    }
    for name, number in numeric.items():
        if number is None:
            raise DomainValidationError(f"{name} must be a finite JSON number")
    for name, number in {**numeric, **optional_numeric}.items():
        if number is not None and (
            isinstance(number, bool) or not isinstance(number, Real) or not math.isfinite(number)
        ):
            raise DomainValidationError(f"{name} must be a finite JSON number")
    if not 0 < rules.residual_top_fraction <= 1:
        raise DomainValidationError("residual_top_fraction must be in (0, 1]")
    if rules.volume_minimum < 0 or rules.extension_maximum < 0:
        raise DomainValidationError("volume_minimum and extension_maximum must be non-negative")
    if not 0 <= rules.squeeze_threshold <= 1:
        raise DomainValidationError("squeeze_threshold must be in [0, 1]")
    for name in ("close_location_minimum", "max_daily_move_atr"):
        number = getattr(rules, name)
        if number is not None and not 0 <= number <= (1 if name == "close_location_minimum" else float("inf")):
            raise DomainValidationError(f"{name} is outside its valid range")
    if rules.squeeze_mode not in {"current", "prior10_minimum", "prior_session"}:
        raise DomainValidationError("invalid squeeze_mode")
    if rules.version == 1 and (rules.squeeze_mode == "prior_session" or rules.adv30_minimum is not None or rules.low_volume_proxy_required):
        raise DomainValidationError("v4 filters require rules version 2")
    if rules.version == 2 and (rules.adv30_minimum is None or not rules.low_volume_proxy_required):
        raise DomainValidationError("rules version 2 requires the liquidity and low-volume filters")
    if rules.adv30_minimum is not None and rules.adv30_minimum < 0:
        raise DomainValidationError("adv30_minimum must be non-negative")
    if rules.round_trip_cost_bps < 0 or any(not 0 < x <= 1 for x in (rules.risk_fraction, rules.position_cap_fraction, rules.participation_fraction)):
        raise DomainValidationError("invalid costs or sizing fractions")
    if not isinstance(rules.low_volume_proxy_required, bool):
        raise DomainValidationError("low_volume_proxy_required must be boolean")
    if rules.trigger not in {"bb_cross", "prior20_high_cross"}:
        raise DomainValidationError("trigger must be bb_cross or prior20_high_cross")
    if rules.ranking_factor not in {"residual_score", "momentum_63_skip5"}:
        raise DomainValidationError("ranking_factor must be residual_score or momentum_63_skip5")
    if not isinstance(rules.benchmark_regime_required, bool):
        raise DomainValidationError("benchmark_regime_required must be boolean")
    return rules

