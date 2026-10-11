"""Generic execution runtime for immutable declarative strategy revisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pandas as pd

from src.domains.indicators import DagExecutor, DagGraph, PandasTaAdapter
from src.gates.indicator_implementations import (
    CROSS_SECTION_IMPLEMENTATIONS,
    INSTRUMENT_IMPLEMENTATIONS,
    INSTRUMENT_SERIES_IMPLEMENTATIONS,
    BenchmarkImplementation,
    InstrumentImplementation,
)
from src.gates.strategy_definitions import StrategyDefinitions
from src.platform_kernel import DomainValidationError

__all__ = ["StrategyRuntime"]


class StrategyRuntime:
    def __init__(
        self, definitions: StrategyDefinitions, adapter: PandasTaAdapter | None = None
    ) -> None:
        self.definitions = definitions
        self._adapter = adapter or PandasTaAdapter()

    def seed(self, directory: str | Path) -> None:
        for path in sorted(Path(directory).glob("*.yml")):
            revision = self.definitions.create_from_yaml(path.read_text(encoding="utf-8"))
            strategy_id = str(revision["strategy_id"])
            active = self.definitions.active(strategy_id)
            active_definition = cast(dict[str, Any], active["definition"]) if active else {}
            new_definition = cast(dict[str, Any], revision["definition"])
            if (
                active is None
                or "portfolio_policy" not in active_definition
                or (
                    strategy_id == "positional_trend_following"
                    and active_definition.get("strategy", {}).get("kind") != "event_signal"
                    and new_definition.get("strategy", {}).get("kind") == "event_signal"
                )
            ):
                self.definitions.activate(str(revision["revision_id"]))

    def revision(self, strategy_id: str) -> dict[str, object]:
        revision = self.definitions.active(strategy_id)
        if revision is None:
            raise DomainValidationError(f"strategy '{strategy_id}' has no active revision")
        return revision

    def strategy_ids(self) -> tuple[str, ...]:
        return tuple(
            item["strategy_id"]
            for item in self.definitions.active_revisions()
        )

    def factor_weights(self, strategy_id: str) -> dict[str, float]:
        definition = cast(dict[str, Any], self.revision(strategy_id)["definition"])
        if self.strategy_kind(strategy_id) == "event_signal":
            raise DomainValidationError("event_signal strategies do not have factor weights")
        return {str(key): float(value) for key, value in definition["factors"].items()}

    def strategy_kind(self, strategy_id: str) -> str:
        definition = cast(dict[str, Any], self.revision(strategy_id)["definition"])
        return str(definition["strategy"].get("kind", "factor_score"))

    def signal_rules(self, strategy_id: str) -> dict[str, object]:
        definition = cast(dict[str, Any], self.revision(strategy_id)["definition"])
        if definition["strategy"].get("kind") != "event_signal":
            raise DomainValidationError("signal rules require an event_signal strategy")
        return {
            **definition["signal_rules"],
            "required_sessions": definition["calculation"]["required_sessions"],
        }

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
        if self.strategy_kind(strategy_id) == "event_signal":
            raise DomainValidationError(
                "event_signal strategies are evaluated by their daily signal job"
            )
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
        """Compute all available sessions without recalculating rolling windows per date.

        Prefers the compiled DAG when available, otherwise falls back to the
        registered Python implementation.
        """
        definition = cast(dict[str, Any], self.revision(strategy_id)["definition"])
        if self.strategy_kind(strategy_id) == "event_signal":
            raise DomainValidationError(
                "event_signal strategies are evaluated by their daily signal job"
            )
        # DAG-first: use compiled DAG when present
        compiled_dag = definition.get("_compiled_dag")
        if compiled_dag is not None:
            return self._compute_dag_series(compiled_dag, bars, benchmark)
        # Fallback: registered Python implementation
        key = str(definition["calculation"]["instrument_implementation"])
        implementation = INSTRUMENT_SERIES_IMPLEMENTATIONS[key]
        if self.benchmark(strategy_id):
            return cast(Any, implementation)(bars, benchmark)
        return cast(Any, implementation)(bars)

    def _compute_dag_series(
        self,
        compiled_dag: list[dict[str, Any]],
        bars: Sequence[dict[str, Any]],
        benchmark: Sequence[dict[str, Any]],
    ) -> dict[str, dict[str, object]]:
        """Execute a compiled DAG and return date-keyed results."""
        if not bars:
            return {}
        graph = DagGraph.from_dict(compiled_dag)
        executor = DagExecutor(self._adapter)
        ohlcv = pd.DataFrame(bars).sort_values("as_of_date").reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            ohlcv[col] = pd.to_numeric(ohlcv[col], errors="coerce")
        bench_df = None
        if benchmark:
            bench_df = pd.DataFrame(benchmark).sort_values("as_of_date").reset_index(drop=True)
            bench_df["close"] = pd.to_numeric(bench_df["close"], errors="coerce")
        results = executor.execute(graph, ohlcv, bench_df)
        # Convert columnar results to date-keyed dicts
        output: dict[str, dict[str, object]] = {}
        dates = ohlcv["as_of_date"].astype(str)
        node_ids = [n.node_id for n in graph.execution_order()]
        for i, day in enumerate(dates):
            row: dict[str, object] = {}
            for node_id in node_ids:
                if node_id in results:
                    val = results[node_id].iloc[i]
                    row[node_id] = float(val) if pd.notna(val) else 0.0
            if row:
                output[day] = row
        return output

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
