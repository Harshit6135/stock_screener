from datetime import date

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.market_data import NSE_INDEX_SYMBOLS, NormalizedBar
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.session_coverage import CompletedSessionCoverage
from src.platform_kernel import SqliteArtifactStore

DAY = date(2026, 1, 5)


def coverage_fixture(tmp_path):
    market, _ = setup_market(tmp_path)
    records = [
        TrackedInstrument("old", "IN0000000001", "OLD", "NSE", "1", DAY),
        TrackedInstrument("new", "IN0000000002", "NEW", "NSE", "2", DAY),
        TrackedInstrument("unrelated", "IN0000000003", "UNRELATED", "NSE", "3", DAY),
    ]
    records += [
        TrackedInstrument(symbol, "INDEX:" + symbol, symbol, "NSE", str(i + 10), DAY)
        for i, symbol in enumerate(sorted(NSE_INDEX_SYMBOLS))
    ]
    market.upsert_instruments(records)
    seed_snapshot(market, "first", DAY, [("IN0000000001", "OLD")])
    seed_snapshot(market, "second", date(2026, 1, 7), [("IN0000000002", "NEW")])
    # Jan 6 is absent from the observed benchmark calendar; Jan 9 is incomplete.
    sessions = [DAY, date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9)]
    for symbol in NSE_INDEX_SYMBOLS:
        seed_bars(market, symbol, sessions)
    seed_bars(market, "old", [DAY, date(2026, 1, 7)])  # Extra exit-only data is not membership.
    seed_bars(market, "new", [date(2026, 1, 7)])
    return market


def setup_market(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    publisher = ArtifactPublisher(SqliteArtifactStore(database), ArtifactCatalog(database))
    return market, publisher


def seed_bars(market, identity, days):
    market.upsert_bars(
        identity,
        [NormalizedBar(identity, day, 100, 101, 99, 100, 1) for day in days],
        "fixture-bars",
    )


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


def test_completed_coverage_uses_membership_and_retains_missing_stock(tmp_path):
    market = coverage_fixture(tmp_path)
    audit = CompletedSessionCoverage(market, NSE_INDEX_SYMBOLS, lambda: date(2026, 1, 9))
    report = audit.record(DAY, date(2026, 1, 9))
    assert report["observed_session_count"] == 3
    assert report["skipped_incomplete_sessions"] == 1
    assert report["status"] == "PARTIAL"
    assert [
        (row["instrument_id"], row["missing_session_sample"]) for row in report["missing_bars"]
    ] == [("new", ["2026-01-08"])]
    assert report["missing_bars"][0]["snapshot_id"] == "second"
    assert report["missing_bars"][0]["market_revision"] == market.market_history_revision("new")
    assert report["missing_identities"] == []
    audit.record(DAY, date(2026, 1, 9))
    assert len(market.quality_events(check_type="missing_completed_sessions")) == 1
    assert market.instrument_by_id("new") is not None
    assert market.universe_snapshot_members("second")[0]["symbol"] == "NEW"
    seed_bars(market, "new", [date(2026, 1, 8)])
    assert audit.read(DAY, date(2026, 1, 9))["status"] == "COMPLETE"


def test_calendar_never_uses_unrelated_bars_as_session_proof(tmp_path):
    market, _ = setup_market(tmp_path)
    market.upsert_instruments(
        [
            TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "1", DAY),
            TrackedInstrument("other", "OTHER:INDEX", "OTHER INDEX", "NSE", "2", DAY),
        ]
    )
    seed_snapshot(market, "first", DAY, [("IN0000000001", "STOCK")])
    seed_bars(market, "stock", [DAY])
    seed_bars(market, "other", [DAY])
    report = CompletedSessionCoverage(market, NSE_INDEX_SYMBOLS, lambda: date(2026, 1, 9)).read(
        DAY, DAY
    )
    assert report["calendar_status"] == "UNAVAILABLE"
    assert report["status"] == "UNAVAILABLE"
    assert report["missing_bars"] == []


def test_coverage_earliest_fallback_and_unresolved_benchmarks(tmp_path):
    market, _ = setup_market(tmp_path)
    market.upsert_instruments(
        [
            TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "1", DAY),
            TrackedInstrument("nifty", "INDEX:NIFTY500", "NIFTY 500", "NSE", "2", DAY),
        ]
    )
    seed_snapshot(market, "later", date(2026, 1, 8), [("IN0000000001", "STOCK")])
    seed_bars(market, "nifty", [DAY])
    seed_bars(market, "stock", [DAY])
    report = CompletedSessionCoverage(market, NSE_INDEX_SYMBOLS, lambda: date(2026, 1, 9)).read(
        DAY, DAY
    )
    assert report["membership_lineage"][0]["earliest_fallback"] is True
    assert len(report["missing_identities"]) == 4
    assert report["status"] == "PARTIAL"
