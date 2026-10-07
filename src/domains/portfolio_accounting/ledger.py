"""Append-only SQLite ledger with idempotent, versioned fill commands."""

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from contextlib import nullcontext
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from src.domains.portfolio_accounting import (
    AccountingEvent,
    Fill,
    FillSide,
    OpeningPosition,
    project,
)
from src.domains.portfolio_accounting.api import (
    ImportedPositionFunding,
    Lot,
    OpenLotReconciliation,
    StockSplit,
)
from src.platform_kernel import DomainValidationError, Money, Quantity
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


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
                    "CREATE TABLE IF NOT EXISTS ledger_accounts (account_id TEXT PRIMARY KEY, opening_cash TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'INR');",
                    """CREATE TABLE IF NOT EXISTS ledger_commands (
                    account_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, resulting_version INTEGER NOT NULL,
                    payload_checksum TEXT NOT NULL DEFAULT '', command_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(account_id, idempotency_key)
                );""",
                    """CREATE TABLE IF NOT EXISTS ledger_events (
                    event_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, version INTEGER NOT NULL,
                    event_json TEXT NOT NULL, event_type TEXT NOT NULL DEFAULT 'FILL_RECORDED',
                    occurred_at TEXT NOT NULL DEFAULT '', UNIQUE(account_id, version)
                );""",
                    "CREATE INDEX IF NOT EXISTS ledger_events_account_type ON ledger_events(account_id, event_type, version)",
                    """CREATE TABLE IF NOT EXISTS ledger_valuation_snapshots (
                        account_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
                        as_of_date TEXT NOT NULL, payload_json TEXT NOT NULL,
                        checksum_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
                        PRIMARY KEY(account_id, snapshot_id))""",
                    "CREATE INDEX IF NOT EXISTS ledger_valuation_dates ON ledger_valuation_snapshots(account_id, as_of_date)",
                ),
                2: (
                    """CREATE TABLE IF NOT EXISTS tradebook_uploads (
                        account_id TEXT NOT NULL, upload_id TEXT NOT NULL,
                        parsed_json TEXT NOT NULL, created_at TEXT NOT NULL,
                        PRIMARY KEY(account_id,upload_id))""",
                ),
                3: (
                    "ALTER TABLE ledger_accounts ADD COLUMN opening_date TEXT",
                    "UPDATE ledger_accounts SET opening_date=COALESCE((SELECT MIN(substr(occurred_at,1,10)) FROM ledger_events e WHERE e.account_id=ledger_accounts.account_id), date('now'))",
                ),
                4: (
                    "ALTER TABLE ledger_accounts ADD COLUMN display_name TEXT",
                    "ALTER TABLE ledger_accounts ADD COLUMN details_version INTEGER NOT NULL DEFAULT 0",
                    "UPDATE ledger_accounts SET display_name=account_id",
                ),
            },
        )

    def open_account(
        self, account_id: str, opening_cash: Money, opening_date: date | None = None
    ) -> None:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        opening_date = opening_date or today
        if opening_date > today:
            raise DomainValidationError("opening date cannot be in the future")
        if not account_id.strip() or opening_cash.amount < 0:
            raise DomainValidationError("account is invalid")
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO ledger_accounts(account_id, opening_cash, currency, opening_date) VALUES (?, ?, ?, ?)",
                    (
                        account_id,
                        str(opening_cash.amount),
                        opening_cash.currency,
                        opening_date.isoformat(),
                    ),
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
                """SELECT event_json, event_type FROM ledger_events WHERE account_id = ?
                   AND event_type IN ('FILL_RECORDED', 'OPENING_POSITION_IMPORTED', 'IMPORTED_POSITION_FUNDED', 'OPEN_LOTS_RECONCILED', 'STOCK_SPLIT_APPLIED') ORDER BY version""",
                (account_id,),
            ).fetchall()
            previous_fills = tuple(
                self._parse_accounting_event(json.loads(row["event_json"]), row["event_type"])
                for row in previous_rows
            )

            existing_trade_ids = {
                f.broker_trade_id for f in previous_fills if getattr(f, "broker_trade_id", None)
            }
            for f in fills:
                if f.broker_trade_id and f.broker_trade_id in existing_trade_ids:
                    raise DomainValidationError(f"duplicate broker trade ID {f.broker_trade_id}")

            # Validate against the complete position/cash history *inside*
            # the same write transaction. A malformed transaction must
            # never be committed and corrupt the account projection.
            transfers = sum(
                (
                    Decimal(json.loads(row[0])["amount"])
                    * (1 if json.loads(row[0])["direction"] == "DEPOSIT" else -1)
                    for row in connection.execute(
                        "SELECT event_json FROM ledger_events WHERE account_id=? AND event_type='CASH_TRANSFER'",
                        (account_id,),
                    )
                ),
                Decimal(0),
            )
            project(
                Money(Decimal(account["opening_cash"]) + transfers, account["currency"]),
                previous_fills + fills,
            )
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

    def import_opening_positions(
        self,
        account_id: str,
        idempotency_key: str,
        expected_version: int,
        positions: Iterable[OpeningPosition],
        *,
        transaction_connection=None,
    ) -> int:
        positions = tuple(positions)
        if not positions or expected_version < 0 or not idempotency_key:
            raise DomainValidationError("ledger command is incomplete")
        command = {
            "type": "IMPORT_OPENING_POSITIONS",
            "account_id": account_id,
            "expected_version": expected_version,
            "positions": [self._opening_position_event(p) for p in positions],
        }
        command_json = json.dumps(command, sort_keys=True, separators=(",", ":"))
        import hashlib

        checksum = hashlib.sha256(command_json.encode("utf-8")).hexdigest()
        with (
            nullcontext(transaction_connection)
            if transaction_connection is not None
            else self._connect()
        ) as connection:
            if not connection.in_transaction:
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
                "SELECT event_json, event_type FROM ledger_events WHERE account_id = ? AND event_type IN ('FILL_RECORDED', 'OPENING_POSITION_IMPORTED', 'IMPORTED_POSITION_FUNDED', 'OPEN_LOTS_RECONCILED', 'STOCK_SPLIT_APPLIED') ORDER BY version",
                (account_id,),
            ).fetchall()
            previous_events = tuple(
                self._parse_accounting_event(json.loads(row["event_json"]), row["event_type"])
                for row in previous_rows
            )

            # Validate
            project(
                Money(account["opening_cash"], account["currency"]), previous_events + positions
            )
            version = current
            for p in positions:
                if p.unit_cost.currency != account["currency"]:
                    raise DomainValidationError("position currency does not match account currency")
                version += 1
                event = self._opening_position_event(p)
                connection.execute(
                    "INSERT INTO ledger_events(account_id, version, event_json, event_type, occurred_at) VALUES (?, ?, ?, 'OPENING_POSITION_IMPORTED', ?)",
                    (
                        account_id,
                        version,
                        json.dumps(event, sort_keys=True),
                        p.imported_at.isoformat(),
                    ),
                )
            connection.execute(
                "INSERT INTO ledger_commands(account_id, idempotency_key, resulting_version, payload_checksum, command_json) VALUES (?, ?, ?, ?, ?)",
                (account_id, idempotency_key, version, checksum, command_json),
            )
            return version

    def fund_broker_imports(
        self, account_id: str, broker_account_id: str, *, transaction_connection=None
    ) -> dict[str, object]:
        """Debit acquisition cost once per imported broker position, including legacy imports."""
        with (
            nullcontext(transaction_connection)
            if transaction_connection is not None
            else self._connect()
        ) as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            if not connection.execute(
                "SELECT 1 FROM ledger_accounts WHERE account_id=?", (account_id,)
            ).fetchone():
                raise DomainValidationError("account does not exist")
            rows = connection.execute(
                "SELECT version,event_type,event_json FROM ledger_events WHERE account_id=? ORDER BY version",
                (account_id,),
            ).fetchall()
            funded = set()
            for row in rows:
                if row["event_type"] == "IMPORTED_POSITION_FUNDED":
                    funded.update(json.loads(row["event_json"])["import_versions"])
            versions, cost = [], Decimal(0)
            for row in rows:
                if row["event_type"] != "OPENING_POSITION_IMPORTED" or row["version"] in funded:
                    continue
                event = json.loads(row["event_json"])
                try:
                    provenance = json.loads(event["broker_provenance"])
                except (ValueError, TypeError):
                    continue
                if (
                    not isinstance(provenance, dict)
                    or provenance.get("source") != "kite-opening-balance"
                    or provenance.get("broker_account_id") != broker_account_id
                ):
                    continue
                versions.append(row["version"])
                cost += Decimal(event["unit_cost"]) * int(event["units"])
            version = rows[-1]["version"] if rows else 0
            if not versions:
                return {"version": version, "cash_deducted": "0"}
            at = datetime.now(UTC).isoformat()
            event = {
                "amount": str(cost),
                "currency": "INR",
                "funded_at": at,
                "broker_account_id": broker_account_id,
                "import_versions": versions,
            }
            version += 1
            connection.execute(
                "INSERT INTO ledger_events(account_id,version,event_json,event_type,occurred_at) VALUES (?,?,?,'IMPORTED_POSITION_FUNDED',?)",
                (account_id, version, json.dumps(event, sort_keys=True), at),
            )
            command = json.dumps(
                {"type": "FUND_BROKER_IMPORTS", "account_id": account_id, **event}, sort_keys=True
            )
            connection.execute(
                "INSERT INTO ledger_commands(account_id,idempotency_key,resulting_version,payload_checksum,command_json) VALUES (?,?,?,?,?)",
                (
                    account_id,
                    "kite-import-funding:" + ",".join(map(str, versions)),
                    version,
                    hashlib.sha256(command.encode()).hexdigest(),
                    command,
                ),
            )
            return {"version": version, "cash_deducted": str(cost)}

    def reconcile_open_lots(
        self, account_id: str, upload_id: str, expected_version: int, positions: list[dict]
    ) -> dict:
        """Replace matching open balances with dated lots without replaying closed trades."""
        if not positions or len({row["instrument_id"] for row in positions}) != len(positions):
            raise DomainValidationError("select unique open holdings to reconcile")
        ids = sorted(row["instrument_id"] for row in positions)
        key = (
            "tradebook-open:"
            + upload_id
            + ":"
            + hashlib.sha256(json.dumps(ids).encode()).hexdigest()
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT command_json FROM ledger_commands WHERE account_id=? AND idempotency_key=?",
                (account_id, key),
            ).fetchone()
            if existing:
                return json.loads(existing[0])["result"]
            current = connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM ledger_events WHERE account_id=?",
                (account_id,),
            ).fetchone()[0]
            if current != expected_version:
                raise DomainValidationError(
                    "portfolio changed; upload or preview the tradebook again"
                )
            projection = self.projection(account_id)
            at = datetime.now(UTC).isoformat()
            cash_delta, lot_count = Decimal(0), 0
            for row in positions:
                instrument_id = row["instrument_id"]
                previous = [
                    lot for lot in projection.open_lots if lot.instrument_id == instrument_id
                ]
                new_lots = row["lots"]
                if sum(lot.remaining_units.units for lot in previous) != sum(
                    lot["units"] for lot in new_lots
                ):
                    raise DomainValidationError(
                        "tradebook open quantity must match the selected portfolio holding"
                    )
                old_cost = sum(
                    (lot.unit_cost.amount * lot.remaining_units.units for lot in previous),
                    Decimal(0),
                )
                new_cost = sum(
                    (Decimal(lot["unit_cost"]) * lot["units"] for lot in new_lots), Decimal(0)
                )
                delta = old_cost - new_cost
                event = {
                    "instrument_id": instrument_id,
                    "lots": new_lots,
                    "cash_delta": str(delta),
                    "currency": "INR",
                    "reconciled_at": at,
                    "upload_id": upload_id,
                }
                self._parse_accounting_event(event, "OPEN_LOTS_RECONCILED")
                current += 1
                connection.execute(
                    "INSERT INTO ledger_events(account_id,version,event_json,event_type,occurred_at) VALUES (?,?,?,'OPEN_LOTS_RECONCILED',?)",
                    (account_id, current, json.dumps(event, sort_keys=True), at),
                )
                cash_delta += delta
                lot_count += len(new_lots)
            result = {
                "account_id": account_id,
                "version": current,
                "updated_holdings": len(positions),
                "open_lots": lot_count,
                "cash_adjustment": str(cash_delta),
                "closed_trades_imported": 0,
            }
            command = json.dumps(
                {
                    "type": "RECONCILE_OPEN_LOTS",
                    "upload_id": upload_id,
                    "positions": positions,
                    "result": result,
                },
                sort_keys=True,
            )
            connection.execute(
                "INSERT INTO ledger_commands(account_id,idempotency_key,resulting_version,payload_checksum,command_json) VALUES (?,?,?,?,?)",
                (account_id, key, current, hashlib.sha256(command.encode()).hexdigest(), command),
            )
            return result

    def record_cash_transfer(
        self,
        account_id: str,
        idempotency_key: str,
        expected_version: int,
        direction: str,
        amount: Money,
        occurred_at: datetime | None = None,
        reason: str | None = None,
    ) -> int:
        """Append an idempotent deposit or withdrawal without mutating history."""
        if direction not in {"DEPOSIT", "WITHDRAW"} or amount.amount <= 0:
            raise DomainValidationError("cash transfer is invalid")
        if not isinstance(reason, str) or not reason.strip():
            raise DomainValidationError("cash transfer reason is required")
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
            "reason": reason.strip(),
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
                    raise DomainValidationError(
                        "idempotency key was reused with a different ledger command"
                    )
                return existing["resulting_version"]
            account = connection.execute(
                "SELECT opening_cash, currency FROM ledger_accounts WHERE account_id=?",
                (account_id,),
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
                "reason": reason.strip(),
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
                "SELECT event_json, event_type FROM ledger_events WHERE account_id = ? AND event_type IN ('FILL_RECORDED', 'OPENING_POSITION_IMPORTED', 'IMPORTED_POSITION_FUNDED', 'OPEN_LOTS_RECONCILED', 'STOCK_SPLIT_APPLIED') AND (? IS NULL OR occurred_at <= ?) ORDER BY version",
                (account_id, cutoff, cutoff),
            ).fetchall()
            transfers = connection.execute(
                "SELECT event_json FROM ledger_events WHERE account_id=? AND event_type='CASH_TRANSFER' AND (? IS NULL OR occurred_at <= ?) ORDER BY version",
                (account_id, cutoff, cutoff),
            ).fetchall()
        events_parsed = tuple(
            self._parse_accounting_event(json.loads(row["event_json"]), row["event_type"])
            for row in rows
        )
        transfer_total = sum(
            (
                Decimal(str(json.loads(row["event_json"])["amount"]))
                * (1 if json.loads(row["event_json"])["direction"] == "DEPOSIT" else -1)
                for row in transfers
            ),
            Decimal(0),
        )
        return project(
            Money(Decimal(account["opening_cash"]) + transfer_total, account["currency"]),
            events_parsed,
        )

    def journal(
        self, account_id: str, *, long_term_days: int = 365, as_of: date | None = None
    ) -> list[dict[str, object]]:
        """Return an immutable FIFO trade journal derived from ledger events."""
        if (
            isinstance(long_term_days, bool)
            or not isinstance(long_term_days, int)
            or not 1 <= long_term_days <= 3650
        ):
            raise DomainValidationError("long_term_days must be between 1 and 3650")
        events = self.events(account_id)
        lots: dict[str, list[dict[str, object]]] = {}
        journal: list[dict[str, object]] = []
        for event in events:
            if as_of is not None and event["occurred_at"][:10] > as_of.isoformat():
                continue
            if event["event_type"] == "STOCK_SPLIT_APPLIED":
                row = event["event"]
                factor = Decimal(row["numerator"]) / Decimal(row["denominator"])
                if row.get("action_type") == "BONUS":
                    previous = lots.setdefault(row["instrument_id"], [])
                    additional = sum(lot["units"] for lot in previous) * (row["numerator"] - row["denominator"]) // row["denominator"]
                    if additional:
                        previous.append({"units": int(additional), "price": Decimal(0), "gross_price": Decimal(0),
                                         "date": datetime.fromisoformat(row["effective_at"]).date()})
                    continue
                for lot in lots.get(row["instrument_id"], []):
                    lot["units"] = lot["units"] * row["numerator"] // row["denominator"]
                    lot["price"] /= factor
                    lot["gross_price"] /= factor
                continue
            if event["event_type"] == "OPEN_LOTS_RECONCILED":
                row = event["event"]
                lots[row["instrument_id"]] = [
                    {
                        "units": lot["units"],
                        "price": Decimal(lot["unit_cost"]),
                        "gross_price": Decimal(lot["unit_cost"]),
                        "date": date.fromisoformat(lot["date"]),
                    }
                    for lot in row["lots"]
                ]
                continue
            if event["event_type"] == "OPENING_POSITION_IMPORTED":
                pos = event["event"]
                units = int(str(pos["units"]))
                price = Decimal(str(pos["unit_cost"]))
                lots.setdefault(str(pos["instrument_id"]), []).append(
                    {
                        "units": units,
                        "price": price,
                        "gross_price": price,
                        "date": date.fromisoformat(str(pos["acquisition_date"])),
                    }
                )
                continue
            if event["event_type"] != "FILL_RECORDED":
                continue
            fill = event["event"]
            units = int(str(fill["units"]))
            price = Decimal(str(fill["price"]))
            if fill["side"] == "BUY":
                lots.setdefault(str(fill["instrument_id"]), []).append(
                    {
                        "units": units,
                        "price": price + Decimal(str(fill.get("fee", "0"))) / units,
                        "gross_price": price,
                        "date": date.fromisoformat(str(fill["fill_date"])),
                    }
                )
                continue
            remaining = units
            for lot in lots.get(str(fill["instrument_id"]), []):
                matched = min(remaining, int(lot["units"]))
                if matched < 1:
                    continue
                sell_fee = Decimal(str(fill.get("fee", "0"))) * Decimal(matched) / Decimal(units)
                holding_days = (date.fromisoformat(str(fill["fill_date"])) - lot["date"]).days
                journal.append(
                    {
                        "instrument_id": fill["instrument_id"],
                        "buy_date": lot["date"].isoformat(),
                        "sell_date": fill["fill_date"],
                        "units": matched,
                        "buy_price": str(lot["price"]),
                        "buy_gross_price": str(lot["gross_price"]),
                        "sell_price": str(price),
                        "realised_pnl": str((price - lot["price"]) * matched - sell_fee),
                        "holding_days": holding_days,
                        "tax_holding_period": "LONG_TERM"
                        if holding_days >= long_term_days
                        else "SHORT_TERM",
                        "hold_recommendation": "LTCG_THRESHOLD_REACHED"
                        if holding_days >= long_term_days
                        else "CONSIDER_HOLDING_TO_LTCG_THRESHOLD",
                    }
                )
                lot["units"] = int(lot["units"]) - matched
                remaining -= matched
                if remaining == 0:
                    break
        return journal

    def save_valuation(
        self, account_id: str, snapshot_id: str, as_of_date: date, payload: dict[str, object]
    ) -> dict[str, object]:
        if not snapshot_id.strip():
            raise DomainValidationError("valuation snapshot id is required")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        checksum = hashlib.sha256(encoded.encode()).hexdigest()
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if (
                connection.execute(
                    "SELECT 1 FROM ledger_accounts WHERE account_id=?", (account_id,)
                ).fetchone()
                is None
            ):
                raise DomainValidationError("account does not exist")
            existing = connection.execute(
                "SELECT checksum_sha256, payload_json, as_of_date FROM ledger_valuation_snapshots WHERE account_id=? AND snapshot_id=?",
                (account_id, snapshot_id),
            ).fetchone()
            if existing is not None:
                if existing["checksum_sha256"] != checksum:
                    raise DomainValidationError(
                        "valuation snapshot id conflicts with existing payload"
                    )
                return {
                    "account_id": account_id,
                    "snapshot_id": snapshot_id,
                    "as_of_date": existing["as_of_date"],
                    "payload": json.loads(existing["payload_json"]),
                    "checksum_sha256": checksum,
                }
            connection.execute(
                "INSERT INTO ledger_valuation_snapshots(account_id, snapshot_id, as_of_date, payload_json, checksum_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (account_id, snapshot_id, as_of_date.isoformat(), encoded, checksum, created_at),
            )
        return {
            "account_id": account_id,
            "snapshot_id": snapshot_id,
            "as_of_date": as_of_date.isoformat(),
            "payload": payload,
            "checksum_sha256": checksum,
        }

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
                if (
                    connection.execute(
                        "SELECT 1 FROM ledger_accounts WHERE account_id=?", (account_id,)
                    ).fetchone()
                    is None
                ):
                    raise DomainValidationError("account does not exist")
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def update_account_details(
        self,
        account_id,
        *,
        display_name,
        opening_date,
        opening_cash,
        expected_version,
        expected_details_version,
    ):
        if not isinstance(display_name, str) or not display_name.strip():
            raise DomainValidationError("account name is required")
        if opening_date > datetime.now(ZoneInfo("Asia/Kolkata")).date() or opening_cash.amount < 0:
            raise DomainValidationError("opening date or initial balance is invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM ledger_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError("account not found")
            version = connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM ledger_events WHERE account_id=?",
                (account_id,),
            ).fetchone()[0]
            if version != expected_version or row["details_version"] != expected_details_version:
                raise DomainValidationError("account changed; reload before saving")
            earliest = connection.execute(
                "SELECT MIN(substr(occurred_at,1,10)) FROM ledger_events WHERE account_id=? AND occurred_at!=''",
                (account_id,),
            ).fetchone()[0]
            if earliest and opening_date.isoformat() > earliest:
                raise DomainValidationError(
                    "opening date cannot be after the earliest recorded transaction"
                )
            has_orders = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='broker_orders'"
            ).fetchone()
            if (
                has_orders
                and connection.execute(
                    "SELECT 1 FROM broker_orders WHERE account_id=? AND status NOT IN ('FILLED','CANCELLED','REJECTED') LIMIT 1",
                    (account_id,),
                ).fetchone()
            ):
                raise DomainValidationError(
                    "finish or cancel outstanding broker orders before changing account details"
                )
            connection.execute(
                "UPDATE ledger_accounts SET display_name=?,opening_date=?,opening_cash=?,details_version=details_version+1 WHERE account_id=?",
                (
                    display_name.strip(),
                    opening_date.isoformat(),
                    str(opening_cash.amount),
                    account_id,
                ),
            )

    def accounts(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT a.account_id, a.opening_cash, a.currency, a.opening_date,
                   COALESCE(a.display_name,a.account_id) AS display_name, a.details_version,
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
                   WHERE account_id=? AND version>? ORDER BY version""",
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
            "broker_trade_id": fill.broker_trade_id,
            "historical_import": fill.historical_import,
        }

    @staticmethod
    def _opening_position_event(p: OpeningPosition) -> dict[str, object]:
        return {
            "instrument_id": p.instrument_id,
            "acquisition_date": p.acquisition_date.isoformat(),
            "units": p.units.units,
            "unit_cost": str(p.unit_cost.amount),
            "currency": p.unit_cost.currency,
            "imported_at": p.imported_at.isoformat(),
            "broker_provenance": p.broker_provenance,
        }

    @staticmethod
    def _parse_accounting_event(event: dict[str, object], event_type: str) -> AccountingEvent:
        if event_type == "STOCK_SPLIT_APPLIED":
            return StockSplit(
                str(event["instrument_id"]),
                datetime.fromisoformat(str(event["effective_at"])),
                int(event["numerator"]),
                int(event["denominator"]),
                str(event["source_url"]),
                action_type=str(event.get("action_type", "SPLIT")),
            )
        if event_type == "OPEN_LOTS_RECONCILED":
            instrument_id = str(event["instrument_id"])
            lots = tuple(
                Lot(
                    instrument_id,
                    date.fromisoformat(row["date"]),
                    Quantity(row["units"]),
                    Money(Decimal(row["unit_cost"]), str(event["currency"])),
                )
                for row in event["lots"]
            )
            if not lots or any(lot.unit_cost.amount < 0 for lot in lots):
                raise DomainValidationError("tradebook open lot is invalid")
            return OpenLotReconciliation(
                instrument_id,
                lots,
                Money(Decimal(str(event["cash_delta"])), str(event["currency"])),
                datetime.fromisoformat(str(event["reconciled_at"])),
            )
        if event_type == "IMPORTED_POSITION_FUNDED":
            return ImportedPositionFunding(
                Money(Decimal(str(event["amount"])), str(event["currency"])),
                datetime.fromisoformat(str(event["funded_at"])),
            )
        if event_type == "FILL_RECORDED":
            return Ledger._event_fill(event)
        elif event_type == "OPENING_POSITION_IMPORTED":
            currency = str(event.get("currency", "INR"))
            return OpeningPosition(
                str(event["instrument_id"]),
                date.fromisoformat(str(event["acquisition_date"])),
                Quantity(int(str(event["units"]))),
                Money(Decimal(str(event["unit_cost"])), currency),
                datetime.fromisoformat(str(event["imported_at"])),
                str(event["broker_provenance"]),
            )
        raise ValueError(f"Unknown event type {event_type}")

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
            str(event["broker_trade_id"]) if event.get("broker_trade_id") else None,
            bool(event.get("historical_import", False)),
        )

    @staticmethod
    def _execution_time(fill: Fill) -> datetime:
        if fill.executed_at is None:
            raise DomainValidationError("fill execution timestamp is required")
        return fill.executed_at

    @staticmethod
    def _cash_balance(connection, account_id: str, account) -> Decimal:
        rows = connection.execute(
            "SELECT event_json, event_type FROM ledger_events WHERE account_id=? ORDER BY version",
            (account_id,),
        ).fetchall()
        balance = Decimal(str(account["opening_cash"]))
        for row in rows:
            event = json.loads(row["event_json"])
            if row["event_type"] == "CASH_TRANSFER":
                balance += Decimal(str(event["amount"])) * (
                    1 if event["direction"] == "DEPOSIT" else -1
                )
            elif row["event_type"] == "IMPORTED_POSITION_FUNDED":
                balance -= Decimal(str(event["amount"]))
            elif row["event_type"] == "OPEN_LOTS_RECONCILED":
                balance += Decimal(str(event["cash_delta"]))
            elif row["event_type"] == "FILL_RECORDED":
                value = Decimal(str(event["price"])) * Decimal(str(event["units"]))
                fee = Decimal(str(event.get("fee", "0")))
                balance += value - fee if event["side"] == "SELL" else -(value + fee)
        return balance
