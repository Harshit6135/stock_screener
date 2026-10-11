"""Indicator validation adapter supplied to the strategies domain."""

from __future__ import annotations

from src.domains.indicators import APPROVED_OPERATIONS, DagGraph, PandasTaAdapter
from src.gates.indicator_implementations import CUSTOM_IMPLEMENTATIONS
from src.platform_kernel import DomainValidationError


class StrategyIndicatorValidator:
    """Bridge strategy definition validation to the indicator capability API."""

    def __init__(self, indicators: PandasTaAdapter) -> None:
        self.indicators = indicators

    def validate_indicator(
        self, function: str, inputs: dict[str, object], parameters: dict[str, object]
    ) -> None:
        spec = self.indicators.spec(function)
        if set(inputs) != set(spec.required_inputs):
            raise DomainValidationError(
                f"indicator inputs do not match approved function '{spec.key}'"
            )
        self.indicators.validate_parameters(spec, parameters)

    def compile_indicators(self, indicators: object, operations: object) -> dict[str, object]:
        return DagGraph.from_yaml_sections(indicators, operations, self.indicators).to_dict()

    @staticmethod
    def is_approved_operation(operation: object) -> bool:
        return operation in APPROVED_OPERATIONS

    @staticmethod
    def is_custom_implementation(implementation: object) -> bool:
        return implementation in CUSTOM_IMPLEMENTATIONS
