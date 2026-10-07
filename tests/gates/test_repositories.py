import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from src.domains.market_data import NormalizedBar
from src.domains.reference_data import (
    ReferenceDataRepository,
)
from src.domains.reference_data import (
    TrackedInstrument as ReferenceTrackedInstrument,
)
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.platform_kernel import DomainValidationError

START = date(2026, 1, 1)


def _members(*items: tuple[str, str, str]):
    return [
        {
            "isin": isin,
            "symbol": symbol,
            "company_name": symbol + " Ltd",
            "industry": "Industry",
            "series": series,
        }
        for isin, symbol, series in items
    ]


def test_snapshot_is_insert_only_and_as_of_selection_is_deterministic(tmp_path):
    repository = MarketRepository(tmp_path / "market.db")
    first = repository.create_universe_snapshot(
        snapshot_id="first",
        index_name="NIFTY 500",
        snapshot_date=date(2026, 1, 2),
        source_url="https://example.test/one",
        raw_csv=b"one",
        members=_members(("INE001", "ONE", "EQ")),
    )
    reused = repository.create_universe_snapshot(
        snapshot_id="different",
        index_name="NIFTY 500",
        snapshot_date=date(2026, 1, 2),
        source_url="https://example.test/two",
        raw_csv=b"two",
        members=_members(("INE002", "TWO", "BE")),
    )
    assert reused["snapshot_id"] == first["snapshot_id"] == "first"
    assert repository.universe_snapshot_as_of("NIFTY 500", date(2025, 1, 1))["earliest_fallback"]


def test_snapshot_diff_captures_membership_and_series_changes(tmp_path):
    repository = MarketRepository(tmp_path / "market.db")
    repository.create_universe_snapshot(
        snapshot_id="old",
        index_name="NIFTY 500",
        snapshot_date=date(2026, 1, 1),
        source_url="https://example.test",
        raw_csv=b"old",
        members=_members(("INE001", "ONE", "EQ"), ("INE002", "TWO", "EQ")),
    )
    repository.create_universe_snapshot(
        snapshot_id="new",
        index_name="NIFTY 500",
        snapshot_date=date(2026, 1, 2),
        source_url="https://example.test",
        raw_csv=b"new",
        members=_members(("INE001", "ONE", "BE"), ("INE003", "THREE", "EQ")),
    )
    diff = repository.universe_snapshot_diff("old", "new")
    assert [item["isin"] for item in diff["additions"]] == ["INE003"]
    assert [item["isin"] for item in diff["removals"]] == ["INE002"]
    assert diff["series_transitions"] == [{"isin": "INE001", "from": "EQ", "to": "BE"}]





def repository(tmp_path, *, index=False):
    market = MarketRepository(tmp_path / "system.db")
    market.upsert_instruments(
        [
            TrackedInstrument(
                "stock",
                "INDEX:NIFTY500" if index else "IN0000000001",
                "NIFTY 500" if index else "STOCK",
                "NSE",
                "42",
                START,
            )
        ]
    )
    return market


def bar(offset, close=100, volume=100):
    price = Decimal(str(close))
    return NormalizedBar(
        "stock", START + timedelta(days=offset), price, price, price, price, volume
    )


def test_sparse_repeat_does_not_invent_close_gap(tmp_path):
    market = repository(tmp_path)
    rows = [bar(0, 100), bar(1, 110), bar(2, 121)]
    market.upsert_bars("stock", rows, "initial")
    revision = market.market_history_revision("stock")
    market.upsert_bars("stock", [rows[0], rows[2]], "sparse-repeat")
    assert market.quality_events(check_type="close_gap") == []
    assert market.market_history_revision("stock") == revision


def test_sparse_repeat_respects_intervening_nonzero_volume(tmp_path):
    market = repository(tmp_path)
    rows = [bar(i, volume=100 if i == 3 else 0) for i in range(7)]
    market.upsert_bars("stock", rows, "initial")
    market.upsert_bars("stock", [item for i, item in enumerate(rows) if i != 3], "sparse-repeat")
    assert market.quality_events(check_type="zero_volume_streak") == []


