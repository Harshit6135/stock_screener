from flask import Flask

from src.domains.artifacts import ArtifactCatalog
from src.gates.http.market import create_market_blueprint
from src.gates.repositories import MarketRepository
from src.gates.workflows.intraday_stream import IntradayStreamLease


def test_intraday_stream_lease_http_lifecycle_is_restart_safe(tmp_path):
    database = tmp_path / "system.db"
    lease = IntradayStreamLease(database)
    app = Flask(__name__)
    app.register_blueprint(
        create_market_blueprint(MarketRepository(database), ArtifactCatalog(database), stream=lease)
    )
    client = app.test_client()
    assert client.get("/api/market/intraday/stream").json["enabled"] == 0
    requested = client.post(
        "/api/market/intraday/stream",
        json={"action": "start", "account_id": "paper", "token_count": 2},
    )
    assert requested.status_code == 202
    assert requested.json["status"] == "REQUESTED"
    connected = client.post(
        "/api/market/intraday/stream", json={"action": "connected", "token_count": 2}
    )
    assert connected.json["status"] == "CONNECTED"
    heartbeat = client.post("/api/market/intraday/stream", json={"action": "heartbeat"})
    assert heartbeat.status_code == 202
    assert heartbeat.json["last_heartbeat_at"]
    failed = client.post(
        "/api/market/intraday/stream",
        json={"action": "error", "message": "provider disconnected"},
    )
    assert failed.json["status"] == "ERROR"
    assert failed.json["last_error"] == "provider disconnected"
    assert IntradayStreamLease(database).state()["account_id"] == "paper"
    stopped = client.post("/api/market/intraday/stream", json={"action": "stop"})
    assert stopped.json["status"] == "STOPPED"
