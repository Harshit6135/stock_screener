from datetime import date
from uuid import uuid4

from flask import Flask

from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.portfolio_web import create_portfolio_blueprint
from src.execution_gateway import Ledger


def test_operator_protected_manual_fill_lifecycle(tmp_path):
    database = tmp_path / "system.db"
    ledger = Ledger(database)
    market = MarketRepository(database)
    market.upsert_instruments(
        [TrackedInstrument(str(uuid4()), "INE000000001", "ABC", "NSE", "42", date(2026, 9, 1))]
    )
    app = Flask(__name__)
    app.config["OPERATOR_TOKEN"] = "local-test-secret"
    app.register_blueprint(create_portfolio_blueprint(ledger, market))
    client = app.test_client()
    headers = {"X-Operator-Token": "local-test-secret"}

    assert client.get("/api/v2/portfolio/accounts").status_code == 401
    response = client.post(
        "/api/v2/portfolio/accounts",
        json={"account_id": "paper", "opening_cash": "1000"},
        headers=headers,
    )
    assert response.status_code == 201
    command = {
        "idempotency_key": "manual-buy-1",
        "expected_version": 0,
        "fills": [
            {
                "symbol": "ABC",
                "fill_date": "2026-09-02",
                "side": "BUY",
                "units": 2,
                "price": "100",
            }
        ],
    }
    assert (
        client.post(
            "/api/v2/portfolio/accounts/paper/fills", json=command, headers=headers
        ).status_code
        == 201
    )
    assert (
        client.post("/api/v2/portfolio/accounts/paper/fills", json=command, headers=headers).json[
            "version"
        ]
        == 1
    )
    account = client.get("/api/v2/portfolio/accounts/paper", headers=headers)
    assert account.json["cash"] == "800"
    assert account.json["open_lots"][0]["symbol"] == "ABC"
    invalid = {
        "idempotency_key": "oversell",
        "expected_version": 1,
        "fills": [
            {
                "symbol": "ABC",
                "fill_date": "2026-09-03",
                "side": "SELL",
                "units": 3,
                "price": "110",
            }
        ],
    }
    assert (
        client.post(
            "/api/v2/portfolio/accounts/paper/fills", json=invalid, headers=headers
        ).status_code
        == 400
    )
    events = client.get("/api/v2/portfolio/accounts/paper/events", headers=headers)
    assert len(events.json["events"]) == 1
