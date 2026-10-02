from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from flask import Flask

from src.application.catalog import ArtifactCatalog
from src.application.intraday_stream import IntradayStreamLease
from src.application.live_quotes import LiveQuotes, LiveQuoteStream
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.market_web import create_market_blueprint
from src.application.providers import KiteStreamingProvider
from src.platform_kernel import DomainValidationError

NOW = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)


def observation(price="100", observed=NOW, received=NOW, verified=True, instrument="stock"):
    return {"instrument_id": instrument, "price": price, "observed_at": observed.isoformat(),
            "received_at": received.isoformat(), "source": "kite-stream",
            "exchange_timestamp_available": verified}


def ingest(store, item, account="ledger"):
    return store.ingest({"account_id": account, "observations": [item]})


def test_quote_persistence_scope_and_out_of_order_ticks(tmp_path):
    database = tmp_path / "system.db"
    store = LiveQuotes(database, lambda: NOW)
    assert ingest(store, observation())["fills_created"] == 0
    ingest(store, observation("20", observed=NOW-timedelta(seconds=1)))
    ingest(store, observation("55"), "another-ledger")
    restarted = LiveQuotes(database, lambda: NOW)
    assert restarted.execution_quote("ledger", "stock")["price"] == "100"
    assert restarted.execution_quote("another-ledger", "stock")["price"] == "55"
    assert restarted.read("missing", "stock")["freshness"] == "MISSING"


@pytest.mark.parametrize(("item", "status"), [
    (observation(observed=NOW-timedelta(seconds=61)), "STALE"),
    (observation(received=NOW-timedelta(seconds=61)), "STALE"),
    (observation(observed=NOW+timedelta(seconds=6)), "CLOCK_SKEW"),
    (observation(received=NOW+timedelta(seconds=6)), "CLOCK_SKEW"),
    (observation(verified=False), "UNVERIFIED_TIMESTAMP"),
])
def test_execution_rejects_unusable_quotes(tmp_path, item, status):
    store = LiveQuotes(tmp_path / "system.db", lambda: NOW)
    ingest(store, item)
    assert store.read("ledger", "stock")["freshness"] == status
    with pytest.raises(DomainValidationError, match=status):
        store.execution_quote("ledger", "stock")


@pytest.mark.parametrize("price", ["NaN", "Infinity", "0", "-1"])
def test_invalid_quote_batch_is_atomic(tmp_path, price):
    store = LiveQuotes(tmp_path / "system.db", lambda: NOW)
    with pytest.raises(DomainValidationError):
        store.ingest({"account_id": "ledger", "observations": [observation(), observation(price, instrument="bad")]})
    assert store.read("ledger", "stock")["freshness"] == "MISSING"


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


def test_provider_timestamps_are_independent_and_invalid_ticks_skipped():
    received = []
    ticker = Ticker()
    provider = KiteStreamingProvider(ticker, "ledger", {42: "a", 43: "b"}, received.append)
    provider.start()
    assert ticker.mode == "full"
    ticker.on_ticks(ticker, [
        {"instrument_token": 42, "last_price": 10, "exchange_timestamp": NOW},
        {"instrument_token": 43, "last_price": 11},
        {"instrument_token": 42, "last_price": "NaN"},
        {"instrument_token": True, "last_price": 11},
    ])
    first, second = received[0]["observations"]
    assert first["observed_at"] == NOW.isoformat()
    assert first["exchange_timestamp_available"]
    assert not second["exchange_timestamp_available"]
    assert second["observed_at"] == second["received_at"]
    assert second["observed_at"] != first["observed_at"]


