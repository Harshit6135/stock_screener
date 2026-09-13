"""Append-only SQLite ledger with idempotent, versioned fill commands."""

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError, Money, Quantity
from src.portfolio_accounting import Fill, FillSide, project


class Ledger:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._initialize()

    def _connect(self):
        return sqlite_connection(self.path, row_factory=True)

    def _initialize(self) -> None:
        migrate_sqlite(
            self.path,
            "ledger",
            {1: (
                "CREATE TABLE IF NOT EXISTS ledger_accounts (account_id TEXT PRIMARY KEY, opening_cash TEXT NOT NULL);",
                """CREATE TABLE IF NOT EXISTS ledger_commands (
                    account_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, resulting_version INTEGER NOT NULL,
                    PRIMARY KEY(account_id, idempotency_key)
                );""",
                """CREATE TABLE IF NOT EXISTS ledger_events (
                    event_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, version INTEGER NOT NULL,
                    event_json TEXT NOT NULL, UNIQUE(account_id, version)
                );""",
            )},
        )

    def open_account(self, account_id: str, opening_cash: Money) -> None:
        with self._connect() as connection:
            try:
                connection.execute("INSERT INTO ledger_accounts(account_id, opening_cash) VALUES (?, ?)", (account_id, str(opening_cash.amount)))
            except sqlite3.IntegrityError as exc:
                raise DomainValidationError("account already exists") from exc

    def record_fills(self, account_id: str, idempotency_key: str, expected_version: int, fills: Iterable[Fill]) -> int:
        fills = tuple(fills)
        if not fills or expected_version < 0 or not idempotency_key:
            raise DomainValidationError("ledger command is incomplete")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT resulting_version FROM ledger_commands WHERE account_id = ? AND idempotency_key = ?", (account_id, idempotency_key)).fetchone()
            if existing:
                return existing["resulting_version"]
            account = connection.execute("SELECT opening_cash FROM ledger_accounts WHERE account_id = ?", (account_id,)).fetchone()
            if account is None:
                raise DomainValidationError("account does not exist")
            current = connection.execute("SELECT COALESCE(MAX(version), 0) AS version FROM ledger_events WHERE account_id = ?", (account_id,)).fetchone()["version"]
            if current != expected_version:
                raise DomainValidationError("stale ledger version")
            version = current
            for fill in fills:
                version += 1
                event = {"instrument_id": fill.instrument_id, "fill_date": fill.fill_date.isoformat(), "side": fill.side.value, "units": fill.units.units, "price": str(fill.price.amount)}
                connection.execute("INSERT INTO ledger_events(account_id, version, event_json) VALUES (?, ?, ?)", (account_id, version, json.dumps(event, sort_keys=True)))
            connection.execute("INSERT INTO ledger_commands(account_id, idempotency_key, resulting_version) VALUES (?, ?, ?)", (account_id, idempotency_key, version))
            return version

    def projection(self, account_id: str):
        with self._connect() as connection:
            account = connection.execute("SELECT opening_cash FROM ledger_accounts WHERE account_id = ?", (account_id,)).fetchone()
            if account is None:
                raise DomainValidationError("account does not exist")
            rows = connection.execute("SELECT event_json FROM ledger_events WHERE account_id = ? ORDER BY version", (account_id,)).fetchall()
        from datetime import date
        fills = tuple(Fill(event["instrument_id"], date.fromisoformat(event["fill_date"]), FillSide(event["side"]), Quantity(event["units"]), Money(event["price"])) for row in rows for event in [json.loads(row["event_json"])])
        return project(Money(account["opening_cash"]), fills)
