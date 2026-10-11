import math

import pandas as pd
import pytest

from src.domains.indicators.dag import APPROVED_OPERATIONS, DagExecutor, DagGraph, DagNode
from src.domains.indicators.registry import PandasTaAdapter
from src.platform_kernel import DomainValidationError


def case(function, *, inputs=None, parameters=(), expected, prerequisite=None):
    return (function, inputs or (("input", "close"),), parameters, expected, prerequisite)


CASES = [
    case("add", inputs=(("left", "close"), ("right", "open")), expected=[3, 6, 6, 16]),
    case("subtract", inputs=(("left", "close"), ("right", "open")), expected=[-1, -2, 2, 0]),
    case("multiply", inputs=(("left", "close"), ("right", "open")), expected=[2, 8, 8, 64]),
    case("divide", inputs=(("left", "close"), ("right", "open")), expected=[0.5, 0.5, 2, 1]),
    case("ratio", inputs=(("left", "close"), ("right", "open")), expected=[0.5, 0.5, 2, 1]),
    case("logarithm", expected=[0, math.log(2), math.log(4), math.log(8)]),
    case("shift", parameters=(("periods", 1),), expected=[None, 1, 2, 4]),
    case("rolling_mean", parameters=(("length", 2),), expected=[None, 1.5, 3, 6]),
    case("rolling_std", parameters=(("length", 2), ("ddof", 0)), expected=[None, 0.5, 1, 2]),
    case(
        "rolling_correlation",
        inputs=(("left", "close"), ("right", "open")),
        parameters=(("length", 2),),
        expected=[None, 1, -1, 1],
    ),
    case("clip", parameters=(("low", 2), ("high", 4)), expected=[2, 2, 4, 4]),
    case("scale", parameters=(("factor", 2), ("offset", 3)), expected=[5, 7, 11, 19]),
    case(
        "piecewise_linear",
        parameters=(("breakpoints", [1, 4, 8]), ("values", [0, 0.5, 1])),
        expected=[0, 1 / 6, 0.5, 1],
    ),
    case(
        "default",
        inputs=(("input", "lag"),),
        parameters=(("value", 10),),
        expected=[10, 1, 2, 4],
        prerequisite=DagNode(
            "lag", "built_in", "shift", (("input", "close"),), (("periods", 1),), "lag"
        ),
    ),
    case(
        "conditional",
        inputs=(("input", "diff"),),
        expected=[0, 0, 1, 0],
        prerequisite=DagNode(
            "diff", "built_in", "subtract", (("left", "close"), ("right", "open")), (), "diff"
        ),
    ),
    case("greater_than", inputs=(("left", "close"), ("right", "open")), expected=[0, 0, 1, 0]),
    case(
        "greater_than_or_equal",
        inputs=(("left", "close"), ("right", "open")),
        expected=[0, 0, 1, 1],
    ),
    case("less_than", inputs=(("left", "close"), ("right", "open")), expected=[1, 1, 0, 0]),
    case(
        "less_than_or_equal", inputs=(("left", "close"), ("right", "open")), expected=[1, 1, 0, 1]
    ),
    case("equal", inputs=(("left", "close"), ("right", "open")), expected=[0, 0, 0, 1]),
    case("weighted_sum", parameters=(("weight", 2),), expected=[2, 4, 8, 16]),
    case(
        "abs",
        inputs=(("input", "diff"),),
        expected=[1, 2, 2, 0],
        prerequisite=DagNode(
            "diff", "built_in", "subtract", (("left", "close"), ("right", "open")), (), "diff"
        ),
    ),
    case("pct_change", parameters=(("periods", 1),), expected=[None, 1, 1, 1]),
    case("ewm_mean", parameters=(("span", 2),), expected=[None, 5 / 3, 29 / 9, 173 / 27]),
]


def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    import numpy as np

    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    close = np.maximum(close, 10)
    return pd.DataFrame(
        {
            "as_of_date": [d.strftime("%Y-%m-%d") for d in dates],
            "open": close * (1 + np.random.randn(n) * 0.001),
            "high": close * (1 + abs(np.random.randn(n)) * 0.005),
            "low": close * (1 - abs(np.random.randn(n)) * 0.005),
            "close": close,
            "volume": np.random.randint(100000, 1000000, n).astype(float),
        }
    )


