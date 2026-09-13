"""SQLite read model for dated Kite instruments and normalized OHLCV bars."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.market_data import NormalizedBar
from src.platform_kernel import DomainValidationError


@dataclass(frozen=True)
class TrackedInstrument:
    instrument_id: str
    isin: str
    symbol: str
    exchange: str
    provider_token: str
    observed_on: date


class MarketRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        migrate_sqlite(
            self.path,
            "market",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS reference_instruments (
                        instrument_id TEXT PRIMARY KEY, isin TEXT NOT NULL,
                        symbol TEXT NOT NULL, exchange TEXT NOT NULL,
                        provider_token TEXT NOT NULL, observed_on TEXT NOT NULL,
                        UNIQUE(exchange, symbol, isin))""",
                    "CREATE INDEX IF NOT EXISTS reference_instruments_symbol ON reference_instruments(exchange, symbol)",
                    """CREATE TABLE IF NOT EXISTS reference_token_observations (
                        instrument_id TEXT NOT NULL, observed_on TEXT NOT NULL,
                        provider_token TEXT NOT NULL,
                        PRIMARY KEY(instrument_id, observed_on),
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                    """CREATE TABLE IF NOT EXISTS market_bars (
                        instrument_id TEXT NOT NULL, as_of_date TEXT NOT NULL,
                        open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL,
                        close TEXT NOT NULL, volume INTEGER NOT NULL,
                        snapshot_id TEXT NOT NULL,
                        PRIMARY KEY(instrument_id, as_of_date),
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                    "CREATE INDEX IF NOT EXISTS market_bars_date ON market_bars(as_of_date)",
                ),
                2: (
                    """CREATE TABLE IF NOT EXISTS market_index_quotes (
                        instrument_id TEXT PRIMARY KEY, exchange TEXT NOT NULL,
                        symbol TEXT NOT NULL, last_price TEXT NOT NULL,
                        prev_close TEXT NOT NULL, change_percent REAL NOT NULL,
                        observed_at TEXT NOT NULL, snapshot_id TEXT NOT NULL,
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                ),
            },
        )

    def upsert_instruments(self, records: Iterable[TrackedInstrument]) -> int:
        instruments = tuple(records)
        if len({item.instrument_id for item in instruments}) != len(instruments):
            raise DomainValidationError("instrument snapshot contains duplicate identities")
        with sqlite_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for item in instruments:
                connection.execute(
                    """INSERT INTO reference_instruments
                       (instrument_id, isin, symbol, exchange, provider_token, observed_on)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(instrument_id) DO UPDATE SET
                       symbol=excluded.symbol, exchange=excluded.exchange,
                       provider_token=excluded.provider_token, observed_on=excluded.observed_on
                       WHERE excluded.observed_on >= reference_instruments.observed_on""",
                    (
                        item.instrument_id,
                        item.isin,
                        item.symbol,
                        item.exchange,
                        item.provider_token,
                        item.observed_on.isoformat(),
                    ),
                )
                connection.execute(
                    """INSERT INTO reference_token_observations
                       (instrument_id, observed_on, provider_token) VALUES (?, ?, ?)
                       ON CONFLICT(instrument_id, observed_on) DO UPDATE SET
                       provider_token=excluded.provider_token""",
                    (item.instrument_id, item.observed_on.isoformat(), item.provider_token),
                )
        return len(instruments)

    def instruments(
        self, *, symbol: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, object]]:
        if not 1 <= limit <= 500 or offset < 0:
            raise DomainValidationError("instrument pagination is invalid")
        sql = "SELECT * FROM reference_instruments"
        parameters: list[object] = []
        if symbol is not None:
            sql += " WHERE symbol = ?"
            parameters.append(symbol)
        sql += " ORDER BY exchange, symbol LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            return [dict(row) for row in connection.execute(sql, parameters)]

    def tracked_instruments(self) -> list[dict[str, object]]:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute("SELECT * FROM reference_instruments ORDER BY exchange, symbol").fetchall()
        return [dict(row) for row in rows]

    def instrument(self, symbol: str, exchange: str = "NSE") -> dict[str, object]:

        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT * FROM reference_instruments WHERE symbol = ? AND exchange = ?",
                (symbol, exchange),
            ).fetchall()
        if len(rows) != 1:
            raise DomainValidationError("instrument was not found or is ambiguous")
        return dict(rows[0])

    def instrument_by_id(self, instrument_id: str) -> dict[str, object] | None:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM reference_instruments WHERE instrument_id=?", (instrument_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def delete_bars_after(self, cutoff: date, instrument_id: str | None = None) -> int:
        """Delete mutable bar projections after a cutoff for compatibility maintenance."""
        if not isinstance(cutoff, date):
            raise DomainValidationError("cutoff must be a date")
        with sqlite_connection(self.path) as connection:
            if instrument_id is None:
                cursor = connection.execute("DELETE FROM market_bars WHERE as_of_date > ?", (cutoff.isoformat(),))
            else:
                cursor = connection.execute(
                    "DELETE FROM market_bars WHERE instrument_id=? AND as_of_date > ?",
                    (instrument_id, cutoff.isoformat()),
                )
        return int(cursor.rowcount)

    def latest_market_date(self) -> date | None:
        """Return the latest as_of_date recorded across all market bars."""
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            row = connection.execute("SELECT MAX(as_of_date) AS max_date FROM market_bars").fetchone()
        if row is not None and row["max_date"]:
            return date.fromisoformat(row["max_date"])
        return None


    def token_assignments(
        self, provider_token: str, *, exchange: str | None = None, as_of: date | None = None
    ) -> list[dict[str, object]]:
        """Resolve a token using each identity's last observation as of a date."""
        if not provider_token.strip() or (exchange is not None and exchange not in {"NSE", "BSE"}):
            raise DomainValidationError("token lookup is invalid")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """WITH latest AS (
                       SELECT instrument_id, MAX(observed_on) AS observed_on
                       FROM reference_token_observations
                       WHERE (? IS NULL OR observed_on <= ?)
                       GROUP BY instrument_id
                   )
                   SELECT i.instrument_id, i.isin, i.symbol AS current_symbol,
                          i.exchange AS current_exchange,
                          o.provider_token, o.observed_on
                   FROM latest l
                   JOIN reference_token_observations o
                     ON o.instrument_id = l.instrument_id AND o.observed_on = l.observed_on
                   JOIN reference_instruments i ON i.instrument_id = l.instrument_id
                   WHERE o.provider_token = ? AND (? IS NULL OR i.exchange = ?)
                   ORDER BY i.exchange, i.symbol, i.instrument_id""",
                (
                    as_of.isoformat() if as_of else None,
                    as_of.isoformat() if as_of else None,
                    provider_token,
                    exchange,
                    exchange,
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def token_history(
        self, instrument_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, object]]:
        """Read dated token observations and identify changes from prior days."""
        if not 1 <= limit <= 500 or offset < 0:
            raise DomainValidationError("token history pagination is invalid")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT observed_on, provider_token, previous_token
                   FROM (
                       SELECT observed_on, provider_token,
                              LAG(provider_token) OVER (ORDER BY observed_on) AS previous_token
                       FROM reference_token_observations WHERE instrument_id = ?
                   ) ORDER BY observed_on DESC LIMIT ? OFFSET ?""",
                (instrument_id, limit, offset),
            ).fetchall()
        return [
            {
                **dict(row),
                "changed": row["previous_token"] is not None
                and row["previous_token"] != row["provider_token"],
            }
            for row in rows
        ]

    def upsert_bars(
        self, instrument_id: str, bars: Iterable[NormalizedBar], snapshot_id: str
    ) -> int:
        values = tuple(bars)
        if not values or len({bar.as_of_date for bar in values}) != len(values):
            raise DomainValidationError("market bar batch is empty or has duplicate dates")
        if any(bar.instrument_id != instrument_id for bar in values):
            raise DomainValidationError("market bar instrument identity does not match")
        with sqlite_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """INSERT INTO market_bars
                   (instrument_id, as_of_date, open, high, low, close, volume, snapshot_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(instrument_id, as_of_date) DO UPDATE SET
                   open=excluded.open, high=excluded.high, low=excluded.low,
                   close=excluded.close, volume=excluded.volume, snapshot_id=excluded.snapshot_id""",
                [
                    (
                        instrument_id,
                        bar.as_of_date.isoformat(),
                        str(bar.open),
                        str(bar.high),
                        str(bar.low),
                        str(bar.close),
                        bar.volume,
                        snapshot_id,
                    )
                    for bar in values
                ],
            )
        return len(values)

    def bars(
        self,
        instrument_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
        *,
        limit: int = 400,
    ) -> list[dict[str, object]]:
        actual_start = start_date or date(2000, 1, 1)
        actual_end = end_date or date(2099, 12, 31)
        if actual_start > actual_end or not 1 <= limit <= 1000:
            raise DomainValidationError("market bar range is invalid")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM market_bars WHERE instrument_id = ?
                   AND as_of_date BETWEEN ? AND ? ORDER BY as_of_date LIMIT ?""",
                (instrument_id, actual_start.isoformat(), actual_end.isoformat(), limit),
            ).fetchall()
        return [dict(row) for row in rows]


    def coverage(
        self,
        *,
        symbol: str | None = None,
        exchange: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        """Return paged bar coverage, including instruments with no bars."""
        if not 1 <= limit <= 500 or offset < 0:
            raise DomainValidationError("market coverage pagination is invalid")
        if symbol is not None and not symbol.strip():
            raise DomainValidationError("market coverage symbol is invalid")
        if exchange is not None and exchange not in {"NSE", "BSE"}:
            raise DomainValidationError("market coverage exchange is invalid")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """WITH page AS (
                       SELECT instrument_id, isin, symbol, exchange, observed_on
                       FROM reference_instruments
                       WHERE (? IS NULL OR symbol = ?) AND (? IS NULL OR exchange = ?)
                       ORDER BY exchange, symbol, instrument_id LIMIT ? OFFSET ?
                   )
                   SELECT i.instrument_id, i.isin, i.symbol, i.exchange,
                           i.observed_on AS reference_observed_on,
                           (SELECT COUNT(*) FROM market_bars b
                            WHERE b.instrument_id = i.instrument_id) AS bar_count,
                           (SELECT MIN(as_of_date) FROM market_bars b
                            WHERE b.instrument_id = i.instrument_id) AS earliest_date,
                           (SELECT MAX(as_of_date) FROM market_bars b
                            WHERE b.instrument_id = i.instrument_id) AS latest_date,
                           (SELECT snapshot_id FROM market_bars b
                            WHERE b.instrument_id = i.instrument_id
                            ORDER BY as_of_date DESC LIMIT 1) AS latest_snapshot_id
                    FROM page i ORDER BY i.exchange, i.symbol, i.instrument_id""",
                (symbol, symbol, exchange, exchange, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def histories(
        self, start_date: date, end_date: date
    ) -> dict[str, tuple[list[dict[str, object]], dict[str, object]]]:
        """Read complete per-instrument warm-up series without future bars."""
        if start_date > end_date:
            raise DomainValidationError("market history range is invalid")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT b.*, i.symbol, i.exchange, i.isin
                   FROM market_bars b JOIN reference_instruments i
                   ON i.instrument_id = b.instrument_id
                   WHERE b.as_of_date BETWEEN ? AND ?
                   ORDER BY b.instrument_id, b.as_of_date""",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        grouped: dict[str, tuple[list[dict[str, object]], dict[str, object]]] = {}
        for row in rows:
            key = str(row["instrument_id"])
            if key not in grouped:
                grouped[key] = (
                    [],
                    {"symbol": row["symbol"], "exchange": row["exchange"], "isin": row["isin"]},
                )
            grouped[key][0].append(dict(row))
        return grouped

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
        return len(values)

    def index_quotes(self) -> list[dict[str, object]]:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT * FROM market_index_quotes ORDER BY exchange, symbol"
            ).fetchall()
        return [dict(row) for row in rows]
