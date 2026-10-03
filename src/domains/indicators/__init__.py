"""Indicator definitions, computation, approved adapters, and result caching."""

from .api import (
    FeatureSnapshot,
    FeatureValue,
    IndicatorConfiguration,
    IndicatorRevision,
    compute_feature,
)
from .dag import APPROVED_OPERATIONS, PRIMITIVE_FIELDS, DagExecutor, DagGraph, DagNode
from .momentum_quality import momentum_quality_indicator_series
from .node_cache import IndicatorNodeCache
from .relative_strength import (
    relative_strength_factor_series,
    relative_strength_factors,
    relative_strength_feature_series,
    relative_strength_features,
)
from .registry import (
    IndicatorProvider,
    IndicatorSpec,
    PandasTaAdapter,
    SupportStatus,
    provider_output_role,
    selected_indicator_output,
)

__all__ = [
    "APPROVED_OPERATIONS",
    "PRIMITIVE_FIELDS",
    "DagExecutor",
    "DagGraph",
    "DagNode",
    "FeatureSnapshot",
    "FeatureValue",
    "IndicatorConfiguration",
    "IndicatorNodeCache",
    "IndicatorProvider",
    "IndicatorRevision",
    "momentum_quality_indicator_series",
    "IndicatorSpec",
    "PandasTaAdapter",
    "SupportStatus",
    "compute_feature",
    "relative_strength_factor_series",
    "relative_strength_factors",
    "relative_strength_feature_series",
    "relative_strength_features",
    "provider_output_role",
    "selected_indicator_output",
]