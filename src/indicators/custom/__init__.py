"""Project-owned indicators used when Pandas TA cannot express a calculation."""

from collections.abc import Callable, Sequence
from typing import Any

from src.application.positional_trend import feature_series as positional_trend_feature_series

from .momentum_quality import (
    momentum_quality_feature_series,
    momentum_quality_features,
    momentum_quality_from_indicators,
    momentum_quality_indicator_series,
)
from .relative_strength import (
    relative_strength_factor_series,
    relative_strength_factors,
    relative_strength_feature_series,
    relative_strength_features,
)


def positional_trend_features(bars: Sequence[dict[str, Any]]) -> dict[str, object] | None:
    """Return the most recent Strategy 4 row for generic registry compatibility."""
    rows = positional_trend_series(bars)
    return next(reversed(rows.values()), None)


def positional_trend_series(bars: Sequence[dict[str, Any]]) -> dict[str, dict[str, object]]:
    """Expose the same date-keyed series contract as the other custom indicators."""
    if not bars:
        return {}
    ordered = sorted(bars, key=lambda bar: str(bar["as_of_date"]))
    sessions = [str(bar["as_of_date"]) for bar in ordered]
    symbol = str(ordered[-1].get("symbol", ""))
    rows = positional_trend_feature_series(ordered, sessions, symbol)
    return {row["signal_date"]: row for row in rows}

InstrumentImplementation = Callable[[Sequence[dict[str, Any]]], dict[str, object] | None]
BenchmarkImplementation = Callable[
    [Sequence[dict[str, Any]], Sequence[dict[str, Any]]], dict[str, object] | None
]
CrossSectionImplementation = Callable[[dict[str, dict[str, object]]], dict[str, dict[str, float]]]

INSTRUMENT_IMPLEMENTATIONS: dict[str, InstrumentImplementation | BenchmarkImplementation] = {
    "custom.momentum_quality_features": momentum_quality_features,
    "custom.relative_strength_features": relative_strength_features,
    "custom.positional_trend_features": positional_trend_features,
}
INSTRUMENT_SERIES_IMPLEMENTATIONS = {
    "custom.momentum_quality_features": momentum_quality_feature_series,
    "custom.relative_strength_features": relative_strength_feature_series,
    "custom.positional_trend_features": positional_trend_series,
}
CROSS_SECTION_IMPLEMENTATIONS: dict[str, CrossSectionImplementation] = {
    "custom.relative_strength_factors": relative_strength_factors,
}
CUSTOM_IMPLEMENTATIONS = frozenset(INSTRUMENT_IMPLEMENTATIONS | CROSS_SECTION_IMPLEMENTATIONS)

__all__ = (
    "CROSS_SECTION_IMPLEMENTATIONS",
    "CUSTOM_IMPLEMENTATIONS",
    "INSTRUMENT_IMPLEMENTATIONS",
    "INSTRUMENT_SERIES_IMPLEMENTATIONS",
    "BenchmarkImplementation",
    "CrossSectionImplementation",
    "InstrumentImplementation",
    "momentum_quality_feature_series",
    "momentum_quality_features",
    "momentum_quality_from_indicators",
    "momentum_quality_indicator_series",
    "positional_trend_features",
    "positional_trend_series",
    "relative_strength_factor_series",
    "relative_strength_factors",
    "relative_strength_feature_series",
    "relative_strength_features",
)
