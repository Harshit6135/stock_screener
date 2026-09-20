"""Generic execution runtime for immutable declarative strategy revisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from src.application.strategy_definitions import StrategyDefinitions
from src.indicators.custom import (
    CROSS_SECTION_IMPLEMENTATIONS,
    INSTRUMENT_IMPLEMENTATIONS,
    INSTRUMENT_SERIES_IMPLEMENTATIONS,
    BenchmarkImplementation,
    InstrumentImplementation,
)
from src.platform_kernel import DomainValidationError


class StrategyRuntime:
    def __init__(self, definitions: StrategyDefinitions) -> None:
        self.definitions = definitions

    def seed(self, directory: str | Path) -> None:
        for path in sorted(Path(directory).glob("*.yml")):
            revision = self.definitions.create_from_yaml(path.read_text(encoding="utf-8"))
            active = self.definitions.active(str(revision["strategy_id"]))
            if active is None or "portfolio_policy" not in cast(
                dict[str, Any], active["definition"]
            ):
                self.definitions.activate(str(revision["revision_id"]))

    def revision(self, strategy_id: str) -> dict[str, object]:
        revision = self.definitions.active(strategy_id)
        if revision is None:
            raise DomainValidationError(f"strategy '{strategy_id}' has no active revision")
        return revision

    def strategy_ids(self) -> tuple[str, ...]:
        return tuple(item["strategy_id"] for item in self.definitions.active_revisions())

    def factor_weights(self, strategy_id: str) -> dict[str, float]:
        definition = cast(dict[str, Any], self.revision(strategy_id)["definition"])
        return {str(key): float(value) for key, value in definition["factors"].items()}

    def benchmark(self, strategy_id: str) -> str | None:
        definition = cast(dict[str, Any], self.revision(strategy_id)["definition"])
        dependencies = definition.get("data_dependencies", {})
        return str(dependencies["benchmark"]) if dependencies.get("benchmark") else None

    def portfolio_policy(self, strategy_id: str) -> dict[str, object]:
        definition = cast(dict[str, Any], self.revision(strategy_id)["definition"])
        return dict(definition["portfolio_policy"])

    def compute(
        self,
        strategy_id: str,
        bars: Sequence[dict[str, Any]],
        benchmark: Sequence[dict[str, Any]],
    ) -> dict[str, object] | None:
        definition = cast(dict[str, Any], self.revision(strategy_id)["definition"])
        key = str(definition["calculation"]["instrument_implementation"])
        implementation = INSTRUMENT_IMPLEMENTATIONS[key]
        if self.benchmark(strategy_id):
            return cast(BenchmarkImplementation, implementation)(bars, benchmark)
        return cast(InstrumentImplementation, implementation)(bars)

    def compute_series(
        self,
        strategy_id: str,
        bars: Sequence[dict[str, Any]],
        benchmark: Sequence[dict[str, Any]],
    ) -> dict[str, dict[str, object]]:
        """Compute all available sessions without recalculating rolling windows per date."""
        definition = cast(dict[str, Any], self.revision(strategy_id)["definition"])
        key = str(definition["calculation"]["instrument_implementation"])
        implementation = INSTRUMENT_SERIES_IMPLEMENTATIONS[key]
        if self.benchmark(strategy_id):
            return cast(Any, implementation)(bars, benchmark)
        return cast(Any, implementation)(bars)

    def cross_section(
        self, strategy_id: str, values: dict[str, dict[str, object]]
    ) -> dict[str, dict[str, float]] | None:
        definition = cast(dict[str, Any], self.revision(strategy_id)["definition"])
        key = definition["calculation"].get("cross_section_implementation")
        return CROSS_SECTION_IMPLEMENTATIONS[str(key)](values) if key else None

    def factor_multiplier(
        self, strategy_id: str, factor: str, values: Mapping[str, object]
    ) -> float:
        definition = cast(dict[str, Any], self.revision(strategy_id)["definition"])
        for modifier in definition.get("score", {}).get("factor_modifiers", []):
            if factor not in modifier["factors"]:
                continue
            observed = float(values[str(modifier["input"])])
            for rule in modifier["rules"]:
                threshold = float(rule["value"])
                if (rule["operator"] == "less_than" and observed < threshold) or (
                    rule["operator"] == "greater_than" and observed > threshold
                ):
                    return float(rule["multiplier"])
            return float(modifier["default"])
        return 1.0
