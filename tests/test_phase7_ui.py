from flask import Flask

from src.application.dashboard_web import create_dashboard_blueprint
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.market_web import create_market_blueprint


def test_phase7_template_routes_and_legacy_redirects():
    app = Flask(__name__)
    app.register_blueprint(create_dashboard_blueprint())
    client = app.test_client()

    for path in ("/", "/actions", "/pipeline", "/rankings", "/universe", "/backtest", "/settings", "/logs"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'css/carbon-emerald.css' in response.get_data(as_text=True)
    for path in ("/app", "/portfolio"):
        assert client.get(path).status_code == 302


def test_index_history_is_bounded_and_read_only(tmp_path):
    repository = MarketRepository(tmp_path / "market.db")
    repository.upsert_instruments((
        TrackedInstrument("nifty", "INE000000001", "NIFTY 50", "NSE", "1", __import__("datetime").date(2026, 9, 1)),
    ))
    repository.upsert_index_quotes(({
        "instrument_id": "nifty", "exchange": "NSE", "symbol": "NIFTY 50",
        "last_price": "25000", "prev_close": "24900", "change_percent": 0.4,
        "observed_at": "2026-09-01T10:00:00+00:00",
    },), "quote-snapshot")
    app = Flask(__name__)
    app.register_blueprint(create_market_blueprint(repository, __import__("src.application.catalog", fromlist=["ArtifactCatalog"]).ArtifactCatalog(tmp_path / "artifacts")))
    response = app.test_client().get("/api/v2/market/indices/history?sessions=30")
    assert response.status_code == 200
    assert response.json["history"][0]["last_price"] == "25000"
    assert app.test_client().get("/api/v2/market/indices/history?sessions=31").status_code == 400
