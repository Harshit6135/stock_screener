"""Phase 5: Broker Accounts and Strategy Linkage."""

import json
from datetime import UTC, datetime
from typing import Optional

from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError

class KiteAccounts:
    """Manages Kite API credentials and account mapping."""

    def __init__(self, database_path: str):
        self.database = database_path
        self._initialize()

    def _initialize(self) -> None:
        migrate_sqlite(
            self.database,
            "kite_accounts",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS kite_accounts (
                        broker_account_id TEXT PRIMARY KEY,
                        account_name TEXT NOT NULL,
                        api_key TEXT NOT NULL,
                        api_secret TEXT NOT NULL,
                        access_token TEXT,
                        broker_user_id TEXT,
                        created_at TEXT NOT NULL,
                        validated_at TEXT
                    )""",
                    """CREATE TABLE IF NOT EXISTS strategy_portfolios (
                        broker_account_id TEXT NOT NULL,
                        strategy_id TEXT NOT NULL,
                        ledger_account_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY(broker_account_id, strategy_id),
                        FOREIGN KEY(broker_account_id) REFERENCES kite_accounts(broker_account_id)
                    )""",
                    """CREATE UNIQUE INDEX IF NOT EXISTS strategy_portfolios_ledger 
                       ON strategy_portfolios(ledger_account_id)"""
                )
            }
        )

    def register_account(self, broker_account_id: str, account_name: str, api_key: str, api_secret: str) -> None:
        if not broker_account_id or not account_name or not api_key or not api_secret:
            raise DomainValidationError("all account fields are required")
        
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR REPLACE INTO kite_accounts 
                   (broker_account_id, account_name, api_key, api_secret, created_at) 
                   VALUES (?, ?, ?, ?, ?)""",
                (broker_account_id, account_name, api_key, api_secret, now)
            )

    def list_accounts(self) -> list[dict[str, str]]:
        """Returns account summaries (no secrets)."""
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT broker_account_id, account_name, broker_user_id, created_at, validated_at FROM kite_accounts"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_credentials(self, broker_account_id: str) -> dict[str, str]:
        """Returns internal credentials for API usage."""
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT api_key, api_secret, access_token, broker_user_id FROM kite_accounts WHERE broker_account_id=?",
                (broker_account_id,)
            ).fetchone()
            if not row:
                raise DomainValidationError("broker account not found")
            return dict(row)

    def update_session(self, broker_account_id: str, access_token: str, broker_user_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE kite_accounts SET access_token=?, broker_user_id=?, validated_at=? WHERE broker_account_id=?",
                (access_token, broker_user_id, now, broker_account_id)
            )

    def link_portfolio(self, broker_account_id: str, strategy_id: str, ledger_account_id: str) -> None:
        from src.application.strategy_runtime import RETAINED_STRATEGIES
        if strategy_id not in RETAINED_STRATEGIES:
            raise DomainValidationError(f"invalid strategy_id: {strategy_id}")
            
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute(
                """INSERT INTO strategy_portfolios (broker_account_id, strategy_id, ledger_account_id, created_at)
                   VALUES (?, ?, ?, ?)""",
                (broker_account_id, strategy_id, ledger_account_id, now)
            )

    def get_portfolio(self, broker_account_id: str, strategy_id: str) -> str:
        """Returns the ledger_account_id for a given broker account and strategy."""
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT ledger_account_id FROM strategy_portfolios WHERE broker_account_id=? AND strategy_id=?",
                (broker_account_id, strategy_id)
            ).fetchone()
            if not row:
                raise DomainValidationError("portfolio mapping not found")
            return row["ledger_account_id"]
