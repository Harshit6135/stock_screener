from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.indicators.registry import PandasTaAdapter
from src.gates.indicator_implementations import (
    INSTRUMENT_IMPLEMENTATIONS,
    INSTRUMENT_SERIES_IMPLEMENTATIONS,
)
from src.gates.strategy_definitions import StrategyDefinitions
from src.gates.strategy_runtime import StrategyRuntime
from src.gates.workflows.positional_trend import PositionalTrendJobs
from src.platform_kernel import ArtifactStore


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


def test_registry_exposes_full_date_keyed_series(tmp_path):
    _, source, _, _, _, _ = _setup(tmp_path)
    bars = source["a"][0]
    key = "custom.positional_trend_features"
    rows = INSTRUMENT_SERIES_IMPLEMENTATIONS[key](list(reversed(bars)))
    assert len(rows) > 1
    assert INSTRUMENT_IMPLEMENTATIONS[key](bars) == rows[bars[-1]["as_of_date"]]
