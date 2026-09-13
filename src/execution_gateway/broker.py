"""Feature-gated broker order intents and append-only reconciliation events."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from kiteconnect import KiteConnect  # type: ignore[import-untyped]

from src.application.kite_auth import KiteCredentials
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError, Money, Quantity
from src.portfolio_accounting import Fill, FillSide

from .ledger import Ledger


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
    ):
        self.credentials = credentials
        self.token_path = Path(token_path)
        self.enabled = enabled
        self.client_factory = client_factory
        self.allowed_accounts = frozenset(allowed_accounts)
        self.allowed_instruments = frozenset(allowed_instruments)
        self.kill_switch = True

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

    def _client(self):
        if not self.enabled:
            raise DomainValidationError("live broker execution is disabled")
        if self.kill_switch:
            raise DomainValidationError("live broker kill switch is active")
        if self.credentials is None or not self.token_path.is_file():
            raise DomainValidationError("portfolio Kite credentials are unavailable")
        token = self.token_path.read_text(encoding="utf-8").strip()
        if not token:
            raise DomainValidationError("portfolio Kite access token is unavailable")
        client = self.client_factory(api_key=self.credentials.api_key)
        client.set_access_token(token)
        return client

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
        client = self._client()
        return str(client.place_order(
            variety="regular", exchange=str(order["exchange"]), tradingsymbol=str(order["symbol"]),
            transaction_type=str(order["side"]), quantity=int(str(order["quantity"])),
            order_type=str(order["order_type"]), product="CNC", validity="DAY",
        ))

    def order_status(self, broker_order_id: str) -> dict[str, object]:
        return dict(self._client().order_history(broker_order_id)[-1])


class BrokerOrderService:
    def __init__(self, database: str | Path, ledger: Ledger, gateway: BrokerExecutionGateway | None = None):
        self.database, self.ledger, self.gateway = Path(database), ledger, gateway
        migrate_sqlite(self.database, "broker_orders", {1: (
            """CREATE TABLE IF NOT EXISTS broker_orders (
                order_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE, instrument_id TEXT NOT NULL,
                symbol TEXT NOT NULL, exchange TEXT NOT NULL, side TEXT NOT NULL,
                quantity INTEGER NOT NULL, order_type TEXT NOT NULL, status TEXT NOT NULL,
                broker_order_id TEXT, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS broker_execution_events (
                event_id INTEGER PRIMARY KEY, order_id TEXT NOT NULL, event_type TEXT NOT NULL,
                broker_fill_id TEXT, payload_json TEXT NOT NULL, occurred_at TEXT NOT NULL,
                UNIQUE(order_id, broker_fill_id))""",
            """CREATE TABLE IF NOT EXISTS broker_baskets (
                basket_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                proposal_id TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
                execution_mode TEXT NOT NULL, slice_count INTEGER NOT NULL,
                interval_seconds INTEGER NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS broker_basket_orders (
                basket_id TEXT NOT NULL, order_id TEXT NOT NULL,
                slice_index INTEGER NOT NULL, PRIMARY KEY(basket_id, order_id),
                FOREIGN KEY(basket_id) REFERENCES broker_baskets(basket_id))""",
        )})

    def execution_controls(self) -> dict[str, object]:
        """Return non-secret execution guard state for operator readback."""
        if self.gateway is None:
            return {"enabled": False, "kill_switch": True, "gateway": "unavailable"}
        controls = getattr(self.gateway, "controls", None)
        if not callable(controls):
            return {"gateway": type(self.gateway).__name__, "controls": "unavailable"}
        return {"gateway": type(self.gateway).__name__, **controls()}

    def create_basket(self, payload: dict[str, object]) -> dict[str, object]:
        required = {"account_id", "proposal_id", "idempotency_key", "execution_mode", "orders"}
        if not isinstance(payload, dict) or set(payload) - (required | {"slice_count", "interval_seconds"}) or not required.issubset(payload) or not isinstance(payload["orders"], list) or not payload["orders"]:
            raise DomainValidationError("basket intent is incomplete")
        mode = payload["execution_mode"]
        if mode not in {"BASKET", "TWAP", "VWAP"}:
            raise DomainValidationError("basket execution mode is invalid")
        slice_count = payload.get("slice_count", 1 if mode == "BASKET" else 2)
        interval = payload.get("interval_seconds", 0 if mode == "BASKET" else 60)
        if isinstance(slice_count, bool) or not isinstance(slice_count, int) or not 1 <= slice_count <= 100 or isinstance(interval, bool) or not isinstance(interval, int) or not 0 <= interval <= 3600:
            raise DomainValidationError("basket slice policy is invalid")
        if mode == "BASKET" and slice_count != 1:
            raise DomainValidationError("BASKET mode must use one slice")
        account_id, proposal_id, idempotency_key = (str(payload[key]) for key in ("account_id", "proposal_id", "idempotency_key"))
        if not all(value.strip() for value in (account_id, proposal_id, idempotency_key)):
            raise DomainValidationError("basket identity is invalid")
        basket_id = str(uuid5(NAMESPACE_URL, f"broker-basket:{idempotency_key}"))
        with sqlite_connection(self.database, row_factory=True) as connection:
            existing = connection.execute("SELECT * FROM broker_baskets WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing is not None:
                return self.basket(str(existing["basket_id"]))
        child_ids: list[str] = []
        for index, order in enumerate(payload["orders"]):
            if not isinstance(order, dict):
                raise DomainValidationError("basket order is invalid")
            child = {**order, "account_id": account_id, "proposal_id": proposal_id, "idempotency_key": f"{idempotency_key}:{index}"}
            child_ids.append(str(self.create_intent(child)["order_id"]))
        timestamp = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute("INSERT INTO broker_baskets VALUES (?, ?, ?, ?, ?, ?, ?, 'LOCAL_CREATED', ?)", (basket_id, account_id, proposal_id, idempotency_key, mode, slice_count, interval, timestamp))
            for index, order_id in enumerate(child_ids):
                connection.execute("INSERT INTO broker_basket_orders VALUES (?, ?, ?)", (basket_id, order_id, index % slice_count))
        return self.basket(basket_id)

    def basket(self, basket_id: str) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute("SELECT * FROM broker_baskets WHERE basket_id=?", (basket_id,)).fetchone()
            if row is None:
                raise DomainValidationError("broker basket was not found")
            children = connection.execute("SELECT order_id, slice_index FROM broker_basket_orders WHERE basket_id=? ORDER BY slice_index, order_id", (basket_id,)).fetchall()
        return {**dict(row), "orders": [{"slice_index": item["slice_index"], "order": self.get(str(item["order_id"]))} for item in children]}

    def submit_basket(self, basket_id: str, slice_index: int = 0) -> dict[str, object]:
        basket = self.basket(basket_id)
        if isinstance(slice_index, bool) or not isinstance(slice_index, int) or slice_index < 0:
            raise DomainValidationError("basket slice index is invalid")
        selected = [item for item in basket["orders"] if item["slice_index"] == slice_index]
        if not selected:
            raise DomainValidationError("basket slice was not found")
        submitted = [self.submit(str(item["order"]["order_id"])) for item in selected]
        return {"basket_id": basket_id, "execution_mode": basket["execution_mode"], "slice_index": slice_index, "orders": submitted}

    def create_intent(self, payload: dict[str, object]) -> dict[str, object]:
        required = {"account_id", "proposal_id", "idempotency_key", "instrument_id", "symbol", "exchange", "side", "quantity", "order_type"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise DomainValidationError("broker order intent is incomplete")
        if payload["side"] not in {"BUY", "SELL"} or payload["exchange"] not in {"NSE", "BSE"} or payload["order_type"] not in {"MARKET", "LIMIT"}:
            raise DomainValidationError("broker order intent values are invalid")
        if isinstance(payload["quantity"], bool) or not isinstance(payload["quantity"], int) or payload["quantity"] < 1:
            raise DomainValidationError("broker order quantity is invalid")
        if not all(isinstance(payload[field], str) and str(payload[field]).strip() for field in ("account_id", "proposal_id", "idempotency_key", "instrument_id", "symbol")):
            raise DomainValidationError("broker order identity is invalid")
        order_id = str(uuid4())
        timestamp = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT * FROM broker_orders WHERE idempotency_key=?", (payload["idempotency_key"],)).fetchone()
            if existing is not None:
                return dict(existing)
            connection.execute(
                "INSERT INTO broker_orders(order_id, account_id, proposal_id, idempotency_key, instrument_id, symbol, exchange, side, quantity, order_type, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'LOCAL_CREATED', ?)",
                (order_id, payload["account_id"], payload["proposal_id"], payload["idempotency_key"], payload["instrument_id"], payload["symbol"], payload["exchange"], payload["side"], payload["quantity"], payload["order_type"], timestamp),
            )
            self._event(connection, order_id, "LOCAL_CREATED", None, payload, timestamp)
        return self.get(order_id)

    def get(self, order_id: str) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute("SELECT * FROM broker_orders WHERE order_id=?", (order_id,)).fetchone()
        if row is None:
            raise DomainValidationError("broker order was not found")
        return dict(row)

    def submit(self, order_id: str) -> dict[str, object]:
        order = self.get(order_id)
        if order["status"] == "SUBMITTED":
            return order
        if order["status"] != "LOCAL_CREATED":
            raise DomainValidationError("broker order is not submit-ready")
        if self.gateway is None:
            raise DomainValidationError("broker execution gateway is unavailable")
        try:
            broker_id = self.gateway.submit_order(order)
        except DomainValidationError:
            raise
        except Exception as exc:
            with sqlite_connection(self.database) as connection:
                connection.execute("UPDATE broker_orders SET status='SUBMIT_UNKNOWN' WHERE order_id=?", (order_id,))
                self._event(connection, order_id, "SUBMIT_UNKNOWN", None, {"error": type(exc).__name__}, datetime.now(UTC).isoformat())
            raise DomainValidationError("broker submission outcome is unknown; reconcile before retry") from exc
        with sqlite_connection(self.database) as connection:
            connection.execute("UPDATE broker_orders SET status='SUBMITTED', broker_order_id=? WHERE order_id=?", (broker_id, order_id))
            self._event(connection, order_id, "SUBMITTED", None, {"broker_order_id": broker_id}, datetime.now(UTC).isoformat())
        return self.get(order_id)

    def reconcile(self, order_id: str) -> dict[str, object]:
        order = self.get(order_id)
        if order["status"] not in {"SUBMITTED", "PARTIALLY_FILLED"} or not order["broker_order_id"]:
            raise DomainValidationError("broker order is not open for reconciliation")
        if self.gateway is None:
            raise DomainValidationError("broker execution gateway is unavailable")
        state = self.gateway.order_status(str(order["broker_order_id"]))
        fills = state.get("fills", [])
        if not isinstance(fills, list):
            raise DomainValidationError("broker status has invalid fills")
        for item in fills:
            if not isinstance(item, dict) or not item.get("trade_id"):
                raise DomainValidationError("broker fill is missing trade id")
            self._post_fill_once(order, item)
        status = str(state.get("status", order["status"]))
        mapped = "PARTIALLY_FILLED" if status in {"OPEN", "PARTIAL"} else "FILLED" if status == "COMPLETE" else status
        with sqlite_connection(self.database) as connection:
            connection.execute("UPDATE broker_orders SET status=? WHERE order_id=?", (mapped, order_id))
            self._event(connection, order_id, "BROKER_STATUS", None, state, datetime.now(UTC).isoformat())
        return self.get(order_id)

    def manual_fill(self, order_id: str, payload: dict[str, object]) -> dict[str, object]:
        order = self.get(order_id)
        if order["status"] not in {"LOCAL_CREATED", "SUBMIT_UNKNOWN"}:
            raise DomainValidationError("manual fill is allowed only for an unresolved local order")
        if not isinstance(payload, dict) or set(payload) != {"quantity", "price", "fill_date", "reason"} or not isinstance(payload["reason"], str) or not str(payload["reason"]).strip():
            raise DomainValidationError("manual fill requires quantity, price, date and reason")
        if isinstance(payload["quantity"], bool) or not isinstance(payload["quantity"], int) or payload["quantity"] < 1:
            raise DomainValidationError("manual fill quantity is invalid")
        try:
            Decimal(str(payload["price"]))
            date.fromisoformat(str(payload["fill_date"]))
        except (ValueError, ArithmeticError) as exc:
            raise DomainValidationError("manual fill price or date is invalid") from exc
        fill = {"trade_id": f"MANUAL:{order_id}", "quantity": payload["quantity"], "price": payload["price"], "fill_date": payload["fill_date"], "manual_reason": payload["reason"]}
        self._post_fill_once(order, fill, manual=True)
        with sqlite_connection(self.database) as connection:
            connection.execute("UPDATE broker_orders SET status='FILLED' WHERE order_id=?", (order_id,))
        return self.get(order_id)

    def _post_fill_once(self, order: dict[str, object], item: dict[str, object], manual: bool = False) -> None:
        trade_id = str(item["trade_id"])
        with sqlite_connection(self.database, read_only=True) as connection:
            if connection.execute("SELECT 1 FROM broker_execution_events WHERE order_id=? AND broker_fill_id=?", (order["order_id"], trade_id)).fetchone() is not None:
                return
        account = next(item for item in self.ledger.accounts() if item["account_id"] == order["account_id"])
        self.ledger.record_fills(
            str(order["account_id"]), f"broker-fill:{trade_id}", int(str(account["version"])),
            [Fill(str(order["instrument_id"]), date.fromisoformat(str(item["fill_date"])), FillSide(str(order["side"])), Quantity(int(str(item["quantity"]))), Money(Decimal(str(item["price"])))),],
            order_id=str(order["order_id"]),
        )
        with sqlite_connection(self.database) as connection:
            self._event(connection, str(order["order_id"]), "MANUAL_FILL" if manual else "BROKER_FILL", trade_id, item, datetime.now(UTC).isoformat())

    @staticmethod
    def _event(connection, order_id: str, event_type: str, fill_id: str | None, payload: dict[str, object], timestamp: str) -> None:
        connection.execute("INSERT OR IGNORE INTO broker_execution_events(order_id, event_type, broker_fill_id, payload_json, occurred_at) VALUES (?, ?, ?, ?, ?)", (order_id, event_type, fill_id, json.dumps(payload, sort_keys=True, default=str), timestamp))
