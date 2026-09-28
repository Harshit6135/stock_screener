"""Regression coverage for Phase 1 DAG/cache identity contracts."""

from datetime import date

from src.application.node_cache import IndicatorNodeCache
from src.indicators.dag import DagGraph, DagNode


def _graph(prefix: str, length: int = 20) -> DagGraph:
    return DagGraph([
        DagNode(f"{prefix}_ema", "pandas_ta", "ema", (("close", "close"),),
                (("length", length),), "ema"),
        DagNode(f"{prefix}_ratio", "built_in", "ratio",
                (("left", "close"), ("right", f"{prefix}_ema")), (), "ratio"),
    ])


def test_recursive_hash_ignores_renamed_nodes_but_tracks_ancestors():
    first = _graph("one")
    renamed = _graph("two")
    changed = _graph("three", length=50)
    assert first.content_hash("one_ratio") == renamed.content_hash("two_ratio")
    assert first.content_hash("one_ratio") != changed.content_hash("three_ratio")


def test_cache_read_requires_matching_input_and_implementation_revision(tmp_path):
    cache = IndicatorNodeCache(tmp_path / "cache.db")
    cache.put("node", "instrument", date(2026, 1, 1), 1.0, "source",
              market_revision="2", implementation_revision="executor:1")
    assert cache.get("node", "instrument", date(2026, 1, 1),
                     market_revision="2", implementation_revision="executor:1") == 1.0
    assert cache.get("node", "instrument", date(2026, 1, 1),
                     market_revision="3", implementation_revision="executor:1") is None
    assert cache.get("node", "instrument", date(2026, 1, 1),
                     market_revision="2", implementation_revision="executor:2") is None
