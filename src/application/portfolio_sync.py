"""Explicit, account-scoped day-zero import and reconciliation commands.

Broker transport is deliberately outside this service: callers supply the
normalized holdings/trades obtained through the selected broker session.  This
keeps reconciliation auditable and prevents a default-account fallback.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.execution_gateway.kite_accounts import KiteAccounts
from src.execution_gateway.ledger import Ledger
from src.platform_kernel import DomainValidationError, Money, Quantity
from src.portfolio_accounting import Fill, FillSide, OpeningPosition


class PortfolioSync:
    def __init__(self, database: str | Path, accounts: KiteAccounts, ledger: Ledger, market=None) -> None:
        self.database, self.accounts, self.ledger = str(database), accounts, ledger
        self.market = market
        migrate_sqlite(self.database, "portfolio_sync", {1: (
            """CREATE TABLE IF NOT EXISTS portfolio_setups (
                broker_account_id TEXT NOT NULL, strategy_id TEXT NOT NULL,
                completed_at TEXT NOT NULL, PRIMARY KEY(broker_account_id, strategy_id))""",
            """CREATE TABLE IF NOT EXISTS reconciliation_discrepancies (
                discrepancy_id INTEGER PRIMARY KEY, broker_account_id TEXT NOT NULL,
                strategy_id TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, reviewed_at TEXT)""",
        ), 2: (
            "ALTER TABLE portfolio_setups ADD COLUMN command_checksum TEXT",
            "ALTER TABLE portfolio_setups ADD COLUMN result_json TEXT",
        )})

    def setup(self, payload: dict[str, Any]) -> dict[str, object]:
        required = {"broker_account_id", "strategy_id", "opening_cash", "positions", "idempotency_key"}
        if not isinstance(payload, dict) or set(payload) != required or not isinstance(payload["positions"], list):
            raise DomainValidationError("portfolio setup payload is invalid")
        broker_id, strategy_id = str(payload["broker_account_id"]), str(payload["strategy_id"])
        from src.application.strategy_runtime import RETAINED_STRATEGIES
        if strategy_id not in RETAINED_STRATEGIES or not isinstance(payload["idempotency_key"], str) or not payload["idempotency_key"].strip():
            raise DomainValidationError("setup strategy or idempotency key is invalid")
        self.accounts.get_credentials(broker_id)
        checksum = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            existing = connection.execute("SELECT * FROM portfolio_setups WHERE broker_account_id=? AND strategy_id=?", (broker_id, strategy_id)).fetchone()
        if existing:
            if existing["command_checksum"] == checksum and existing["result_json"]:
                return json.loads(existing["result_json"])
            raise DomainValidationError("day-zero setup is already complete; use reconciliation")
        try:
            cash = Money(Decimal(str(payload["opening_cash"])))
        except Exception as exc:
            raise DomainValidationError("opening_cash is invalid") from exc
        if cash.amount < 0:
            raise DomainValidationError("opening_cash must be non-negative")
        positions: list[OpeningPosition] = []
        imported_at = datetime.now(UTC)
        selected = set()
        broker_holdings = {}
        if payload["positions"]:
            if self.market is None:
                raise DomainValidationError("broker holding resolution is unavailable")
            self.accounts.validate(broker_id)
            try:
                broker_holdings = {str(row["isin"]): row for row in self.accounts.client(broker_id).holdings()}
            except Exception as exc:
                raise DomainValidationError("broker holdings verification failed") from exc
        for row in payload["positions"]:
            if not isinstance(row, dict) or set(row) != {"instrument_id", "units", "unit_cost", "acquisition_date", "provenance"}:
                raise DomainValidationError("opening position is invalid")
            if isinstance(row["units"], bool) or not isinstance(row["units"], int) or row["units"] < 1 or row["instrument_id"] in selected:
                raise DomainValidationError("opening quantity must be positive, integral and unique")
            selected.add(row["instrument_id"])
            identity = self.market.instrument_by_id(str(row["instrument_id"]))
            holding = broker_holdings.get(str(identity["isin"])) if identity else None
            if not holding or int(holding["quantity"]) != row["units"]:
                raise DomainValidationError("import must use the entire selected broker holding quantity")
            acquired = date.fromisoformat(str(row["acquisition_date"]))
            if acquired > imported_at.date() or not str(row["provenance"]).strip():
                raise DomainValidationError("opening acquisition date or provenance is invalid")
            positions.append(OpeningPosition(
                str(row["instrument_id"]), date.fromisoformat(str(row["acquisition_date"])),
                Quantity(int(row["units"])), Money(Decimal(str(row["unit_cost"]))),
                imported_at, str(row["provenance"]),
            ))
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM portfolio_setups WHERE broker_account_id=? AND strategy_id=?", (broker_id, strategy_id)).fetchone():
                raise DomainValidationError("day-zero setup was completed concurrently; reload setup status")
            binding = connection.execute("SELECT ledger_account_id FROM strategy_portfolios WHERE broker_account_id=? AND strategy_id=?", (broker_id, strategy_id)).fetchone()
            ledger_id = binding[0] if binding else f"{broker_id}:{strategy_id}"
            connection.execute("INSERT OR IGNORE INTO ledger_accounts(account_id,opening_cash,currency) VALUES (?,?,?)", (ledger_id, str(cash.amount), cash.currency))
            account = connection.execute("SELECT opening_cash FROM ledger_accounts WHERE account_id=?", (ledger_id,)).fetchone()
            if Decimal(account[0]) != cash.amount:
                raise DomainValidationError("existing ledger opening cash differs from setup")
            connection.execute("INSERT OR IGNORE INTO strategy_portfolios VALUES (?,?,?,?)", (broker_id, strategy_id, ledger_id, imported_at.isoformat()))
            version = connection.execute("SELECT COALESCE(MAX(version),0) FROM ledger_events WHERE account_id=?", (ledger_id,)).fetchone()[0]
            if version:
                raise DomainValidationError("day-zero setup requires an unused ledger")
            if positions:
                version = self.ledger.import_opening_positions(ledger_id, payload["idempotency_key"], version, positions, transaction_connection=connection)
            result = {"broker_account_id": broker_id, "strategy_id": strategy_id, "ledger_account_id": ledger_id, "version": version, "imported_positions": len(positions)}
            connection.execute("INSERT INTO portfolio_setups(broker_account_id,strategy_id,completed_at,command_checksum,result_json) VALUES (?,?,?,?,?)", (broker_id, strategy_id, imported_at.isoformat(), checksum, json.dumps(result)))
            return result

    def reconcile(self, payload: dict[str, Any]) -> dict[str, object]:
        required = {"broker_account_id", "strategy_id", "trades", "idempotency_key"}
        if not isinstance(payload, dict) or set(payload) != required or not isinstance(payload["trades"], list):
            raise DomainValidationError("portfolio reconciliation payload is invalid")
        ledger_id = self.accounts.get_portfolio(str(payload["broker_account_id"]), str(payload["strategy_id"]))
        version = next(item["version"] for item in self.ledger.accounts() if item["account_id"] == ledger_id)
        fills: list[Fill] = []
        for row in payload["trades"]:
            if not isinstance(row, dict) or set(row) != {"trade_id", "instrument_id", "side", "units", "price", "executed_at"}:
                raise DomainValidationError("reconciliation trade is invalid")
            at = datetime.fromisoformat(str(row["executed_at"]))
            if at.tzinfo is None:
                raise DomainValidationError("reconciliation trade timestamp must be timezone-aware")
            fills.append(Fill(str(row["instrument_id"]), at.date(), FillSide(str(row["side"])), Quantity(int(row["units"])), Money(Decimal(str(row["price"]))), executed_at=at, broker_trade_id=str(row["trade_id"])))
        if not fills:
            return {"ledger_account_id": ledger_id, "version": version, "posted_fills": 0}
        version = self.ledger.record_fills(ledger_id, str(payload["idempotency_key"]), int(version), fills)
        return {"ledger_account_id": ledger_id, "version": version, "posted_fills": len(fills)}
