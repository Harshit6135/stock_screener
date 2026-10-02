"""Fresh-store and validation evidence for Phase 1 entry and exit checks."""

import sqlite3
from pathlib import Path

import pytest
import yaml

from run import create_app
from src.application.strategy_definitions import StrategyDefinitions
from src.indicators.dag import DagGraph, DagNode
from src.indicators.registry import PandasTaAdapter
from src.platform_kernel import DomainValidationError


def test_fresh_app_has_contiguous_namespaced_migrations_and_readback(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "phase-1-test"
        DATA_DIRECTORY = tmp_path

    app = create_app(Config)
    assert app.test_client().get("/health/ready").status_code == 200
    database = app.extensions["screener_services"].database
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT namespace, version FROM system_schema_migrations ORDER BY namespace, version").fetchall()
    by_namespace = {}
    for namespace, version in rows:
        by_namespace.setdefault(namespace, []).append(version)
    assert all(versions == list(range(1, max(versions)+1)) for versions in by_namespace.values())
    assert by_namespace["market"][-1] >= 15
    assert by_namespace["indicator_node_cache"][-1] >= 2
    assert by_namespace["ops"][-1] >= 3
    assert by_namespace["research"]
    assert app.test_client().get("/api/v2/market/quality-events").status_code == 200


def test_strategy_definition_rejects_unsupported_operation_before_publication(tmp_path):
    definitions = StrategyDefinitions(tmp_path / "definitions.db", PandasTaAdapter())
    source = Path(__file__).resolve().parents[1] / "strategies" / "momentum.yml"
    definition = yaml.safe_load(source.read_text(encoding="utf-8"))
    definition["operations"] = [{"id": "invalid", "operation": "percentile_rank", "input": "close"}]
    with pytest.raises(DomainValidationError, match="not approved"):
        definitions.create_from_yaml(yaml.safe_dump(definition))
    assert definitions.revisions("momentum") == []
    definition["operations"] = [{"id": "ignored", "operation": "add", "left": "close", "right": "close"}]
    with pytest.raises(DomainValidationError, match="require an indicators DAG"):
        definitions.create_from_yaml(yaml.safe_dump(definition))
    assert definitions.revisions("momentum") == []


def test_public_indicator_parameter_validation_and_graph_operand_roles():
    adapter = PandasTaAdapter()
    spec = adapter.spec("ema")
    assert adapter.validate_parameters(spec, {"length": 21})["length"] == 21
    with pytest.raises(DomainValidationError, match="must be numeric"):
        adapter.validate_parameters(spec, {"length": True})

    def graph(left, right, *, size=2, prefix="one"):
        return DagGraph([DagNode(prefix, "built_in", "rolling_mean", (("input", "close"),),
                                 (("length", size),), prefix),
                         DagNode(prefix+"_ratio", "built_in", "ratio",
                                 (("left", left if left == "close" else prefix),
                                  ("right", right if right == "close" else prefix)), (), prefix+"_ratio")])
    normal = graph("close", "node")
    renamed = graph("close", "node", prefix="other")
    reversed_roles = graph("node", "close")
    changed_parent = graph("close", "node", size=3)
    assert normal.content_hash("one_ratio") == renamed.content_hash("other_ratio")
    assert normal.content_hash("one_ratio") != reversed_roles.content_hash("one_ratio")
    assert normal.content_hash("one_ratio") != changed_parent.content_hash("one_ratio")
