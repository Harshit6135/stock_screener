from datetime import date, timedelta
from uuid import uuid4

import pytest

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.operations import JobStore
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.market_jobs import PHASE2_BENCHMARK_SYMBOLS
from src.gates.workflows.market_refresh import MarketRefreshPlanner
from src.platform_kernel import ArtifactStore, DomainValidationError


def test_reconciliation_reports_symbol_level_exclusions_and_unmatched_sources(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    market.upsert_instruments(
        [
            TrackedInstrument("index", "INDEX:NIFTY", "NIFTY 500", "NSE", "", date(2026, 1, 1)),
            TrackedInstrument(
                "missing-token", "IN0000000001", "MISSING", "NSE", "", date(2026, 1, 1)
            ),
            TrackedInstrument("live", "IN0000000002", "LIVE", "NSE", "42", date(2026, 1, 1)),
        ]
    )
    planner = MarketRefreshPlanner(database, market, JobStore(database), publisher)
    report = planner.reconcile(
        {
            "as_of_date": "2026-01-05",
            "source_instruments": [
                {"isin": "IN0000000002", "symbol": "LIVE"},
                {"isin": "IN0000000003", "symbol": "UNKNOWN"},
            ],
        }
    )
    assert report["unmatched_source_symbols"] == ["UNKNOWN"]
    assert {(row["symbol"], row["reason"]) for row in report["excluded_identities"]} == {
        ("NIFTY 500", "index_identity"),
        ("MISSING", "missing_provider_token"),
    }
    assert publisher.store.read_json("reference/reconciliations", report["artifact_id"])[1][
        "unmatched_source_symbols"
    ] == ["UNKNOWN"]


def test_refresh_schedules_snapshot_members_and_benchmark_with_managed_exclusions(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    jobs = JobStore(database)
    observed_on = date(2026, 1, 1)
    records = (
        TrackedInstrument("member", "IN0000000001", "MEMBER", "NSE", "1", observed_on),
        TrackedInstrument("outside", "IN0000000002", "OUTSIDE", "NSE", "2", observed_on),
        TrackedInstrument("holding", "IN0000000003", "HOLDING", "BSE", "3", observed_on),
        TrackedInstrument("blocked", "IN0000000004", "BLOCKED", "NSE", "", observed_on),
        TrackedInstrument("benchmark", "INDEX:NIFTY 500", "NIFTY 500", "NSE", "5", observed_on),
    )
    market.upsert_instruments(records)
    market.replace_universe_members(
        (
            {
                "isin": "IN0000000001",
                "instrument_id": "member",
                "symbol": "MEMBER",
                "exchange": "NSE",
                "membership_type": "BASE",
                "first_eligible_date": observed_on.isoformat(),
                "initial_market_cap": 6_000_000_000,
                "threshold_crore": 500,
                "source": "yfinance",
                "snapshot_date": observed_on.isoformat(),
                "last_market_cap": 6_000_000_000,
            },
        ),
        snapshot_date=observed_on.isoformat(),
        threshold_crore=500,
        source="yfinance",
        total_tracked=1,
        resolved_count=1,
        unresolved_count=0,
    )
    market.create_universe_snapshot(
        snapshot_id="membership",
        index_name="NIFTY 500",
        snapshot_date=observed_on,
        source_url="fixture://membership",
        raw_csv=b"fixture",
        members=[
            {
                "isin": "IN0000000001",
                "symbol": "MEMBER",
                "company_name": "Member",
                "industry": "IT",
                "series": "EQ",
            }
        ],
    )
    planner = MarketRefreshPlanner(
        database,
        market,
        jobs,
        held_instrument_ids=lambda: {"holding", "blocked", "unknown-holding"},
    )

    result = planner.schedule({"start_date": "2025-01-01", "end_date": "2025-12-31"})

    assert result["scheduled_count"] == 2
    queued = {
        item["symbol"] for job_id in result["job_ids"] for item in jobs.get(job_id).payload["items"]
    }
    assert queued == {"MEMBER", "NIFTY 500"}
    assert {row["instrument_id"] for row in result["excluded"]} >= {"holding"}
    assert "OUTSIDE" not in queued
    assert result["blocked_held_positions"] == [
        {"instrument_id": "blocked", "reason": "missing_provider_token"},
        {"instrument_id": "unknown-holding", "reason": "held_position_not_in_reference_catalog"},
    ]


def test_refresh_refuses_to_download_before_a_universe_snapshot_exists(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    planner = MarketRefreshPlanner(database, market, JobStore(database))

    with pytest.raises(DomainValidationError, match="NIFTY 500 snapshot is unavailable"):
        planner.schedule({"start_date": "2025-01-01", "end_date": "2025-12-31"})


def test_refresh_refuses_legacy_membership_rows_without_a_snapshot(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    observed_on = date(2026, 1, 1)
    market.upsert_instruments(
        [TrackedInstrument("partial", "IN0000000001", "PARTIAL", "NSE", "1", observed_on)]
    )
    market.upsert_universe_members(
        [
            {
                "isin": "IN0000000001",
                "instrument_id": "partial",
                "symbol": "PARTIAL",
                "exchange": "NSE",
                "membership_type": "BASE",
                "first_eligible_date": observed_on.isoformat(),
                "initial_market_cap": 6_000_000_000,
                "threshold_crore": 500,
                "source": "yfinance",
                "snapshot_date": observed_on.isoformat(),
                "last_market_cap": 6_000_000_000,
            }
        ]
    )

    with pytest.raises(DomainValidationError, match="NIFTY 500 snapshot is unavailable"):
        MarketRefreshPlanner(database, market, JobStore(database)).schedule(
            {"start_date": "2025-01-01", "end_date": "2025-12-31"}
        )


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


def test_held_exclusions_only_schedule_the_declared_exit_session(tmp_path):
    _, jobs, planner = refresh_fixture(tmp_path)
    result = planner.schedule({"start_date": "2026-06-01", "end_date": "2026-06-10"})
    regular = [
        jobs.get(job_id) for job_id in result["job_ids"] if job_id not in result["exit_job_ids"]
    ]
    assert [item["symbol"] for job in regular for item in job.payload["items"]] == ["MEMBER"]
    assert len(result["exit_job_ids"]) == 1
    exit_job = jobs.get(result["exit_job_ids"][0])
    assert exit_job.payload == {
        "symbol": "EXITING",
        "exchange": "NSE",
        "start_date": "2026-06-02",
        "end_date": "2026-06-02",
        "exit_only": True,
    }
    assert (
        planner.schedule({"start_date": "2026-06-01", "end_date": "2026-06-10"})["job_ids"]
        == result["job_ids"]
    )


def test_later_refresh_does_not_extend_unfilled_exit_coverage(tmp_path):
    _, jobs, planner = refresh_fixture(tmp_path)
    result = planner.schedule({"start_date": "2026-06-03", "end_date": "2026-06-10"})
    assert result["exit_job_ids"] == []
    assert [
        item["symbol"] for job_id in result["job_ids"] for item in jobs.get(job_id).payload["items"]
    ] == ["MEMBER"]


class TestRefreshPlannerPhase2:
    def test_refresh_includes_all_six_benchmarks(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        jobs = JobStore(database)
        observed = date(2026, 1, 1)
        # Create a universe member
        market.upsert_instruments(
            [
                TrackedInstrument("member", "IN0000000001", "MEMBER", "NSE", "1", observed),
                TrackedInstrument(
                    "bench-nifty50", "INDEX:NIFTY 50", "NIFTY 50", "NSE", "50", observed
                ),
                TrackedInstrument(
                    "bench-nifty500", "INDEX:NIFTY 500", "NIFTY 500", "NSE", "500", observed
                ),
                TrackedInstrument(
                    "bench-next50", "INDEX:NIFTY NEXT 50", "NIFTY NEXT 50", "NSE", "51", observed
                ),
                TrackedInstrument(
                    "bench-mid150",
                    "INDEX:NIFTY MIDCAP 150",
                    "NIFTY MIDCAP 150",
                    "NSE",
                    "150",
                    observed,
                ),
                TrackedInstrument(
                    "bench-sml250",
                    "INDEX:NIFTY SMLCAP 250",
                    "NIFTY SMLCAP 250",
                    "NSE",
                    "250",
                    observed,
                ),
                TrackedInstrument(
                    "bench-vix", "INDEX:INDIA VIX", "INDIA VIX", "NSE", "999", observed
                ),
            ]
        )
        market.replace_universe_members(
            (
                {
                    "isin": "IN0000000001",
                    "instrument_id": "member",
                    "symbol": "MEMBER",
                    "exchange": "NSE",
                    "membership_type": "BASE",
                    "first_eligible_date": observed.isoformat(),
                    "initial_market_cap": 6e9,
                    "threshold_crore": 500,
                    "source": "test",
                    "snapshot_date": observed.isoformat(),
                    "last_market_cap": 6e9,
                },
            ),
            snapshot_date=observed.isoformat(),
            threshold_crore=500,
            source="test",
            total_tracked=1,
            resolved_count=1,
            unresolved_count=0,
        )
        market.create_universe_snapshot(
            snapshot_id="snapshot-benchmarks",
            index_name="NIFTY 500",
            snapshot_date=observed,
            source_url="fixture://membership",
            raw_csv=b"fixture",
            members=[
                {
                    "isin": "IN0000000001",
                    "symbol": "MEMBER",
                    "company_name": "Member",
                    "industry": "IT",
                    "series": "EQ",
                }
            ],
        )
        planner = MarketRefreshPlanner(database, market, jobs)
        result = planner.schedule({"start_date": "2025-01-01", "end_date": "2025-12-31"})
        queued = {
            item["symbol"]
            for job_id in result["job_ids"]
            for item in jobs.get(job_id).payload["items"]
        }
        assert "MEMBER" in queued
        # All six benchmarks should be included
        for bm in PHASE2_BENCHMARK_SYMBOLS:
            assert bm in queued, f"benchmark {bm} should be in scheduled set"

    def test_refresh_excludes_exit_only_instruments(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        jobs = JobStore(database)
        observed = date(2026, 1, 1)
        market.upsert_instruments(
            [
                TrackedInstrument("member", "IN0000000001", "MEMBER", "NSE", "1", observed),
                TrackedInstrument("exiting", "IN0000000002", "EXITING", "NSE", "2", observed),
                TrackedInstrument(
                    "bench-n500", "INDEX:NIFTY 500", "NIFTY 500", "NSE", "500", observed
                ),
            ]
        )
        market.replace_universe_members(
            (
                {
                    "isin": "IN0000000001",
                    "instrument_id": "member",
                    "symbol": "MEMBER",
                    "exchange": "NSE",
                    "membership_type": "BASE",
                    "first_eligible_date": observed.isoformat(),
                    "initial_market_cap": 6e9,
                    "threshold_crore": 500,
                    "source": "test",
                    "snapshot_date": observed.isoformat(),
                    "last_market_cap": 6e9,
                },
                {
                    "isin": "IN0000000002",
                    "instrument_id": "exiting",
                    "symbol": "EXITING",
                    "exchange": "NSE",
                    "membership_type": "BASE",
                    "first_eligible_date": observed.isoformat(),
                    "initial_market_cap": 6e9,
                    "threshold_crore": 500,
                    "source": "test",
                    "snapshot_date": observed.isoformat(),
                    "last_market_cap": 6e9,
                },
            ),
            snapshot_date=observed.isoformat(),
            threshold_crore=500,
            source="test",
            total_tracked=2,
            resolved_count=2,
            unresolved_count=0,
        )
        # Create a snapshot to satisfy FK
        snap_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap_id,
            index_name="NIFTY 500",
            snapshot_date=observed,
            source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,MEMBER,M,IT,EQ",
            members=[
                {
                    "isin": "IN0000000001",
                    "symbol": "MEMBER",
                    "company_name": "M",
                    "industry": "IT",
                    "series": "EQ",
                }
            ],
        )
        # Mark exiting as exit-only
        market.record_exit_eligibility(
            instrument_id="exiting",
            isin="IN0000000002",
            symbol="EXITING",
            decision_date=observed,
            decision_snapshot_id=snap_id,
            target_session_date=observed + timedelta(days=1),
        )
        planner = MarketRefreshPlanner(database, market, jobs)
        result = planner.schedule({"start_date": "2025-01-01", "end_date": "2025-12-31"})
        queued = {
            item["symbol"]
            for job_id in result["job_ids"]
            for item in jobs.get(job_id).payload["items"]
        }
        assert "MEMBER" in queued
        # Exit-only instruments never enter regular refresh
        assert "EXITING" not in queued
        excluded_ids = {item["instrument_id"] for item in result["excluded"]}
        assert "exiting" in excluded_ids
