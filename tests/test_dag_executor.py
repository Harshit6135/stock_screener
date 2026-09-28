"""Tests for the generic indicator DAG engine."""

import math
from collections.abc import Sequence

import pandas as pd
import pytest

from src.indicators.dag import DagExecutor, DagGraph, DagNode, PRIMITIVE_FIELDS
from src.indicators.registry import PandasTaAdapter
from src.platform_kernel import DomainValidationError


# ---------------------------------------------------------------------------
# DagNode tests
# ---------------------------------------------------------------------------

class TestDagNode:
    def test_content_hash_is_deterministic(self):
        a = DagNode("ema_fast", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 20),), "ema_20", 20)
        b = DagNode("ema_fast", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 20),), "ema_20", 20)
        assert a.content_hash == b.content_hash

    def test_content_hash_ignores_node_id_and_output_key(self):
        """Two nodes with different YAML ids but identical computation share a hash."""
        a = DagNode("strategy1_ema", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 50),), "my_ema", 50)
        b = DagNode("strategy2_ema", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 50),), "other_ema", 50)
        assert a.content_hash == b.content_hash

    def test_content_hash_differs_on_parameters(self):
        a = DagNode("ema20", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 20),), "ema_20", 20)
        b = DagNode("ema50", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 50),), "ema_50", 50)
        assert a.content_hash != b.content_hash

    def test_content_hash_differs_on_function(self):
        a = DagNode("ind_a", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 20),), "out", 20)
        b = DagNode("ind_b", "pandas_ta", "sma",
                     (("close", "close"),), (("length", 20),), "out", 20)
        assert a.content_hash != b.content_hash

    def test_input_refs(self):
        node = DagNode("atr", "pandas_ta", "atr",
                        (("close", "close"), ("high", "high"), ("low", "low")),
                        (("length", 14),), "atr_14", 14)
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


# ---------------------------------------------------------------------------
# DagGraph tests
# ---------------------------------------------------------------------------

