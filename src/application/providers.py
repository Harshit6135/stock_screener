"""Read-only provider adapters; credentials and browser login are out of scope."""

from datetime import date
from decimal import Decimal
from typing import Callable, Sequence

from src.market_data import NormalizedBar
from src.platform_kernel import DomainValidationError


class KiteHistoricalBarsProvider:
    def __init__(self, client: object):
        self.client = client

    def get_bars(self, instrument_id: str, start_date: date, end_date: date) -> tuple[NormalizedBar, ...]:
        records = self.client.historical_data(int(instrument_id), start_date, end_date, interval="day")
        return tuple(
            NormalizedBar(
                instrument_id=instrument_id,
                as_of_date=record["date"].date() if hasattr(record["date"], "date") else record["date"],
                open=Decimal(str(record["open"])), high=Decimal(str(record["high"])),
                low=Decimal(str(record["low"])), close=Decimal(str(record["close"])),
                volume=int(record.get("volume", 0)),
            ) for record in records
        )


class KiteInstrumentProvider:
    def __init__(self, client: object, exchange: str | None = None):
        self.client, self.exchange = client, exchange

    def get_instruments(self) -> Sequence[object]:
        return tuple(self.client.instruments(self.exchange) if self.exchange else self.client.instruments())


class KiteQuoteProvider:
    def __init__(self, client: object):
        self.client = client

    def get_quote(self, instrument_id: str) -> object:
        response = self.client.ohlc([instrument_id])
        try:
            return response[instrument_id]
        except KeyError as exc:
            raise DomainValidationError(f"quote provider did not return {instrument_id}") from exc


class YFinanceHistoricalBarsProvider:
    def __init__(self, downloader: Callable[..., object] | None = None):
        if downloader is None:
            import yfinance
            downloader = yfinance.download
        self.downloader = downloader

    def get_bars(self, instrument_id: str, start_date: date, end_date: date) -> tuple[NormalizedBar, ...]:
        frame = self.downloader(instrument_id, start=start_date, end=end_date, auto_adjust=False, progress=False)
        if frame is None or len(frame.index) == 0:
            return ()
        return tuple(
            NormalizedBar(
                instrument_id=instrument_id,
                as_of_date=as_of.date() if hasattr(as_of, "date") else as_of,
                open=Decimal(str(self._scalar(row["Open"]))), high=Decimal(str(self._scalar(row["High"]))),
                low=Decimal(str(self._scalar(row["Low"]))), close=Decimal(str(self._scalar(row["Close"]))), volume=int(self._scalar(row.get("Volume", 0))),
            ) for as_of, row in frame.iterrows()
        )

    @staticmethod
    def _scalar(value: object) -> object:
        """Accept yfinance's one-ticker scalar and single-column MultiIndex forms."""
        if hasattr(value, "iloc"):
            if len(value) != 1:
                raise DomainValidationError("yfinance response contains multiple tickers; request one instrument at a time")
            return value.iloc[0]
        return value