def _identity_graph(prefix: str, length: int = 20) -> DagGraph:
    return DagGraph(
        [
            DagNode(
                f"{prefix}_ema",
                "pandas_ta",
                "ema",
                (("close", "close"),),
                (("length", length),),
                "ema",
            ),
            DagNode(
                f"{prefix}_ratio",
                "built_in",
                "ratio",
                (("left", "close"), ("right", f"{prefix}_ema")),
                (),
                "ratio",
            ),
        ]
    )


@pytest.mark.parametrize(
    ("function", "inputs", "parameters", "expected", "prerequisite"),
    CASES,
    ids=[item[0] for item in CASES],
)
def test_every_approved_operation_executes_with_expected_values(
    function, inputs, parameters, expected, prerequisite
):
    frame = pd.DataFrame(
        {
            "close": [1, 2, 4, 8],
            "open": [2, 4, 2, 8],
            "high": [3, 5, 5, 9],
            "low": [0.5, 1, 1, 7],
            "volume": [10, 20, 40, 80],
        }
    )
    node = DagNode("result", "built_in", function, inputs, parameters, "result")
    graph = DagGraph(([prerequisite] if prerequisite is not None else []) + [node])
    actual = DagExecutor(PandasTaAdapter()).execute(graph, frame)["result"].tolist()
    for observed, wanted in zip(actual, expected):
        if wanted is None:
            assert math.isnan(observed)
        else:
            assert observed == pytest.approx(wanted, abs=1e-09)


def test_approved_operation_manifest_has_an_executable_case_for_every_handler():
    assert {item[0] for item in CASES} == APPROVED_OPERATIONS


def test_recursive_hash_ignores_renamed_nodes_but_tracks_ancestors():
    first = _identity_graph("one")
    renamed = _identity_graph("two")
    changed = _identity_graph("three", length=50)
    assert first.content_hash("one_ratio") == renamed.content_hash("two_ratio")
    assert first.content_hash("one_ratio") != changed.content_hash("three_ratio")


def test_graph_hash_respects_operand_roles_and_parent_parameters():

    def graph(left, right, *, size=2, prefix="one"):
        return DagGraph(
            [
                DagNode(
                    prefix,
                    "built_in",
                    "rolling_mean",
                    (("input", "close"),),
                    (("length", size),),
                    prefix,
                ),
                DagNode(
                    prefix + "_ratio",
                    "built_in",
                    "ratio",
                    (
                        ("left", left if left == "close" else prefix),
                        ("right", right if right == "close" else prefix),
                    ),
                    (),
                    prefix + "_ratio",
                ),
            ]
        )

    normal = graph("close", "node")
    renamed = graph("close", "node", prefix="other")
    reversed_roles = graph("node", "close")
    changed_parent = graph("close", "node", size=3)
    assert normal.content_hash("one_ratio") == renamed.content_hash("other_ratio")
    assert normal.content_hash("one_ratio") != reversed_roles.content_hash("one_ratio")
    assert normal.content_hash("one_ratio") != changed_parent.content_hash("one_ratio")


class TestDagNode:
    def test_content_hash_is_deterministic(self):
        a = DagNode(
            "ema_fast", "pandas_ta", "ema", (("close", "close"),), (("length", 20),), "ema_20", 20
        )
        b = DagNode(
            "ema_fast", "pandas_ta", "ema", (("close", "close"),), (("length", 20),), "ema_20", 20
        )
        assert a.content_hash == b.content_hash

    def test_content_hash_ignores_node_id_and_output_key(self):
        """Two nodes with different YAML ids but identical computation share a hash."""
        a = DagNode(
            "momentum_ema",
            "pandas_ta",
            "ema",
            (("close", "close"),),
            (("length", 50),),
            "my_ema",
            50,
        )
        b = DagNode(
            "benchmark_ema",
            "pandas_ta",
            "ema",
            (("close", "close"),),
            (("length", 50),),
            "other_ema",
            50,
        )
        assert a.content_hash == b.content_hash

    def test_content_hash_differs_on_parameters(self):
        a = DagNode(
            "ema20", "pandas_ta", "ema", (("close", "close"),), (("length", 20),), "ema_20", 20
        )
        b = DagNode(
            "ema50", "pandas_ta", "ema", (("close", "close"),), (("length", 50),), "ema_50", 50
        )
        assert a.content_hash != b.content_hash

    def test_content_hash_differs_on_function(self):
        a = DagNode(
            "ind_a", "pandas_ta", "ema", (("close", "close"),), (("length", 20),), "out", 20
        )
        b = DagNode(
            "ind_b", "pandas_ta", "sma", (("close", "close"),), (("length", 20),), "out", 20
        )
        assert a.content_hash != b.content_hash

    def test_input_refs(self):
        node = DagNode(
            "atr",
            "pandas_ta",
            "atr",
            (("close", "close"), ("high", "high"), ("low", "low")),
            (("length", 14),),
            "atr_14",
            14,
        )
        assert node.input_refs == {"close", "high", "low"}

    def test_requires_id_provider_function(self):
        with pytest.raises(DomainValidationError):
            DagNode("", "pandas_ta", "ema", (), (), "out")
        with pytest.raises(DomainValidationError):
            DagNode("id", "", "ema", (), (), "out")
        with pytest.raises(DomainValidationError):
            DagNode("id", "pandas_ta", "", (), (), "out")

    def test_requires_output_key(self):
        with pytest.raises(DomainValidationError):
            DagNode("id", "pandas_ta", "ema", (), (), "")


