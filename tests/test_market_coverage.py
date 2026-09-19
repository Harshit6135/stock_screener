from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from flask import Flask

from src.application.catalog import ArtifactCatalog
from src.application.jobs import JobStore
from src.application.market_refresh import MarketRefreshPlanner
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.market_web import create_market_blueprint
from src.application.publication import ArtifactPublisher
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactStore, DomainValidationError, QualityStatus


def test_coverage_api_paginates_and_reports_latest_cataloged_source(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    catalog = ArtifactCatalog(database)
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), catalog)
    observed_on = date(2026, 1, 6)
    market.upsert_instruments(
        (
            TrackedInstrument("bse-empty", "IN0000000001", "AAA", "BSE", "10", observed_on),
            TrackedInstrument("nse-bars", "IN0000000002", "BBB", "NSE", "20", observed_on),
        )
    )
    first_id, latest_id = str(uuid4()), str(uuid4())
    publisher.publish_json("market/normalized", first_id, {"date": "2026-01-02"})
    publisher.publish_json(
        "market/normalized",
        latest_id,
        {"date": "2026-01-05"},
        quality=QualityStatus.PARTIAL,
    )
    catalog.set_status(latest_id, "QUALIFIED", "source requires review")
    for day, artifact_id in ((date(2026, 1, 2), first_id), (date(2026, 1, 5), latest_id)):
        market.upsert_bars(
            "nse-bars",
            (NormalizedBar("nse-bars", day, Decimal(10), Decimal(12), Decimal(9), Decimal(11), 5),),
            artifact_id,
        )

    app = Flask(__name__)
    app.register_blueprint(create_market_blueprint(market, catalog))
    client = app.test_client()

    first_page = client.get("/api/v2/market/coverage?limit=1").json
    assert first_page["limit"] == 1
    assert first_page["coverage"][0]["symbol"] == "AAA"
    assert first_page["coverage"][0]["bar_count"] == 0
    assert first_page["coverage"][0]["latest_source_artifact"] is None

    second_page = client.get("/api/v2/market/coverage?limit=1&offset=1").json
    covered = second_page["coverage"][0]
    assert covered["symbol"] == "BBB"
    assert covered["earliest_date"] == "2026-01-02"
    assert covered["latest_date"] == "2026-01-05"
    assert covered["bar_count"] == 2
    assert covered["latest_source_artifact"] == {
        "artifact_id": latest_id,
        "quality": "PARTIAL",
        "status": "QUALIFIED",
    }
    assert (
        client.get("/api/v2/market/coverage?symbol=BBB&exchange=NSE").json["coverage"][0][
            "instrument_id"
        ]
        == "nse-bars"
    )
    assert client.get("/api/v2/market/coverage?exchange=INVALID").status_code == 400
    assert client.get("/api/v2/market/coverage?limit=501").status_code == 400


def test_reconciliation_reports_symbol_level_exclusions_and_unmatched_sources(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    market.upsert_instruments(
        [
            TrackedInstrument("index", "INDEX:NIFTY", "NIFTY 500", "NSE", "", date(2026, 1, 1)),
            TrackedInstrument("missing-token", "IN0000000001", "MISSING", "NSE", "", date(2026, 1, 1)),
            TrackedInstrument("live", "IN0000000002", "LIVE", "NSE", "42", date(2026, 1, 1)),
        ]
    )
    planner = MarketRefreshPlanner(database, market, JobStore(database), publisher)
    report = planner.reconcile(
        {
            "as_of_date": "2026-01-05",
            "source_instruments": [{"isin": "IN0000000002", "symbol": "LIVE"}, {"isin": "IN0000000003", "symbol": "UNKNOWN"}],
        }
    )
    assert report["unmatched_source_symbols"] == ["UNKNOWN"]
    assert {(row["symbol"], row["reason"]) for row in report["excluded_identities"]} == {
        ("NIFTY 500", "index_identity"),
        ("MISSING", "missing_provider_token"),
    }
    assert publisher.store.read_json("reference/reconciliations", report["artifact_id"])[1]["unmatched_source_symbols"] == ["UNKNOWN"]


def test_refresh_schedules_only_fixed_universe_holdings_and_benchmark(tmp_path):
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
    market.upsert_universe_members(
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
        )
    )
    planner = MarketRefreshPlanner(
        database,
        market,
        jobs,
        held_instrument_ids=lambda: {"holding", "blocked", "unknown-holding"},
    )

    result = planner.schedule({"start_date": "2025-01-01", "end_date": "2025-12-31"})

    assert result["scheduled_count"] == 3
    queued = {jobs.get(job_id).payload["symbol"] for job_id in result["job_ids"]}
    assert queued == {"MEMBER", "HOLDING", "NIFTY 500"}
    assert "OUTSIDE" not in queued
    assert result["blocked_held_positions"] == [
        {"instrument_id": "blocked", "reason": "missing_provider_token"},
        {"instrument_id": "unknown-holding", "reason": "held_position_not_in_reference_catalog"},
    ]


def test_refresh_refuses_to_download_before_fixed_universe_is_built(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    planner = MarketRefreshPlanner(database, market, JobStore(database))

    with pytest.raises(DomainValidationError, match="fixed universe is empty"):
        planner.schedule({"start_date": "2025-01-01", "end_date": "2025-12-31"})
