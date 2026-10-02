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
                raise DomainValidationError("explicit ledger account is required for broker routing")
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
        client = self._client(account_id)
        return str(client.place_order(
            variety=str(order.get("variety", "regular")), exchange=str(order["exchange"]), tradingsymbol=str(order["symbol"]),
            transaction_type=str(order["side"]), quantity=int(str(order["quantity"])),
            order_type=str(order["order_type"]), product="CNC", validity="DAY",
            tag=str(order["order_id"]).replace("-", "")[:20],
        ))

    def order_status(self, broker_order_id: str, account_id: str | None = None) -> dict[str, object]:
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
        tag = str(order["order_id"]).replace("-", "")[:20]
        matches = [row for row in client.orders() if row.get("tag") == tag]
        if len(matches) > 1:
            raise DomainValidationError("ambiguous broker receipt; operator review required")
        return str(matches[0]["order_id"]) if matches else None


class BrokerOrderService:
    def __init__(self, database: str | Path, ledger: Ledger, gateway: BrokerExecutionGateway | None = None, risk_config=None):
        self.database, self.ledger, self.gateway, self.risk_config = Path(database), ledger, gateway, risk_config
        self.risk_guard = None
        def upgrade_variety(connection):
            columns = {row[1] for row in connection.execute("PRAGMA table_info(broker_orders)")}
            if "variety" not in columns:
                connection.execute("ALTER TABLE broker_orders ADD COLUMN variety TEXT NOT NULL DEFAULT 'regular'")

        def upgrade_context(connection):
            columns = {row[1] for row in connection.execute("PRAGMA table_info(broker_orders)")}
            for column in ("broker_account_id", "strategy_id", "decision_date", "target_session_date", "exit_reason", "expected_ledger_version"):
                if column not in columns:
                    connection.execute(f"ALTER TABLE broker_orders ADD COLUMN {column} TEXT")

        migrate_sqlite(self.database, "broker_orders", {1: (
            """CREATE TABLE IF NOT EXISTS broker_orders (
                order_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE, instrument_id TEXT NOT NULL,
                symbol TEXT NOT NULL, exchange TEXT NOT NULL, side TEXT NOT NULL,
                quantity INTEGER NOT NULL, order_type TEXT NOT NULL, variety TEXT NOT NULL DEFAULT 'regular', status TEXT NOT NULL,
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
        ), 2: (upgrade_variety,), 3: (upgrade_context,)})

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
        optional = {"variety"}
        if not isinstance(payload, dict) or not required.issubset(payload) or set(payload) - (required | optional):
            raise DomainValidationError("broker order intent is incomplete")
        if payload["side"] not in {"BUY", "SELL"} or payload["exchange"] != "NSE" or payload["order_type"] not in {"MARKET", "LIMIT"}:
            raise DomainValidationError("broker order intent values are invalid")
        variety = str(payload.get("variety", "regular"))
        if variety not in {"regular", "amo"}:
            raise DomainValidationError("broker order variety is invalid")
        if variety == "amo" and payload["side"] != "SELL":
            raise DomainValidationError("AMO is only supported for next-session SELL intents")
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
                for field in required - {"idempotency_key"}:
                    if str(existing[field]) != str(payload[field]):
                        raise DomainValidationError("idempotency key reused with different broker intent")
                if existing["variety"] != variety:
                    raise DomainValidationError("idempotency key reused with different order variety")
                return dict(existing)
            connection.execute(
                "INSERT INTO broker_orders(order_id, account_id, proposal_id, idempotency_key, instrument_id, symbol, exchange, side, quantity, order_type, variety, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'LOCAL_CREATED', ?)",
                (order_id, payload["account_id"], payload["proposal_id"], payload["idempotency_key"], payload["instrument_id"], payload["symbol"], payload["exchange"], payload["side"], payload["quantity"], payload["order_type"], variety, timestamp),
            )
            self._event(connection, order_id, "LOCAL_CREATED", None, payload, timestamp)
        return self.get(order_id)

    def get(self, order_id: str) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute("SELECT * FROM broker_orders WHERE order_id=?", (order_id,)).fetchone()
        if row is None:
            raise DomainValidationError("broker order was not found")
        return dict(row)

    def prepare_proposal(self, proposal_id: str) -> list[dict[str, object]]:
        """Create local intents only. Submission remains an explicit gated command."""
        if self.risk_guard is None:
            raise DomainValidationError("managed portfolio guards are unavailable")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            proposal = connection.execute("SELECT * FROM action_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        if proposal is None or proposal["status"] != "APPROVED":
            raise DomainValidationError("an approved proposal is required")
        accounts = getattr(self.gateway, "accounts", None)
        if accounts is None:
            raise DomainValidationError("account-specific broker routing is unavailable")
        binding = accounts.binding(proposal["account_id"])
        decisions = json.loads(proposal["decision_json"])
        self.risk_guard.validate(proposal["account_id"], decisions, int(proposal["expected_ledger_version"]),
            reservation_id=f"proposal:{proposal_id}", proposal_id=proposal_id)
        results = []
        for index, decision in enumerate(decisions):
            if decision["type"] == "NO_ACTION":
                continue
            instrument = self.risk_guard.market.instrument_by_id(decision["instrument_id"])
            if instrument is None:
                raise DomainValidationError("proposal instrument identity is unavailable")
            side = "BUY" if decision["type"] in {"BUY", "PYRAMID_ADD"} else "SELL"
            protective = decision["type"] in {"HARD_STOP", "STOP_LOSS"}
            variety = "amo" if side == "SELL" and not protective and proposal["strategy_id"] != "manual" else "regular"
            order = self.create_intent({"account_id": proposal["account_id"], "proposal_id": proposal_id,
                "idempotency_key": f"proposal:{proposal_id}:decision:{index}", "instrument_id": decision["instrument_id"],
                "symbol": instrument["symbol"], "exchange": "NSE", "side": side,
                "quantity": int(decision["units"]), "order_type": "MARKET", "variety": variety})
            with sqlite_connection(self.database) as connection:
                connection.execute("""UPDATE broker_orders SET broker_account_id=?, strategy_id=?, decision_date=?,
                    target_session_date=?, exit_reason=?, expected_ledger_version=? WHERE order_id=?""",
                    (binding["broker_account_id"], binding["strategy_id"], proposal["ranking_week_end"], proposal["action_date"],
                     decision.get("exit_reason") or decision["type"].lower(), str(proposal["expected_ledger_version"]), order["order_id"]))
            results.append(self.get(order["order_id"]))
        return results

    def submit(self, order_id: str) -> dict[str, object]:
        order = self.get(order_id)
        if order["status"] == "SUBMITTED":
            return order
        if order["status"] != "LOCAL_CREATED":
            raise DomainValidationError("broker order is not submit-ready")
        if self.gateway is None:
            raise DomainValidationError("broker execution gateway is unavailable")
        if self.risk_guard:
            with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
                proposal = connection.execute("SELECT * FROM action_proposals WHERE proposal_id=? AND account_id=?", (order["proposal_id"], order["account_id"])).fetchone()
            if proposal is None or proposal["status"] != "APPROVED":
                raise DomainValidationError("broker order requires an approved owning proposal")
            decisions = json.loads(proposal["decision_json"])
            decision = next((item for item in decisions if item.get("instrument_id") == order["instrument_id"] and (item.get("type") in {"BUY", "PYRAMID_ADD"}) == (order["side"] == "BUY")), None)
            if not decision or int(order["quantity"]) > int(decision["units"]):
                raise DomainValidationError("broker order does not match the approved decision")
            self.risk_guard.validate(str(order["account_id"]), [{**decision, "units": order["quantity"]}],
                int(proposal["expected_ledger_version"]), reservation_id=f"broker:{order_id}", proposal_id=str(order["proposal_id"]))
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            claimed = connection.execute("UPDATE broker_orders SET status='SUBMITTING' WHERE order_id=? AND status='LOCAL_CREATED'", (order_id,)).rowcount
            if claimed != 1:
                raise DomainValidationError("broker order is already being submitted; reconcile before retry")
            self._event(connection, order_id, "SUBMITTING", None, {}, datetime.now(UTC).isoformat())
        try:
            broker_id = self.gateway.submit_order(order)
        except DomainValidationError:
            with sqlite_connection(self.database) as connection:
                connection.execute("UPDATE broker_orders SET status='LOCAL_CREATED' WHERE order_id=? AND status='SUBMITTING'", (order_id,))
            if self.risk_guard:
                self.risk_guard.release(f"broker:{order_id}")
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
        if order["status"] in {"SUBMITTING", "SUBMIT_UNKNOWN"}:
            lookup = getattr(self.gateway, "find_order", None)
            if not callable(lookup):
                raise DomainValidationError("unknown broker receipt requires explicit operator review")
            broker_id = lookup(order)
            if not broker_id:
                raise DomainValidationError("broker has no confirmed matching receipt; do not resubmit")
            with sqlite_connection(self.database) as connection:
                connection.execute("UPDATE broker_orders SET status='SUBMITTED', broker_order_id=? WHERE order_id=?", (broker_id, order_id))
                self._event(connection, order_id, "RECEIPT_RECOVERED", None, {"broker_order_id": broker_id}, datetime.now(UTC).isoformat())
            order = self.get(order_id)
        if order["status"] not in {"SUBMITTED", "PARTIALLY_FILLED"} or not order["broker_order_id"]:
            raise DomainValidationError("broker order is not open for reconciliation")
        if self.gateway is None:
            raise DomainValidationError("broker execution gateway is unavailable")
        if isinstance(self.gateway, KiteExecutionGateway):
            state = self.gateway.order_status(str(order["broker_order_id"]), str(order["account_id"]))
        else:
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
        if self.risk_guard and mapped in {"FILLED", "CANCELLED", "REJECTED"}:
            self.risk_guard.release(f"broker:{order_id}")
            with sqlite_connection(self.database, read_only=True) as connection:
                outstanding = connection.execute("SELECT COUNT(*) FROM broker_orders WHERE proposal_id=? AND status NOT IN ('FILLED','CANCELLED','REJECTED')", (order["proposal_id"],)).fetchone()[0]
            if not outstanding:
                self.risk_guard.release(f"proposal:{order['proposal_id']}")
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
            [Fill(
                instrument_id=str(order["instrument_id"]), 
                fill_date=date.fromisoformat(str(item["fill_date"])), 
                side=FillSide(str(order["side"])), 
                units=Quantity(int(str(item["quantity"]))), 
                price=Money(Decimal(str(item["price"]))),
                broker_trade_id=trade_id
            )],
            order_id=str(order["order_id"]),
        )
        with sqlite_connection(self.database) as connection:
            self._event(connection, str(order["order_id"]), "MANUAL_FILL" if manual else "BROKER_FILL", trade_id, item, datetime.now(UTC).isoformat())

    @staticmethod
    def _event(connection, order_id: str, event_type: str, fill_id: str | None, payload: dict[str, object], timestamp: str) -> None:
        connection.execute("INSERT OR IGNORE INTO broker_execution_events(order_id, event_type, broker_fill_id, payload_json, occurred_at) VALUES (?, ?, ?, ?, ?)", (order_id, event_type, fill_id, json.dumps(payload, sort_keys=True, default=str), timestamp))