class TestDagGraph:
    def _make_ema_chain(self) -> list[DagNode]:
        return [
            DagNode(
                "ema20", "pandas_ta", "ema", (("close", "close"),), (("length", 20),), "ema_20", 20
            ),
            DagNode(
                "ema50", "pandas_ta", "ema", (("close", "close"),), (("length", 50),), "ema_50", 50
            ),
            DagNode(
                "distance",
                "built_in",
                "ratio",
                (("left", "close"), ("right", "ema50")),
                (),
                "ema_distance",
            ),
        ]

    def test_basic_graph_creation(self):
        nodes = self._make_ema_chain()
        graph = DagGraph(nodes)
        assert len(graph.nodes) == 3

    def test_execution_order_respects_dependencies(self):
        nodes = self._make_ema_chain()
        graph = DagGraph(nodes)
        order = [n.node_id for n in graph.execution_order()]
        assert order.index("ema50") < order.index("distance")

    def test_duplicate_node_ids_rejected(self):
        node = DagNode(
            "ema", "pandas_ta", "ema", (("close", "close"),), (("length", 20),), "ema_20", 20
        )
        with pytest.raises(DomainValidationError, match="duplicate"):
            DagGraph([node, node])

    def test_cycle_detection(self):
        a = DagNode("a", "built_in", "add", (("left", "b"), ("right", "close")), (), "out_a")
        b = DagNode("b", "built_in", "add", (("left", "a"), ("right", "close")), (), "out_b")
        with pytest.raises(DomainValidationError, match="cycle"):
            DagGraph([a, b])

    def test_unknown_reference_rejected(self):
        node = DagNode(
            "x", "built_in", "add", (("left", "nonexistent"), ("right", "close")), (), "out"
        )
        with pytest.raises(DomainValidationError, match="unknown"):
            DagGraph([node])

    def test_primitive_fields_accepted(self):
        node = DagNode("x", "built_in", "add", (("left", "close"), ("right", "volume")), (), "out")
        graph = DagGraph([node])
        assert len(graph.execution_order()) == 1

    def test_max_warmup_simple(self):
        nodes = [
            DagNode(
                "ema20", "pandas_ta", "ema", (("close", "close"),), (("length", 20),), "ema_20", 20
            ),
            DagNode(
                "ema50", "pandas_ta", "ema", (("close", "close"),), (("length", 50),), "ema_50", 50
            ),
        ]
        graph = DagGraph(nodes)
        assert graph.max_warmup() == 50

    def test_max_warmup_chained(self):
        """Chained indicators: EMA(20) of RSI(14) needs 14 + 20 = 34 bars."""
        nodes = [
            DagNode(
                "rsi", "pandas_ta", "rsi", (("close", "close"),), (("length", 14),), "rsi_14", 14
            ),
            DagNode(
                "rsi_ema",
                "pandas_ta",
                "ema",
                (("close", "rsi"),),
                (("length", 20),),
                "rsi_ema_20",
                20,
            ),
        ]
        graph = DagGraph(nodes)
        assert graph.max_warmup() == 34

    def test_serialization_round_trip(self):
        nodes = self._make_ema_chain()
        graph = DagGraph(nodes)
        serialized = graph.to_dict()
        restored = DagGraph.from_dict(serialized)
        assert len(restored.nodes) == len(graph.nodes)
        for nid in graph.nodes:
            assert graph.nodes[nid].content_hash == restored.nodes[nid].content_hash

    def test_unique_content_hashes(self):
        nodes = self._make_ema_chain()
        graph = DagGraph(nodes)
        hashes = graph.unique_content_hashes()
        assert len(hashes) == 3
        assert hashes["ema20"] != hashes["ema50"]


