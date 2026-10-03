from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from src.domains.execution import KiteStreamingProvider
from src.domains.market_data import LiveQuotes
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.intraday_stream import IntradayStreamLease
from src.gates.workflows.live_quote_stream import LiveQuoteStream
from src.platform_kernel import DomainValidationError


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


def test_controller_connect_reconnect_stop_and_late_callback(tmp_path):
    _database, market, store, lease, stream, calls = stream_services(tmp_path)
    assert stream.start("ledger", ["stock"])["status"] == "CONNECTED"
    assert calls == ["selected-broker"]
    ticker = stream.provider.ticker
    assert ticker.credentials == ("fake-key", "fake-token")
    now = datetime.now(UTC)
    ticker.on_ticks(
        ticker, [{"instrument_token": 42, "last_price": 100, "exchange_timestamp": now}]
    )
    assert store.execution_quote("ledger", "stock")["price"] == "100"
    assert lease.state()["last_heartbeat_at"]
    ticker.on_close(ticker, 1006, "disconnected")
    assert lease.state()["status"] == "ERROR"
    ticker.on_connect(ticker, {})
    assert lease.state()["status"] == "CONNECTED"
    with pytest.raises(DomainValidationError, match="stop"):
        stream.start("ledger", ["stock"])
    assert stream.stop()["status"] == "STOPPED"
    ticker.on_ticks(
        ticker,
        [{"instrument_token": 42, "last_price": 200, "exchange_timestamp": datetime.now(UTC)}],
    )
    assert store.read("ledger", "stock")["price"] == "100"
    assert lease.state()["status"] == "STOPPED"
    assert market.bars("stock", date(2026, 9, 29), date(2026, 9, 29)) == []


def test_missing_stop_projection_preserves_quotes(tmp_path):
    def unavailable(payload):
        raise DomainValidationError("missing projection")

    _, _, store, _, stream, _ = stream_services(tmp_path, SimpleNamespace(ingest=unavailable))
    stream.start("ledger", ["stock"])
    stream.provider.ticker.on_ticks(
        None, [{"instrument_token": 42, "last_price": 100, "exchange_timestamp": datetime.now(UTC)}]
    )
    assert store.execution_quote("ledger", "stock")["price"] == "100"


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
