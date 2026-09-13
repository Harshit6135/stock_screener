from datetime import UTC, date, datetime

import pytest

from src.application.providers import (
    KiteHistoricalBarsProvider,
    KiteInstrumentProvider,
    KiteQuoteProvider,
)
from src.market_data import publish_raw_snapshot
from src.platform_kernel import ArtifactStore, DomainValidationError


class FakeKiteClient:
    def historical_data(self, token, start, end, interval):
        assert token == 42 and interval == "day"
        return [
            {
                "date": datetime(2025, 1, 2, tzinfo=UTC),
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
                "volume": 7,
            }
        ]

    def ohlc(self, instruments):
        return {instruments[0]: {"last_price": 11}}

    def instruments(self, exchange=None):
        return [{"exchange": exchange or "ALL"}]


def test_provider_adapters_are_read_only_and_raw_payload_is_immutable(tmp_path):
    client = FakeKiteClient()
    bars = KiteHistoricalBarsProvider(client).get_bars("42", date(2025, 1, 1), date(2025, 1, 3))
    assert bars[0].close == 11
    assert KiteQuoteProvider(client).get_quote("NSE:ABC")["last_price"] == 11

    manifest = publish_raw_snapshot(ArtifactStore(tmp_path), "kite", {"records": [{"token": 42}]})
    assert manifest.category == "market/raw/kite"


class MissingQuoteClient:
    def ohlc(self, instruments):
        return {}


def test_instrument_and_quote_adapter_paths():
    client = FakeKiteClient()
    assert KiteInstrumentProvider(client, "NSE").get_instruments() == ({"exchange": "NSE"},)
    assert KiteInstrumentProvider(client).get_instruments() == ({"exchange": "ALL"},)
    with pytest.raises(DomainValidationError, match="did not return"):
        KiteQuoteProvider(MissingQuoteClient()).get_quote("MISSING")
