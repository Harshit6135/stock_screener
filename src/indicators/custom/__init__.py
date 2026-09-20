"""Project-owned indicators used when Pandas TA cannot express a calculation."""

from collections.abc import Callable, Sequence
from typing import Any

from .momentum_quality import momentum_quality_feature_series, momentum_quality_features
from .relative_strength import (
    relative_strength_factor_series,
    relative_strength_factors,
    relative_strength_feature_series,
    relative_strength_features,
)

InstrumentImplementation = Callable[[Sequence[dict[str, Any]]], dict[str, object] | None]
BenchmarkImplementation = Callable[
    [Sequence[dict[str, Any]], Sequence[dict[str, Any]]], dict[str, object] | None
]
CrossSectionImplementation = Callable[[dict[str, dict[str, object]]], dict[str, dict[str, float]]]

INSTRUMENT_IMPLEMENTATIONS: dict[str, InstrumentImplementation | BenchmarkImplementation] = {
    "custom.momentum_quality_features": momentum_quality_features,
    "custom.relative_strength_features": relative_strength_features,
}
INSTRUMENT_SERIES_IMPLEMENTATIONS = {
    "custom.momentum_quality_features": momentum_quality_feature_series,
    "custom.relative_strength_features": relative_strength_feature_series,
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
    "relative_strength_factor_series",
    "relative_strength_factors",
    "relative_strength_feature_series",
    "relative_strength_features",
)
