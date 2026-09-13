"""Read-only provider adapters; credentials and browser login are out of scope."""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from time import monotonic, sleep
from typing import Any

from src.market_data import NormalizedBar
from src.platform_kernel import DomainValidationError


class _ProviderThrottle:
    def __init__(
        self, requests_per_second: float, sleeper: Callable[[float], None] = sleep
    ) -> None:
        if requests_per_second <= 0:
            raise DomainValidationError("provider rate must be positive")
        self.interval, self.sleeper, self._last_request = 1.0 / requests_per_second, sleeper, 0.0

    def wait(self) -> None:
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
        self._throttle.wait()
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


class KiteStreamingProvider:
    """Adapt KiteTicker callbacks to the durable, fill-free alert sink."""

    def __init__(
        self,
        ticker: Any,
        account_id: str,
        instrument_tokens: Mapping[int, str],
        alert_sink: Callable[[dict[str, object]], object],
    ) -> None:
        if not isinstance(account_id, str) or not account_id.strip():
            raise DomainValidationError("stream account_id is required")
        if not 1 <= len(instrument_tokens) <= 500:
            raise DomainValidationError("stream requires 1..500 instrument tokens")
        if any(
            isinstance(token, bool) or not isinstance(token, int) or token <= 0
            for token in instrument_tokens
        ):
            raise DomainValidationError("stream instrument tokens must be positive integers")
        if any(
            not isinstance(instrument_id, str) or not instrument_id.strip()
            for instrument_id in instrument_tokens.values()
        ):
            raise DomainValidationError("stream instrument identities are invalid")
        if not callable(alert_sink):
            raise DomainValidationError("stream alert sink is required")
        self.ticker = ticker
        self.account_id = account_id
        self.instrument_tokens = dict(instrument_tokens)
        self.alert_sink = alert_sink
        self.connected = False

    def start(self) -> dict[str, object]:
        """Register callbacks, subscribe, and start KiteTicker in threaded mode."""
        self.ticker.on_connect = self._on_connect
        self.ticker.on_ticks = self._on_ticks
        self.ticker.on_close = self._on_close
        self.ticker.connect(threaded=True)
        return {
            "account_id": self.account_id,
            "token_count": len(self.instrument_tokens),
            "status": "STARTING",
        }

    def stop(self) -> dict[str, object]:
        close = getattr(self.ticker, "close", None)
        if callable(close):
            close()
        self.connected = False
        return {
            "account_id": self.account_id,
            "token_count": len(self.instrument_tokens),
            "status": "STOPPED",
        }

    def _on_connect(self, _ws: object, _response: object) -> None:
        self.ticker.subscribe(list(self.instrument_tokens))
        mode = getattr(self.ticker, "MODE_LTP", None)
        if mode is not None:
            self.ticker.set_mode(mode, list(self.instrument_tokens))
        self.connected = True

    def _on_close(self, _ws: object, _code: object, _reason: object) -> None:
        self.connected = False

    def _on_ticks(self, _ws: object, ticks: Sequence[object]) -> None:
        observations: list[dict[str, object]] = []
        observed_at = datetime.now(UTC).isoformat()
        for tick in ticks:
            if not isinstance(tick, dict):
                continue
            token = tick.get("instrument_token")
            instrument_id = self.instrument_tokens.get(token) if isinstance(token, int) else None
            price = tick.get("last_price")
            if (
                instrument_id is None
                or isinstance(price, bool)
                or not isinstance(price, (str, int, float, Decimal))
            ):
                continue
            timestamp = tick.get("exchange_timestamp") or tick.get("timestamp")
            if isinstance(timestamp, datetime):
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=UTC)
                observed_at = timestamp.astimezone(UTC).isoformat()
            observations.append(
                {
                    "instrument_id": instrument_id,
                    "price": price,
                    "observed_at": observed_at,
                    "source": "kite-stream",
                }
            )
        if observations:
            self.alert_sink({"account_id": self.account_id, "observations": observations})
