"""Explicit, account-scoped day-zero import and reconciliation commands.

Broker transport is deliberately outside this service: callers supply the
normalized holdings/trades obtained through the selected broker session.  This
keeps reconciliation auditable and prevents a default-account fallback.
"""

from __future__ import annotations

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
    def __init__(self, database: str | Path, accounts: KiteAccounts, ledger: Ledger) -> None:
        self.database, self.accounts, self.ledger = str(database), accounts, ledger
        migrate_sqlite(self.database, "portfolio_sync", {1: (
            """CREATE TABLE IF NOT EXISTS portfolio_setups (
                broker_account_id TEXT NOT NULL, strategy_id TEXT NOT NULL,
                completed_at TEXT NOT NULL, PRIMARY KEY(broker_account_id, strategy_id))""",
            """CREATE TABLE IF NOT EXISTS reconciliation_discrepancies (
                discrepancy_id INTEGER PRIMARY KEY, broker_account_id TEXT NOT NULL,
                strategy_id TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, reviewed_at TEXT)""",
        )})

    def setup(self, payload: dict[str, Any]) -> dict[str, object]:
        required = {"broker_account_id", "strategy_id", "opening_cash", "positions", "idempotency_key"}
        if not isinstance(payload, dict) or set(payload) != required or not isinstance(payload["positions"], list):
            raise DomainValidationError("portfolio setup payload is invalid")
        broker_id, strategy_id = str(payload["broker_account_id"]), str(payload["strategy_id"])
        ledger_id = self.accounts.get_portfolio(broker_id, strategy_id)
        try:
            cash = Money(Decimal(str(payload["opening_cash"])))
        except Exception as exc:
            raise DomainValidationError("opening_cash is invalid") from exc
        if cash.amount < 0:
            raise DomainValidationError("opening_cash must be non-negative")
        try:
            self.ledger.open_account(ledger_id, cash)
        except DomainValidationError as exc:
            if "already exists" not in str(exc):
                raise
        positions: list[OpeningPosition] = []
        for row in payload["positions"]:
            if not isinstance(row, dict) or set(row) != {"instrument_id", "units", "unit_cost", "acquisition_date", "provenance"}:
                raise DomainValidationError("opening position is invalid")
            positions.append(OpeningPosition(
                str(row["instrument_id"]), date.fromisoformat(str(row["acquisition_date"])),
                Quantity(int(row["units"])), Money(Decimal(str(row["unit_cost"]))),
                datetime.now(UTC), str(row["provenance"]),
            ))
        version = next(item["version"] for item in self.ledger.accounts() if item["account_id"] == ledger_id)
        if positions:
            version = self.ledger.import_opening_positions(ledger_id, str(payload["idempotency_key"]), int(version), positions)
        with sqlite_connection(self.database) as connection:
            connection.execute("INSERT OR IGNORE INTO portfolio_setups VALUES (?, ?, ?)", (broker_id, strategy_id, datetime.now(UTC).isoformat()))
        return {"broker_account_id": broker_id, "strategy_id": strategy_id, "ledger_account_id": ledger_id, "version": version, "imported_positions": len(positions)}

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
