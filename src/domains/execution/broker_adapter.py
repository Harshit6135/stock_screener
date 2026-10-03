"""Broker API client protocol and Kite execution adapter."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from kiteconnect import KiteConnect  # type: ignore[import-untyped]

from src.platform_kernel import DomainValidationError

from .kite_auth import KiteCredentials


class BrokerExecutionGateway(Protocol):
    def submit_order(self, order: dict[str, object]) -> str: ...
    def order_status(self, broker_order_id: str) -> dict[str, object]: ...


class KiteExecutionGateway:
    """Kite adapter that refuses all writes unless explicitly enabled."""

    def __init__(
        self,
        credentials: KiteCredentials | None,
        token_path: str | Path,
        enabled: bool = False,
        client_factory=KiteConnect,
        allowed_accounts: Iterable[str] = (),
        allowed_instruments: Iterable[str] = (),
        accounts=None,
    ):
        self.credentials = credentials
        self.token_path = Path(token_path)
        self.enabled = enabled
        self.client_factory = client_factory
        self.allowed_accounts = frozenset(allowed_accounts)
        self.allowed_instruments = frozenset(allowed_instruments)
        self.kill_switch = True
        self.accounts = accounts

    def arm(self) -> None:
        """Explicitly clear the kill switch for a controlled deployment."""
        self.kill_switch = False

    def disarm(self) -> None:
        self.kill_switch = True

    def controls(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "kill_switch": self.kill_switch,
            "allowlisted_account_count": len(self.allowed_accounts),
            "allowlisted_instrument_count": len(self.allowed_instruments),
        }

    def _client(self, account_id: str | None = None, *, for_write=True):
        if for_write and not self.enabled:
            raise DomainValidationError("live broker execution is disabled")
        if for_write and self.kill_switch:
            raise DomainValidationError("live broker kill switch is active")
        if self.accounts is not None:
            if not account_id:
                raise DomainValidationError(
                    "explicit ledger account is required for broker routing"
                )
            binding = self.accounts.binding(account_id)
            self.accounts.validate(binding["broker_account_id"])
            return self.accounts.client(binding["broker_account_id"])
        if self.credentials is None or not self.token_path.is_file():
            raise DomainValidationError("portfolio Kite credentials are unavailable")
        token = self.token_path.read_text(encoding="utf-8").strip()
        if not token:
            raise DomainValidationError("portfolio Kite access token is unavailable")
        client = self.client_factory(api_key=self.credentials.api_key)
        client.set_access_token(token)
        return client

    @staticmethod
    def _order_tag(order: dict[str, object]) -> str:
        identity = order.get("order_id") or order.get("idempotency_key")
        if not isinstance(identity, str) or not identity.strip():
            raise DomainValidationError("broker order requires a stable order identity")
        if order.get("order_id"):
            # Retain tags already used by existing persisted order intents.
            return identity.replace("-", "")[:20]
        return str(
            uuid5(NAMESPACE_URL, f"kite-order:{order.get('account_id')}:{identity}")
        ).replace("-", "")[:20]

    def submit_order(self, order: dict[str, object]) -> str:
        if not self.enabled:
            raise DomainValidationError("live broker execution is disabled")
        if self.kill_switch:
            raise DomainValidationError("live broker kill switch is active")
        account_id = str(order.get("account_id", ""))
        instrument_id = str(order.get("instrument_id", ""))
        if not self.allowed_accounts or account_id not in self.allowed_accounts:
            raise DomainValidationError("broker account is not allowlisted")
        if not self.allowed_instruments or instrument_id not in self.allowed_instruments:
            raise DomainValidationError("broker instrument is not allowlisted")
        tag = self._order_tag(order)
        client = self._client(account_id)
        return str(
            client.place_order(
                variety=str(order.get("variety", "regular")),
                exchange=str(order["exchange"]),
                tradingsymbol=str(order["symbol"]),
                transaction_type=str(order["side"]),
                quantity=int(str(order["quantity"])),
                order_type=str(order["order_type"]),
                product="CNC",
                validity="DAY",
                tag=tag,
            )
        )

    def order_status(
        self, broker_order_id: str, account_id: str | None = None
    ) -> dict[str, object]:
        client = self._client(account_id, for_write=False)
        status = dict(client.order_history(broker_order_id)[-1])
        # Reconciliation consumes actual trade rows, not the aggregate order
        # history returned by Kite.
        status["fills"] = [
            {
                "trade_id": str(row["trade_id"]),
                "quantity": int(row["quantity"]),
                "price": str(row["fill_price"]),
                "fill_date": str(row.get("exchange_timestamp") or row.get("order_timestamp"))[:10],
                "executed_at": str(row.get("exchange_timestamp") or row.get("order_timestamp")),
            }
            for row in client.order_trades(broker_order_id)
            if row.get("trade_id") and row.get("quantity") and row.get("fill_price")
        ]
        return status

    def find_order(self, order: dict[str, object]) -> str | None:
        client = self._client(str(order["account_id"]), for_write=False)
        tag = self._order_tag(order)
        matches = [row for row in client.orders() if row.get("tag") == tag]
        if len(matches) > 1:
            raise DomainValidationError("ambiguous broker receipt; operator review required")
        return str(matches[0]["order_id"]) if matches else None
