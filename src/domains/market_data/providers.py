"""Rate-limited market-data adapters around injected provider clients."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from threading import Lock
from time import monotonic, sleep
from typing import Any

from src.platform_kernel import DomainValidationError

from .api import NormalizedBar


class _ProviderThrottle:
    def __init__(
        self, requests_per_second: float, sleeper: Callable[[float], None] = sleep
    ) -> None:
        if requests_per_second <= 0:
            raise DomainValidationError("provider rate must be positive")
        self.interval, self.sleeper, self._last_request = 1.0 / requests_per_second, sleeper, 0.0
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self.interval - (monotonic() - self._last_request)
            if delay > 0:
                self.sleeper(delay)
            self._last_request = monotonic()


class KiteHistoricalBarsProvider:
    def __init__(
        self,
        client: Any,
        *,
        requests_per_second: float = 3.0,
        sleeper: Callable[[float], None] = sleep,
    ):
        self.client, self._throttle = client, _ProviderThrottle(requests_per_second, sleeper)

    def get_bars(
        self, instrument_id: str, start_date: date, end_date: date
    ) -> tuple[NormalizedBar, ...]:
        if (not isinstance(instrument_id, str) or not instrument_id.strip()
                or not isinstance(start_date, date) or not isinstance(end_date, date)
                or start_date > end_date):
            raise DomainValidationError("historical provider request is invalid")
        try:
            token = int(instrument_id)
        except ValueError as exc:
            raise DomainValidationError("historical provider token must be a positive integer") from exc
        if token <= 0:
            raise DomainValidationError("historical provider token must be a positive integer")
        self._throttle.wait()
        records = self.client.historical_data(token, start_date, end_date, interval="day")
        if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
            raise DomainValidationError("historical provider response must contain records")
        bars = []
        seen_dates = set()
        for record in records:
            if not isinstance(record, Mapping):
                raise DomainValidationError("historical provider record is invalid")
            try:
                timestamp = record["date"]
                day = timestamp.date() if isinstance(timestamp, datetime) else timestamp
                if isinstance(day, str):
                    day = date.fromisoformat(day)
                if not isinstance(day, date) or not start_date <= day <= end_date or day in seen_dates:
                    raise DomainValidationError("historical provider dates are invalid or duplicated")
                volume = Decimal(str(record["volume"]))
                if isinstance(record["volume"], bool) or not volume.is_finite() or volume < 0 or volume != volume.to_integral_value():
                    raise DomainValidationError("historical provider volume must be a non-negative integer")
                bar = NormalizedBar(instrument_id, day, Decimal(str(record["open"])),
                    Decimal(str(record["high"])), Decimal(str(record["low"])),
                    Decimal(str(record["close"])), int(volume))
            except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                raise DomainValidationError("historical provider OHLCV record is invalid") from exc
            bars.append(bar)
            seen_dates.add(day)
        return tuple(sorted(bars, key=lambda bar: bar.as_of_date))


class KiteInstrumentProvider:
    def __init__(
        self,
        client: Any,
        exchange: str | None = None,
        *,
        requests_per_second: float = 3.0,
        sleeper: Callable[[float], None] = sleep,
    ):
        self.client, self.exchange = client, exchange
        self._throttle = _ProviderThrottle(requests_per_second, sleeper)

    def get_instruments(self) -> Sequence[object]:
        self._throttle.wait()
        return tuple(
            self.client.instruments(self.exchange) if self.exchange else self.client.instruments()
        )


class KiteQuoteProvider:
    def __init__(
        self,
        client: Any,
        *,
        requests_per_second: float = 3.0,
        sleeper: Callable[[float], None] = sleep,
    ):
        self.client = client
        self._throttle = _ProviderThrottle(requests_per_second, sleeper)

    def get_quote(self, instrument_id: str) -> object:
        self._throttle.wait()
        response = self.client.ohlc([instrument_id])
        try:
            return response[instrument_id]
        except KeyError as exc:
            raise DomainValidationError(f"quote provider did not return {instrument_id}") from exc