class TestDagGraph:
    def _make_ema_chain(self) -> list[DagNode]:
        return [
            DagNode("ema20", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 20),), "ema_20", 20),
            DagNode("ema50", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 50),), "ema_50", 50),
            DagNode("distance", "built_in", "ratio",
                     (("left", "close"), ("right", "ema50")),
                     (), "ema_distance"),
        ]

    def test_basic_graph_creation(self):
        nodes = self._make_ema_chain()
        graph = DagGraph(nodes)
        assert len(graph.nodes) == 3

    def test_execution_order_respects_dependencies(self):
        nodes = self._make_ema_chain()
        graph = DagGraph(nodes)
        order = [n.node_id for n in graph.execution_order()]
        # ema50 must come before distance
        assert order.index("ema50") < order.index("distance")

    def test_duplicate_node_ids_rejected(self):
        node = DagNode("ema", "pandas_ta", "ema",
                        (("close", "close"),), (("length", 20),), "ema_20", 20)
        with pytest.raises(DomainValidationError, match="duplicate"):
            DagGraph([node, node])

    def test_cycle_detection(self):
        a = DagNode("a", "built_in", "add",
                     (("left", "b"), ("right", "close")), (), "out_a")
        b = DagNode("b", "built_in", "add",
                     (("left", "a"), ("right", "close")), (), "out_b")
        with pytest.raises(DomainValidationError, match="cycle"):
            DagGraph([a, b])

    def test_unknown_reference_rejected(self):
        node = DagNode("x", "built_in", "add",
                        (("left", "nonexistent"), ("right", "close")), (), "out")
        with pytest.raises(DomainValidationError, match="unknown"):
            DagGraph([node])

    def test_primitive_fields_accepted(self):
        node = DagNode("x", "built_in", "add",
                        (("left", "close"), ("right", "volume")), (), "out")
        graph = DagGraph([node])
        assert len(graph.execution_order()) == 1

    def test_max_warmup_simple(self):
        nodes = [
            DagNode("ema20", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 20),), "ema_20", 20),
            DagNode("ema50", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 50),), "ema_50", 50),
        ]
        graph = DagGraph(nodes)
        assert graph.max_warmup() == 50

    def test_max_warmup_chained(self):
        """Chained indicators: EMA(20) of RSI(14) needs 14 + 20 = 34 bars."""
        nodes = [
            DagNode("rsi", "pandas_ta", "rsi",
                     (("close", "close"),), (("length", 14),), "rsi_14", 14),
            DagNode("rsi_ema", "pandas_ta", "ema",
                     (("close", "rsi"),), (("length", 20),), "rsi_ema_20", 20),
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
        # EMA20 and EMA50 have different hashes
        assert hashes["ema20"] != hashes["ema50"]


class TestDagGraphFromYaml:
    def test_build_from_yaml_indicators(self):
        indicators = [
            {"id": "ema_20", "provider": "pandas_ta", "function": "ema",
             "inputs": {"close": "close"}, "parameters": {"length": 20}, "output": "ema_20"},
            {"id": "rsi_14", "provider": "pandas_ta", "function": "rsi",
             "inputs": {"close": "close"}, "parameters": {"length": 14}, "output": "rsi_14"},
        ]
        adapter = PandasTaAdapter()
        graph = DagGraph.from_yaml_sections(indicators, adapter=adapter)
        assert len(graph.nodes) == 2
        assert graph.max_warmup() == 20

    def test_build_with_operations(self):
        indicators = [
            {"id": "ema_50", "provider": "pandas_ta", "function": "ema",
             "inputs": {"close": "close"}, "parameters": {"length": 50}, "output": "ema_50"},
        ]
        operations = [
            {"id": "ema_distance", "operation": "ratio",
             "left": "close", "right": "ema_50", "output": "ema_distance"},
        ]
        graph = DagGraph.from_yaml_sections(indicators, operations)
        assert len(graph.nodes) == 2
        order = [n.node_id for n in graph.execution_order()]
        assert order.index("ema_50") < order.index("ema_distance")


# ---------------------------------------------------------------------------
# DagExecutor tests
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    import numpy as np
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    close = np.maximum(close, 10)  # ensure positive
    return pd.DataFrame({
        "as_of_date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": close * (1 + np.random.randn(n) * 0.001),
        "high": close * (1 + abs(np.random.randn(n)) * 0.005),
        "low": close * (1 - abs(np.random.randn(n)) * 0.005),
        "close": close,
        "volume": np.random.randint(100_000, 1_000_000, n).astype(float),
    })


class TestDagExecutor:
    @pytest.fixture
    def adapter(self) -> PandasTaAdapter:
        return PandasTaAdapter()

    @pytest.fixture
    def ohlcv(self) -> pd.DataFrame:
        return _make_ohlcv(200)

    def test_execute_single_ema(self, adapter, ohlcv):
        nodes = [
            DagNode("ema_20", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 20),), "ema_20", 20),
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "ema_20" in results
        # First 19 values should be NaN (warmup), rest should be valid
        assert results["ema_20"].iloc[19:].notna().all()

    def test_execute_chained_ema_of_rsi(self, adapter, ohlcv):
        nodes = [
            DagNode("rsi_14", "pandas_ta", "rsi",
                     (("close", "close"),), (("length", 14),), "rsi_14", 14),
            DagNode("rsi_ema", "pandas_ta", "ema",
                     (("close", "rsi_14"),), (("length", 10),), "rsi_ema", 10),
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "rsi_ema" in results
        # After warmup (14 + 10 - 1), values should be valid
        valid = results["rsi_ema"].iloc[30:].dropna()
        assert len(valid) > 0

    def test_execute_arithmetic_operations(self, adapter, ohlcv):
        nodes = [
            DagNode("ema_50", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 50),), "ema_50", 50),
            DagNode("distance", "built_in", "ratio",
                     (("left", "close"), ("right", "ema_50")), (), "distance"),
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "distance" in results
        # Should be close/ema_50
        valid_idx = results["ema_50"].dropna().index
        close = ohlcv["close"].astype(float)
        expected = close.loc[valid_idx] / results["ema_50"].loc[valid_idx]
        pd.testing.assert_series_equal(
            results["distance"].loc[valid_idx], expected,
            check_names=False, atol=1e-10,
        )

    def test_execute_shift_operation(self, adapter, ohlcv):
        nodes = [
            DagNode("shifted", "built_in", "shift",
                     (("input", "close"),), (("periods", 5),), "shifted_5", 5),
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "shifted" in results
        close = ohlcv["close"].astype(float)
        expected = close.shift(5)
        pd.testing.assert_series_equal(
            results["shifted"], expected,
            check_names=False, atol=1e-10,
        )

    def test_execute_clip_operation(self, adapter, ohlcv):
        nodes = [
            DagNode("clipped", "built_in", "clip",
                     (("input", "close"),), (("low", 95.0), ("high", 105.0)),
                     "clipped"),
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert results["clipped"].min() >= 95.0
        assert results["clipped"].max() <= 105.0

    def test_execute_piecewise_linear(self, adapter, ohlcv):
        nodes = [
            DagNode("scored", "built_in", "piecewise_linear",
                     (("input", "close"),),
                     (("breakpoints", [90, 100, 110]),
                      ("values", [0, 50, 100])),
                     "scored"),
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "scored" in results
        # Value at close=100 should be 50
        for i, c in enumerate(ohlcv["close"].astype(float)):
            if abs(c - 100) < 0.01:
                assert abs(results["scored"].iloc[i] - 50) < 1

    def test_execute_with_benchmark(self, adapter, ohlcv):
        benchmark = _make_ohlcv(200)
        nodes = [
            DagNode("rel", "built_in", "ratio",
                     (("left", "close"), ("right", "benchmark.close")),
                     (), "relative_price"),
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv, benchmark)
        assert "rel" in results
        assert results["rel"].notna().sum() > 0

    def test_execute_empty_dataframe(self, adapter):
        ohlcv = pd.DataFrame()
        nodes = [
            DagNode("ema", "pandas_ta", "ema",
                     (("close", "close"),), (("length", 20),), "ema_20", 20),
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert results == {}

    def test_execute_multi_output_indicator(self, adapter, ohlcv):
        """MACD produces 3 columns; the node should select the correct one."""
        nodes = [
            DagNode("macd_line", "pandas_ta", "macd",
                     (("close", "close"),),
                     (("fast", 12), ("signal", 9), ("slow", 26)),
                     "macd", 26),
        ]
        graph = DagGraph(nodes)
        executor = DagExecutor(adapter)
        results = executor.execute(graph, ohlcv)
        assert "macd_line" in results
        # After warmup, should have values
        valid = results["macd_line"].iloc[30:].dropna()
        assert len(valid) > 0
