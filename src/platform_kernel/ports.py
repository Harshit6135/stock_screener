"""Dependency-inversion ports implemented by provider and storage adapters."""

from collections.abc import Sequence
from datetime import date
from typing import Protocol


class HistoricalBarsProvider(Protocol):
    def get_bars(
        self, instrument_id: str, start_date: date, end_date: date
    ) -> Sequence[object]: ...


class InstrumentProvider(Protocol):
    def get_instruments(self) -> Sequence[object]: ...


class LiveQuoteProvider(Protocol):
    def get_quote(self, instrument_id: str) -> object: ...


class Broker(Protocol):
    def submit(self, order_intent: object, allow_live: bool = False) -> object: ...
