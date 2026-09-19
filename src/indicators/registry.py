"""Approved indicator catalogue and safe Pandas TA adapter.

Only explicitly registered functions are callable.  Definitions never execute
arbitrary Python supplied by a strategy YAML document.
"""

from __future__ import annotations

import importlib.metadata
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import pandas as pd

from src.platform_kernel import DomainValidationError


class IndicatorProvider(StrEnum):
    PANDAS_TA = "pandas_ta"
    CUSTOM = "custom"
    BUILT_IN = "built_in"


class SupportStatus(StrEnum):
    AVAILABLE_UNTESTED = "AVAILABLE_UNTESTED"
    SUPPORTED = "SUPPORTED"
    SUPPORTED_WITH_RESTRICTIONS = "SUPPORTED_WITH_RESTRICTIONS"
    CUSTOM_IMPLEMENTATION = "CUSTOM_IMPLEMENTATION"
    MANUAL_IMPLEMENTATION_REQUIRED = "MANUAL_IMPLEMENTATION_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class IndicatorSpec:
    key: str
    display_name: str
    category: str
    required_inputs: tuple[str, ...]
    parameters: Mapping[str, Mapping[str, object]]
    outputs: tuple[str, ...]
    warmup_parameter: str | None
    status: SupportStatus
    lookahead_safe: bool = True
    restriction: str | None = None

    def catalogue_item(self, package_version: str, adapter_version: str) -> dict[str, object]:
        return {
            "provider": IndicatorProvider.PANDAS_TA,
            "indicator_key": self.key,
            "display_name": self.display_name,
            "category": self.category,
            "required_inputs": list(self.required_inputs),
            "parameters": self.parameters,
            "outputs": list(self.outputs),
            "warmup_parameter": self.warmup_parameter,
            "support_status": self.status,
            "test_status": "TESTED" if self.status == SupportStatus.SUPPORTED else "PENDING",
            "lookahead_safe": self.lookahead_safe,
            "manual_effort_required": self.status
            in {SupportStatus.CUSTOM_IMPLEMENTATION, SupportStatus.MANUAL_IMPLEMENTATION_REQUIRED},
            "restriction": self.restriction,
            "package_version": package_version,
            "adapter_version": adapter_version,
        }


_SPECS = (
    IndicatorSpec("ema", "Exponential Moving Average", "overlap", ("close",), {"length": {"type": "integer", "minimum": 1, "default": 10}}, ("ema",), "length", SupportStatus.SUPPORTED),
    IndicatorSpec("sma", "Simple Moving Average", "overlap", ("close",), {"length": {"type": "integer", "minimum": 1, "default": 10}}, ("sma",), "length", SupportStatus.SUPPORTED),
    IndicatorSpec("rsi", "Relative Strength Index", "momentum", ("close",), {"length": {"type": "integer", "minimum": 1, "default": 14}}, ("rsi",), "length", SupportStatus.SUPPORTED),
    IndicatorSpec("roc", "Rate of Change", "momentum", ("close",), {"length": {"type": "integer", "minimum": 1, "default": 10}}, ("roc",), "length", SupportStatus.SUPPORTED),
    IndicatorSpec("atr", "Average True Range", "volatility", ("high", "low", "close"), {"length": {"type": "integer", "minimum": 1, "default": 14}}, ("atr",), "length", SupportStatus.SUPPORTED),
    IndicatorSpec("macd", "Moving Average Convergence Divergence", "momentum", ("close",), {"fast": {"type": "integer", "minimum": 1, "default": 12}, "slow": {"type": "integer", "minimum": 2, "default": 26}, "signal": {"type": "integer", "minimum": 1, "default": 9}}, ("macd", "histogram", "signal"), "slow", SupportStatus.SUPPORTED),
    IndicatorSpec("bbands", "Bollinger Bands", "volatility", ("close",), {"length": {"type": "integer", "minimum": 1, "default": 20}, "std": {"type": "number", "minimum": 0.000001, "default": 2}}, ("lower", "mid", "upper", "bandwidth", "percent"), "length", SupportStatus.SUPPORTED),
    IndicatorSpec("adx", "Average Directional Index", "trend", ("high", "low", "close"), {"length": {"type": "integer", "minimum": 1, "default": 14}, "lensig": {"type": "integer", "minimum": 1, "default": 14}}, ("adx", "dmp", "dmn"), "length", SupportStatus.SUPPORTED),
)