def test_historical_correction_checks_stored_successor_and_retains_bars(tmp_path):
    market = repository(tmp_path)
    market.upsert_bars("stock", [bar(0), bar(1)], "initial")
    market.upsert_bars("stock", [bar(0, 50)], "correction")
    events = market.quality_events(check_type="close_gap")
    assert len(events) == 1
    assert events[0]["as_of_date"] == (START + timedelta(days=1)).isoformat()
    assert events[0]["detail"]["expected_close"] == 50
    assert events[0]["detail"]["source_snapshot_id"] == "initial"
    assert events[0]["detail"]["validation_snapshot_id"] == "correction"
    assert len(market.bars("stock", START, START + timedelta(days=1))) == 2
    market.upsert_bars("stock", [bar(0, 50)], "repeat")
    assert len(market.quality_events(check_type="close_gap")) == 1


def test_historical_volume_correction_checks_following_sessions(tmp_path):
    market = repository(tmp_path)
    market.upsert_bars("stock", [bar(i, volume=100 if i == 0 else 0) for i in range(6)], "initial")
    assert market.quality_events(check_type="zero_volume_streak") == []
    market.upsert_bars("stock", [bar(0, volume=0)], "correction")
    events = market.quality_events(check_type="zero_volume_streak")
    assert len(events) == 1
    assert events[0]["as_of_date"] == (START + timedelta(days=5)).isoformat()


def test_index_has_no_traded_volume_streak_warning(tmp_path):
    market = repository(tmp_path, index=True)
    market.upsert_bars("stock", [bar(i, volume=0) for i in range(10)], "index-history")
    assert market.quality_events(check_type="zero_volume_streak") == []


def test_unknown_quality_instrument_is_a_domain_error(tmp_path):
    market = repository(tmp_path)
    with pytest.raises(DomainValidationError, match="not registered"):
        market.record_quality_event("unknown", START, "missing_bar", "WARNING", {})


