from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.indicators.registry import PandasTaAdapter
from src.gates.strategy_definitions import StrategyDefinitions
from src.gates.strategy_runtime import StrategyRuntime
from src.gates.workflows.positional_trend import PositionalTrendJobs
from src.platform_kernel import ArtifactStore, DomainValidationError


def test_yaml_strategy_revision_is_immutable_and_activation_retires_previous(tmp_path):
    strategies = StrategyDefinitions(tmp_path / "strategies.db", PandasTaAdapter())
    template = """schema_version: 1
strategy:
  id: momentum_quality
  name: Momentum Quality
  version: %s
calculation:
  instrument_implementation: custom.momentum_quality_features
  required_sessions: 200
factors:
  trend: 0.30
  momentum: 0.25
  efficiency: 0.20
  volume: 0.15
  structure: 0.10
portfolio_policy:
  initial_capital: 100000
  max_positions: 15
  exit_threshold: 40
  buffer_percent: 0.25
  max_concentration_pct: 0.25
ranking:
  frequency: weekly
  session: last_trading_session
"""
    first = strategies.create_from_yaml(template % "1.0.0")
    second = strategies.create_from_yaml(template % "1.0.1")
    assert first["status"] == "VALIDATED"
    assert strategies.activate(first["revision_id"])["status"] == "ACTIVE"
    assert strategies.activate(second["revision_id"])["status"] == "ACTIVE"
    assert strategies.get(first["revision_id"])["status"] == "RETIRED"


def test_strategy_definition_rejects_unsupported_operation_before_publication(tmp_path):
    definitions = StrategyDefinitions(tmp_path / "definitions.db", PandasTaAdapter())
    source = Path(__file__).resolve().parents[2] / "strategies" / "momentum.yml"
    definition = yaml.safe_load(source.read_text(encoding="utf-8"))
    definition["operations"] = [{"id": "invalid", "operation": "percentile_rank", "input": "close"}]
    with pytest.raises(DomainValidationError, match="not approved"):
        definitions.create_from_yaml(yaml.safe_dump(definition))
    assert definitions.revisions("momentum") == []
    definition["operations"] = [
        {"id": "ignored", "operation": "add", "left": "close", "right": "close"}
    ]
    with pytest.raises(DomainValidationError, match="require an indicators DAG"):
        definitions.create_from_yaml(yaml.safe_dump(definition))
    assert definitions.revisions("momentum") == []


def _setup(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    text = (
        Path(__file__).resolve().parents[2] / "strategies/positional_trend_following.yml"
    ).read_text()
    revision = definitions.create_from_yaml(text)
    definitions.activate(revision["revision_id"])
    runtime = StrategyRuntime(definitions)
    days = [(date(2022, 1, 1) + timedelta(days=i)).isoformat() for i in range(110)]
    bars = [
        {
            "as_of_date": day,
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 2_000_000,
            "snapshot_id": str(uuid4()),
        }
        for day in days
    ]
    source = {"a": (bars, {"symbol": "A", "exchange": "NSE", "isin": "ISIN-A"})}
    market = SimpleNamespace(
        path=database,
        histories=lambda *_, **__: source,
        session_dates=lambda *_, exchange="NSE": days if exchange == "NSE" else [],
        latest_universe_snapshot=lambda _: {"snapshot_id": "snapshot-a", "snapshot_date": days[-1]},
        universe_snapshot_as_of=lambda *_: {"snapshot_id": "snapshot-a", "snapshot_date": days[-1]},
        universe_snapshot_members=lambda *_args, **_kwargs: [{"isin": "ISIN-A"}],
    )
    jobs = PositionalTrendJobs(market, publisher, runtime)
    return jobs, source, runtime, text, publisher, days


@pytest.mark.parametrize("field,value", [("adx_period", 14.5), ("minimum_adtv", float("inf"))])
def test_indicator_rules_reject_invalid_numbers(tmp_path, field, value):
    _, _, runtime, text, _, _ = _setup(tmp_path)
    definition = yaml.safe_load(text)
    definition["signal_rules"][field] = value
    with pytest.raises(DomainValidationError):
        runtime.definitions.create_from_yaml(yaml.safe_dump(definition))
