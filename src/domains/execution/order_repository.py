"""Execution-owned persistence for broker order intents and execution events."""

from __future__ import annotations

import json
from pathlib import Path

from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


class BrokerOrderRepository:
    """Own broker intent, basket, and reconciliation-event storage."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)

        migrate_sqlite(
            self.database,
            "broker_orders",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS broker_orders (
                        order_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL UNIQUE, instrument_id TEXT NOT NULL,
                        symbol TEXT NOT NULL, exchange TEXT NOT NULL, side TEXT NOT NULL,
                        quantity INTEGER NOT NULL, order_type TEXT NOT NULL,
                        variety TEXT NOT NULL DEFAULT 'regular', status TEXT NOT NULL,
                        broker_order_id TEXT, created_at TEXT NOT NULL,
                        broker_account_id TEXT, strategy_id TEXT, decision_date TEXT,
                        target_session_date TEXT, exit_reason TEXT, expected_ledger_version TEXT)""",
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
                ),
            },
        )

    def existing_basket(self, idempotency_key: str) -> dict[str, object] | None:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM broker_baskets WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
        return dict(row) if row is not None else None

    def create_basket(
        self,
        *,
        basket_id: str,
        account_id: str,
        proposal_id: str,
        idempotency_key: str,
        execution_mode: str,
        slice_count: int,
        interval_seconds: int,
        created_at: str,
        child_order_ids: list[str],
    ) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "INSERT INTO broker_baskets VALUES (?, ?, ?, ?, ?, ?, ?, 'LOCAL_CREATED', ?)",
                (
                    basket_id,
                    account_id,
                    proposal_id,
                    idempotency_key,
                    execution_mode,
                    slice_count,
                    interval_seconds,
                    created_at,
                ),
            )
            for index, order_id in enumerate(child_order_ids):
                connection.execute(
                    "INSERT INTO broker_basket_orders VALUES (?, ?, ?)",
                    (basket_id, order_id, index % slice_count),
                )

    def basket(self, basket_id: str) -> tuple[dict[str, object], list[dict[str, object]]]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM broker_baskets WHERE basket_id=?", (basket_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError("broker basket was not found")
            children = connection.execute(
                "SELECT order_id, slice_index FROM broker_basket_orders "
                "WHERE basket_id=? ORDER BY slice_index, order_id",
                (basket_id,),
            ).fetchall()
        return dict(row), [dict(item) for item in children]

    def create_intent(
        self,
        *,
        order_id: str,
        payload: dict[str, object],
        variety: str,
        created_at: str,
    ) -> dict[str, object]:
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM broker_orders WHERE idempotency_key=?",
                (payload["idempotency_key"],),
            ).fetchone()
            if existing is not None:
                required = {
                    "account_id",
                    "proposal_id",
                    "idempotency_key",
                    "instrument_id",
                    "symbol",
                    "exchange",
                    "side",
                    "quantity",
                    "order_type",
                }
                for field in required - {"idempotency_key"}:
                    if str(existing[field]) != str(payload[field]):
                        raise DomainValidationError(
                            "idempotency key reused with different broker intent"
                        )
                if existing["variety"] != variety:
                    raise DomainValidationError(
                        "idempotency key reused with different order variety"
                    )
                return dict(existing)
            connection.execute(
                """INSERT INTO broker_orders(
                    order_id, account_id, proposal_id, idempotency_key, instrument_id, symbol,
                    exchange, side, quantity, order_type, variety, status, created_at,
                    broker_account_id, strategy_id, decision_date, target_session_date,
                    exit_reason, expected_ledger_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'LOCAL_CREATED', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order_id,
                    payload["account_id"],
                    payload["proposal_id"],
                    payload["idempotency_key"],
                    payload["instrument_id"],
                    payload["symbol"],
                    payload["exchange"],
                    payload["side"],
                    payload["quantity"],
                    payload["order_type"],
                    variety,
                    created_at,
                    payload.get("broker_account_id"),
                    payload.get("strategy_id"),
                    payload.get("decision_date"),
                    payload.get("target_session_date"),
                    payload.get("exit_reason"),
                    str(payload["expected_ledger_version"])
                    if payload.get("expected_ledger_version") is not None
                    else None,
                ),
            )
            self._event(connection, order_id, "LOCAL_CREATED", None, payload, created_at)
        return self.get(order_id)

    def get(self, order_id: str) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM broker_orders WHERE order_id=?", (order_id,)
            ).fetchone()
        if row is None:
            raise DomainValidationError("broker order was not found")
        return dict(row)

    def outstanding_order_count(self, proposal_id: str) -> int:
        with sqlite_connection(self.database, read_only=True) as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM broker_orders WHERE proposal_id=? "
                    "AND status NOT IN ('FILLED','CANCELLED','REJECTED')",
                    (proposal_id,),
                ).fetchone()[0]
            )

    def claim_submission(self, order_id: str, timestamp: str) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            claimed = connection.execute(
                "UPDATE broker_orders SET status='SUBMITTING' "
                "WHERE order_id=? AND status='LOCAL_CREATED'",
                (order_id,),
            ).rowcount
            if claimed != 1:
                raise DomainValidationError(
                    "broker order is already being submitted; reconcile before retry"
                )
            self._event(connection, order_id, "SUBMITTING", None, {}, timestamp)

    def reset_local_created(self, order_id: str) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE broker_orders SET status='LOCAL_CREATED' "
                "WHERE order_id=? AND status='SUBMITTING'",
                (order_id,),
            )

    def mark_submit_unknown(self, order_id: str, error_type: str, timestamp: str) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE broker_orders SET status='SUBMIT_UNKNOWN' WHERE order_id=?", (order_id,)
            )
            self._event(
                connection, order_id, "SUBMIT_UNKNOWN", None, {"error": error_type}, timestamp
            )

    def mark_submitted(self, order_id: str, broker_order_id: str, timestamp: str) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE broker_orders SET status='SUBMITTED', broker_order_id=? WHERE order_id=?",
                (broker_order_id, order_id),
            )
            self._event(
                connection,
                order_id,
                "SUBMITTED",
                None,
                {"broker_order_id": broker_order_id},
                timestamp,
            )

    def recover_receipt(self, order_id: str, broker_order_id: str, timestamp: str) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE broker_orders SET status='SUBMITTED', broker_order_id=? WHERE order_id=?",
                (broker_order_id, order_id),
            )
            self._event(
                connection,
                order_id,
                "RECEIPT_RECOVERED",
                None,
                {"broker_order_id": broker_order_id},
                timestamp,
            )

    def update_status(
        self, order_id: str, status: str, state: dict[str, object], timestamp: str
    ) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE broker_orders SET status=? WHERE order_id=?", (status, order_id)
            )
            self._event(connection, order_id, "BROKER_STATUS", None, state, timestamp)

    def mark_manual_filled(self, order_id: str) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE broker_orders SET status='FILLED' WHERE order_id=?", (order_id,)
            )

    def has_fill_event(self, order_id: str, fill_id: str) -> bool:
        with sqlite_connection(self.database, read_only=True) as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM broker_execution_events WHERE order_id=? AND broker_fill_id=?",
                    (order_id, fill_id),
                ).fetchone()
                is not None
            )

    def record_fill_event(
        self,
        order_id: str,
        fill_id: str,
        event_type: str,
        payload: dict[str, object],
        timestamp: str,
    ) -> None:
        with sqlite_connection(self.database) as connection:
            self._event(connection, order_id, event_type, fill_id, payload, timestamp)

    @staticmethod
    def _event(
        connection,
        order_id: str,
        event_type: str,
        fill_id: str | None,
        payload: dict[str, object],
        timestamp: str,
    ) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO broker_execution_events"
            "(order_id, event_type, broker_fill_id, payload_json, occurred_at) VALUES (?, ?, ?, ?, ?)",
            (
                order_id,
                event_type,
                fill_id,
                json.dumps(payload, sort_keys=True, default=str),
                timestamp,
            ),
        )


__all__ = ["BrokerOrderRepository"]