class PandasTaAdapter:
    """Stable, validated boundary around the installed ``pandas_ta`` package."""

    adapter_version = "1"

    def __init__(self) -> None:
        try:
            import pandas_ta
        except ImportError as exc:  # pragma: no cover - deployment configuration
            raise DomainValidationError("pandas_ta is not installed") from exc
        self._module = pandas_ta
        self.package_version = importlib.metadata.version("pandas-ta")
        self._specs = {spec.key: spec for spec in _SPECS}

    def catalogue(self) -> list[dict[str, object]]:
        return [self._specs[key].catalogue_item(self.package_version, self.adapter_version) for key in sorted(self._specs)]

    def spec(self, key: str) -> IndicatorSpec:
        try:
            return self._specs[key]
        except KeyError as exc:
            raise DomainValidationError(f"indicator '{key}' is not approved") from exc

    def calculate(
        self, key: str, inputs: Mapping[str, pd.Series], parameters: Mapping[str, object] | None = None
    ) -> pd.DataFrame:
        spec = self.spec(key)
        params = self._validate_parameters(spec, parameters or {})
        if set(inputs) != set(spec.required_inputs):
            raise DomainValidationError(f"indicator '{key}' requires inputs: {', '.join(spec.required_inputs)}")
        series = {name: self._validate_series(name, value) for name, value in inputs.items()}
        index = next(iter(series.values())).index
        if any(not value.index.equals(index) for value in series.values()):
            raise DomainValidationError("indicator inputs must share an identical index")
        function: Callable[..., Any] | None = getattr(self._module, key, None)
        if function is None:
            raise DomainValidationError(f"installed pandas_ta does not provide '{key}'")
        try:
            result = function(**series, **params)
        except (TypeError, ValueError) as exc:
            raise DomainValidationError(f"indicator '{key}' could not be calculated: {exc}") from exc
        frame = result.to_frame(name=key) if isinstance(result, pd.Series) else result
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise DomainValidationError(f"indicator '{key}' returned no values")
        frame = frame.copy().astype("float64")
        if not frame.index.equals(index) or frame.isin([float("inf"), float("-inf")]).any().any():
            raise DomainValidationError(f"indicator '{key}' returned invalid values")
        return frame

    @staticmethod
    def _validate_series(name: str, series: object) -> pd.Series:
        if not isinstance(series, pd.Series) or series.empty:
            raise DomainValidationError(f"indicator input '{name}' must be a non-empty pandas Series")
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.isna().any() or not numeric.map(math.isfinite).all():
            raise DomainValidationError(f"indicator input '{name}' must contain only finite numbers")
        return numeric.astype("float64")

    @staticmethod
    def _validate_parameters(spec: IndicatorSpec, supplied: Mapping[str, object]) -> dict[str, object]:
        if unknown := set(supplied) - set(spec.parameters):
            raise DomainValidationError(f"indicator '{spec.key}' has unsupported parameters: {', '.join(sorted(unknown))}")
        result: dict[str, object] = {}
        for name, schema in spec.parameters.items():
            value = supplied.get(name, schema["default"])
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise DomainValidationError(f"indicator parameter '{name}' must be numeric")
            if schema["type"] == "integer" and not isinstance(value, int):
                raise DomainValidationError(f"indicator parameter '{name}' must be an integer")
            if not math.isfinite(float(value)) or float(value) < float(schema["minimum"]):
                raise DomainValidationError(f"indicator parameter '{name}' is outside its supported range")
            result[name] = value
        if spec.key == "macd" and int(result["fast"]) >= int(result["slow"]):
            raise DomainValidationError("indicator parameter 'fast' must be less than 'slow'")
        return result
