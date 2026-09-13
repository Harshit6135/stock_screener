"""Tests verifying all ported V3 compatibility features, endpoints, and workflows."""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from flask import Flask

from src.application.compatibility_web import create_compatibility_blueprint
from src.application.composition import ApplicationServices
from src.application.market_repository import TrackedInstrument
from src.application.sqlite import sqlite_connection
from src.market_data import NormalizedBar
from src.platform_kernel import Money, Quantity
from src.portfolio_accounting import Fill, FillSide


@pytest.fixture
def test_app(tmp_path):
    services = ApplicationServices.create(tmp_path)
    instrument_id = str(uuid4())
    services.market.upsert_instruments(
        [TrackedInstrument(instrument_id, "INE002A01018", "RELIANCE", "NSE", "738561", date(2026, 9, 4))]
    )
    services.market.upsert_bars(
        instrument_id,
        [
            NormalizedBar(instrument_id, date(2026, 9, 3), 2900, 2950, 2890, 2920, 50000),
            NormalizedBar(instrument_id, date(2026, 9, 4), 2920, 2980, 2910, 2950, 60000),
        ],
        "test-bars-reliance",
    )
    # Publish dummy ranking
    ranking_art = services.publisher.publish_json(
        "rankings/strategy1", str(uuid4()), {"week_end": "2026-09-04"}
    )
    with sqlite_connection(services.database) as conn:
        conn.execute(
            """INSERT INTO research_weekly_rankings
               (strategy_id, week_end, instrument_id, symbol, score, rank, artifact_id)
               VALUES ('strategy1', '2026-09-04', ?, 'RELIANCE', 88.5, 1, ?)""",
            (instrument_id, ranking_art.artifact_id),
        )

    # Initialize paper ledger account and initial fill
    services.ledger.open_account("paper", Money(Decimal("10000000")))
    fill = Fill(instrument_id, date(2026, 9, 4), FillSide.BUY, Quantity(10), Money(Decimal("2920")))
    services.ledger.record_fills("paper", "init-fill", 0, [fill])

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["OPERATOR_TOKEN"] = "test-operator-secret"
    app.register_blueprint(create_compatibility_blueprint(services))

    @app.get("/dashboard")
    def dashboard():
        return "<html>Dashboard</html>", 200

    return app, services, instrument_id


def test_dashboard_and_openapi_routes(test_app):
    app, services, _ = test_app
    client = app.test_client()

    # Dashboard HTML
    resp = client.get("/dashboard")
    assert resp.status_code == 200

    # Swagger UI
    resp = client.get("/api/v1/swagger-ui")
    assert resp.status_code == 200
    assert "SwaggerUIBundle" in resp.text

    # OpenAPI JSON spec
    resp = client.get("/api/v1/openapi.json")
    assert resp.status_code == 200
    spec = resp.get_json()
    assert spec["openapi"] == "3.0.3"
    assert "/api/v1/app/run-pipeline" in spec["paths"]


def test_init_and_universe_status(test_app):
    app, services, _ = test_app
    client = app.test_client()
    headers = {"X-Operator-Token": "test-operator-secret"}

    resp = client.get("/api/v1/init/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ready"
    assert data["instruments_count"] >= 1


def test_market_data_crud_and_latest_date(test_app):
    app, services, instrument_id = test_app
    client = app.test_client()
    headers = {"X-Operator-Token": "test-operator-secret"}

    # Latest date
    resp = client.get("/api/v1/marketdata/latest-date")
    assert resp.status_code == 200
    assert resp.get_json()["latest_date"] == "2026-09-04"

    # Get bars for symbol
    resp = client.get("/api/v1/marketdata/RELIANCE")
    assert resp.status_code == 200
    bars = resp.get_json()
    assert len(bars) == 2
    assert bars[-1]["close"] == 2950.0

    # Insert bars
    payload = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "bars": [{"as_of_date": "2026-09-07", "open": 2960, "high": 2990, "low": 2940, "close": 2975, "volume": 40000}],
    }
    resp = client.post("/api/v1/marketdata", json=payload, headers=headers)
    assert resp.status_code == 201

    # Delete bars after cutoff
    resp = client.delete("/api/v1/marketdata/RELIANCE?after=2026-09-06", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] == 1


def test_indicators_patch_and_query(test_app):
    app, services, _ = test_app
    client = app.test_client()
    headers = {"X-Operator-Token": "test-operator-secret"}

    # Query indicators for symbol
    resp = client.get("/api/v1/indicators/RELIANCE")
    assert resp.status_code == 200
    assert resp.get_json()["symbol"] == "RELIANCE"

    # Patch indicators
    resp = client.post("/api/v1/indicators/patch", json={"indicators": ["EMA_200", "RSI_14"]}, headers=headers)
    assert resp.status_code == 202
    assert "job_id" in resp.get_json()


def test_portfolio_holdings_summary_and_ticker(test_app):
    app, services, _ = test_app
    client = app.test_client()

    # Portfolio holdings
    resp = client.get("/api/v1/investment/holdings")
    assert resp.status_code == 200
    holdings = resp.get_json()
    assert len(holdings) == 1
    assert holdings[0]["symbol"] == "RELIANCE"
    assert holdings[0]["units"] == 10

    # Summary
    resp = client.get("/api/v1/investment/summary")
    assert resp.status_code == 200
    summary = resp.get_json()
    assert summary["invested_capital"] > 0
    assert summary["remaining_capital"] > 0

    # Live ticker start, read, stop
    resp = client.post("/api/v1/investment/prices/start")
    assert resp.status_code == 200

    resp = client.get("/api/v1/investment/prices")
    assert resp.status_code == 200
    prices = resp.get_json()
    assert "RELIANCE" in prices
    assert prices["RELIANCE"]["last_price"] == 2950.0

    resp = client.post("/api/v1/investment/prices/stop")
    assert resp.status_code == 200


def test_ranking_symbol_friday_normalization(test_app):
    app, services, _ = test_app
    client = app.test_client()

    # Query date: 2026-09-06 (Sunday) -> Should normalize to 2026-09-04 (Friday)
    resp = client.get("/api/v1/ranking/symbol/RELIANCE?date=2026-09-06")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["symbol"] == "RELIANCE"
    assert data["week_end"] == "2026-09-04"
    assert data["rank"] == 1
    assert data["close_price"] == 2950.0


def test_pipeline_in_order_execution(test_app):
    app, services, _ = test_app
    client = app.test_client()
    headers = {"X-Operator-Token": "test-operator-secret"}

    payload = {
        "init": True,
        "marketdata": True,
        "indicators": True,
        "ranking": True,
    }
    resp = client.post("/api/v1/app/run-pipeline", json=payload, headers=headers)
    assert resp.status_code == 200


    res = resp.get_json()
    assert res["message"] == "Pipeline completed successfully"
    assert "init" in res["results"]
    assert "marketdata" in res["results"]
    assert "indicators" in res["results"]
    assert "ranking" in res["results"]


def test_delete_backtest_run(test_app):
    app, services, _ = test_app
    client = app.test_client()
    headers = {"X-Operator-Token": "test-operator-secret"}

    # Deleting nonexistent run returns 404
    resp = client.delete("/api/v1/backtest/history/nonexistent-run-id", headers=headers)
    assert resp.status_code == 404
