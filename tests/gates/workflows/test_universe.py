from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.domains.market_data import NormalizedBar
from src.domains.operations import JobStore
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.market_refresh import MarketRefreshPlanner
from src.gates.workflows.universe import UniverseJobs


def test_daily_collection_reuses_snapshot_without_a_second_download(tmp_path):
    class Client:
        calls = 0

        def nifty_500_csv(self):
            self.calls += 1
            return "https://example.test/nifty500.csv", (
                b"Company Name,Industry,Symbol,Series,ISIN Code\nOne Ltd,Tech,ONE,EQ,INE001\n"
            )

    client = Client()
    job = UniverseJobs(
        MarketRepository(tmp_path / "market.db"), client, collection_date=lambda: date(2026, 1, 2)
    )
    first = job.download_nifty500_constituents({"snapshot_date": "2026-01-02"})
    second = job.download_nifty500_constituents({"snapshot_date": "2026-01-02"})
    assert first["status"] == "stored"
    assert second["status"] == "reused"
    assert second["snapshot_id"] == first["snapshot_id"]
    assert client.calls == 1


def refresh_fixture(tmp_path):
    db = tmp_path / "system.db"
    market = MarketRepository(db)
    jobs = JobStore(db)
    market.upsert_instruments(
        [
            TrackedInstrument(name, name.upper(), name.upper(), "NSE", str(i), date(2026, 1, 1))
            for i, name in enumerate(["member", "exiting", "unrelated"], 1)
        ]
    )
    market.create_universe_snapshot(
        snapshot_id="snapshot",
        index_name="NIFTY 500",
        snapshot_date=date(2026, 6, 1),
        source_url="fixture://membership",
        raw_csv=b"fixture",
        members=[
            {
                "isin": "member",
                "symbol": "MEMBER",
                "company_name": "Member",
                "industry": "IT",
                "series": "BE",
            }
        ],
    )
    market.record_exit_eligibility(
        instrument_id="exiting",
        isin="exiting",
        symbol="EXITING",
        decision_date=date(2026, 6, 1),
        decision_snapshot_id="snapshot",
        target_session_date=date(2026, 6, 2),
    )
    return (
        market,
        jobs,
        MarketRefreshPlanner(
            db, market, jobs, held_instrument_ids=lambda: {"exiting", "unrelated"}
        ),
    )


def test_universe_download_rejects_backdated_current_source_without_network(tmp_path):
    from src.gates.workflows.universe import UniverseJobs

    class Client:
        def nifty_500_csv(self):
            raise AssertionError("a backdated current-source download must not occur")

    service = UniverseJobs(
        MarketRepository(tmp_path / "system.db"), Client(), collection_date=lambda: date(2026, 6, 5)
    )
    from src.platform_kernel import DomainValidationError

    with pytest.raises(DomainValidationError, match="actual collection date"):
        service.download_nifty500_constituents({"snapshot_date": "2026-06-04"})


def test_concurrent_universe_collectors_use_the_first_committed_identity(tmp_path, monkeypatch):
    from src.gates.workflows.universe import UniverseJobs

    market = MarketRepository(tmp_path / "system.db")
    day = date(2026, 6, 5)
    create = market.create_universe_snapshot

    def competing_collection(**payload):
        create(
            snapshot_id="winner",
            index_name="NIFTY 500",
            snapshot_date=day,
            source_url="fixture://winner",
            raw_csv=b"winner",
            members=[
                {
                    "isin": "WINNER",
                    "symbol": "WINNER",
                    "company_name": "Winner",
                    "industry": "IT",
                    "series": "EQ",
                }
            ],
        )
        return create(**payload)

    monkeypatch.setattr(market, "create_universe_snapshot", competing_collection)

    class Client:
        def nifty_500_csv(self):
            return (
                "fixture://loser",
                b"Company Name,Industry,Symbol,Series,ISIN Code\nLoser,IT,LOSER,BE,LOSER\n",
            )

    result = UniverseJobs(
        market, Client(), collection_date=lambda: day
    ).download_nifty500_constituents({})
    assert result["snapshot_id"] == "winner"
    assert market.universe_snapshot_members(result["snapshot_id"])[0]["isin"] == "WINNER"


def test_unknown_future_exit_session_remains_pending_until_benchmark_evidence(tmp_path):
    from src.gates.workflows.universe import UniverseJobs

    market, jobs, planner = refresh_fixture(tmp_path)
    records = UniverseJobs(market)._record_exit_eligibility(
        [{"isin": "UNRELATED", "symbol": "UNRELATED"}], date(2026, 6, 5), "snapshot"
    )
    assert records[0]["target_session"] is None
    assert records[0]["status"] == "missing_session"
    planned = planner.schedule({"start_date": "2026-06-05", "end_date": "2026-06-10"})
    assert planned["pending_exit_sessions"][0]["instrument_id"] == "unrelated"
    market.upsert_instruments(
        [
            TrackedInstrument(
                "benchmark", "INDEX:NIFTY 500", "NIFTY 500", "NSE", "500", date(2026, 6, 8)
            )
        ]
    )
    market.upsert_bars(
        "benchmark",
        [
            NormalizedBar(
                "benchmark",
                date(2026, 6, 8),
                Decimal(100),
                Decimal(100),
                Decimal(100),
                Decimal(100),
                0,
            )
        ],
        "benchmark-source",
    )
    planned = planner.schedule({"start_date": "2026-06-05", "end_date": "2026-06-10"})
    assert planned["pending_exit_sessions"] == []
    exit_job = jobs.get(planned["exit_job_ids"][0])
    assert exit_job.payload["symbol"] == "UNRELATED"
    assert exit_job.payload["start_date"] == exit_job.payload["end_date"] == "2026-06-08"
    resolved = next(
        row for row in market.exit_eligible_instruments() if row["instrument_id"] == "unrelated"
    )
    assert resolved["session_source"] == "observed_market"


class TestUniverseExitDetection:
    def test_detect_exits_identifies_held_instruments_absent_from_snapshot(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        observed = date(2026, 1, 1)
        market.upsert_instruments(
            [
                TrackedInstrument("held-1", "IN0000000001", "HELD", "NSE", "1", observed),
                TrackedInstrument("in-snap", "IN0000000002", "INSNAP", "NSE", "2", observed),
            ]
        )
        snap_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap_id,
            index_name="NIFTY 500",
            snapshot_date=observed,
            source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000002,INSNAP,InSnap Co,IT,EQ",
            members=[
                {
                    "isin": "IN0000000002",
                    "symbol": "INSNAP",
                    "company_name": "InSnap Co",
                    "industry": "IT",
                    "series": "EQ",
                }
            ],
        )
        universe = UniverseJobs(market)
        result = universe.detect_universe_exits(
            {
                "snapshot_id": snap_id,
                "held_instrument_ids": ["held-1", "in-snap"],
            }
        )
        assert result["exit_count"] == 1
        assert result["exits"][0]["instrument_id"] == "held-1"
        assert result["exits"][0]["reason"] == "universe_exit"
