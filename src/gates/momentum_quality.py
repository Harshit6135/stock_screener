"""Cross-domain momentum-quality feature composition."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.domains.indicators import momentum_quality_indicator_series
from src.domains.strategies import momentum_quality_from_indicators


def momentum_quality_feature_series(bars: Sequence[dict[str, Any]]) -> dict[str, dict[str, object]]:
    return {
        day: momentum_quality_from_indicators(values)
        for day, values in momentum_quality_indicator_series(bars).items()
    }


def momentum_quality_features(bars: Sequence[dict[str, Any]]) -> dict[str, object] | None:
    """Compute Strategy 1 inputs for the final completed session."""
    values = momentum_quality_feature_series(bars)
    return next(reversed(values.values())) if values else None
