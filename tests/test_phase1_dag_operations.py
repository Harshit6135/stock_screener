"""Executable evidence for every approved per-instrument DAG operation."""

import math

import pandas as pd
import pytest

from src.indicators.dag import APPROVED_OPERATIONS, DagExecutor, DagGraph, DagNode
from src.indicators.registry import PandasTaAdapter


def case(function, *, inputs=None, parameters=(), expected, prerequisite=None):
    return function, inputs or (("input", "close"),), parameters, expected, prerequisite


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
    case("rolling_correlation", inputs=(("left", "close"), ("right", "open")), parameters=(("length", 2),), expected=[None, 1, -1, 1]),
    case("clip", parameters=(("low", 2), ("high", 4)), expected=[2, 2, 4, 4]),
    case("scale", parameters=(("factor", 2), ("offset", 3)), expected=[5, 7, 11, 19]),
    case("piecewise_linear", parameters=(("breakpoints", [1, 4, 8]), ("values", [0, 0.5, 1])), expected=[0, 1/6, 0.5, 1]),
    case("default", inputs=(("input", "lag"),), parameters=(("value", 10),), expected=[10, 1, 2, 4],
         prerequisite=DagNode("lag", "built_in", "shift", (("input", "close"),), (("periods", 1),), "lag")),
    case("conditional", inputs=(("input", "diff"),), expected=[0, 0, 1, 0],
         prerequisite=DagNode("diff", "built_in", "subtract", (("left", "close"), ("right", "open")), (), "diff")),
    case("greater_than", inputs=(("left", "close"), ("right", "open")), expected=[0, 0, 1, 0]),
    case("greater_than_or_equal", inputs=(("left", "close"), ("right", "open")), expected=[0, 0, 1, 1]),
    case("less_than", inputs=(("left", "close"), ("right", "open")), expected=[1, 1, 0, 0]),
    case("less_than_or_equal", inputs=(("left", "close"), ("right", "open")), expected=[1, 1, 0, 1]),
    case("equal", inputs=(("left", "close"), ("right", "open")), expected=[0, 0, 0, 1]),
    case("weighted_sum", parameters=(("weight", 2),), expected=[2, 4, 8, 16]),
    case("abs", inputs=(("input", "diff"),), expected=[1, 2, 2, 0],
         prerequisite=DagNode("diff", "built_in", "subtract", (("left", "close"), ("right", "open")), (), "diff")),
    case("pct_change", parameters=(("periods", 1),), expected=[None, 1, 1, 1]),
    case("ewm_mean", parameters=(("span", 2),), expected=[None, 5/3, 29/9, 173/27]),
]


@pytest.mark.parametrize(("function", "inputs", "parameters", "expected", "prerequisite"), CASES, ids=[item[0] for item in CASES])
def test_every_approved_operation_executes_with_expected_values(function, inputs, parameters, expected, prerequisite):
    frame = pd.DataFrame({"close": [1, 2, 4, 8], "open": [2, 4, 2, 8],
                          "high": [3, 5, 5, 9], "low": [0.5, 1, 1, 7], "volume": [10, 20, 40, 80]})
    node = DagNode("result", "built_in", function, inputs, parameters, "result")
    graph = DagGraph(([prerequisite] if prerequisite is not None else []) + [node])
    actual = DagExecutor(PandasTaAdapter()).execute(graph, frame)["result"].tolist()
    for observed, wanted in zip(actual, expected):
        if wanted is None:
            assert math.isnan(observed)
        else:
            assert observed == pytest.approx(wanted, abs=1e-9)


def test_approved_operation_manifest_has_an_executable_case_for_every_handler():
    assert {item[0] for item in CASES} == APPROVED_OPERATIONS
