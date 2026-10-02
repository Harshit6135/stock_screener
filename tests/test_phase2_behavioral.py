"""Phase 2 behavioral tests: universe snapshots, exit eligibility, benchmark set,
BSE removal, snapshot-driven strategy consumers, and refresh planner rules."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.application.catalog import ArtifactCatalog
from src.application.jobs import JobStore
from src.application.market_jobs import (
    NSE_INDEX_SYMBOLS,
    PHASE2_BENCHMARK_SYMBOLS,
    KiteMarketJobs,
)
from src.application.market_refresh import MarketRefreshPlanner
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.publication import ArtifactPublisher
from src.application.universe_jobs import UniverseJobs
from src.platform_kernel import ArtifactStore, DomainValidationError

# â”€â”€ Task 2.9: six NSE benchmarks â”€â”€

class TestBenchmarkSet:
    def test_six_benchmarks_are_defined(self):
        expected = {"NIFTY 50", "NIFTY 500", "NIFTY NEXT 50", "NIFTY MIDCAP 150", "NIFTY SMLCAP 250", "INDIA VIX"}
        assert NSE_INDEX_SYMBOLS == expected
        assert PHASE2_BENCHMARK_SYMBOLS == expected

# â”€â”€ Task 2.7: BSE runtime removed â”€â”€

class TestBseRemoval:
    def test_direct_and_bulk_bse_history_requests_fail_before_provider_access(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(tmp_path / "system.db"))
        jobs = KiteMarketJobs(market, publisher, None, tmp_path / "token.txt")
        with pytest.raises(DomainValidationError, match="bar fetch requires"):
            jobs.fetch_bars({"symbol": "OLD", "exchange": "BSE", "start_date": "2026-01-01", "end_date": "2026-01-01"})
        with pytest.raises(DomainValidationError, match="supported exchange"):
            jobs.fetch_bulk_bars({"items": [{"symbol": "OLD", "exchange": "BSE"}],
                "start_date": "2026-01-01", "end_date": "2026-01-01"}, None)



# â”€â”€ Task 2.11: exit eligibility â”€â”€

class TestExitEligibility:
    def test_record_and_query_exit_eligibility(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        observed = date(2026, 1, 1)
        market.upsert_instruments([
            TrackedInstrument("inst-1", "IN0000000001", "ALPHA", "NSE", "100", observed),
            TrackedInstrument("inst-2", "IN0000000002", "BETA", "NSE", "200", observed),
        ])
        decision_date = date(2026, 6, 1)
        target_session = date(2026, 6, 2)
        snapshot_id = str(uuid4())
        # Manually create a snapshot so FK is satisfied (or rely on IGNORE)
        market.create_universe_snapshot(
            snapshot_id=snapshot_id, index_name="NIFTY 500",
            snapshot_date=decision_date, source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,ALPHA,Alpha Co,IT,EQ",
            members=[{"isin": "IN0000000001", "symbol": "ALPHA", "company_name": "Alpha Co",
                      "industry": "IT", "series": "EQ"}],
        )
        # Record exit eligibility for removed member
        result = market.record_exit_eligibility(
            instrument_id="inst-2", isin="IN0000000002", symbol="BETA",
            decision_date=decision_date, decision_snapshot_id=snapshot_id,
            target_session_date=target_session,
        )
        assert result is True
        # Query by target date
        eligible = market.exit_eligible_instruments(target_date=target_session)
        assert len(eligible) == 1
        assert eligible[0]["instrument_id"] == "inst-2"
        assert eligible[0]["symbol"] == "BETA"
        # Query without target date
        all_eligible = market.exit_eligible_instruments()
        assert len(all_eligible) == 1
        # Check is_exit_only
        assert market.is_exit_only("inst-2") is True
        assert market.is_exit_only("inst-1") is False
        # Idempotent: second insert is ignored
        second_result = market.record_exit_eligibility(
            instrument_id="inst-2", isin="IN0000000002", symbol="BETA",
            decision_date=decision_date, decision_snapshot_id=snapshot_id,
            target_session_date=target_session,
        )
        assert second_result is False

    def test_exit_eligibility_rejects_invalid_dates(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        with pytest.raises(DomainValidationError, match="exit eligibility record is invalid"):
            market.record_exit_eligibility(
                instrument_id="x", isin="y", symbol="z",
                decision_date=date(2026, 6, 2),  # after target
                decision_snapshot_id="snap",
                target_session_date=date(2026, 6, 1),
            )


# â”€â”€ Task 2.12: refresh planner respects benchmarks and exit-only â”€â”€

class TestRefreshPlannerPhase2:
    def test_refresh_includes_all_six_benchmarks(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        jobs = JobStore(database)
        observed = date(2026, 1, 1)
        # Create a universe member
        market.upsert_instruments([
            TrackedInstrument("member", "IN0000000001", "MEMBER", "NSE", "1", observed),
            TrackedInstrument("bench-nifty50", "INDEX:NIFTY 50", "NIFTY 50", "NSE", "50", observed),
            TrackedInstrument("bench-nifty500", "INDEX:NIFTY 500", "NIFTY 500", "NSE", "500", observed),
            TrackedInstrument("bench-next50", "INDEX:NIFTY NEXT 50", "NIFTY NEXT 50", "NSE", "51", observed),
            TrackedInstrument("bench-mid150", "INDEX:NIFTY MIDCAP 150", "NIFTY MIDCAP 150", "NSE", "150", observed),
            TrackedInstrument("bench-sml250", "INDEX:NIFTY SMLCAP 250", "NIFTY SMLCAP 250", "NSE", "250", observed),
            TrackedInstrument("bench-vix", "INDEX:INDIA VIX", "INDIA VIX", "NSE", "999", observed),
        ])
        market.replace_universe_members(
            ({"isin": "IN0000000001", "instrument_id": "member", "symbol": "MEMBER",
              "exchange": "NSE", "membership_type": "BASE", "first_eligible_date": observed.isoformat(),
              "initial_market_cap": 6e9, "threshold_crore": 500, "source": "test",
              "snapshot_date": observed.isoformat(), "last_market_cap": 6e9},),
            snapshot_date=observed.isoformat(), threshold_crore=500, source="test",
            total_tracked=1, resolved_count=1, unresolved_count=0,
        )
        market.create_universe_snapshot(snapshot_id="snapshot-benchmarks", index_name="NIFTY 500",
            snapshot_date=observed, source_url="fixture://membership", raw_csv=b"fixture",
            members=[{"isin": "IN0000000001", "symbol": "MEMBER", "company_name": "Member",
                      "industry": "IT", "series": "EQ"}])
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
        market.upsert_instruments([
            TrackedInstrument("member", "IN0000000001", "MEMBER", "NSE", "1", observed),
            TrackedInstrument("exiting", "IN0000000002", "EXITING", "NSE", "2", observed),
            TrackedInstrument("bench-n500", "INDEX:NIFTY 500", "NIFTY 500", "NSE", "500", observed),
        ])
        market.replace_universe_members(
            (
                {"isin": "IN0000000001", "instrument_id": "member", "symbol": "MEMBER",
                 "exchange": "NSE", "membership_type": "BASE", "first_eligible_date": observed.isoformat(),
                 "initial_market_cap": 6e9, "threshold_crore": 500, "source": "test",
                 "snapshot_date": observed.isoformat(), "last_market_cap": 6e9},
                {"isin": "IN0000000002", "instrument_id": "exiting", "symbol": "EXITING",
                 "exchange": "NSE", "membership_type": "BASE", "first_eligible_date": observed.isoformat(),
                 "initial_market_cap": 6e9, "threshold_crore": 500, "source": "test",
                 "snapshot_date": observed.isoformat(), "last_market_cap": 6e9},
            ),
            snapshot_date=observed.isoformat(), threshold_crore=500, source="test",
            total_tracked=2, resolved_count=2, unresolved_count=0,
        )
        # Create a snapshot to satisfy FK
        snap_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap_id, index_name="NIFTY 500",
            snapshot_date=observed, source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,MEMBER,M,IT,EQ",
            members=[{"isin": "IN0000000001", "symbol": "MEMBER", "company_name": "M",
                      "industry": "IT", "series": "EQ"}],
        )
        # Mark exiting as exit-only
        market.record_exit_eligibility(
            instrument_id="exiting", isin="IN0000000002", symbol="EXITING",
            decision_date=observed, decision_snapshot_id=snap_id,
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


# â”€â”€ Task 2.13: universe exit detection â”€â”€

class TestUniverseExitDetection:
    def test_detect_exits_identifies_held_instruments_absent_from_snapshot(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        observed = date(2026, 1, 1)
        market.upsert_instruments([
            TrackedInstrument("held-1", "IN0000000001", "HELD", "NSE", "1", observed),
            TrackedInstrument("in-snap", "IN0000000002", "INSNAP", "NSE", "2", observed),
        ])
        snap_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap_id, index_name="NIFTY 500",
            snapshot_date=observed, source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000002,INSNAP,InSnap Co,IT,EQ",
            members=[{"isin": "IN0000000002", "symbol": "INSNAP", "company_name": "InSnap Co",
                      "industry": "IT", "series": "EQ"}],
        )
        universe = UniverseJobs(market)
        result = universe.detect_universe_exits({
            "snapshot_id": snap_id,
            "held_instrument_ids": ["held-1", "in-snap"],
        })
        assert result["exit_count"] == 1
        assert result["exits"][0]["instrument_id"] == "held-1"
        assert result["exits"][0]["reason"] == "universe_exit"


# â”€â”€ Task 2.8: snapshot-driven strategy consumer â”€â”€

class TestSnapshotDrivenStrategy:
    def test_snapshot_nifty500_universe_resolves_from_snapshot(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        observed = date(2026, 1, 1)
        snap_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap_id, index_name="NIFTY 500",
            snapshot_date=observed, source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,A,A Co,IT,EQ\nIN0000000002,B,B Co,IT,EQ",
            members=[
                {"isin": "IN0000000001", "symbol": "A", "company_name": "A Co", "industry": "IT", "series": "EQ"},
                {"isin": "IN0000000002", "symbol": "B", "company_name": "B Co", "industry": "IT", "series": "EQ"},
            ],
        )
        from src.application.positional_trend_jobs import PositionalTrendJobs
        trend = PositionalTrendJobs(market, MagicMock(), MagicMock())
        members, digest, metadata = trend._members("SNAPSHOT_NIFTY500")
        assert digest == trend._members("SNAPSHOT_NIFTY500")[1]
        assert members == {"IN0000000001", "IN0000000002"}
        assert metadata["source"] == "SNAPSHOT_NIFTY500"
        assert metadata["snapshot_id"] == snap_id
        assert metadata["member_count"] == 2
        with pytest.raises(DomainValidationError, match="SNAPSHOT_NIFTY500"):
            trend._members("APPLICATION_MCAP500")
        with pytest.raises(DomainValidationError, match="universe is invalid"):
            trend.build_signals({"as_of_date": observed.isoformat(),
                                 "universe": "APPLICATION_MCAP500"})


# â”€â”€ Task 2.6: snapshot-driven instrument sync â”€â”€

class TestSnapshotInstrumentSync:
    def test_sync_snapshot_instruments_resolves_members_and_benchmarks(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        catalog = ArtifactCatalog(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), catalog)
        snap_id = str(uuid4())
        observed = date(2026, 1, 1)
        market.create_universe_snapshot(
            snapshot_id=snap_id, index_name="NIFTY 500",
            snapshot_date=observed, source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,RELIANCE,Reliance,Energy,EQ",
            members=[{"isin": "IN0000000001", "symbol": "RELIANCE", "company_name": "Reliance",
                      "industry": "Energy", "series": "EQ"}],
        )
        # Mock the Kite NSE dump
        fake_kite_dump = [
            {"tradingsymbol": "RELIANCE", "instrument_token": "256265", "instrument_type": "EQ"},
            {"tradingsymbol": "NIFTY 50", "instrument_token": "256000", "instrument_type": "INDEX"},
            {"tradingsymbol": "NIFTY 500", "instrument_token": "256001", "instrument_type": "INDEX"},
            {"tradingsymbol": "NIFTY NEXT 50", "instrument_token": "256002", "instrument_type": "INDEX"},
            {"tradingsymbol": "NIFTY MIDCAP 150", "instrument_token": "256003", "instrument_type": "INDEX"},
            {"tradingsymbol": "NIFTY SMLCAP 250", "instrument_token": "256004", "instrument_type": "INDEX"},
            {"tradingsymbol": "INDIA VIX", "instrument_token": "256005", "instrument_type": "INDEX"},
        ]
        token_path = tmp_path / "token.txt"
        token_path.write_text("dummy_token")
        jobs = KiteMarketJobs(
            market, publisher, None, token_path,
        )
        jobs._kite_dump_cache = {datetime.now(UTC).date().isoformat(): fake_kite_dump}
        result = jobs.sync_snapshot_instruments({"snapshot_id": snap_id})
        assert result["resolved_count"] == 7  # 1 member + 6 benchmarks
        assert result["unresolved"] == []
        # Verify instruments are persisted
        instruments = market.instruments(symbol="RELIANCE", limit=1)
        assert len(instruments) == 1
        assert instruments[0]["provider_token"] == "256265"

    def test_sync_snapshot_instruments_reports_unresolved(self, tmp_path):
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        catalog = ArtifactCatalog(database)
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), catalog)
        snap_id = str(uuid4())
        observed = date(2026, 1, 1)
        market.create_universe_snapshot(
            snapshot_id=snap_id, index_name="NIFTY 500",
            snapshot_date=observed, source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000099,GHOSTSYM,Ghost,IT,EQ",
            members=[{"isin": "IN0000000099", "symbol": "GHOSTSYM", "company_name": "Ghost",
                      "industry": "IT", "series": "EQ"}],
        )
        # Kite dump without GHOSTSYM
        fake_kite_dump = [
            {"tradingsymbol": "NIFTY 50", "instrument_token": "256000", "instrument_type": "INDEX"},
            {"tradingsymbol": "NIFTY 500", "instrument_token": "256001", "instrument_type": "INDEX"},
            {"tradingsymbol": "NIFTY NEXT 50", "instrument_token": "256002", "instrument_type": "INDEX"},
            {"tradingsymbol": "NIFTY MIDCAP 150", "instrument_token": "256003", "instrument_type": "INDEX"},
            {"tradingsymbol": "NIFTY SMLCAP 250", "instrument_token": "256004", "instrument_type": "INDEX"},
            {"tradingsymbol": "INDIA VIX", "instrument_token": "256005", "instrument_type": "INDEX"},
        ]
        token_path = tmp_path / "token.txt"
        token_path.write_text("dummy_token")
        jobs = KiteMarketJobs(
            market, publisher, None, token_path,
        )
        jobs._kite_dump_cache = {datetime.now(UTC).date().isoformat(): fake_kite_dump}
        result = jobs.sync_snapshot_instruments({"snapshot_id": snap_id})
        assert result["resolved_count"] == 6  # only benchmarks, not GHOSTSYM
        assert len(result["unresolved"]) == 1
        assert result["unresolved"][0]["symbol"] == "GHOSTSYM"


# â”€â”€ Task 2.14: pipeline prerequisites check â”€â”€

class TestPipelinePrerequisites:
    def test_snapshot_exists_before_pipeline_can_proceed(self, tmp_path):
        """Pipeline should be able to check whether a universe snapshot exists."""
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        assert market.latest_universe_snapshot("NIFTY 500") is None
        snap_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap_id, index_name="NIFTY 500",
            snapshot_date=date(2026, 1, 1), source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,A,A,IT,EQ",
            members=[{"isin": "IN0000000001", "symbol": "A", "company_name": "A", "industry": "IT", "series": "EQ"}],
        )
        snapshot = market.latest_universe_snapshot("NIFTY 500")
        assert snapshot is not None
        assert snapshot["snapshot_id"] == snap_id


# â”€â”€ Comprehensive universe snapshot lifecycle test â”€â”€

class TestUniverseSnapshotLifecycle:
    def test_snapshot_diff_triggers_exit_eligibility(self, tmp_path):
        """When members are removed between snapshots, exit eligibility is persisted."""
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        observed = date(2026, 1, 1)
        # Add instruments so exit eligibility recording can find them
        market.upsert_instruments([
            TrackedInstrument("inst-a", "IN0000000001", "ALPHA", "NSE", "1", observed),
            TrackedInstrument("inst-b", "IN0000000002", "BETA", "NSE", "2", observed),
            TrackedInstrument("inst-c", "IN0000000003", "GAMMA", "NSE", "3", observed),
        ])
        # First snapshot: ALPHA and BETA
        snap1_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap1_id, index_name="NIFTY 500",
            snapshot_date=date(2026, 6, 1), source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,ALPHA,A,IT,EQ\nIN0000000002,BETA,B,IT,EQ",
            members=[
                {"isin": "IN0000000001", "symbol": "ALPHA", "company_name": "A", "industry": "IT", "series": "EQ"},
                {"isin": "IN0000000002", "symbol": "BETA", "company_name": "B", "industry": "IT", "series": "EQ"},
            ],
        )
        # Second snapshot: ALPHA and GAMMA (BETA removed, GAMMA added)
        snap2_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap2_id, index_name="NIFTY 500",
            snapshot_date=date(2026, 6, 2), source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,ALPHA,A,IT,EQ\nIN0000000003,GAMMA,C,IT,EQ",
            members=[
                {"isin": "IN0000000001", "symbol": "ALPHA", "company_name": "A", "industry": "IT", "series": "EQ"},
                {"isin": "IN0000000003", "symbol": "GAMMA", "company_name": "C", "industry": "IT", "series": "EQ"},
            ],
        )
        diff = market.universe_snapshot_diff(snap1_id, snap2_id)
        assert len(diff["removals"]) == 1
        assert diff["removals"][0]["isin"] == "IN0000000002"
        assert len(diff["additions"]) == 1
        assert diff["additions"][0]["isin"] == "IN0000000003"
        # Now record exit eligibility for the removed member
        result = market.record_exit_eligibility(
            instrument_id="inst-b", isin="IN0000000002", symbol="BETA",
            decision_date=date(2026, 6, 2), decision_snapshot_id=snap2_id,
            target_session_date=date(2026, 6, 3),
        )
        assert result is True
        assert market.is_exit_only("inst-b") is True
        assert market.is_exit_only("inst-a") is False
        assert market.is_exit_only("inst-c") is False


def test_history_fetch_requires_current_membership_or_exact_exit_session(tmp_path, monkeypatch):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    first = date(2026, 6, 1)
    decision = date(2026, 6, 2)
    target = date(2026, 6, 3)
    market.upsert_instruments([
        TrackedInstrument("removed", "IN0000000001", "REMOVED", "NSE", "11", first),
        TrackedInstrument("current", "IN0000000002", "CURRENT", "NSE", "12", first),
    ])
    market.create_universe_snapshot(snapshot_id="before", index_name="NIFTY 500",
        snapshot_date=first, source_url="fixture://nse", raw_csv=b"before",
        members=[{"isin": "IN0000000001", "symbol": "REMOVED", "company_name": "Removed",
                  "industry": "IT", "series": "EQ"}])
    market.create_universe_snapshot(snapshot_id="decision", index_name="NIFTY 500",
        snapshot_date=decision, source_url="fixture://nse", raw_csv=b"after",
        members=[{"isin": "IN0000000002", "symbol": "CURRENT", "company_name": "Current",
                  "industry": "IT", "series": "EQ"}])
    market.record_exit_eligibility(instrument_id="removed", isin="IN0000000001",
        symbol="REMOVED", decision_date=decision, decision_snapshot_id="decision",
        target_session_date=target)
    queue = JobStore(database)
    planner = MarketRefreshPlanner(database, market, queue)
    planned = planner.schedule({"start_date": first.isoformat(), "end_date": first.isoformat()})
    queued_symbols = {item["symbol"] for job_id in planned["job_ids"]
                      for item in queue.get(job_id).payload.get("items", [])}
    assert "CURRENT" in queued_symbols
    assert "REMOVED" not in queued_symbols
    jobs = KiteMarketJobs(market, publisher, None, tmp_path / "token.txt")
    calls = []

    class Client:
        def historical_data(self, token, start, end, interval):
            calls.append((token, start, end))
            return [{"date": target, "open": 100, "high": 101, "low": 99,
                     "close": 100, "volume": 10}]

    monkeypatch.setattr(jobs, "_client", Client)
    monkeypatch.setattr("src.application.providers._ProviderThrottle.wait", lambda self: None)
    payload = {"symbol": "REMOVED", "exchange": "NSE",
               "start_date": target.isoformat(), "end_date": target.isoformat()}
    with pytest.raises(DomainValidationError, match="outside the current"):
        jobs.fetch_bars(payload)
    with pytest.raises(DomainValidationError, match="outside the current"):
        jobs.fetch_bulk_bars({"items": [{"symbol": "REMOVED"}],
            "start_date": target.isoformat(), "end_date": target.isoformat()}, None)
    assert calls == []
    fetched = jobs.fetch_bars({**payload, "exit_only": True})
    assert fetched["bar_count"] == 1
    assert len(calls) == 1
    assert market.has_coverage("removed", target, target, "kite", coverage_context="exit_only")
    assert not market.has_coverage("removed", target, target, "kite")
    assert jobs.fetch_bars({**payload, "exit_only": True})["skipped"] is True
    with pytest.raises(DomainValidationError, match="exit-only"):
        jobs.fetch_bars({**payload, "start_date": decision.isoformat(), "exit_only": True})


def test_legacy_fetch_coverage_upgrade_preserves_regular_windows(tmp_path):
    from src.application.sqlite import sqlite_connection

    database = tmp_path / "system.db"
    market = MarketRepository(database)
    day = date(2026, 6, 1)
    market.upsert_instruments([TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "1", day)])
    market.record_fetch_coverage("stock", day, day, provider="kite", bar_count=1)
    with sqlite_connection(database) as connection:
        connection.execute("""CREATE TABLE legacy_fetch_coverage (
            instrument_id TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
            provider TEXT NOT NULL, fetched_at TEXT NOT NULL, bar_count INTEGER NOT NULL,
            PRIMARY KEY(instrument_id, start_date, end_date, provider),
            FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""")
        connection.execute("""INSERT INTO legacy_fetch_coverage
            SELECT instrument_id, start_date, end_date, provider, fetched_at, bar_count
            FROM market_fetch_coverage""")
        connection.execute("DROP TABLE market_fetch_coverage")
        connection.execute("ALTER TABLE legacy_fetch_coverage RENAME TO market_fetch_coverage")
        connection.execute("DELETE FROM system_schema_migrations WHERE namespace='market' AND version>=16")
    upgraded = MarketRepository(database)
    assert upgraded.has_coverage("stock", day, day, "kite")
    assert not upgraded.has_coverage("stock", day, day, "kite", coverage_context="exit_only")
    upgraded.record_fetch_coverage("stock", day, day, provider="kite", bar_count=1,
                                   coverage_context="exit_only")
    assert upgraded.has_coverage("stock", day, day, "kite")
    assert upgraded.has_coverage("stock", day, day, "kite", coverage_context="exit_only")
