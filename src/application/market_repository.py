"""SQLite read model for dated Kite instruments and normalized OHLCV bars."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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
                3: (
                    """CREATE TABLE IF NOT EXISTS market_indicators (
                        strategy_id TEXT NOT NULL, instrument_id TEXT NOT NULL,
                        as_of_date TEXT NOT NULL, values_json TEXT NOT NULL,
                        source_snapshot_id TEXT NOT NULL, calculated_at TEXT NOT NULL,
                        PRIMARY KEY(strategy_id, instrument_id, as_of_date),
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                    "CREATE INDEX IF NOT EXISTS market_indicators_date ON market_indicators(strategy_id, as_of_date)",
                ),
                4: (
                    "ALTER TABLE market_indicators RENAME TO market_indicators_strategy_cache",
                    "DROP INDEX IF EXISTS market_indicators_date",
                    """CREATE TABLE market_indicators (
                        instrument_id TEXT NOT NULL, as_of_date TEXT NOT NULL,
                        values_json TEXT NOT NULL, source_snapshot_id TEXT NOT NULL,
                        calculated_at TEXT NOT NULL,
                        PRIMARY KEY(instrument_id, as_of_date),
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                    """INSERT OR REPLACE INTO market_indicators
                       (instrument_id, as_of_date, values_json, source_snapshot_id, calculated_at)
                       SELECT instrument_id, as_of_date, values_json, source_snapshot_id, calculated_at
                       FROM market_indicators_strategy_cache ORDER BY calculated_at""",
                    "DROP TABLE market_indicators_strategy_cache",
                    "CREATE INDEX market_indicators_date ON market_indicators(as_of_date)",
                ),
                5: (
                    """CREATE TABLE IF NOT EXISTS universe_membership (
                        isin TEXT PRIMARY KEY, instrument_id TEXT NOT NULL,
                        symbol TEXT NOT NULL, exchange TEXT NOT NULL,
                        membership_type TEXT NOT NULL, first_eligible_date TEXT NOT NULL,
                        initial_market_cap REAL NOT NULL, threshold_crore REAL NOT NULL,
                        source TEXT NOT NULL, snapshot_date TEXT NOT NULL,
                        last_market_cap REAL NOT NULL,
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id)
                    )""",
                    "CREATE INDEX IF NOT EXISTS universe_membership_instrument ON universe_membership(instrument_id)",
                ),
                6: (
                    """CREATE TABLE IF NOT EXISTS universe_build_state (
                        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                        snapshot_date TEXT NOT NULL, threshold_crore REAL NOT NULL,
                        source TEXT NOT NULL, total_tracked INTEGER NOT NULL,
                        resolved_count INTEGER NOT NULL, unresolved_count INTEGER NOT NULL,
                        member_count INTEGER NOT NULL, completed_at TEXT NOT NULL
                    )""",
                ),
                7: (
                    """CREATE TABLE IF NOT EXISTS market_fetch_coverage (
                        instrument_id TEXT NOT NULL, start_date TEXT NOT NULL,
                        end_date TEXT NOT NULL, provider TEXT NOT NULL,
                        fetched_at TEXT NOT NULL, bar_count INTEGER NOT NULL,
                        PRIMARY KEY(instrument_id, start_date, end_date, provider),
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id)
                    )""",
                    "CREATE INDEX IF NOT EXISTS market_fetch_coverage_range ON market_fetch_coverage(instrument_id, provider, start_date, end_date)",
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
            rows = connection.execute(
                """SELECT * FROM (
                       SELECT i.*, ROW_NUMBER() OVER (
                           PARTITION BY CASE WHEN i.isin LIKE 'INDEX:%'
                                             THEN i.isin ELSE i.isin END
                           ORDER BY CASE WHEN i.isin LIKE 'INDEX:%' AND i.exchange='NSE' THEN 0
                                         WHEN i.isin NOT LIKE 'INDEX:%' AND i.exchange='NSE' THEN 0
                                         ELSE 1 END,
                                    i.exchange, i.symbol, i.instrument_id
                       ) AS preferred_row
                       FROM reference_instruments i
                   )
                   WHERE preferred_row = 1
                   ORDER BY exchange, symbol, instrument_id"""
            ).fetchall()
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

    def universe_members(self) -> list[dict[str, object]]:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT * FROM universe_membership ORDER BY exchange, symbol, isin"
            ).fetchall()
        return [dict(row) for row in rows]

    def universe_build_state(self) -> dict[str, object] | None:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM universe_build_state WHERE singleton=1"
            ).fetchone()
        return dict(row) if row is not None else None

    def active_universe_members(self) -> list[dict[str, object]]:
        state = self.universe_build_state()
        members = self.universe_members()
        if state is None or int(state["member_count"]) != len(members):
            return []
        return members

    def upsert_universe_members(self, members: Iterable[dict[str, object]]) -> int:
        values = tuple(members)
        if not values:
            return 0
        with sqlite_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """INSERT INTO universe_membership
                   (isin, instrument_id, symbol, exchange, membership_type,
                    first_eligible_date, initial_market_cap, threshold_crore,
                    source, snapshot_date, last_market_cap)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(isin) DO UPDATE SET
                   instrument_id=excluded.instrument_id,
                   symbol=excluded.symbol,
                   exchange=excluded.exchange,
                   last_market_cap=excluded.last_market_cap,
                   snapshot_date=excluded.snapshot_date""",
                [
                    (
                        item["isin"], item["instrument_id"], item["symbol"], item["exchange"],
                        item["membership_type"], item["first_eligible_date"],
                        item["initial_market_cap"], item["threshold_crore"],
                        item["source"], item["snapshot_date"], item["last_market_cap"],
                    )
                    for item in values
                ],
            )
        return len(values)

    def replace_universe_members(
        self,
        members: Iterable[dict[str, object]],
        *,
        snapshot_date: str,
        threshold_crore: float,
        source: str,
        total_tracked: int,
        resolved_count: int,
        unresolved_count: int,
    ) -> int:
        """Atomically replace and activate one completed universe snapshot."""
        values = tuple(members)
        if (
            not values
            or len({str(item["isin"]) for item in values}) != len(values)
            or total_tracked < 1
            or resolved_count < 0
            or unresolved_count < 0
            or resolved_count + unresolved_count != total_tracked
            or threshold_crore <= 0
            or not source.strip()
        ):
            raise DomainValidationError("completed universe snapshot is invalid")
        with sqlite_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM universe_membership")
            connection.executemany(
                """INSERT INTO universe_membership
                   (isin, instrument_id, symbol, exchange, membership_type,
                    first_eligible_date, initial_market_cap, threshold_crore,
                    source, snapshot_date, last_market_cap)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item["isin"], item["instrument_id"], item["symbol"], item["exchange"],
                        item["membership_type"], item["first_eligible_date"],
                        item["initial_market_cap"], item["threshold_crore"],
                        item["source"], item["snapshot_date"], item["last_market_cap"],
                    )
                    for item in values
                ],
            )
            connection.execute(
                """INSERT INTO universe_build_state
                   (singleton, snapshot_date, threshold_crore, source, total_tracked,
                    resolved_count, unresolved_count, member_count, completed_at)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET
                   snapshot_date=excluded.snapshot_date,
                   threshold_crore=excluded.threshold_crore,
                   source=excluded.source,
                   total_tracked=excluded.total_tracked,
                   resolved_count=excluded.resolved_count,
                   unresolved_count=excluded.unresolved_count,
                   member_count=excluded.member_count,
                   completed_at=excluded.completed_at""",
                (
                    snapshot_date, threshold_crore, source, total_tracked,
                    resolved_count, unresolved_count, len(values), datetime.now(UTC).isoformat(),
                ),
            )
        return len(values)

    def delete_bars_after(self, cutoff: date, instrument_id: str | None = None) -> int:
        """Delete mutable bar projections after a cutoff for compatibility maintenance."""
        if not isinstance(cutoff, date):
            raise DomainValidationError("cutoff must be a date")
        with sqlite_connection(self.path) as connection:
            if instrument_id is None:
                cursor = connection.execute("DELETE FROM market_bars WHERE as_of_date > ?", (cutoff.isoformat(),))
                connection.execute("DELETE FROM market_indicators WHERE as_of_date > ?", (cutoff.isoformat(),))
            else:
                cursor = connection.execute(
                    "DELETE FROM market_bars WHERE instrument_id=? AND as_of_date > ?",
                    (instrument_id, cutoff.isoformat()),
                )
                connection.execute(
                    "DELETE FROM market_indicators WHERE instrument_id=? AND as_of_date > ?",
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
            dates = tuple(bar.as_of_date.isoformat() for bar in values)
            existing = connection.execute(
                "SELECT as_of_date, open, high, low, close, volume FROM market_bars "
                f"WHERE instrument_id=? AND as_of_date IN ({','.join('?' for _ in dates)})",
                (instrument_id, *dates),
            ).fetchall()
            incoming = {bar.as_of_date.isoformat(): bar for bar in values}
            changed = any(
                str(row["open"]) != str(incoming[row["as_of_date"]].open)
                or str(row["high"]) != str(incoming[row["as_of_date"]].high)
                or str(row["low"]) != str(incoming[row["as_of_date"]].low)
                or str(row["close"]) != str(incoming[row["as_of_date"]].close)
                or int(row["volume"]) != int(incoming[row["as_of_date"]].volume)
                for row in existing
            )
            if changed:
                connection.execute("DELETE FROM market_indicators WHERE instrument_id=?", (instrument_id,))
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

    def indicators_for_date(self, as_of_date: date) -> dict[str, dict[str, object]]:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT instrument_id, values_json FROM market_indicators WHERE as_of_date=?",
                (as_of_date.isoformat(),),
            ).fetchall()
        return {str(row["instrument_id"]): json.loads(row["values_json"]) for row in rows}

    def upsert_indicators(
        self, as_of_date: date, values: dict[str, dict[str, object]], source_snapshot_id: str
    ) -> int:
        if not values:
            return 0
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """INSERT INTO market_indicators
                   (instrument_id, as_of_date, values_json, source_snapshot_id, calculated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(instrument_id, as_of_date) DO UPDATE SET
                   values_json=excluded.values_json, source_snapshot_id=excluded.source_snapshot_id,
                   calculated_at=excluded.calculated_at""",
                [
                    (instrument_id, as_of_date.isoformat(), json.dumps(item, sort_keys=True), source_snapshot_id, now)
                    for instrument_id, item in values.items()
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

    def record_fetch_coverage(
        self,
        instrument_id: str,
        start_date: date,
        end_date: date,
        *,
        provider: str,
        bar_count: int,
    ) -> None:
        """Record a completed provider request, including valid empty ranges."""
        if start_date > end_date or not provider.strip() or bar_count < 0:
            raise DomainValidationError("market fetch coverage is invalid")
        with sqlite_connection(self.path) as connection:
            connection.execute(
                """INSERT INTO market_fetch_coverage
                   (instrument_id, start_date, end_date, provider, fetched_at, bar_count)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(instrument_id, start_date, end_date, provider) DO UPDATE SET
                   fetched_at=excluded.fetched_at, bar_count=excluded.bar_count""",
                (
                    instrument_id,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    provider,
                    datetime.now(UTC).isoformat(),
                    bar_count,
                ),
            )

    def has_coverage(
        self, instrument_id: str, start_date: date, end_date: date, provider: str = "kite"
    ) -> bool:
        """Return whether completed provider windows cover the full calendar range."""
        if start_date > end_date or not provider.strip():
            raise DomainValidationError("market fetch coverage range is invalid")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT start_date, end_date FROM market_fetch_coverage
                   WHERE instrument_id=? AND provider=?
                   AND end_date>=? AND start_date<=?
                   ORDER BY start_date, end_date""",
                (instrument_id, provider, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        covered_through = start_date - timedelta(days=1)
        for row in rows:
            window_start = date.fromisoformat(str(row["start_date"]))
            window_end = date.fromisoformat(str(row["end_date"]))
            if window_start > covered_through + timedelta(days=1):
                return False
            covered_through = max(covered_through, window_end)
            if covered_through >= end_date:
                return True
        return False


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
                """WITH preferred_instruments AS (
                       SELECT i.*,
                              ROW_NUMBER() OVER (
                                  PARTITION BY i.isin
                                  ORDER BY CASE WHEN i.exchange='NSE' THEN 0 ELSE 1 END,
                                           i.symbol, i.instrument_id
                              ) AS preferred_row
                       FROM reference_instruments i
                   )
                   SELECT b.*, i.symbol, i.exchange, i.isin
                   FROM market_bars b JOIN preferred_instruments i
                   ON i.instrument_id = b.instrument_id AND i.preferred_row = 1
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