class TestExitEligibility:
    def test_record_and_query_exit_eligibility(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        observed = date(2026, 1, 1)
        market.upsert_instruments(
            [
                TrackedInstrument("inst-1", "IN0000000001", "ALPHA", "NSE", "100", observed),
                TrackedInstrument("inst-2", "IN0000000002", "BETA", "NSE", "200", observed),
            ]
        )
        decision_date = date(2026, 6, 1)
        target_session = date(2026, 6, 2)
        snapshot_id = str(uuid4())
        # Manually create a snapshot so FK is satisfied (or rely on IGNORE)
        market.create_universe_snapshot(
            snapshot_id=snapshot_id,
            index_name="NIFTY 500",
            snapshot_date=decision_date,
            source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,ALPHA,Alpha Co,IT,EQ",
            members=[
                {
                    "isin": "IN0000000001",
                    "symbol": "ALPHA",
                    "company_name": "Alpha Co",
                    "industry": "IT",
                    "series": "EQ",
                }
            ],
        )
        # Record exit eligibility for removed member
        result = market.record_exit_eligibility(
            instrument_id="inst-2",
            isin="IN0000000002",
            symbol="BETA",
            decision_date=decision_date,
            decision_snapshot_id=snapshot_id,
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
            instrument_id="inst-2",
            isin="IN0000000002",
            symbol="BETA",
            decision_date=decision_date,
            decision_snapshot_id=snapshot_id,
            target_session_date=target_session,
        )
        assert second_result is False

    def test_exit_eligibility_rejects_invalid_dates(self, tmp_path):
        market = MarketRepository(tmp_path / "system.db")
        with pytest.raises(DomainValidationError, match="exit eligibility record is invalid"):
            market.record_exit_eligibility(
                instrument_id="x",
                isin="y",
                symbol="z",
                decision_date=date(2026, 6, 2),  # after target
                decision_snapshot_id="snap",
                target_session_date=date(2026, 6, 1),
            )


class TestUniverseSnapshotLifecycle:
    def test_snapshot_diff_triggers_exit_eligibility(self, tmp_path):
        """When members are removed between snapshots, exit eligibility is persisted."""
        database = tmp_path / "system.db"
        market = MarketRepository(database)
        observed = date(2026, 1, 1)
        # Add instruments so exit eligibility recording can find them
        market.upsert_instruments(
            [
                TrackedInstrument("inst-a", "IN0000000001", "ALPHA", "NSE", "1", observed),
                TrackedInstrument("inst-b", "IN0000000002", "BETA", "NSE", "2", observed),
                TrackedInstrument("inst-c", "IN0000000003", "GAMMA", "NSE", "3", observed),
            ]
        )
        # First snapshot: ALPHA and BETA
        snap1_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap1_id,
            index_name="NIFTY 500",
            snapshot_date=date(2026, 6, 1),
            source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,ALPHA,A,IT,EQ\nIN0000000002,BETA,B,IT,EQ",
            members=[
                {
                    "isin": "IN0000000001",
                    "symbol": "ALPHA",
                    "company_name": "A",
                    "industry": "IT",
                    "series": "EQ",
                },
                {
                    "isin": "IN0000000002",
                    "symbol": "BETA",
                    "company_name": "B",
                    "industry": "IT",
                    "series": "EQ",
                },
            ],
        )
        # Second snapshot: ALPHA and GAMMA (BETA removed, GAMMA added)
        snap2_id = str(uuid4())
        market.create_universe_snapshot(
            snapshot_id=snap2_id,
            index_name="NIFTY 500",
            snapshot_date=date(2026, 6, 2),
            source_url="https://nse.example",
            raw_csv=b"ISIN Code,Symbol,Company Name,Industry,Series\nIN0000000001,ALPHA,A,IT,EQ\nIN0000000003,GAMMA,C,IT,EQ",
            members=[
                {
                    "isin": "IN0000000001",
                    "symbol": "ALPHA",
                    "company_name": "A",
                    "industry": "IT",
                    "series": "EQ",
                },
                {
                    "isin": "IN0000000003",
                    "symbol": "GAMMA",
                    "company_name": "C",
                    "industry": "IT",
                    "series": "EQ",
                },
            ],
        )
        diff = market.universe_snapshot_diff(snap1_id, snap2_id)
        assert len(diff["removals"]) == 1
        assert diff["removals"][0]["isin"] == "IN0000000002"
        assert len(diff["additions"]) == 1
        assert diff["additions"][0]["isin"] == "IN0000000003"
        # Now record exit eligibility for the removed member
        result = market.record_exit_eligibility(
            instrument_id="inst-b",
            isin="IN0000000002",
            symbol="BETA",
            decision_date=date(2026, 6, 2),
            decision_snapshot_id=snap2_id,
            target_session_date=date(2026, 6, 3),
        )
        assert result is True
        assert market.is_exit_only("inst-b") is True
        assert market.is_exit_only("inst-a") is False
        assert market.is_exit_only("inst-c") is False


def test_fresh_application_uses_only_owner_migrations(tmp_path):
    database = tmp_path / "combined.db"
    reference = ReferenceDataRepository(database)
    reference.upsert_instruments(
        [ReferenceTrackedInstrument("instrument-1", "ISIN-1", "ONE", "NSE", "11", date(2026, 1, 2))]
    )

    market = MarketRepository(database)

    assert market.instrument_by_id("instrument-1")["series"] == "EQ"
    with sqlite3.connect(database) as connection:
        versions = dict(
            connection.execute(
                "SELECT namespace, MAX(version) FROM system_schema_migrations GROUP BY namespace"
            )
        )
    assert versions == {"market_data": 2, "reference_data": 1}
