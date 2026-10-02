"""Phase 1 proof that selected DAG outputs and cache identities have the same meaning."""

import pandas as pd
import pytest

from src.indicators.dag import DagExecutor, DagGraph, DagNode
from src.indicators.registry import PandasTaAdapter
from src.platform_kernel import DomainValidationError


@pytest.mark.parametrize(("function", "inputs", "parameters", "selector", "column_prefix"), [
    ("macd", (("close", "close"),), (("fast", 12), ("slow", 26), ("signal", 9)), "histogram", "MACDh"),
    ("macd", (("close", "close"),), (("fast", 12), ("slow", 26), ("signal", 9)), "signal", "MACDs"),
    ("bbands", (("close", "close"),), (("length", 20), ("std", 2)), "upper", "BBU"),
    ("adx", (("high", "high"), ("low", "low"), ("close", "close")), (("length", 14), ("lensig", 14)), "dmp", "DMP"),
])
def test_multi_output_selection_matches_provider_column(function, inputs, parameters, selector, column_prefix):
    frame = pd.DataFrame({
        "close": [100 + i + (i % 7) for i in range(100)],
        "high": [103 + i + (i % 7) for i in range(100)],
        "low": [97 + i + (i % 7) for i in range(100)],
    })
    adapter = PandasTaAdapter()
    expected_frame = adapter.calculate(function, {name: frame[ref] for name, ref in inputs}, dict(parameters))
    expected_column = next(col for col in expected_frame.columns if str(col).split("_", 1)[0] == column_prefix)
    node = DagNode("chosen", "pandas_ta", function, inputs, parameters, selector)
    actual = DagExecutor(adapter).execute(DagGraph([node]), frame)["chosen"]
    pd.testing.assert_series_equal(actual, expected_frame[expected_column])


def test_semantic_output_hash_ignores_local_alias_but_distinguishes_different_series():
    def graph(node_id, output_key):
        return DagGraph([DagNode(node_id, "pandas_ta", "macd", (("close", "close"),), (), output_key)])
    assert graph("hist", "histogram").content_hash("hist") == graph("renamed", "my_histogram").content_hash("renamed")
    assert graph("hist", "histogram").content_hash("hist") != graph("signal", "signal").content_hash("signal")
    assert graph("default", "custom_alias").content_hash("default") == graph("base", "macd").content_hash("base")
    assert DagGraph([DagNode("ema", "pandas_ta", "ema", (("close", "close"),), (), "local")]).content_hash("ema") == DagGraph([DagNode("renamed", "pandas_ta", "ema", (("close", "close"),), (), "other")]).content_hash("renamed")


def test_compiled_graph_rejects_unsupported_operation_at_construction():
    with pytest.raises(DomainValidationError, match="unsupported operation 'percentile_rank'"):
        DagGraph.from_dict([{"node_id": "bad", "provider": "built_in", "function": "percentile_rank",
                             "inputs": [["input", "close"]], "parameters": [], "output_key": "bad"}])
