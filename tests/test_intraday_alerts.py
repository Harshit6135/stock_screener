from datetime import UTC, datetime

from src.application.catalog import ArtifactCatalog
from src.application.intraday_alerts import IntradayStopAlerts
from src.application.intraday_stream import IntradayStreamLease
from src.application.market_repository import MarketRepository
from src.application.market_web import create_market_blueprint
from src.application.publication import ArtifactPublisher
from src.execution_gateway import Ledger
from src.platform_kernel import ArtifactStore, Money, Quantity
from src.portfolio_accounting import Fill, FillSide


def test_intraday_stop_alert_is_immutable_and_does_not_create_fill(tmp_path):
    database = tmp_path / "system.db"
    ledger = Ledger(database)
    ledger.open_account("paper", Money(1000))
    ledger.record_fills(
        "paper", "buy-1", 0,
        [Fill("ABC", datetime(2026, 9, 1, tzinfo=UTC).date(), FillSide.BUY, Quantity(1), Money(100), Money(0), datetime(2026, 9, 1, 9, 15, tzinfo=UTC))],
    )
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    alerts = IntradayStopAlerts(database, ledger, publisher)
    payload = {"account_id": "paper", "observations": [{"instrument_id": "ABC", "price": "89", "observed_at": "2026-09-10T10:00:00+00:00"}]}
    first = alerts.ingest(payload)
    second = alerts.ingest(payload)
    assert first["alert_count"] == second["alert_count"] == 1
    assert first["fills_created"] == 0
    assert len(ledger.events("paper")) == 1
    assert alerts.read("paper")[0]["alert_id"] == first["alerts"][0]["alert_id"]


def test_intraday_alerts_have_sse_readback(tmp_path):
    from flask import Flask

    database = tmp_path / "system.db"
    ledger = Ledger(database)
    ledger.open_account("paper", Money(1000))
    ledger.record_fills("paper", "buy-1", 0, [Fill("ABC", datetime(2026, 9, 1, tzinfo=UTC).date(), FillSide.BUY, Quantity(1), Money(100), Money(0), datetime(2026, 9, 1, 9, 15, tzinfo=UTC))])
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    alerts = IntradayStopAlerts(database, ledger, publisher)
    alerts.ingest({"account_id": "paper", "observations": [{"instrument_id": "ABC", "price": "89", "observed_at": "2026-09-10T10:00:00+00:00"}]})
    app = Flask(__name__)
    app.register_blueprint(create_market_blueprint(MarketRepository(database), ArtifactCatalog(database), intraday_alerts=alerts))
    response = app.test_client().get("/api/v2/market/intraday/stop-alerts/stream?account_id=paper")
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert b"event: stop-alert" in response.data


def test_intraday_stream_lease_is_restart_safe(tmp_path):
    from flask import Flask

    database = tmp_path / "system.db"
    lease = IntradayStreamLease(database)
    app = Flask(__name__)
    app.register_blueprint(create_market_blueprint(MarketRepository(database), ArtifactCatalog(database), stream=lease))
    client = app.test_client()
    assert client.get("/api/v2/market/intraday/stream").json["enabled"] == 0
    assert client.post("/api/v2/market/intraday/stream", json={"action": "start", "account_id": "paper", "token_count": 2}).status_code == 202
    response = client.post(
        "/api/v2/market/intraday/stream",
        json={"action": "start", "account_id": "paper", "token_count": 2},
    )
    assert response.status_code == 202
    assert response.json["status"] == "REQUESTED"
    connected = client.post(
        "/api/v2/market/intraday/stream",
        json={"action": "connected", "token_count": 2},
    )
    assert connected.json["status"] == "CONNECTED"
    heartbeat = client.post(
        "/api/v2/market/intraday/stream",
        json={"action": "heartbeat"},
    )
    assert heartbeat.status_code == 202
    assert heartbeat.json["last_heartbeat_at"]
    failed = client.post(
        "/api/v2/market/intraday/stream",
        json={"action": "error", "message": "provider disconnected"},
    )
    assert failed.json["status"] == "ERROR"
    assert failed.json["last_error"] == "provider disconnected"
    restarted = IntradayStreamLease(database)
    assert restarted.state()["account_id"] == "paper"
    stopped = client.post(
        "/api/v2/market/intraday/stream",
        json={"action": "stop"},
    )
    assert stopped.json["status"] == "STOPPED"
