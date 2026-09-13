from datetime import date
from decimal import Decimal
from uuid import uuid4

from flask import Flask

from src.application.catalog import ArtifactCatalog
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.market_web import create_market_blueprint
from src.application.publication import ArtifactPublisher
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactStore, QualityStatus


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
