"""Portfolio-owned reservation state, usable inside a caller transaction."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.platform_kernel.sqlite import migrate_sqlite


class RiskReservationRepository:
    """Own the durable rows that reserve portfolio buying power."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        migrate_sqlite(
            self.database,
            "risk_reservations",
            {
                1: (
                    """CREATE TABLE risk_reservations (
                        reservation_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                        proposal_id TEXT NOT NULL, orders_json TEXT NOT NULL,
                        ledger_version INTEGER NOT NULL, config_version INTEGER NOT NULL,
                        status TEXT NOT NULL DEFAULT 'ACTIVE')""",
                    "CREATE INDEX risk_reservations_account ON risk_reservations(account_id, status)",
                )
            },
        )

    @staticmethod
    def active_for_account(
        connection: sqlite3.Connection, account_id: str
    ) -> list[sqlite3.Row | tuple[object, ...]]:
        """Read active reservations using the caller’s shared transaction."""
        return connection.execute(
            "SELECT * FROM risk_reservations WHERE account_id=? AND status='ACTIVE'",
            (account_id,),
        ).fetchall()

    @staticmethod
    def upsert(
        connection: sqlite3.Connection,
        reservation_id: str,
        account_id: str,
        proposal_id: str,
        orders_json: str,
        ledger_version: int,
        config_version: int,
    ) -> None:
        """Persist a reservation without committing the caller’s transaction."""
        connection.execute(
            """INSERT INTO risk_reservations VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')
               ON CONFLICT(reservation_id) DO UPDATE SET
               orders_json=excluded.orders_json,
               ledger_version=excluded.ledger_version,
               config_version=excluded.config_version,
               status='ACTIVE'""",
            (
                reservation_id,
                account_id,
                proposal_id,
                orders_json,
                ledger_version,
                config_version,
            ),
        )

    @staticmethod
    def release(connection: sqlite3.Connection, reservation_id: str) -> None:
        """Release a reservation using the caller’s transaction."""
        connection.execute(
            "UPDATE risk_reservations SET status='RELEASED' WHERE reservation_id=?",
            (reservation_id,),
        )


__all__ = ["RiskReservationRepository"]
