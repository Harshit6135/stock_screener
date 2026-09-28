"""Generic indicator DAG: node model, graph validation, and vectorized executor.

A strategy's YAML ``indicators`` and ``operations`` sections compile into a
directed acyclic graph of computation nodes.  Each node has a deterministic
content hash derived solely from its provider, function, parameters, and the
content hashes of its input nodes.  This makes node identity independent of
strategy identity and enables cross-strategy result sharing.

The module is a pure domain component.  It does not import Flask, SQLite
helpers, or provider SDKs.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.platform_kernel import DomainValidationError

from .registry import IndicatorSpec, PandasTaAdapter

# ---------------------------------------------------------------------------
# Primitive field names that are directly available from OHLCV / benchmark data
# ---------------------------------------------------------------------------
PRIMITIVE_FIELDS = frozenset({"open", "high", "low", "close", "volume", "benchmark.close"})

# Operations which have an executable, per-instrument DAG handler.  Keep this
# list next to the dispatcher so publication validation cannot approve a node
# which fails later in a worker.
APPROVED_OPERATIONS = frozenset({
    "add", "subtract", "multiply", "divide", "ratio", "logarithm", "shift",
    "rolling_mean", "rolling_std", "rolling_correlation", "clip", "scale",
    "piecewise_linear", "default", "conditional",
    "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal",
    "equal", "weighted_sum", "abs", "pct_change", "ewm_mean",
})


# ---------------------------------------------------------------------------
# DagNode — a single computation step with a content-addressed identity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DagNode:
    """An immutable computation node in an indicator DAG.

    Parameters
    ----------
    node_id : str
        Human-readable name from the YAML ``id`` field.
    provider : str
        ``"pandas_ta"``, ``"built_in"``, ``"primitive"``, or ``"custom"``.
    function : str
        The concrete function name (e.g. ``"ema"``, ``"divide"``).
    inputs : tuple[tuple[str, str], ...]
        Sorted pairs of ``(parameter_name, source_node_id_or_field)``.
    parameters : tuple[tuple[str, object], ...]
        Sorted pairs of ``(name, value)``.
    output_key : str
        The column / series name that this node produces.
    warmup_bars : int
        Number of leading rows consumed before the first valid output.
    """

    node_id: str
    provider: str
    function: str
    inputs: tuple[tuple[str, str], ...]
    parameters: tuple[tuple[str, object], ...]
    output_key: str
    warmup_bars: int = 0

    def __post_init__(self) -> None:
        if not self.node_id or not self.provider or not self.function:
            raise DomainValidationError("DAG node requires id, provider, and function")
        if not self.output_key:
            raise DomainValidationError("DAG node requires an output_key")

    @property
    def input_refs(self) -> frozenset[str]:
        """Return the set of node IDs / primitive fields this node depends on."""
        return frozenset(ref for _, ref in self.inputs)

    @property
    def content_hash(self) -> str:
        """Deterministic SHA-256 based on provider, function, parameters, and input refs.

        The hash does **not** include ``node_id`` or ``output_key`` — two nodes
        with different YAML ids but identical computation produce the same hash.
        This is what enables cross-strategy sharing of cached results.
        """
        body = json.dumps(
            {
                "provider": self.provider,
                "function": self.function,
                "inputs": list(self.inputs),
                "parameters": list(self.parameters),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(body).hexdigest()


# ---------------------------------------------------------------------------
# DagGraph — the validated computation graph
# ---------------------------------------------------------------------------

class DagGraph:
    """A validated directed acyclic graph of indicator computation nodes.

    Construction validates that every input reference resolves to either a
    primitive field or a declared node, and that no dependency cycles exist.
    """

    def __init__(self, nodes: Sequence[DagNode]) -> None:
        self._nodes: dict[str, DagNode] = {}
        for node in nodes:
            if node.node_id in self._nodes:
                raise DomainValidationError(
                    f"duplicate DAG node id '{node.node_id}'"
                )
            self._nodes[node.node_id] = node
        self._validate_references()
        self._execution_order = self._topological_sort()
        self._content_hashes = self._compute_content_hashes()

    @property
    def nodes(self) -> dict[str, DagNode]:
        return dict(self._nodes)

    def _validate_references(self) -> None:
        """Ensure every input reference points to a declared node or primitive field."""
        known = set(self._nodes) | PRIMITIVE_FIELDS
        for node in self._nodes.values():
            for _, ref in node.inputs:
                if ref not in known:
                    raise DomainValidationError(
                        f"DAG node '{node.node_id}' references unknown input '{ref}'"
                    )

    def _topological_sort(self) -> list[DagNode]:
        """Kahn's algorithm.  Raises on cycles."""
        # Build adjacency: non-primitive inputs → edges
        in_degree: dict[str, int] = {nid: 0 for nid in self._nodes}
        dependents: dict[str, list[str]] = defaultdict(list)
        for nid, node in self._nodes.items():
            for _, ref in node.inputs:
                if ref in self._nodes:
                    in_degree[nid] += 1
                    dependents[ref].append(nid)

        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        ordered: list[DagNode] = []
        while queue:
            nid = queue.popleft()
            ordered.append(self._nodes[nid])
            for dependent in dependents[nid]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(ordered) != len(self._nodes):
            # Remaining nodes form a cycle
            remaining = set(self._nodes) - {n.node_id for n in ordered}
            raise DomainValidationError(
                f"DAG contains a dependency cycle involving: {', '.join(sorted(remaining))}"
            )
        return ordered

    def execution_order(self) -> list[DagNode]:
        """Return nodes in a safe execution order (dependencies before dependents)."""
        return list(self._execution_order)

    def max_warmup(self, specs: Mapping[str, IndicatorSpec] | None = None) -> int:
        """Compute the maximum warmup bars needed across all paths in the graph.

        For chained indicators (e.g. EMA of RSI), warmup periods are additive.
        For parallel branches, only the maximum matters.
        """
        memo: dict[str, int] = {}

        def _warmup(node_id: str) -> int:
            if node_id in memo:
                return memo[node_id]
            if node_id in PRIMITIVE_FIELDS:
                return 0
            if node_id not in self._nodes:
                return 0
            node = self._nodes[node_id]
            # Warmup from this node's own computation
            own = node.warmup_bars
            # Max warmup from inputs (chained)
            upstream = max(
                (_warmup(ref) for _, ref in node.inputs),
                default=0,
            )
            total = own + upstream
            memo[node_id] = total
            return total

        return max((_warmup(nid) for nid in self._nodes), default=0)

    def unique_content_hashes(self) -> dict[str, str]:
        """Return graph-resolved, recursive content identities by node id.

        A node's standalone ``DagNode.content_hash`` remains useful for a
        leaf, but cannot identify a graph because its string references are
        local names.  These hashes replace each node reference with that
        dependency's identity in topological order.
        """
        return dict(self._content_hashes)

    def content_hash(self, node_id: str) -> str:
        """Return the graph-resolved identity for ``node_id``."""
        try:
            return self._content_hashes[node_id]
        except KeyError as exc:
            raise DomainValidationError(f"unknown DAG node '{node_id}'") from exc

    def _compute_content_hashes(self) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for node in self._execution_order:
            dependencies = [
                (role, hashes.get(ref, {"primitive": ref}))
                for role, ref in node.inputs
            ]
            body = json.dumps(
                {
                    "provider": node.provider,
                    "function": node.function,
                    "inputs": dependencies,
                    "parameters": list(node.parameters),
                    # This identifies a selected output of a multi-output
                    # provider without incorporating its local node name.
                    "output_key": node.output_key,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            hashes[node.node_id] = hashlib.sha256(body).hexdigest()
        return hashes

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> list[dict[str, object]]:
        """Serialize the graph to a JSON-safe list of node dicts."""
        return [
            {
                "node_id": node.node_id,
                "provider": node.provider,
                "function": node.function,
                "inputs": list(node.inputs),
                "parameters": list(node.parameters),
                "output_key": node.output_key,
                "warmup_bars": node.warmup_bars,
            }
            for node in self._execution_order
        ]

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]]) -> DagGraph:
        """Deserialize a graph from a list of node dicts."""
        nodes = [
            DagNode(
                node_id=str(item["node_id"]),
                provider=str(item["provider"]),
                function=str(item["function"]),
                inputs=tuple(tuple(pair) for pair in item["inputs"]),
                parameters=tuple(tuple(pair) for pair in item["parameters"]),
                output_key=str(item["output_key"]),
                warmup_bars=int(item.get("warmup_bars", 0)),
            )
            for item in data
        ]
        return cls(nodes)

    @classmethod
    def from_yaml_sections(
        cls,
        indicators: list[dict[str, Any]],
        operations: list[dict[str, Any]] | None = None,
        adapter: PandasTaAdapter | None = None,
    ) -> DagGraph:
        """Build a ``DagGraph`` from the YAML ``indicators`` and ``operations`` sections.

        Indicator warmup is resolved from the adapter's spec catalogue when
        an adapter is provided.
        """
        nodes: list[DagNode] = []
        for item in indicators:
            function = str(item["function"])
            warmup = 0
            if adapter is not None:
                try:
                    spec = adapter.spec(function)
                    warmup_param = spec.warmup_parameter
                    if warmup_param is not None:
                        params = item.get("parameters", {})
                        warmup = int(params.get(warmup_param, spec.parameters[warmup_param]["default"]))
                except DomainValidationError:
                    pass  # non-pandas_ta provider
            raw_inputs = item.get("inputs", {})
            nodes.append(
                DagNode(
                    node_id=str(item["id"]),
                    provider=str(item.get("provider", "pandas_ta")),
                    function=function,
                    inputs=tuple(sorted(raw_inputs.items())),
                    parameters=tuple(sorted(item.get("parameters", {}).items())),
                    output_key=str(item.get("output", item["id"])),
                    warmup_bars=warmup,
                )
            )
        for item in (operations or []):
            operation = str(item.get("operation", item.get("function", "")))
            if operation and operation not in APPROVED_OPERATIONS:
                raise DomainValidationError(f"operation '{operation}' is not approved")
            raw_inputs = {}
            for key in ("input", "left", "right", "factor", "numerator", "denominator"):
                ref = item.get(key)
                if isinstance(ref, str):
                    raw_inputs[key] = ref
            warmup = 0
            params = item.get("parameters", {})
            for wp in ("length", "periods", "window", "span"):
                if wp in params:
                    warmup = max(warmup, int(params[wp]))
            nodes.append(
                DagNode(
                    node_id=str(item["id"]),
                    provider="built_in",
                    function=operation,
                    inputs=tuple(sorted(raw_inputs.items())),
                    parameters=tuple(sorted(params.items())),
                    output_key=str(item.get("output", item["id"])),
                    warmup_bars=warmup,
                )
            )
        return cls(nodes)


