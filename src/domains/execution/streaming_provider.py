"""Account-scoped Kite streaming provider adapter."""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from src.platform_kernel import DomainValidationError


class KiteStreamingProvider:
    """Kite provider adapter used by the gate-owned stream workflow."""

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
        mode = getattr(self.ticker, "MODE_FULL", getattr(self.ticker, "MODE_LTP", None))
        if mode is not None:
            self.ticker.set_mode(mode, list(self.instrument_tokens))
        self.connected = True

    def _on_close(self, _ws: object, _code: object, _reason: object) -> None:
        self.connected = False

    def _on_ticks(self, _ws: object, ticks: Sequence[object]) -> None:
        observations: list[dict[str, object]] = []
        received_at = datetime.now(UTC).isoformat()
        for tick in ticks:
            if not isinstance(tick, dict):
                continue
            token = tick.get("instrument_token")
            instrument_id = (
                self.instrument_tokens.get(token)
                if isinstance(token, int) and not isinstance(token, bool)
                else None
            )
            price = tick.get("last_price")
            if (
                instrument_id is None
                or isinstance(price, bool)
                or not isinstance(price, (str, int, float, Decimal))
            ):
                continue
            try:
                parsed_price = Decimal(str(price))
            except InvalidOperation:
                continue
            if not parsed_price.is_finite() or parsed_price <= 0:
                continue
            observed_at = received_at
            timestamp = tick.get("exchange_timestamp") or tick.get("timestamp")
            if isinstance(timestamp, datetime):
                # Kite decodes epoch timestamps with datetime.fromtimestamp,
                # so a naive value is in the host timezone, not necessarily UTC.
                observed_at = timestamp.astimezone(UTC).isoformat()
            observations.append(
                {
                    "instrument_id": instrument_id,
                    "price": price,
                    "observed_at": observed_at,
                    "source": "kite-stream",
                    "received_at": received_at,
                    "exchange_timestamp_available": isinstance(timestamp, datetime),
                }
            )
        if observations:
            self.alert_sink({"account_id": self.account_id, "observations": observations})
