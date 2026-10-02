"""Phase 5: Broker Accounts and Strategy Linkage."""

from datetime import UTC, datetime

from kiteconnect import KiteConnect

from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError


class KiteAccounts:
    """Manages Kite API credentials and account mapping."""

    def __init__(self, database_path: str, client_factory=KiteConnect):
        self.database = database_path
        self.client_factory = client_factory
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
                """INSERT INTO kite_accounts 
                   (broker_account_id, account_name, api_key, api_secret, created_at) 
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(broker_account_id) DO UPDATE SET
                   account_name=excluded.account_name,
                   access_token=CASE WHEN api_key=excluded.api_key AND api_secret=excluded.api_secret THEN access_token ELSE NULL END,
                   validated_at=CASE WHEN api_key=excluded.api_key AND api_secret=excluded.api_secret THEN validated_at ELSE NULL END,
                   api_key=excluded.api_key, api_secret=excluded.api_secret""",
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
        previous = self.get_credentials(broker_account_id)
        if not access_token or not broker_user_id:
            raise DomainValidationError("broker session is incomplete")
        if previous["broker_user_id"] and previous["broker_user_id"] != broker_user_id:
            raise DomainValidationError("broker login belongs to a different user")
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

    def binding(self, ledger_account_id: str) -> dict[str, str]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute("SELECT * FROM strategy_portfolios WHERE ledger_account_id=?", (ledger_account_id,)).fetchone()
        if row is None:
            raise DomainValidationError("ledger has no explicit broker/strategy binding")
        return dict(row)

    def client(self, broker_account_id: str):
        credentials = self.get_credentials(broker_account_id)
        if not credentials["access_token"]:
            raise DomainValidationError("selected broker account requires login")
        client = self.client_factory(api_key=credentials["api_key"])
        client.set_access_token(credentials["access_token"])
        return client

    def login_url(self, broker_account_id: str) -> str:
        credentials = self.get_credentials(broker_account_id)
        return self.client_factory(api_key=credentials["api_key"]).login_url()

    def authenticate(self, broker_account_id: str, request_token: str) -> dict[str, str]:
        if not isinstance(request_token, str) or not request_token.strip():
            raise DomainValidationError("request_token is required")
        credentials = self.get_credentials(broker_account_id)
        try:
            client = self.client_factory(api_key=credentials["api_key"])
            session = client.generate_session(request_token, api_secret=credentials["api_secret"])
            client.set_access_token(session["access_token"])
            profile = client.profile()
        except Exception as exc:
            raise DomainValidationError("selected broker login failed") from exc
        self.update_session(broker_account_id, session["access_token"], str(profile["user_id"]))
        return {"broker_account_id": broker_account_id, "broker_user_id": str(profile["user_id"])}

    def validate(self, broker_account_id: str) -> dict[str, str]:
        credentials = self.get_credentials(broker_account_id)
        try:
            profile = self.client(broker_account_id).profile()
        except Exception as exc:
            raise DomainValidationError("selected broker session is expired or unavailable") from exc
        self.update_session(broker_account_id, credentials["access_token"], str(profile["user_id"]))
        return {"broker_account_id": broker_account_id, "broker_user_id": str(profile["user_id"])}

    def portfolio_inputs(self, broker_account_id: str) -> dict[str, object]:
        self.validate(broker_account_id)
        client = self.client(broker_account_id)
        try:
            return {"holdings": client.holdings(), "positions": client.positions(),
                    "orders": client.orders(), "trades": client.trades(), "margins": client.margins()}
        except Exception as exc:
            raise DomainValidationError("selected broker portfolio read failed") from exc
