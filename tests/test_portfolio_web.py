from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from flask import Flask

from src.application.market_repository import MarketRepository, NormalizedBar, TrackedInstrument
from src.application.portfolio_web import create_portfolio_blueprint
from src.execution_gateway import Ledger


def test_manual_fill_lifecycle(tmp_path):
    database = tmp_path / "system.db"
    ledger = Ledger(database)
    market = MarketRepository(database)
    instrument_id = str(uuid4())
    market.upsert_instruments(
        [TrackedInstrument(instrument_id, "INE000000001", "ABC", "NSE", "42", date(2026, 9, 1))]
    )
    app = Flask(__name__)
    app.register_blueprint(create_portfolio_blueprint(ledger, market))
    client = app.test_client()

    assert client.get("/api/v2/portfolio/accounts").status_code == 200
    response = client.post(
        "/api/v2/portfolio/accounts",
        json={"account_id": "paper", "opening_cash": "1000"},
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
            "/api/v2/portfolio/accounts/paper/fills", json=command
        ).status_code
        == 201
    )
    assert (
        client.post("/api/v2/portfolio/accounts/paper/fills", json=command).json[
            "version"
        ]
        == 1
    )
    account = client.get("/api/v2/portfolio/accounts/paper")
    assert account.json["cash"] == "800"
    assert account.json["open_lots"][0]["symbol"] == "ABC"
    transfer = client.post(
        "/api/v2/portfolio/accounts/paper/cash-transfers",
        json={
            "idempotency_key": "withdraw-1",
            "expected_version": 1,
            "direction": "WITHDRAW",
            "amount": "100",
        },
    )
    assert transfer.status_code == 201
    assert transfer.json["version"] == 2
    assert client.get("/api/v2/portfolio/accounts/paper").json["cash"] == "700"
    valuation = client.get(
        "/api/v2/portfolio/accounts/paper/valuation?as_of_date=2026-09-03&persist=1"
    )
    assert valuation.status_code == 200
    assert valuation.json["stale_prices"] == 1
    market.upsert_bars(
        instrument_id,
        [NormalizedBar(instrument_id, datetime.now(ZoneInfo("Asia/Kolkata")).date(), 105, 110, 100, 108, 1000)],
        "ticker-snapshot",
    )
    assert client.get("/api/v2/portfolio/accounts/paper/ticker").status_code == 200
    ticker = client.get("/api/v2/portfolio/accounts/paper/ticker")
    assert ticker.status_code == 200
    assert ticker.json["basis"] == "latest_available_market_bar"
    assert ticker.json["holdings"][0]["fresh"] is True
    assert ticker.json["holdings"][0]["price"] == "108"
    stream = client.get(
        "/api/v2/portfolio/accounts/paper/ticker/stream"
    )
    assert stream.status_code == 200
    assert stream.mimetype == "text/event-stream"
    assert b"event: portfolio-ticker" in stream.data
    snapshots = client.get("/api/v2/portfolio/accounts/paper/valuation/snapshots")
    assert snapshots.status_code == 200
    assert snapshots.json["snapshots"][0]["as_of_date"] == "2026-09-03"
    summary = client.get(
        "/api/v2/portfolio/accounts/paper/summary?as_of_date=2026-09-04"
    )
    assert summary.status_code == 200
    assert summary.json["summary_basis"] == "checksum_verified_valuation_snapshot"
    history = client.get(
        "/api/v2/portfolio/accounts/paper/valuation/history"
    )
    assert history.status_code == 200
    assert history.json["history"][0]["snapshot_id"] == snapshots.json["snapshots"][0]["snapshot_id"]
    journal = client.get(
        "/api/v2/portfolio/accounts/paper/journal?long_term_days=1"
    )
    assert journal.status_code == 200
    assert journal.json["long_term_days"] == 1
    invalid = {
        "idempotency_key": "oversell",
        "expected_version": 2,
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
            "/api/v2/portfolio/accounts/paper/fills", json=invalid
        ).status_code
        == 400
    )
    events = client.get("/api/v2/portfolio/accounts/paper/events")
    assert len(events.json["events"]) == 2
