"""Phase 2 behavioral tests: universe snapshots, exit eligibility, benchmark set,
BSE removal, snapshot-driven strategy consumers, and refresh planner rules."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.application.catalog import ArtifactCatalog
from src.application.jobs import JobStore
from src.application.market_jobs import (
    BSE_INDEX_SYMBOLS,
    NSE_INDEX_SYMBOLS,
    PHASE2_BENCHMARK_SYMBOLS,
    KiteMarketJobs,
)
from src.application.market_refresh import MarketRefreshPlanner
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.publication import ArtifactPublisher
from src.application.universe_jobs import UniverseJobs
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactStore, DomainValidationError


# ── Task 2.9: six NSE benchmarks ──

class TestBenchmarkSet:
    def test_six_benchmarks_are_defined(self):
        expected = {"NIFTY 50", "NIFTY 500", "NIFTY NEXT 50", "NIFTY MIDCAP 150", "NIFTY SMLCAP 250", "INDIA VIX"}
        assert NSE_INDEX_SYMBOLS == expected
        assert PHASE2_BENCHMARK_SYMBOLS == expected

    def test_bse_index_symbols_is_empty(self):
        assert BSE_INDEX_SYMBOLS == frozenset()


# ── Task 2.7: BSE runtime removed ──

class TestBseRemoval:
    def test_sync_bse_instruments_raises(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(tmp_path / "system.db"))
        jobs = KiteMarketJobs(market, publisher, None, tmp_path / "token.txt", tmp_path / "nse.csv")
        with pytest.raises(DomainValidationError, match="BSE runtime support has been removed"):
            jobs.sync_bse_instruments({})


# ── Task 2.11: exit eligibility ──

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


# ── Task 2.12: refresh planner respects benchmarks and exit-only ──

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
        # Exit-only instruments should be excluded unless held
        assert "EXITING" not in queued
        excluded_ids = {item["instrument_id"] for item in result["excluded"]}
        assert "exiting" in excluded_ids


# ── Task 2.13: universe exit detection ──

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


# ── Task 2.8: snapshot-driven strategy consumer ──

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
        assert members == {"IN0000000001", "IN0000000002"}
        assert metadata["source"] == "SNAPSHOT_NIFTY500"
        assert metadata["snapshot_id"] == snap_id
        assert metadata["member_count"] == 2


# ── Task 2.6: snapshot-driven instrument sync ──

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
            market, publisher, None, token_path, tmp_path / "nse.csv",
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
            market, publisher, None, token_path, tmp_path / "nse.csv",
        )
        jobs._kite_dump_cache = {datetime.now(UTC).date().isoformat(): fake_kite_dump}
        result = jobs.sync_snapshot_instruments({"snapshot_id": snap_id})
        assert result["resolved_count"] == 6  # only benchmarks, not GHOSTSYM
        assert len(result["unresolved"]) == 1
        assert result["unresolved"][0]["symbol"] == "GHOSTSYM"


# ── Task 2.14: pipeline prerequisites check ──

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


# ── Comprehensive universe snapshot lifecycle test ──

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
