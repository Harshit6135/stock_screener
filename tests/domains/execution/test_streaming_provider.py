from datetime import UTC, datetime

import pytest

from src.domains.execution import KiteStreamingProvider


class FakeTicker:
    MODE_LTP = "ltp"

    def connect(self, threaded):
        assert threaded is True
        self.on_connect(self, {"ok": True})

    def subscribe(self, tokens):
        self.tokens = tokens

    def set_mode(self, mode, tokens):
        self.mode, self.mode_tokens = mode, tokens

    def close(self):
        self.closed = True


def test_streaming_provider_subscribes_and_emits_alert_observations():
    received = []
    ticker = FakeTicker()
    provider = KiteStreamingProvider(ticker, "paper", {42: "instrument-1"}, received.append)
    assert provider.start()["status"] == "STARTING"
    assert ticker.tokens == [42]
    ticker.on_ticks(ticker, [{"instrument_token": 42, "last_price": 101}])
    assert received[0]["account_id"] == "paper"
    assert received[0]["observations"][0]["source"] == "kite-stream"
    assert provider.stop()["status"] == "STOPPED"
    assert ticker.closed is True


NOW = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)


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
    ticker.on_ticks(
        ticker,
        [
            {"instrument_token": 42, "last_price": 10, "exchange_timestamp": NOW},
            {"instrument_token": 43, "last_price": 11},
            {"instrument_token": 42, "last_price": "NaN"},
            {"instrument_token": True, "last_price": 11},
        ],
    )
    first, second = received[0]["observations"]
    assert first["observed_at"] == NOW.isoformat()
    assert first["exchange_timestamp_available"]
    assert not second["exchange_timestamp_available"]
    assert second["observed_at"] == second["received_at"]
    assert second["observed_at"] != first["observed_at"]


@pytest.mark.parametrize("close", [None, 0, -1, True, "NaN", "Infinity", "bad"])
def test_invalid_ohlc_close_does_not_discard_valid_last_price(close):
    received = []
    ticker = Ticker()
    provider = KiteStreamingProvider(ticker, "ledger", {42: "a"}, received.append)
    provider.start()
    ticker.on_ticks(ticker, [{"instrument_token": 42, "last_price": 101,
                             "exchange_timestamp": NOW, "ohlc": {"close": close}}])
    item = received[0]["observations"][0]
    assert item["price"] == 101
    assert item["previous_close"] is None
