"""Append-only SQLite ledger with idempotent, versioned fill commands."""

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

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
            {
                1: (
                    "CREATE TABLE IF NOT EXISTS ledger_accounts (account_id TEXT PRIMARY KEY, opening_cash TEXT NOT NULL);",
                    """CREATE TABLE IF NOT EXISTS ledger_commands (
                    account_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, resulting_version INTEGER NOT NULL,
                    PRIMARY KEY(account_id, idempotency_key)
                );""",
                    """CREATE TABLE IF NOT EXISTS ledger_events (
                    event_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, version INTEGER NOT NULL,
                    event_json TEXT NOT NULL, UNIQUE(account_id, version)
                );""",
                ),
                2: (
                    "ALTER TABLE ledger_accounts ADD COLUMN currency TEXT NOT NULL DEFAULT 'INR'",
                    "ALTER TABLE ledger_commands ADD COLUMN payload_checksum TEXT NOT NULL DEFAULT ''",
                    "ALTER TABLE ledger_commands ADD COLUMN command_json TEXT NOT NULL DEFAULT '{}'",
                    "ALTER TABLE ledger_events ADD COLUMN event_type TEXT NOT NULL DEFAULT 'FILL_RECORDED'",
                    "ALTER TABLE ledger_events ADD COLUMN occurred_at TEXT NOT NULL DEFAULT ''",
                ),
                3: (
                    "CREATE INDEX IF NOT EXISTS ledger_events_account_type ON ledger_events(account_id, event_type, version)",
                ),
                4: (
                    """CREATE TABLE IF NOT EXISTS ledger_valuation_snapshots (
                        account_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
                        as_of_date TEXT NOT NULL, payload_json TEXT NOT NULL,
                        checksum_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                        PRIMARY KEY(account_id, snapshot_id))""",
                    "CREATE INDEX IF NOT EXISTS ledger_valuation_dates ON ledger_valuation_snapshots(account_id, as_of_date)",
                ),
            },
        )

    def open_account(self, account_id: str, opening_cash: Money) -> None:
        if not account_id.strip() or opening_cash.amount < 0:
            raise DomainValidationError("account is invalid")
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO ledger_accounts(account_id, opening_cash, currency) VALUES (?, ?, ?)",
                    (account_id, str(opening_cash.amount), opening_cash.currency),
                )
            except sqlite3.IntegrityError as exc:
                raise DomainValidationError("account already exists") from exc

    def record_fills(
        self,
        account_id: str,
        idempotency_key: str,
        expected_version: int,
        fills: Iterable[Fill],
        *,
        order_id: str | None = None,
    ) -> int:
        fills = tuple(fills)
        if not fills or expected_version < 0 or not idempotency_key:
            raise DomainValidationError("ledger command is incomplete")
        command = {
            "type": "RECORD_FILLS",
            "account_id": account_id,
            "expected_version": expected_version,
            "order_id": order_id,
            "fills": [self._fill_event(fill) for fill in fills],
        }
        command_json = json.dumps(command, sort_keys=True, separators=(",", ":"))
        checksum = hashlib.sha256(command_json.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT resulting_version, payload_checksum FROM ledger_commands WHERE account_id = ? AND idempotency_key = ?",
                (account_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["payload_checksum"] != checksum:
                    raise DomainValidationError(
                        "idempotency key was reused with a different ledger command"
                    )
                return existing["resulting_version"]
            account = connection.execute(
                "SELECT opening_cash, currency FROM ledger_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if account is None:
                raise DomainValidationError("account does not exist")
            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM ledger_events WHERE account_id = ?",
                (account_id,),
            ).fetchone()["version"]
            if current != expected_version:
                raise DomainValidationError("stale ledger version")
            previous_rows = connection.execute(
                """SELECT event_json FROM ledger_events WHERE account_id = ?
                   AND event_type = 'FILL_RECORDED' ORDER BY version""",
                (account_id,),
            ).fetchall()
            previous_fills = tuple(
                self._event_fill(json.loads(row["event_json"])) for row in previous_rows
            )
            # Validate against the complete position/cash history *inside*
            # the same write transaction. A malformed transaction must
            # never be committed and corrupt the account projection.
            project(Money(account["opening_cash"], account["currency"]), previous_fills + fills)
            version = current
            if order_id:
                occurred_at = min(self._execution_time(fill) for fill in fills).isoformat()
                order_event = {
                    "order_id": order_id,
                    "origin": "MANUAL",
                    "idempotency_key": idempotency_key,
                }
                for event_type in ("ORDER_PROPOSED", "ORDER_APPROVED", "ORDER_SUBMITTED"):
                    version += 1
                    connection.execute(
                        "INSERT INTO ledger_events(account_id, version, event_json, event_type, occurred_at) VALUES (?, ?, ?, ?, ?)",
                        (
                            account_id,
                            version,
                            json.dumps(order_event, sort_keys=True),
                            event_type,
                            occurred_at,
                        ),
                    )
            for fill in fills:
                if fill.price.currency != account["currency"]:
                    raise DomainValidationError("fill currency does not match account currency")
                version += 1
                event = self._fill_event(fill)
                connection.execute(
                    "INSERT INTO ledger_events(account_id, version, event_json, event_type, occurred_at) VALUES (?, ?, ?, 'FILL_RECORDED', ?)",
                    (
                        account_id,
                        version,
                        json.dumps(event, sort_keys=True),
                        self._execution_time(fill).isoformat(),
                    ),
                )
            connection.execute(
                "INSERT INTO ledger_commands(account_id, idempotency_key, resulting_version, payload_checksum, command_json) VALUES (?, ?, ?, ?, ?)",
                (account_id, idempotency_key, version, checksum, command_json),
            )
            return version

    def record_cash_transfer(
        self,
        account_id: str,
        idempotency_key: str,
        expected_version: int,
        direction: str,
        amount: Money,
        occurred_at: datetime | None = None,
    ) -> int:
        """Append an idempotent deposit or withdrawal without mutating history."""
        if direction not in {"DEPOSIT", "WITHDRAW"} or amount.amount <= 0:
            raise DomainValidationError("cash transfer is invalid")
        if occurred_at is None:
            occurred_at = datetime.now(UTC)
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise DomainValidationError("cash transfer timestamp must be timezone-aware")
        command = {
            "type": "CASH_TRANSFER",
            "account_id": account_id,
            "expected_version": expected_version,
            "direction": direction,
            "amount": str(amount.amount),
            "currency": amount.currency,
            "occurred_at": occurred_at.isoformat(),
        }
        command_json = json.dumps(command, sort_keys=True, separators=(",", ":"))
        checksum = hashlib.sha256(command_json.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT resulting_version, payload_checksum FROM ledger_commands WHERE account_id=? AND idempotency_key=?",
                (account_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["payload_checksum"] != checksum:
                    raise DomainValidationError("idempotency key was reused with a different ledger command")
                return existing["resulting_version"]
            account = connection.execute(
                "SELECT opening_cash, currency FROM ledger_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            if account is None:
                raise DomainValidationError("account does not exist")
            if amount.currency != account["currency"]:
                raise DomainValidationError("cash transfer currency does not match account")
            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM ledger_events WHERE account_id=?",
                (account_id,),
            ).fetchone()["version"]
            if current != expected_version:
                raise DomainValidationError("stale ledger version")
            balance = self._cash_balance(connection, account_id, account)
            if direction == "WITHDRAW" and amount.amount > balance:
                raise DomainValidationError("withdrawal exceeds confirmed cash")
            version = current + 1
            event = {
                "direction": direction,
                "amount": str(amount.amount),
                "currency": amount.currency,
                "transfer_at": occurred_at.isoformat(),
            }
            connection.execute(
                "INSERT INTO ledger_events(account_id, version, event_json, event_type, occurred_at) VALUES (?, ?, ?, 'CASH_TRANSFER', ?)",
                (account_id, version, json.dumps(event, sort_keys=True), occurred_at.isoformat()),
            )
            connection.execute(
                "INSERT INTO ledger_commands(account_id, idempotency_key, resulting_version, payload_checksum, command_json) VALUES (?, ?, ?, ?, ?)",
                (account_id, idempotency_key, version, checksum, command_json),
            )
            return version

    def projection(self, account_id: str):
        return self.projection_at(account_id, None)

    def open_instrument_ids(self) -> set[str]:
        """Return instruments with non-zero positions across all accounts."""
        held: set[str] = set()
        for account in self.accounts():
            projection = self.projection(str(account["account_id"]))
            held.update(str(lot.instrument_id) for lot in projection.open_lots)
        return held

    def projection_at(self, account_id: str, as_of: date | None):
        with self._connect() as connection:
            account = connection.execute(
                "SELECT opening_cash, currency FROM ledger_accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if account is None:
                raise DomainValidationError("account does not exist")
            cutoff = f"{as_of.isoformat()}T23:59:59.999999" if as_of else None
            rows = connection.execute(
                "SELECT event_json FROM ledger_events WHERE account_id = ? AND event_type = 'FILL_RECORDED' AND (? IS NULL OR occurred_at <= ?) ORDER BY version",
                (account_id, cutoff, cutoff),
            ).fetchall()
            transfers = connection.execute(
                "SELECT event_json FROM ledger_events WHERE account_id=? AND event_type='CASH_TRANSFER' AND (? IS NULL OR occurred_at <= ?) ORDER BY version",
                (account_id, cutoff, cutoff),
            ).fetchall()
        fills = tuple(self._event_fill(json.loads(row["event_json"])) for row in rows)
        transfer_total = sum(
            (Decimal(str(json.loads(row["event_json"])["amount"]))
             * (1 if json.loads(row["event_json"])["direction"] == "DEPOSIT" else -1)
             for row in transfers),
            Decimal(0),
        )
        return project(Money(Decimal(account["opening_cash"]) + transfer_total, account["currency"]), fills)

    def journal(self, account_id: str, *, long_term_days: int = 365) -> list[dict[str, object]]:
        """Return an immutable FIFO trade journal derived from ledger events."""
        if isinstance(long_term_days, bool) or not isinstance(long_term_days, int) or not 1 <= long_term_days <= 3650:
            raise DomainValidationError("long_term_days must be between 1 and 3650")
        events = self.events(account_id)
        lots: dict[str, list[dict[str, object]]] = {}
        journal: list[dict[str, object]] = []
        for event in events:
            if event["event_type"] != "FILL_RECORDED":
                continue
            fill = event["event"]
            units = int(str(fill["units"]))
            price = Decimal(str(fill["price"]))
            if fill["side"] == "BUY":
                lots.setdefault(str(fill["instrument_id"]), []).append(
                    {"units": units, "price": price, "date": date.fromisoformat(str(fill["fill_date"]))}
                )
                continue
            remaining = units
            for lot in lots.get(str(fill["instrument_id"]), []):
                matched = min(remaining, int(lot["units"]))
                if matched < 1:
                    continue
                sell_fee = Decimal(str(fill.get("fee", "0"))) * Decimal(matched) / Decimal(units)
                holding_days = (date.fromisoformat(str(fill["fill_date"])) - lot["date"]).days
                journal.append({
                    "instrument_id": fill["instrument_id"], "buy_date": lot["date"].isoformat(),
                    "sell_date": fill["fill_date"], "units": matched,
                    "buy_price": str(lot["price"]), "sell_price": str(price),
                    "realised_pnl": str((price - lot["price"]) * matched - sell_fee),
                    "holding_days": holding_days,
                    "tax_holding_period": "LONG_TERM" if holding_days >= long_term_days else "SHORT_TERM",
                    "hold_recommendation": "LTCG_THRESHOLD_REACHED" if holding_days >= long_term_days else "CONSIDER_HOLDING_TO_LTCG_THRESHOLD",
                })
                lot["units"] = int(lot["units"]) - matched
                remaining -= matched
                if remaining == 0:
                    break
        return journal

    def save_valuation(self, account_id: str, snapshot_id: str, as_of_date: date, payload: dict[str, object]) -> dict[str, object]:
        if not snapshot_id.strip():
            raise DomainValidationError("valuation snapshot id is required")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        checksum = hashlib.sha256(encoded.encode()).hexdigest()
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM ledger_accounts WHERE account_id=?", (account_id,)).fetchone() is None:
                raise DomainValidationError("account does not exist")
            existing = connection.execute(
                "SELECT checksum_sha256, payload_json, as_of_date FROM ledger_valuation_snapshots WHERE account_id=? AND snapshot_id=?",
                (account_id, snapshot_id),
            ).fetchone()
            if existing is not None:
                if existing["checksum_sha256"] != checksum:
                    raise DomainValidationError("valuation snapshot id conflicts with existing payload")
                return {"account_id": account_id, "snapshot_id": snapshot_id, "as_of_date": existing["as_of_date"], "payload": json.loads(existing["payload_json"]), "checksum_sha256": checksum}
            connection.execute(
                "INSERT INTO ledger_valuation_snapshots(account_id, snapshot_id, as_of_date, payload_json, checksum_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (account_id, snapshot_id, as_of_date.isoformat(), encoded, checksum, created_at),
            )
        return {"account_id": account_id, "snapshot_id": snapshot_id, "as_of_date": as_of_date.isoformat(), "payload": payload, "checksum_sha256": checksum}

    def valuations(self, account_id: str, limit: int = 100) -> list[dict[str, object]]:
        if not 1 <= limit <= 500:
            raise DomainValidationError("valuation limit must be 1..500")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT account_id, snapshot_id, as_of_date, payload_json, checksum_sha256, created_at FROM ledger_valuation_snapshots WHERE account_id=? ORDER BY as_of_date DESC, created_at DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        if not rows:
            with self._connect() as connection:
                if connection.execute("SELECT 1 FROM ledger_accounts WHERE account_id=?", (account_id,)).fetchone() is None:
                    raise DomainValidationError("account does not exist")
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def accounts(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT a.account_id, a.opening_cash, a.currency,
                   COALESCE(MAX(e.version), 0) AS version
                   FROM ledger_accounts a LEFT JOIN ledger_events e
                   ON e.account_id = a.account_id
                   GROUP BY a.account_id ORDER BY a.account_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def events(self, account_id: str, *, after_version: int = 0) -> list[dict[str, object]]:
        if after_version < 0:
            raise DomainValidationError("after_version must be non-negative")
        with self._connect() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM ledger_accounts WHERE account_id = ?", (account_id,)
                ).fetchone()
                is None
            ):
                raise DomainValidationError("account does not exist")
            rows = connection.execute(
                """SELECT version, event_type, occurred_at, event_json FROM ledger_events
                   WHERE account_id=? AND version>? ORDER BY version LIMIT 500""",
                (account_id, after_version),
            ).fetchall()
        return [
            {
                "version": row["version"],
                "event_type": row["event_type"],
                "occurred_at": row["occurred_at"],
                "event": json.loads(row["event_json"]),
            }
            for row in rows
        ]

    @staticmethod
    def _fill_event(fill: Fill) -> dict[str, object]:
        return {
            "instrument_id": fill.instrument_id,
            "fill_date": fill.fill_date.isoformat(),
            "executed_at": Ledger._execution_time(fill).isoformat(),
            "side": fill.side.value,
            "units": fill.units.units,
            "price": str(fill.price.amount),
            "currency": fill.price.currency,
            "fee": str(fill.fee.amount),
            "correlation_id": fill.correlation_id,
        }

    @staticmethod
    def _event_fill(event: dict[str, object]) -> Fill:
        currency = str(event.get("currency", "INR"))
        executed_at = event.get("executed_at")
        return Fill(
            str(event["instrument_id"]),
            date.fromisoformat(str(event["fill_date"])),
            FillSide(str(event["side"])),
            Quantity(int(str(event["units"]))),
            Money(Decimal(str(event["price"])), currency),
            Money(Decimal(str(event.get("fee", "0"))), currency),
            datetime.fromisoformat(str(executed_at)) if executed_at else None,
            str(event["correlation_id"]) if event.get("correlation_id") else None,
        )

    @staticmethod
    def _execution_time(fill: Fill) -> datetime:
        if fill.executed_at is None:
            raise DomainValidationError("fill execution timestamp is required")
        return fill.executed_at

    @staticmethod
    def _cash_balance(connection, account_id: str, account) -> Decimal:
        rows = connection.execute(
            "SELECT event_json, event_type FROM ledger_events WHERE account_id=? ORDER BY version", (account_id,)
        ).fetchall()
        balance = Decimal(str(account["opening_cash"]))
        for row in rows:
            event = json.loads(row["event_json"])
            if row["event_type"] == "CASH_TRANSFER":
                balance += Decimal(str(event["amount"])) * (1 if event["direction"] == "DEPOSIT" else -1)
            elif row["event_type"] == "FILL_RECORDED":
                value = Decimal(str(event["price"])) * Decimal(str(event["units"]))
                fee = Decimal(str(event.get("fee", "0")))
                balance += value - fee if event["side"] == "SELL" else -(value + fee)
        return balance
