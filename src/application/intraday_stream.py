"""Durable intent and state for an externally supervised intraday stream."""

from datetime import UTC, datetime
from pathlib import Path

from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError


class IntradayStreamLease:
    def __init__(self, database: str | Path, stream_name: str = "kite-intraday") -> None:
        self.database, self.stream_name = Path(database), stream_name
        migrate_sqlite(self.database, "intraday_stream", {
            1: (
                """CREATE TABLE IF NOT EXISTS intraday_stream_leases (
                    stream_name TEXT PRIMARY KEY, account_id TEXT, token_count INTEGER NOT NULL,
                    enabled INTEGER NOT NULL, status TEXT NOT NULL, last_started_at TEXT,
                    last_stopped_at TEXT, last_error TEXT, updated_at TEXT NOT NULL)""",
            ),
            2: ("ALTER TABLE intraday_stream_leases ADD COLUMN last_heartbeat_at TEXT",),
        })
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO intraday_stream_leases(stream_name, token_count, enabled, status, updated_at) VALUES (?, 0, 0, 'STOPPED', ?)",
                (self.stream_name, datetime.now(UTC).isoformat()),
            )

    def state(self) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM intraday_stream_leases WHERE stream_name=?", (self.stream_name,)
            ).fetchone()
        return dict(row)

    def start(self, account_id: str, token_count: int) -> dict[str, object]:
        if not isinstance(account_id, str) or not account_id.strip():
            raise DomainValidationError("stream account_id is required")
        if isinstance(token_count, bool) or not isinstance(token_count, int) or not 1 <= token_count <= 500:
            raise DomainValidationError("stream token_count must be between 1 and 500")
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE intraday_stream_leases SET account_id=?, token_count=?, enabled=1, status='REQUESTED', last_started_at=?, last_error=NULL, updated_at=? WHERE stream_name=?",
                (account_id, token_count, now, now, self.stream_name),
            )
        return self.state()

    def stop(self) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE intraday_stream_leases SET enabled=0, status='STOPPED', last_stopped_at=?, updated_at=? WHERE stream_name=?",
                (now, now, self.stream_name),
            )
        return self.state()

    def connected(self, token_count: int | None = None) -> dict[str, object]:
        if token_count is not None and (
            isinstance(token_count, bool) or not isinstance(token_count, int) or not 1 <= token_count <= 500
        ):
            raise DomainValidationError("stream token_count must be between 1 and 500")
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            if token_count is None:
                connection.execute(
                    "UPDATE intraday_stream_leases SET enabled=1, status='CONNECTED', last_error=NULL, updated_at=? WHERE stream_name=?",
                    (now, self.stream_name),
                )
            else:
                connection.execute(
                    "UPDATE intraday_stream_leases SET token_count=?, enabled=1, status='CONNECTED', last_error=NULL, updated_at=? WHERE stream_name=?",
                    (token_count, now, self.stream_name),
                )
        return self.state()

    def mark_error(self, message: str) -> dict[str, object]:
        if not isinstance(message, str) or not message.strip():
            raise DomainValidationError("stream error message is required")
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE intraday_stream_leases SET status='ERROR', last_error=?, updated_at=? WHERE stream_name=?",
                (message[:500], now, self.stream_name),
            )
        return self.state()

    def heartbeat(self) -> dict[str, object]:
        """Record a supervisor heartbeat without changing stream state."""
        current = self.state()
        if not current["enabled"]:
            raise DomainValidationError("cannot heartbeat a stopped stream")
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE intraday_stream_leases SET last_heartbeat_at=?, updated_at=? WHERE stream_name=?",
                (now, now, self.stream_name),
            )
        return self.state()