class TestDagGraphFromYaml:
    def test_build_from_yaml_indicators(self):
        indicators = [
            {
                "id": "ema_20",
                "provider": "pandas_ta",
                "function": "ema",
                "inputs": {"close": "close"},
                "parameters": {"length": 20},
                "output": "ema_20",
            },
            {
                "id": "rsi_14",
                "provider": "pandas_ta",
                "function": "rsi",
                "inputs": {"close": "close"},
                "parameters": {"length": 14},
                "output": "rsi_14",
            },
        ]
        adapter = PandasTaAdapter()
        graph = DagGraph.from_yaml_sections(indicators, adapter=adapter)
        assert len(graph.nodes) == 2
        assert graph.max_warmup() == 20

    def test_build_with_operations(self):
        indicators = [
            {
                "id": "ema_50",
                "provider": "pandas_ta",
                "function": "ema",
                "inputs": {"close": "close"},
                "parameters": {"length": 50},
                "output": "ema_50",
            }
        ]
        operations = [
            {
                "id": "ema_distance",
                "operation": "ratio",
                "left": "close",
                "right": "ema_50",
                "output": "ema_distance",
            }
        ]
        graph = DagGraph.from_yaml_sections(indicators, operations)
        assert len(graph.nodes) == 2
        order = [n.node_id for n in graph.execution_order()]
        assert order.index("ema_50") < order.index("ema_distance")


