from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import Flask

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.execution import KiteStreamingProvider
from src.domains.market_data import LiveQuotes, NormalizedBar
from src.domains.portfolio_accounting import Fill, FillSide, IntradayStopAlerts, Ledger
from src.gates.http.market import create_market_blueprint
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.intraday_stream import IntradayStreamLease
from src.gates.workflows.live_quote_stream import LiveQuoteStream
from src.platform_kernel import ArtifactStore, DomainValidationError, Money, QualityStatus, Quantity


def test_retired_fact_based_corporate_action_routes_are_not_mounted(tmp_path):
    database = tmp_path / "system.db"
    app = Flask(__name__)
    app.register_blueprint(
        create_market_blueprint(MarketRepository(database), ArtifactCatalog(database))
    )
    client = app.test_client()

    assert client.post("/api/v2/market/corporate-actions", json={}).status_code == 404
    assert client.post("/api/v2/market/corporate-actions/liquidation-plan", json={}).status_code == 404
    assert client.get("/api/v2/market/bars/ABC/adjusted?end=2026-09-01").status_code == 404


def test_index_history_is_bounded_and_read_only(tmp_path):
    repository = MarketRepository(tmp_path / "market.db")
    repository.upsert_instruments(
        (TrackedInstrument("nifty", "INE000000001", "NIFTY 50", "NSE", "1", date(2026, 9, 1)),)
    )
    repository.upsert_index_quotes(
        (
            {
                "instrument_id": "nifty",
                "exchange": "NSE",
                "symbol": "NIFTY 50",
                "last_price": "25000",
                "prev_close": "24900",
                "change_percent": 0.4,
                "observed_at": "2026-09-01T10:00:00+00:00",
            },
        ),
        "quote-snapshot",
    )
    app = Flask(__name__)
    app.register_blueprint(
        create_market_blueprint(repository, ArtifactCatalog(tmp_path / "artifacts"))
    )
    client = app.test_client()
    response = client.get("/api/v2/market/indices/history?sessions=30")
    assert response.status_code == 200
    assert response.json["history"][0]["last_price"] == "25000"
    assert client.get("/api/v2/market/indices/history?sessions=31").status_code == 400


def test_intraday_alerts_have_sse_readback(tmp_path):
    database = tmp_path / "system.db"
    ledger = Ledger(database)
    ledger.open_account("paper", Money(1000))
    ledger.record_fills(
        "paper",
        "buy-1",
        0,
        [
            Fill(
                "ABC",
                datetime(2026, 9, 1, tzinfo=UTC).date(),
                FillSide.BUY,
                Quantity(1),
                Money(100),
                Money(0),
                datetime(2026, 9, 1, 9, 15, tzinfo=UTC),
            )
        ],
    )
    catalog = ArtifactCatalog(database)
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), catalog)
    risk = SimpleNamespace(
        risk_projection=lambda account: [
            {
                "account_id": account,
                "action_date": "2026-09-04",
                "stop_model": "ATR",
                "positions": [{"instrument_id": "ABC", "current_trailing_stop": "95"}],
            }
        ]
    )
    alerts = IntradayStopAlerts(database, ledger, risk, publisher)
    alerts.ingest(
        {
            "account_id": "paper",
            "observations": [
                {"instrument_id": "ABC", "price": "89", "observed_at": "2026-09-10T10:00:00+00:00"}
            ],
        }
    )
    app = Flask(__name__)
    app.register_blueprint(
        create_market_blueprint(MarketRepository(database), catalog, intraday_alerts=alerts)
    )
    response = app.test_client().get("/api/v2/market/intraday/stop-alerts/stream?account_id=paper")
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert b"event: stop-alert" in response.data


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
    first_id, latest_id = (str(uuid4()), str(uuid4()))
    publisher.publish_json("market/normalized", first_id, {"date": "2026-01-02"})
    publisher.publish_json(
        "market/normalized", latest_id, {"date": "2026-01-05"}, quality=QualityStatus.PARTIAL
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


def stream_services(tmp_path, alerts=None):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    market.upsert_instruments(
        [TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "42", date(2026, 9, 29))]
    )
    calls = []
    accounts = SimpleNamespace(
        binding=lambda account: {"broker_account_id": "selected-broker"},
        validate=lambda account: calls.append(account),
        get_credentials=lambda account: {"api_key": "fake-key", "access_token": "fake-token"},
    )
    store = LiveQuotes(database)
    lease = IntradayStreamLease(database)
    alerts = alerts or SimpleNamespace(ingest=lambda payload: {"fills_created": 0})
    stream = LiveQuoteStream(accounts, market, store, lease, alerts, KiteStreamingProvider, Ticker)
    return database, market, store, lease, stream, calls


