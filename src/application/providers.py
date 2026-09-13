"""Read-only provider adapters; credentials and browser login are out of scope."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from src.market_data import NormalizedBar
from src.platform_kernel import DomainValidationError


class KiteHistoricalBarsProvider:
    def __init__(self, client: Any):
        self.client = client

    def get_bars(
        self, instrument_id: str, start_date: date, end_date: date
    ) -> tuple[NormalizedBar, ...]:
        records = self.client.historical_data(
            int(instrument_id), start_date, end_date, interval="day"
        )
        return tuple(
            NormalizedBar(
                instrument_id=instrument_id,
                as_of_date=record["date"].date()
                if hasattr(record["date"], "date")
                else record["date"],
                open=Decimal(str(record["open"])),
                high=Decimal(str(record["high"])),
                low=Decimal(str(record["low"])),
                close=Decimal(str(record["close"])),
                volume=int(record.get("volume", 0)),
            )
            for record in records
        )


class KiteInstrumentProvider:
    def __init__(self, client: Any, exchange: str | None = None):
        self.client, self.exchange = client, exchange

    def get_instruments(self) -> Sequence[object]:
        return tuple(
            self.client.instruments(self.exchange) if self.exchange else self.client.instruments()
        )


class KiteQuoteProvider:
    def __init__(self, client: Any):
        self.client = client

    def get_quote(self, instrument_id: str) -> object:
        response = self.client.ohlc([instrument_id])
        try:
            return response[instrument_id]
        except KeyError as exc:
            raise DomainValidationError(f"quote provider did not return {instrument_id}") from exc