class TestDagExecutor:
    @pytest.fixture
    def adapter(self) -> PandasTaAdapter:
        return PandasTaAdapter()

    @pytest.fixture
    def ohlcv(self) -> pd.DataFrame:
        return _make_ohlcv(200)

    def test_execute_single_ema(self, adapter, ohlcv):
        nodes = [
            DagNode(
                "ema_20", "pandas_ta", "ema", (("close", "close"),), (("length", 20),), "ema_20", 20
            )
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "ema_20" in results
        assert results["ema_20"].iloc[19:].notna().all()

    def test_execute_chained_ema_of_rsi(self, adapter, ohlcv):
        nodes = [
            DagNode(
                "rsi_14", "pandas_ta", "rsi", (("close", "close"),), (("length", 14),), "rsi_14", 14
            ),
            DagNode(
                "rsi_ema",
                "pandas_ta",
                "ema",
                (("close", "rsi_14"),),
                (("length", 10),),
                "rsi_ema",
                10,
            ),
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "rsi_ema" in results
        valid = results["rsi_ema"].iloc[30:].dropna()
        assert len(valid) > 0

    def test_execute_arithmetic_operations(self, adapter, ohlcv):
        nodes = [
            DagNode(
                "ema_50", "pandas_ta", "ema", (("close", "close"),), (("length", 50),), "ema_50", 50
            ),
            DagNode(
                "distance",
                "built_in",
                "ratio",
                (("left", "close"), ("right", "ema_50")),
                (),
                "distance",
            ),
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "distance" in results
        valid_idx = results["ema_50"].dropna().index
        close = ohlcv["close"].astype(float)
        expected = close.loc[valid_idx] / results["ema_50"].loc[valid_idx]
        pd.testing.assert_series_equal(
            results["distance"].loc[valid_idx], expected, check_names=False, atol=1e-10
        )

    def test_execute_shift_operation(self, adapter, ohlcv):
        nodes = [
            DagNode(
                "shifted",
                "built_in",
                "shift",
                (("input", "close"),),
                (("periods", 5),),
                "shifted_5",
                5,
            )
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "shifted" in results
        close = ohlcv["close"].astype(float)
        expected = close.shift(5)
        pd.testing.assert_series_equal(results["shifted"], expected, check_names=False, atol=1e-10)

    def test_execute_clip_operation(self, adapter, ohlcv):
        nodes = [
            DagNode(
                "clipped",
                "built_in",
                "clip",
                (("input", "close"),),
                (("low", 95.0), ("high", 105.0)),
                "clipped",
            )
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert results["clipped"].min() >= 95.0
        assert results["clipped"].max() <= 105.0

    def test_execute_piecewise_linear(self, adapter, ohlcv):
        nodes = [
            DagNode(
                "scored",
                "built_in",
                "piecewise_linear",
                (("input", "close"),),
                (("breakpoints", [90, 100, 110]), ("values", [0, 50, 100])),
                "scored",
            )
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "scored" in results
        for i, c in enumerate(ohlcv["close"].astype(float)):
            if abs(c - 100) < 0.01:
                assert abs(results["scored"].iloc[i] - 50) < 1

    def test_execute_with_benchmark(self, adapter, ohlcv):
        benchmark = _make_ohlcv(200)
        nodes = [
            DagNode(
                "rel",
                "built_in",
                "ratio",
                (("left", "close"), ("right", "benchmark.close")),
                (),
                "relative_price",
            )
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv, benchmark)
        assert "rel" in results
        assert results["rel"].notna().sum() > 0

    def test_execute_empty_dataframe(self, adapter):
        ohlcv = pd.DataFrame()
        nodes = [
            DagNode(
                "ema", "pandas_ta", "ema", (("close", "close"),), (("length", 20),), "ema_20", 20
            )
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert results == {}

    def test_execute_multi_output_indicator(self, adapter, ohlcv):
        """MACD produces 3 columns; the node should select the correct one."""
        nodes = [
            DagNode(
                "macd_line",
                "pandas_ta",
                "macd",
                (("close", "close"),),
                (("fast", 12), ("signal", 9), ("slow", 26)),
                "macd",
                26,
            )
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "macd_line" in results
        valid = results["macd_line"].iloc[30:].dropna()
        assert len(valid) > 0


def test_semantic_output_hash_ignores_local_alias_but_distinguishes_different_series():

    def graph(node_id, output_key):
        return DagGraph(
            [DagNode(node_id, "pandas_ta", "macd", (("close", "close"),), (), output_key)]
        )

    assert graph("hist", "histogram").content_hash("hist") == graph(
        "renamed", "my_histogram"
    ).content_hash("renamed")
    assert graph("hist", "histogram").content_hash("hist") != graph(
        "signal", "signal"
    ).content_hash("signal")
    assert graph("default", "custom_alias").content_hash("default") == graph(
        "base", "macd"
    ).content_hash("base")
    assert DagGraph(
        [DagNode("ema", "pandas_ta", "ema", (("close", "close"),), (), "local")]
    ).content_hash("ema") == DagGraph(
        [DagNode("renamed", "pandas_ta", "ema", (("close", "close"),), (), "other")]
    ).content_hash("renamed")


def test_compiled_graph_rejects_unsupported_operation_at_construction():
    with pytest.raises(DomainValidationError, match="unsupported operation 'percentile_rank'"):
        DagGraph.from_dict(
            [
                {
                    "node_id": "bad",
                    "provider": "built_in",
                    "function": "percentile_rank",
                    "inputs": [["input", "close"]],
                    "parameters": [],
                    "output_key": "bad",
                }
            ]
        )


@pytest.mark.parametrize(
    ("function", "inputs", "parameters", "selector", "column_prefix"),
    [
        (
            "macd",
            (("close", "close"),),
            (("fast", 12), ("slow", 26), ("signal", 9)),
            "histogram",
            "MACDh",
        ),
        (
            "macd",
            (("close", "close"),),
            (("fast", 12), ("slow", 26), ("signal", 9)),
            "signal",
            "MACDs",
        ),
        ("bbands", (("close", "close"),), (("length", 20), ("std", 2)), "upper", "BBU"),
        (
            "adx",
            (("high", "high"), ("low", "low"), ("close", "close")),
            (("length", 14), ("lensig", 14)),
            "dmp",
            "DMP",
        ),
    ],
)
def test_multi_output_selection_matches_provider_column(
    function, inputs, parameters, selector, column_prefix
):
    frame = pd.DataFrame(
        {
            "close": [100 + i + i % 7 for i in range(100)],
            "high": [103 + i + i % 7 for i in range(100)],
            "low": [97 + i + i % 7 for i in range(100)],
        }
    )
    adapter = PandasTaAdapter()
    expected_frame = adapter.calculate(
        function, {name: frame[ref] for name, ref in inputs}, dict(parameters)
    )
    expected_column = next(
        col for col in expected_frame.columns if str(col).split("_", 1)[0] == column_prefix
    )
    node = DagNode("chosen", "pandas_ta", function, inputs, parameters, selector)
    actual = DagExecutor(adapter).execute(DagGraph([node]), frame)["chosen"]
    pd.testing.assert_series_equal(actual, expected_frame[expected_column])
