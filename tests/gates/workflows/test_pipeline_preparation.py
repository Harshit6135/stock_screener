from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.market_data import NSE_INDEX_SYMBOLS
from src.domains.operations import JobStore
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.market_jobs import KiteMarketJobs
from src.gates.workflows.market_refresh import MarketRefreshPlanner
from src.gates.workflows.pipeline_preparation import PipelinePreparation
from src.platform_kernel import SqliteArtifactStore

DAY = date(2026, 1, 5)


def setup_market(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    publisher = ArtifactPublisher(SqliteArtifactStore(database), ArtifactCatalog(database))
    return market, publisher


def seed_snapshot(market, snapshot_id, day, instruments):
    market.create_universe_snapshot(
        snapshot_id=snapshot_id,
        index_name="NIFTY 500",
        snapshot_date=day,
        source_url="fixture://nse",
        raw_csv=snapshot_id.encode(),
        members=[
            {
                "isin": isin,
                "symbol": symbol,
                "company_name": symbol,
                "industry": "IT",
                "series": "BE",
            }
            for isin, symbol in instruments
        ],
    )


def test_manual_preparation_runs_quality_before_indicators_and_reuses_history(
    tmp_path, monkeypatch
):

    market, publisher = setup_market(tmp_path)
    seed_snapshot(market, "pinned", DAY, [("IN0000000001", "STOCK")])
    records = [TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "1", DAY)]
    records += [
        TrackedInstrument(symbol, "INDEX:" + symbol, symbol, "NSE", str(i + 10), DAY)
        for i, symbol in enumerate(sorted(NSE_INDEX_SYMBOLS))
    ]
    records.append(
        TrackedInstrument("obsolete-index", "INDEX:OBSOLETE", "OBSOLETE", "NSE", "999", DAY)
    )
    market.upsert_instruments(records)
    provider_calls, stages = [], []

    class Client:
        def historical_data(self, token, start, end, interval):
            provider_calls.append((token, start, end))
            if token == 1 or not start <= DAY <= end:
                return []
            return [{"date": DAY, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 0}]

    market_jobs = KiteMarketJobs(market, publisher, None, tmp_path / "token")
    monkeypatch.setattr(market_jobs, "_client", Client)
    monkeypatch.setattr(
        market_jobs, "sync_snapshot_instruments", lambda payload, context: {"unresolved": []}
    )
    monkeypatch.setattr(
        "src.domains.market_data.providers._ProviderThrottle.wait", lambda self: None
    )
    universe = SimpleNamespace(
        download_nifty500_constituents=lambda payload, context: {
            "snapshot_id": "pinned",
            "reused": True,
        }
    )
    corporate = SimpleNamespace(
        detect_job=lambda payload, context: {}, process_actionable=lambda history, context: {}
    )

    def indicators(payload, context):
        assert market.quality_events(check_type="missing_completed_sessions")
        return {"rebuilt": 0}

    refresh = MarketRefreshPlanner(market.path, market, JobStore(market.path), publisher)
    preparation = PipelinePreparation(
        universe,
        market,
        market_jobs,
        corporate,
        SimpleNamespace(rebuild_indicators=indicators),
        refresh,
        None,
    )
    context = SimpleNamespace(
        checkpoint=lambda **kwargs: stages.append(kwargs["progress"]["stage"])
    )
    first = preparation.run({"start_date": DAY.isoformat(), "end_date": DAY.isoformat()}, context)
    assert first["quality"]["missing_bars"][0]["instrument_id"] == "stock"
    assert all(token != "999" for token, _, _ in provider_calls)
    assert stages.index("quality") > max(
        i for i, stage in enumerate(stages) if stage == "market_history"
    )
    assert stages.index("quality") < stages.index("indicators")
    assert first["reconciliation"]["session_coverage"] == first["quality"]
    first_call_count = len(provider_calls)
    second = preparation.run({"start_date": DAY.isoformat(), "end_date": DAY.isoformat()}, context)
    assert len(provider_calls) == first_call_count
    assert second["quality"] == first["quality"]
    assert len(market.quality_events(check_type="missing_completed_sessions")) == 1


class TestPipelinePrerequisites:
    def test_snapshot_exists_before_pipeline_can_proceed(self, tmp_path):
        """Pipeline should be able to check whether a universe snapshot exists."""
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        assert market.latest_universe_snapshot("NIFTY 500") is None
        snap_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap_id,
            index_name="NIFTY 500",
            snapshot_date=date(2026, 1, 1),
            source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,A,A,IT,EQ",
            members=[
                {
                    "isin": "IN0000000001",
                    "symbol": "A",
                    "company_name": "A",
                    "industry": "IT",
                    "series": "EQ",
                }
            ],
        )
        snapshot = market.latest_universe_snapshot("NIFTY 500")
        assert snapshot is not None
        assert snapshot["snapshot_id"] == snap_id