def stream_services(tmp_path, alerts=None):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    market.upsert_instruments([TrackedInstrument("stock", "IN0000000001", "STOCK", "NSE", "42", date(2026, 9, 29))])
    calls = []
    accounts = SimpleNamespace(
        binding=lambda account: {"broker_account_id": "selected-broker"},
        validate=lambda account: calls.append(account),
        get_credentials=lambda account: {"api_key": "fake-key", "access_token": "fake-token"},
    )
    store = LiveQuotes(database)
    lease = IntradayStreamLease(database)
    alerts = alerts or SimpleNamespace(ingest=lambda payload: {"fills_created": 0})
    stream = LiveQuoteStream(accounts, market, store, lease, alerts, Ticker)
    return database, market, store, lease, stream, calls


def test_controller_connect_reconnect_stop_and_late_callback(tmp_path):
    _database, market, store, lease, stream, calls = stream_services(tmp_path)
    assert stream.start("ledger", ["stock"])["status"] == "CONNECTED"
    assert calls == ["selected-broker"]
    ticker = stream.provider.ticker
    assert ticker.credentials == ("fake-key", "fake-token")
    now = datetime.now(UTC)
    ticker.on_ticks(ticker, [{"instrument_token": 42, "last_price": 100, "exchange_timestamp": now}])
    assert store.execution_quote("ledger", "stock")["price"] == "100"
    assert lease.state()["last_heartbeat_at"]
    ticker.on_close(ticker, 1006, "disconnected")
    assert lease.state()["status"] == "ERROR"
    ticker.on_connect(ticker, {})
    assert lease.state()["status"] == "CONNECTED"
    with pytest.raises(DomainValidationError, match="stop"):
        stream.start("ledger", ["stock"])
    assert stream.stop()["status"] == "STOPPED"
    ticker.on_ticks(ticker, [{"instrument_token": 42, "last_price": 200, "exchange_timestamp": datetime.now(UTC)}])
    assert store.read("ledger", "stock")["price"] == "100"
    assert lease.state()["status"] == "STOPPED"
    assert market.bars("stock", date(2026, 9, 29), date(2026, 9, 29)) == []


def test_missing_stop_projection_preserves_quotes(tmp_path):
    def unavailable(payload):
        raise DomainValidationError("missing projection")
    _, _, store, _, stream, _ = stream_services(tmp_path, SimpleNamespace(ingest=unavailable))
    stream.start("ledger", ["stock"])
    stream.provider.ticker.on_ticks(None, [{"instrument_token": 42, "last_price": 100,
                                           "exchange_timestamp": datetime.now(UTC)}])
    assert store.execution_quote("ledger", "stock")["price"] == "100"


def test_live_stream_api_and_quote_ping(tmp_path):
    database, market, store, lease, stream, _ = stream_services(tmp_path)
    app = Flask(__name__)
    app.register_blueprint(create_market_blueprint(market, ArtifactCatalog(database), stream=lease,
                                                   live_quotes=store, live_stream=stream))
    client = app.test_client()
    path = "/api/v2/market/intraday/"
    assert client.post(path+"live-stream", json={"action": "start", "account_id": "ledger", "instrument_ids": ["stock"]}).status_code == 202
    stream.provider.ticker.on_ticks(None, [{"instrument_token": 42, "last_price": 100, "exchange_timestamp": datetime.now(UTC)}])
    assert client.get(path+"quotes?account_id=ledger&instrument_id=stock").json["freshness"] == "FRESH"
    assert client.get(path+"quotes").status_code == 400
    assert client.post(path+"stream", json={"action": "stop"}).json["status"] == "STOPPED"


def test_connection_failure_and_stopped_lease_cannot_claim_connected(tmp_path):
    _, _, _, lease, stream, _ = stream_services(tmp_path)

    class BrokenTicker(Ticker):
        def connect(self, threaded):
            raise RuntimeError("failed")

    stream.ticker_factory = BrokenTicker
    with pytest.raises(DomainValidationError, match="connection failed"):
        stream.start("ledger", ["stock"])
    assert lease.state()["status"] == "ERROR"
    assert stream.provider is None
    stream.stop()
    with pytest.raises(DomainValidationError, match="stopped"):
        lease.connected()
    assert lease.state()["status"] == "STOPPED"