class Ticker:
    MODE_FULL = "full"

    def __init__(self, *args):
        self.credentials = args

    def connect(self, threaded):
        assert threaded
        self.on_connect(self, {})

    def subscribe(self, tokens):
        self.tokens = tokens

    def set_mode(self, mode, tokens):
        self.mode = mode

    def close(self):
        self.closed = True
        self.on_close(self, 1000, "closed")


def test_live_stream_api_and_quote_ping(tmp_path):
    database, market, store, lease, stream, _ = stream_services(tmp_path)
    app = Flask(__name__)
    app.register_blueprint(
        create_market_blueprint(
            market, ArtifactCatalog(database), stream=lease, live_quotes=store, live_stream=stream
        )
    )
    client = app.test_client()
    path = "/api/v2/market/intraday/"
    assert (
        client.post(
            path + "live-stream",
            json={"action": "start", "account_id": "ledger", "instrument_ids": ["stock"]},
        ).status_code
        == 202
    )
    stream.provider.ticker.on_ticks(
        None, [{"instrument_token": 42, "last_price": 100, "exchange_timestamp": datetime.now(UTC)}]
    )
    assert (
        client.get(path + "quotes?account_id=ledger&instrument_id=stock").json["freshness"]
        == "FRESH"
    )
    assert client.get(path + "quotes").status_code == 400
    assert client.post(path + "stream", json={"action": "stop"}).json["status"] == "STOPPED"


START = date(2026, 1, 5)


def repository(tmp_path, *, index=False):
    market = MarketRepository(tmp_path / "system.db")
    market.upsert_instruments(
        [
            TrackedInstrument(
                "stock",
                "INDEX:NIFTY500" if index else "IN0000000001",
                "NIFTY 500" if index else "STOCK",
                "NSE",
                "42",
                START,
            )
        ]
    )
    return market


@pytest.mark.parametrize(
    "filters",
    [
        {"limit": True},
        {"limit": "10"},
        {"offset": False},
        {"offset": "0"},
        {"instrument_id": []},
        {"check_type": " "},
    ],
)
def test_invalid_quality_filters_fail_cleanly(tmp_path, filters):
    with pytest.raises(DomainValidationError, match="filters"):
        repository(tmp_path).quality_events(**filters)


def test_quality_readback_filters_and_pagination(tmp_path):
    from flask import Flask

    from src.domains.artifacts import ArtifactCatalog
    from src.gates.http.market import create_market_blueprint

    market = repository(tmp_path)
    assert market.record_quality_event(
        "stock",
        START,
        "missing_bar",
        "WARNING",
        {"expected": 1, "actual": 0, "message": "access_token=DO_NOT_PERSIST"},
    )
    assert not market.record_quality_event(
        "stock",
        START,
        "missing_bar",
        "WARNING",
        {"actual": 0, "expected": 1, "message": "access_token=DO_NOT_PERSIST"},
    )
    market.record_quality_event(
        "stock", START, "close_gap", "WARNING", {"expected": 100, "actual": 120}
    )
    app = Flask(__name__)
    app.register_blueprint(create_market_blueprint(market, ArtifactCatalog(market.path)))
    client = app.test_client()
    path = "/api/v2/market/quality-events"
    filtered = client.get(path + "?instrument_id=stock&check_type=missing_bar&severity=WARNING")
    assert filtered.status_code == 200
    assert len(filtered.json["quality_events"]) == 1
    assert "DO_NOT_PERSIST" not in filtered.get_data(as_text=True)
    first = client.get(path + "?limit=1").json["quality_events"][0]
    second = client.get(path + "?limit=1&offset=1").json["quality_events"][0]
    assert first["event_id"] != second["event_id"]
    assert client.get(path + "?limit=0").status_code == 400
