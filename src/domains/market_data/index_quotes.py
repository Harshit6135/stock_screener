"""Persistence operations for current and historical index quotes."""

from collections.abc import Iterable

from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import sqlite_connection


class IndexQuoteRepositoryMixin:
    """Index quote operations for a repository with an initialized market database."""

    def upsert_index_quotes(self, quotes: Iterable[dict[str, object]], snapshot_id: str) -> int:
        values = tuple(quotes)
        if not values or len({item["instrument_id"] for item in values}) != len(values):
            raise DomainValidationError("index quote batch is empty or has duplicate identities")
        with sqlite_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """INSERT INTO market_index_quotes
                   (instrument_id, exchange, symbol, last_price, prev_close,
                    change_percent, observed_at, snapshot_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                   last_price=excluded.last_price, prev_close=excluded.prev_close,
                   change_percent=excluded.change_percent, observed_at=excluded.observed_at,
                   snapshot_id=excluded.snapshot_id, symbol=excluded.symbol,
                   exchange=excluded.exchange""",
                [
                    (
                        item["instrument_id"],
                        item["exchange"],
                        item["symbol"],
                        item["last_price"],
                        item["prev_close"],
                        item["change_percent"],
                        item["observed_at"],
                        snapshot_id,
                    )
                    for item in values
                ],
            )
            connection.executemany(
                """INSERT OR IGNORE INTO market_index_quote_history
                   (instrument_id, observed_at, last_price, prev_close, change_percent, snapshot_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item["instrument_id"],
                        item["observed_at"],
                        item["last_price"],
                        item["prev_close"],
                        item["change_percent"],
                        snapshot_id,
                    )
                    for item in values
                ],
            )
        return len(values)

    def index_quotes(self) -> list[dict[str, object]]:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT * FROM market_index_quotes ORDER BY exchange, symbol"
            ).fetchall()
        return [dict(row) for row in rows]

    def index_quote_history(self, sessions: int = 30) -> list[dict[str, object]]:
        """Return a bounded UI readback, never an unbounded tick archive."""
        if not 1 <= sessions <= 30:
            raise DomainValidationError("sessions must be 1..30")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT instrument_id, observed_at, last_price, prev_close, change_percent, snapshot_id
                   FROM (
                     SELECT *, ROW_NUMBER() OVER (PARTITION BY instrument_id ORDER BY observed_at DESC) AS row_number
                     FROM (
                         SELECT *, ROW_NUMBER() OVER (
                             PARTITION BY instrument_id, substr(observed_at, 1, 10)
                             ORDER BY observed_at DESC) AS daily_row
                         FROM market_index_quote_history
                     ) WHERE daily_row=1
                   ) WHERE row_number <= ? ORDER BY instrument_id, observed_at""",
                (sessions,),
            ).fetchall()
        return [dict(row) for row in rows]