# ---------------------------------------------------------------------------
# DagExecutor — vectorized execution of a DagGraph
# ---------------------------------------------------------------------------

class DagExecutor:
    """Execute a ``DagGraph`` against OHLCV data in one vectorized pass.

    The executor processes nodes in topological order.  Each node's result
    is a ``pd.Series`` aligned to the input OHLCV DataFrame index.
    """

    def __init__(self, adapter: PandasTaAdapter) -> None:
        self._adapter = adapter

    def execute(
        self,
        graph: DagGraph,
        ohlcv: pd.DataFrame,
        benchmark: pd.DataFrame | None = None,
        precomputed: dict[str, pd.Series] | None = None,
    ) -> dict[str, pd.Series]:
        """Execute all nodes and return ``{output_key: series}``."""
        if ohlcv.empty:
            return {}

        # Seed the result pool with primitive fields and precomputed nodes
        results: dict[str, pd.Series] = dict(precomputed) if precomputed else {}
        for col in ("open", "high", "low", "close", "volume"):
            if col in ohlcv.columns and col not in results:
                results[col] = pd.to_numeric(ohlcv[col], errors="coerce").astype("float64")

        if benchmark is not None and not benchmark.empty and "benchmark.close" not in results:
            bench_close = pd.to_numeric(benchmark["close"], errors="coerce").astype("float64")
            # Align benchmark to OHLCV index via date-based join
            if "as_of_date" in benchmark.columns and "as_of_date" in ohlcv.columns:
                bench_by_date = pd.Series(
                    bench_close.to_numpy(),
                    index=benchmark["as_of_date"].astype(str).to_numpy(),
                )
                aligned = bench_by_date.reindex(
                    ohlcv["as_of_date"].astype(str), method="ffill"
                )
                aligned.index = ohlcv.index
                results["benchmark.close"] = aligned.astype("float64")
            else:
                results["benchmark.close"] = bench_close.reindex(ohlcv.index, method="ffill").astype("float64")

        for node in graph.execution_order():
            if node.node_id in results:
                # Also store by output_key if different from node_id (for precomputed nodes)
                if node.output_key != node.node_id:
                    results[node.output_key] = results[node.node_id]
                continue
                
            result = self._execute_node(node, results)
            results[node.node_id] = result
            # Also store by output_key if different from node_id
            if node.output_key != node.node_id:
                results[node.output_key] = result

        return results

    def _execute_node(
        self, node: DagNode, results: dict[str, pd.Series]
    ) -> pd.Series:
        """Dispatch a single node to the appropriate executor."""
        if node.provider == "pandas_ta":
            return self._execute_pandas_ta(node, results)
        if node.provider == "built_in":
            return self._execute_operation(node, results)
        raise DomainValidationError(
            f"DAG node '{node.node_id}' has unsupported provider '{node.provider}'"
        )

    def _execute_pandas_ta(
        self, node: DagNode, results: dict[str, pd.Series]
    ) -> pd.Series:
        """Execute a Pandas TA indicator node.

        When chaining indicators (e.g. EMA of RSI), upstream outputs may
        contain NaN values in their warmup region.  The strict adapter
        validation rejects NaN, so we call pandas_ta directly with the raw
        series and let the underlying implementation handle NaN naturally.
        """
        raw_inputs = {param: results[ref] for param, ref in node.inputs}
        parameters = dict(node.parameters)
        spec = self._adapter.spec(node.function)

        # Check if any input contains NaN (chained indicator scenario)
        has_nan = any(s.isna().any() for s in raw_inputs.values())

        if not has_nan:
            # No NaN — safe to use the strict adapter path
            frame = self._adapter.calculate(node.function, raw_inputs, parameters)
        else:
            # Chained indicator — call pandas_ta directly with NaN-tolerant inputs
            import pandas_ta  # type: ignore[import-untyped]

            validated_params = self._adapter.validate_parameters(spec, parameters)
            series = {name: s.astype("float64") for name, s in raw_inputs.items()}
            function = getattr(pandas_ta, node.function, None)
            if function is None:
                raise DomainValidationError(
                    f"installed pandas_ta does not provide '{node.function}'"
                )
            try:
                result = function(**series, **validated_params)
            except (TypeError, ValueError) as exc:
                raise DomainValidationError(
                    f"indicator '{node.function}' could not be calculated: {exc}"
                ) from exc
            frame = result.to_frame(name=node.function) if isinstance(result, pd.Series) else result
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                raise DomainValidationError(
                    f"indicator '{node.function}' returned no values"
                )
            frame = frame.copy().astype("float64")

        # Select the appropriate output column
        if len(spec.outputs) == 1:
            return frame.iloc[:, 0]

        # Multi-output indicator: match by output_key or first column
        for col in frame.columns:
            col_lower = str(col).lower()
            if node.output_key.lower() in col_lower or node.function.lower() in col_lower:
                return frame[col]
        # Fall back to first column
        return frame.iloc[:, 0]

    def _execute_operation(
        self, node: DagNode, results: dict[str, pd.Series]
    ) -> pd.Series:
        """Execute a built-in mathematical operation node."""
        params = dict(node.parameters)
        inputs = dict(node.inputs)

        def _resolve(key: str) -> pd.Series:
            ref = inputs.get(key)
            if ref is None:
                raise DomainValidationError(
                    f"operation '{node.node_id}' is missing required input '{key}'"
                )
            if ref not in results:
                raise DomainValidationError(
                    f"operation '{node.node_id}' references unresolved input '{ref}'"
                )
            return results[ref]

        def _resolve_optional(key: str) -> pd.Series | None:
            ref = inputs.get(key)
            if ref is None:
                return None
            return results.get(ref)

        fn = node.function

        # Arithmetic
        if fn == "add":
            return _resolve("left") + _resolve("right")
        if fn == "subtract":
            return _resolve("left") - _resolve("right")
        if fn == "multiply":
            return _resolve("left") * _resolve("right")
        if fn in ("divide", "ratio"):
            right = _resolve("right")
            return _resolve("left") / right.replace(0, float("nan"))
        if fn == "logarithm":
            series = _resolve("input")
            return series.map(
                lambda x: math.log(x) if x > 0 and math.isfinite(x) else float("nan"),
                na_action="ignore",
            )
        if fn == "abs":
            return _resolve("input").abs()

        # Time-series
        if fn == "shift":
            periods = int(params.get("periods", 1))
            return _resolve("input").shift(periods)
        if fn == "pct_change":
            periods = int(params.get("periods", 1))
            return _resolve("input").pct_change(periods)
        if fn == "rolling_mean":
            window = int(params.get("length", params.get("window", 20)))
            return _resolve("input").rolling(window, min_periods=window).mean()
        if fn == "rolling_std":
            window = int(params.get("length", params.get("window", 20)))
            ddof = int(params.get("ddof", 0))
            return _resolve("input").rolling(window, min_periods=window).std(ddof=ddof)
        if fn == "rolling_correlation":
            window = int(params.get("length", params.get("window", 20)))
            return _resolve("left").rolling(window).corr(_resolve("right"))
        if fn == "ewm_mean":
            span = int(params.get("span", 20))
            return _resolve("input").ewm(span=span, adjust=False, min_periods=span).mean()

        # Shaping
        if fn == "clip":
            low = float(params.get("low", float("-inf")))
            high = float(params.get("high", float("inf")))
            return _resolve("input").clip(lower=low, upper=high)
        if fn == "scale":
            factor = float(params.get("factor", 1.0))
            offset = float(params.get("offset", 0.0))
            return _resolve("input") * factor + offset

        # Scoring
        if fn == "piecewise_linear":
            series = _resolve("input")
            breakpoints = [float(b) for b in params["breakpoints"]]
            values = [float(v) for v in params["values"]]
            if len(breakpoints) != len(values):
                raise DomainValidationError(
                    f"piecewise_linear '{node.node_id}': breakpoints and values must have equal length"
                )
            return series.map(
                lambda x: _interpolate_piecewise(x, breakpoints, values),
                na_action="ignore",
            )

        # Comparison / boolean
        if fn == "greater_than":
            return (_resolve("left") > _resolve("right")).astype("float64")
        if fn == "greater_than_or_equal":
            return (_resolve("left") >= _resolve("right")).astype("float64")
        if fn == "less_than":
            return (_resolve("left") < _resolve("right")).astype("float64")
        if fn == "less_than_or_equal":
            return (_resolve("left") <= _resolve("right")).astype("float64")
        if fn == "equal":
            return (_resolve("left") == _resolve("right")).astype("float64")

        # Default / conditional
        if fn == "default":
            primary = _resolve("input")
            fallback = float(params.get("value", 0.0))
            return primary.fillna(fallback)
        if fn == "conditional":
            condition = _resolve("input")
            true_val = float(params.get("true_value", 1.0))
            false_val = float(params.get("false_value", 0.0))
            return condition.map(
                lambda x: true_val if x > 0 else false_val, na_action="ignore"
            )

        # Weighted sum is typically applied across factor nodes at the scoring
        # level.  For the DAG it simply multiplies an input by a weight.
        if fn == "weighted_sum":
            weight = float(params.get("weight", 1.0))
            return _resolve("input") * weight

        raise DomainValidationError(
            f"DAG operation '{fn}' in node '{node.node_id}' is not yet implemented"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _interpolate_piecewise(
    x: float, breakpoints: list[float], values: list[float]
) -> float:
    """Linear interpolation between breakpoints; flat extrapolation at edges."""
    if not math.isfinite(x):
        return float("nan")
    if x <= breakpoints[0]:
        return values[0]
    if x >= breakpoints[-1]:
        return values[-1]
    for i in range(len(breakpoints) - 1):
        if breakpoints[i] <= x <= breakpoints[i + 1]:
            span = breakpoints[i + 1] - breakpoints[i]
            if span == 0:
                return values[i]
            fraction = (x - breakpoints[i]) / span
            return values[i] + fraction * (values[i + 1] - values[i])
    return values[-1]
