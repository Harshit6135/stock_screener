from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask

from src.domains.market_data import LiveQuotes
from src.domains.operations import JobStore
from src.domains.portfolio_accounting import Ledger
from src.gates.http.operations import create_operations_blueprint
from src.gates.http.portfolio import create_portfolio_blueprint
from src.gates.http.wiki import create_wiki_blueprint
from src.gates.repositories import MarketRepository, NormalizedBar, TrackedInstrument
from src.gates.workflows.intraday_stream import IntradayStreamLease


def live_client(tmp_path):
    database = tmp_path / "system.db"
    ledger, market, quotes = Ledger(database), MarketRepository(database), LiveQuotes(database)
    lease = IntradayStreamLease(database)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    market.upsert_instruments([TrackedInstrument("abc", "INE000000001", "ABC", "NSE", "42", today)])
    market.upsert_bars(
        "abc",
        [NormalizedBar("abc", today - timedelta(days=1), 100, 100, 100, 100, 1000)],
        "prior-close",
    )
    app = Flask(__name__)
    app.register_blueprint(
        create_portfolio_blueprint(ledger, market, live_quotes=quotes, intraday_stream=lease)
    )
    client = app.test_client()
    client.post(
        "/api/portfolio/accounts",
        json={"account_id": "paper", "opening_cash": "1000", "opening_date": today.isoformat()},
    )
    result = client.post(
        "/api/portfolio/accounts/paper/fills",
        json={
            "idempotency_key": "buy",
            "expected_version": 0,
            "fills": [
                {
                    "symbol": "ABC",
                    "fill_date": today.isoformat(),
                    "side": "BUY",
                    "units": 2,
                    "price": "90",
                }
            ],
        },
    )
    assert result.status_code == 201
    return client, quotes, lease, ledger


def ingest_quote(quotes, account, price, age=0):
    stamp = (datetime.now(UTC) - timedelta(seconds=age)).isoformat()
    quotes.ingest(
        {
            "account_id": account,
            "observations": [
                {
                    "instrument_id": "abc",
                    "price": str(price),
                    "observed_at": stamp,
                    "received_at": stamp,
                    "source": "kite-stream",
                    "exchange_timestamp_available": True,
                }
            ],
        }
    )


def test_live_prices_revalue_holdings_and_day_pnl_without_changing_ledger(tmp_path):
    client, quotes, lease, ledger = live_client(tmp_path)
    before = ledger.events("paper")
    lease.start("paper", 1)
    lease.connected(1)
    ingest_quote(quotes, "different-account", 999)
    missing = client.get("/api/portfolio/accounts/paper/ticker?live=1").json
    assert missing["all_quotes_fresh"] is False
    assert missing["holdings"][0]["price"] == "100"
    ingest_quote(quotes, "paper", 110)
    live = client.get("/api/portfolio/accounts/paper/ticker?live=1").json
    assert live["all_quotes_fresh"] is True
    assert Decimal(live["equity"]) == 1040
    assert Decimal(live["unrealised_pnl"]) == 40
    assert Decimal(live["day_pnl"]) == 20
    assert live["stream"]["status"] == "CONNECTED"
    assert live["holdings"][0]["quote_time"]
    assert ledger.events("paper") == before


def test_stale_quotes_are_not_presented_as_live_and_stream_updates(tmp_path, monkeypatch):
    client, quotes, _lease, _ledger = live_client(tmp_path)
    ingest_quote(quotes, "paper", 999, age=120)
    stale = client.get("/api/portfolio/accounts/paper/ticker?live=1").json
    assert stale["all_quotes_fresh"] is False
    assert stale["holdings"][0]["price_basis"] == "market-bar"
    assert stale["holdings"][0]["price"] == "100"
    monkeypatch.setattr("src.gates.http.portfolio.time.sleep", lambda _: None)
    response = client.get(
        "/api/portfolio/accounts/paper/ticker/stream?live=1&continuous=1", buffered=False
    )
    events = iter(response.response)
    assert b"retry:" in next(events)
    first = next(events)
    assert b'"all_quotes_fresh": false' in first
    ingest_quote(quotes, "paper", 120)
    second = next(events)
    assert b'"all_quotes_fresh": true' in second
    assert b'"price": "120"' in second
    response.close()


def test_job_registry_recent_list_and_terminal_retry(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    app = Flask(__name__)
    app.register_blueprint(create_operations_blueprint(store, {"system.echo"}))
    client = app.test_client()
    assert [j["kind"] for j in client.get("/api/operations/job-types").json["jobs"]] == [
        "system.echo"
    ]
    first = store.submit("first", "system.echo", {"message": "hello"})
    second = store.submit("second", "system.echo", {})
    assert [j["job_id"] for j in client.get("/api/operations/jobs").json["jobs"]] == [
        second.job_id,
        first.job_id,
    ]
    assert client.get("/api/operations/jobs?limit=1000").status_code == 400
    assert client.post(f"/api/operations/jobs/{first.job_id}/retry").status_code == 409
    claim = store.claim_next("worker")
    store.fail(first.job_id, "missing input", claim.claim_token, retryable=False)
    assert client.post(f"/api/operations/jobs/{first.job_id}/retry").json["status"] == "QUEUED"
    assert client.post("/api/operations/jobs/99999/retry").status_code == 404


def test_job_definitions_are_allowlisted_and_link_to_selected_launcher():
    root = Path(__file__).resolve().parents[3]
    app = Flask(__name__, template_folder=str(root / "templates"))
    app.register_blueprint(create_wiki_blueprint())
    client = app.test_client()
    index = client.get("/guide/jobs")
    assert index.status_code == 200
    response = client.get("/guide/jobs/research.rebuild-indicators")
    assert response.status_code == 200
    assert b"Parameters explained" in response.data
    assert b"/pipeline?job=research.rebuild-indicators" in response.data
    assert client.get("/guide/jobs/unknown-kind").status_code == 404
