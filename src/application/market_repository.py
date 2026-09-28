"""SQLite read model for dated Kite instruments and normalized OHLCV bars."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

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
    series: str = "EQ"


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
                8: (
                    "ALTER TABLE market_indicators RENAME TO market_indicators_legacy",
                    "DROP INDEX IF EXISTS market_indicators_date",
                    """CREATE TABLE market_indicators (
                        indicator_set TEXT NOT NULL, instrument_id TEXT NOT NULL,
                        as_of_date TEXT NOT NULL, values_json TEXT NOT NULL,
                        source_snapshot_id TEXT NOT NULL, calculated_at TEXT NOT NULL,
                        PRIMARY KEY(indicator_set, instrument_id, as_of_date),
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                    """INSERT INTO market_indicators
                       (indicator_set, instrument_id, as_of_date, values_json,
                        source_snapshot_id, calculated_at)
                       SELECT 'legacy', instrument_id, as_of_date, values_json,
                              source_snapshot_id, calculated_at
                       FROM market_indicators_legacy""",
                    "DROP TABLE market_indicators_legacy",
                    "CREATE INDEX market_indicators_date ON market_indicators(indicator_set, as_of_date)",
                ),
                9: (
                    """CREATE TABLE IF NOT EXISTS market_history_revisions (
                        instrument_id TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                ),
                10: (
                    """CREATE TABLE IF NOT EXISTS data_quality_events (
                        event_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL,
                        as_of_date TEXT NOT NULL, check_type TEXT NOT NULL,
                        severity TEXT NOT NULL, detail_json TEXT NOT NULL,
                        detected_at TEXT NOT NULL,
                        UNIQUE(instrument_id, as_of_date, check_type, detail_json),
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                    "CREATE INDEX IF NOT EXISTS data_quality_events_instrument_date ON data_quality_events(instrument_id, as_of_date)",
                    "CREATE INDEX IF NOT EXISTS data_quality_events_detected ON data_quality_events(detected_at DESC, event_id DESC)",
                ),
                11: (
                    "ALTER TABLE reference_instruments ADD COLUMN series TEXT NOT NULL DEFAULT 'EQ'",
                    """CREATE TABLE IF NOT EXISTS universe_snapshots (
                        snapshot_id TEXT PRIMARY KEY, index_name TEXT NOT NULL,
                        snapshot_date TEXT NOT NULL, source_url TEXT NOT NULL,
                        source_hash TEXT NOT NULL, member_count INTEGER NOT NULL,
                        raw_csv BLOB NOT NULL, created_at TEXT NOT NULL,
                        UNIQUE(index_name, snapshot_date))""",
                    """CREATE TABLE IF NOT EXISTS universe_snapshot_members (
                        snapshot_id TEXT NOT NULL, isin TEXT NOT NULL, symbol TEXT NOT NULL,
                        company_name TEXT NOT NULL, industry TEXT NOT NULL, series TEXT NOT NULL,
                        PRIMARY KEY(snapshot_id, isin),
                        FOREIGN KEY(snapshot_id) REFERENCES universe_snapshots(snapshot_id))""",
                    "CREATE INDEX IF NOT EXISTS universe_snapshots_index_date ON universe_snapshots(index_name, snapshot_date DESC)",
                    "CREATE INDEX IF NOT EXISTS universe_snapshot_members_symbol ON universe_snapshot_members(snapshot_id, symbol)",
                ),
                12: (
                    """CREATE TABLE IF NOT EXISTS universe_exit_eligibility (
                        instrument_id TEXT NOT NULL, isin TEXT NOT NULL,
                        symbol TEXT NOT NULL, decision_date TEXT NOT NULL,
                        decision_snapshot_id TEXT NOT NULL,
                        target_session_date TEXT NOT NULL,
                        exit_only INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY(instrument_id, decision_snapshot_id),
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id),
                        FOREIGN KEY(decision_snapshot_id) REFERENCES universe_snapshots(snapshot_id))""",
                    "CREATE INDEX IF NOT EXISTS universe_exit_eligibility_target ON universe_exit_eligibility(target_session_date)",
                ),
                13: (
                    """CREATE TABLE IF NOT EXISTS corporate_action_events (
                        event_id TEXT PRIMARY KEY,
                        instrument_id TEXT,
                        isin TEXT NOT NULL, symbol TEXT NOT NULL,
                        action_type TEXT NOT NULL,
                        ex_date TEXT NOT NULL,
                        ratio_numerator REAL, ratio_denominator REAL,
                        raw_source_json TEXT NOT NULL,
                        state TEXT NOT NULL DEFAULT 'DETECTED',
                        baseline_revision TEXT,
                        applied_factor REAL,
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        last_attempt_at TEXT,
                        last_attempt_outcome TEXT,
                        verified_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                    "CREATE INDEX IF NOT EXISTS corporate_action_events_state ON corporate_action_events(state, ex_date)",
                    "CREATE INDEX IF NOT EXISTS corporate_action_events_instrument ON corporate_action_events(instrument_id, ex_date)",
                    "CREATE UNIQUE INDEX IF NOT EXISTS corporate_action_events_unique ON corporate_action_events(isin, action_type, ex_date)",
                    """CREATE TABLE IF NOT EXISTS corporate_action_watermark (
                        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                        last_checked_date TEXT NOT NULL,
                        updated_at TEXT NOT NULL)""",
                ),
                14: (
                    """CREATE TABLE IF NOT EXISTS market_index_quote_history (
                        instrument_id TEXT NOT NULL, observed_at TEXT NOT NULL,
                        last_price TEXT NOT NULL, prev_close TEXT NOT NULL,
                        change_percent REAL NOT NULL, snapshot_id TEXT NOT NULL,
                        PRIMARY KEY(instrument_id, observed_at),
                        FOREIGN KEY(instrument_id) REFERENCES reference_instruments(instrument_id))""",
                    "CREATE INDEX IF NOT EXISTS market_index_quote_history_recent ON market_index_quote_history(instrument_id, observed_at DESC)",
                ),
            },
        )

    def upsert_instruments(self, records: Iterable[TrackedInstrument]) -> int:
        instruments = tuple(records)
        if len({item.instrument_id for item in instruments}) != len(instruments):
            raise DomainValidationError("instrument snapshot contains duplicate identities")
        with sqlite_connection(self.path, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for item in instruments:
                connection.execute(
                    """INSERT INTO reference_instruments
                       (instrument_id, isin, symbol, exchange, provider_token, observed_on, series)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(instrument_id) DO UPDATE SET
                       symbol=excluded.symbol, exchange=excluded.exchange,
                       provider_token=excluded.provider_token, observed_on=excluded.observed_on
                       ,series=excluded.series
                       WHERE excluded.observed_on >= reference_instruments.observed_on""",
                    (
                        item.instrument_id,
                        item.isin,
                        item.symbol,
                        item.exchange,
                        item.provider_token,
                        item.observed_on.isoformat(),
                        item.series,
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

    def universe_snapshot(self, index_name: str, snapshot_date: date) -> dict[str, object] | None:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT snapshot_id, index_name, snapshot_date, source_url, source_hash, member_count, created_at FROM universe_snapshots WHERE index_name=? AND snapshot_date=?",
                (index_name, snapshot_date.isoformat()),
            ).fetchone()
        return dict(row) if row is not None else None

    def latest_universe_snapshot(self, index_name: str) -> dict[str, object] | None:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT snapshot_id, index_name, snapshot_date, source_url, source_hash, member_count, created_at FROM universe_snapshots WHERE index_name=? ORDER BY snapshot_date DESC LIMIT 1",
                (index_name,),
            ).fetchone()
        return dict(row) if row is not None else None

    def universe_snapshot_as_of(self, index_name: str, as_of: date) -> dict[str, object] | None:
        """Latest snapshot at or before a decision date, else the earliest known one."""
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                """SELECT snapshot_id, index_name, snapshot_date, source_url, source_hash, member_count, created_at FROM universe_snapshots WHERE index_name=? AND snapshot_date<=?
                   ORDER BY snapshot_date DESC LIMIT 1""", (index_name, as_of.isoformat())
            ).fetchone()
            fallback = False
            if row is None:
                row = connection.execute(
                    "SELECT snapshot_id, index_name, snapshot_date, source_url, source_hash, member_count, created_at FROM universe_snapshots WHERE index_name=? ORDER BY snapshot_date LIMIT 1",
                    (index_name,),
                ).fetchone()
                fallback = row is not None
        if row is None:
            return None
        result = dict(row)
        result["earliest_fallback"] = fallback
        return result

    def universe_snapshot_members(self, snapshot_id: str, *, limit: int = 500, offset: int = 0) -> list[dict[str, object]]:
        if not snapshot_id or not 1 <= limit <= 1000 or offset < 0:
            raise DomainValidationError("universe snapshot member query is invalid")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT isin, symbol, company_name, industry, series FROM universe_snapshot_members
                   WHERE snapshot_id=? ORDER BY symbol, isin LIMIT ? OFFSET ?""",
                (snapshot_id, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_universe_snapshots(self, index_name: str, *, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        if not index_name or not 1 <= limit <= 500 or offset < 0:
            raise DomainValidationError("universe snapshot query is invalid")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT snapshot_id, index_name, snapshot_date, source_url, source_hash, member_count, created_at FROM universe_snapshots WHERE index_name=? ORDER BY snapshot_date DESC LIMIT ? OFFSET ?",
                (index_name, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_universe_snapshot(self, *, snapshot_id: str, index_name: str, snapshot_date: date,
                                 source_url: str, raw_csv: bytes, members: Iterable[dict[str, object]]) -> dict[str, object]:
        rows = tuple(members)
        required = {"isin", "symbol", "company_name", "industry", "series"}
        if (not snapshot_id or not index_name or not source_url or not raw_csv or not rows
                or any(set(row) != required or any(not isinstance(row[key], str) or not row[key].strip() for key in required) for row in rows)
                or len({str(row["isin"]).upper() for row in rows}) != len(rows)):
            raise DomainValidationError("universe snapshot is invalid")
        source_hash = hashlib.sha256(raw_csv).hexdigest()
        with sqlite_connection(self.path, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM universe_snapshots WHERE index_name=? AND snapshot_date=?",
                (index_name, snapshot_date.isoformat()),
            ).fetchone()
            if existing is not None:
                return dict(existing)
            connection.execute(
                """INSERT INTO universe_snapshots
                   (snapshot_id, index_name, snapshot_date, source_url, source_hash, member_count, raw_csv, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (snapshot_id, index_name, snapshot_date.isoformat(), source_url, source_hash,
                 len(rows), raw_csv, datetime.now(UTC).isoformat()),
            )
            connection.executemany(
                """INSERT INTO universe_snapshot_members
                   (snapshot_id, isin, symbol, company_name, industry, series) VALUES (?, ?, ?, ?, ?, ?)""",
                [(snapshot_id, row["isin"].upper(), row["symbol"].upper(), row["company_name"], row["industry"], row["series"].upper()) for row in rows],
            )
        return self.universe_snapshot(index_name, snapshot_date) or {}

    def universe_snapshot_diff(self, older_snapshot_id: str, newer_snapshot_id: str) -> dict[str, list[dict[str, object]]]:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            def members(snapshot_id: str) -> dict[str, dict[str, object]]:
                rows = connection.execute("SELECT isin, symbol, company_name, industry, series FROM universe_snapshot_members WHERE snapshot_id=?", (snapshot_id,)).fetchall()
                return {str(row["isin"]): dict(row) for row in rows}
            older, newer = members(older_snapshot_id), members(newer_snapshot_id)
        if not older and not newer:
            raise DomainValidationError("universe snapshots were not found")
        return {"additions": [newer[key] for key in sorted(newer.keys() - older.keys())],
                "removals": [older[key] for key in sorted(older.keys() - newer.keys())],
                "series_transitions": [{"isin": key, "from": older[key]["series"], "to": newer[key]["series"]}
                                       for key in sorted(older.keys() & newer.keys()) if older[key]["series"] != newer[key]["series"]]}

    def record_exit_eligibility(
        self, *, instrument_id: str, isin: str, symbol: str,
        decision_date: date, decision_snapshot_id: str, target_session_date: date,
    ) -> bool:
        """Persist a universe-exit eligibility record for one-session exit-only coverage."""
        if (not instrument_id or not isin or not symbol or not decision_snapshot_id
                or decision_date > target_session_date):
            raise DomainValidationError("exit eligibility record is invalid")
        with sqlite_connection(self.path) as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO universe_exit_eligibility
                   (instrument_id, isin, symbol, decision_date, decision_snapshot_id,
                    target_session_date, exit_only, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (instrument_id, isin, symbol, decision_date.isoformat(),
                 decision_snapshot_id, target_session_date.isoformat(),
                 datetime.now(UTC).isoformat()),
            )
        return cursor.rowcount == 1

    def exit_eligible_instruments(self, *, target_date: date | None = None) -> list[dict[str, object]]:
        """Return instruments that need exit-only price coverage."""
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            if target_date is not None:
                rows = connection.execute(
                    "SELECT * FROM universe_exit_eligibility WHERE target_session_date=? AND exit_only=1",
                    (target_date.isoformat(),),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM universe_exit_eligibility WHERE exit_only=1 ORDER BY target_session_date",
                ).fetchall()
        return [dict(row) for row in rows]

    def is_exit_only(self, instrument_id: str) -> bool:
        """Check whether an instrument is currently flagged for exit-only coverage."""
        with sqlite_connection(self.path, read_only=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM universe_exit_eligibility WHERE instrument_id=? AND exit_only=1",
                (instrument_id,),
            ).fetchone()
        return row is not None

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

    def session_dates(self, start_date: date, end_date: date, *, exchange: str = "NSE") -> list[str]:
        """Return the stored exchange sessions in a date range."""
        if start_date > end_date or exchange not in {"NSE", "BSE"}:
            raise DomainValidationError("market session range is invalid")
        with sqlite_connection(self.path, read_only=True) as connection:
            rows = connection.execute(
                """SELECT DISTINCT b.as_of_date FROM market_bars b
                   JOIN reference_instruments i ON i.instrument_id=b.instrument_id
                   WHERE i.exchange=? AND b.as_of_date BETWEEN ? AND ?
                   ORDER BY b.as_of_date""",
                (exchange, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return [str(row[0]) for row in rows]


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
        self._validate_bars(values)
        with sqlite_connection(self.path, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            dates = tuple(bar.as_of_date.isoformat() for bar in values)
            existing = connection.execute(
                "SELECT as_of_date, open, high, low, close, volume FROM market_bars "
                f"WHERE instrument_id=? AND as_of_date IN ({','.join('?' for _ in dates)})",
                (instrument_id, *dates),
            ).fetchall()
            prior = connection.execute(
                """SELECT as_of_date, close, volume FROM market_bars
                   WHERE instrument_id=? AND as_of_date < ?
                   ORDER BY as_of_date DESC LIMIT 6""",
                (instrument_id, min(dates)),
            ).fetchall()
            incoming = {bar.as_of_date.isoformat(): bar for bar in values}
            # A new bar is a history change too; prior code only noticed
            # replacements, allowing stale indicator caches after extension.
            changed = len(existing) != len(values) or any(
                str(row["open"]) != str(incoming[row["as_of_date"]].open)
                or str(row["high"]) != str(incoming[row["as_of_date"]].high)
                or str(row["low"]) != str(incoming[row["as_of_date"]].low)
                or str(row["close"]) != str(incoming[row["as_of_date"]].close)
                or int(row["volume"]) != int(incoming[row["as_of_date"]].volume)
                for row in existing
            )
            if changed:
                connection.execute("DELETE FROM market_indicators WHERE instrument_id=?", (instrument_id,))
                connection.execute(
                    """INSERT INTO market_history_revisions(instrument_id, revision, updated_at)
                       VALUES (?, 1, ?)
                       ON CONFLICT(instrument_id) DO UPDATE SET
                       revision=market_history_revisions.revision + 1,
                       updated_at=excluded.updated_at""",
                    (instrument_id, datetime.now(UTC).isoformat()),
                )
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
            # These are warnings, not eligibility filters: downstream signal
            # evaluation still sees the stored bar and can make its own data
            # sufficiency decision.
            preceding_close = float(prior[0]["close"]) if prior else None
            zero_run = sum(1 for row in prior if int(row["volume"]) == 0)
            for bar in sorted(values, key=lambda item: item.as_of_date):
                close = float(bar.close)
                if preceding_close and abs(close / preceding_close - 1.0) > 0.15:
                    detail = json.dumps(
                        {"expected_close": preceding_close, "actual_close": close,
                         "source_snapshot_id": snapshot_id},
                        sort_keys=True, separators=(",", ":"),
                    )
                    connection.execute(
                        """INSERT OR IGNORE INTO data_quality_events
                           (event_id, instrument_id, as_of_date, check_type, severity, detail_json, detected_at)
                           VALUES (?, ?, ?, 'close_gap', 'WARNING', ?, ?)""",
                        (str(uuid4()), instrument_id, bar.as_of_date.isoformat(), detail,
                         datetime.now(UTC).isoformat()),
                    )
                zero_run = zero_run + 1 if int(bar.volume) == 0 else 0
                if zero_run == 6:
                    detail = json.dumps(
                        {"consecutive_sessions": zero_run, "actual_volume": 0,
                         "source_snapshot_id": snapshot_id},
                        sort_keys=True, separators=(",", ":"),
                    )
                    connection.execute(
                        """INSERT OR IGNORE INTO data_quality_events
                           (event_id, instrument_id, as_of_date, check_type, severity, detail_json, detected_at)
                           VALUES (?, ?, ?, 'zero_volume_streak', 'WARNING', ?, ?)""",
                        (str(uuid4()), instrument_id, bar.as_of_date.isoformat(), detail,
                         datetime.now(UTC).isoformat()),
                    )
                preceding_close = close
        return len(values)

    @staticmethod
    def _validate_bars(bars: tuple[NormalizedBar, ...]) -> None:
        """Reject impossible OHLCV rows before they can contaminate projections."""
        for bar in bars:
            values = (float(bar.open), float(bar.high), float(bar.low), float(bar.close))
            if not all(math.isfinite(value) and value > 0 for value in values):
                raise DomainValidationError("market bar prices must be positive finite values")
            if float(bar.low) > min(float(bar.open), float(bar.close)) or float(bar.high) < max(float(bar.open), float(bar.close)):
                raise DomainValidationError("market bar OHLC bounds are invalid")
            if isinstance(bar.volume, bool) or int(bar.volume) < 0:
                raise DomainValidationError("market bar volume must be non-negative")

    def record_quality_event(
        self, instrument_id: str, as_of_date: date, check_type: str, severity: str,
        detail: dict[str, object],
    ) -> bool:
        """Persist one idempotent, operator-visible data-quality observation."""
        if (not instrument_id or not isinstance(as_of_date, date) or not check_type
                or severity not in {"INFO", "WARNING", "ERROR"} or not isinstance(detail, dict)):
            raise DomainValidationError("data quality event is invalid")
        encoded = json.dumps(detail, sort_keys=True, separators=(",", ":"), default=str)
        with sqlite_connection(self.path) as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO data_quality_events
                   (event_id, instrument_id, as_of_date, check_type, severity, detail_json, detected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), instrument_id, as_of_date.isoformat(), check_type, severity,
                 encoded, datetime.now(UTC).isoformat()),
            )
        return cursor.rowcount == 1

    def quality_events(
        self, *, instrument_id: str | None = None, check_type: str | None = None,
        severity: str | None = None, limit: int = 100, offset: int = 0,
    ) -> list[dict[str, object]]:
        if not 1 <= limit <= 500 or offset < 0 or (severity is not None and severity not in {"INFO", "WARNING", "ERROR"}):
            raise DomainValidationError("quality event filters are invalid")
        clauses: list[str] = []
        args: list[object] = []
        for column, value in (("instrument_id", instrument_id), ("check_type", check_type), ("severity", severity)):
            if value is not None:
                clauses.append(f"{column}=?")
                args.append(value)
        sql = "SELECT * FROM data_quality_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY detected_at DESC, event_id DESC LIMIT ? OFFSET ?"
        args.extend((limit, offset))
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(sql, args).fetchall()
        return [{**dict(row), "detail": json.loads(row["detail_json"])} for row in rows]

    def market_history_revision(self, instrument_id: str) -> str:
        """Return the current input identity used by indicator-cache reads."""
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT revision FROM market_history_revisions WHERE instrument_id=?", (instrument_id,)
            ).fetchone()
        return str(row["revision"]) if row is not None else "0"

    def market_history_revisions(self, instrument_ids: Iterable[str]) -> dict[str, str]:
        ids = tuple(instrument_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                f"SELECT instrument_id, revision FROM market_history_revisions WHERE instrument_id IN ({placeholders})",
                ids,
            ).fetchall()
        revisions = {str(row["instrument_id"]): str(row["revision"]) for row in rows}
        return {instrument_id: revisions.get(instrument_id, "0") for instrument_id in ids}

    def bump_market_history_revision(self, instrument_id: str) -> str:
        """Explicitly bump the market history revision for an instrument."""
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.path) as connection:
            connection.execute(
                """INSERT INTO market_history_revisions(instrument_id, revision, updated_at)
                   VALUES (?, 1, ?)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                   revision=market_history_revisions.revision + 1,
                   updated_at=excluded.updated_at""",
                (instrument_id, now),
            )
        return self.market_history_revision(instrument_id)

    def apply_price_factor(self, instrument_id: str, ex_date: date, factor: float) -> int:
        """Phase 3 Task 3.4: Scale pre-ex-date OHLC by factor atomically.

        Returns the number of bars adjusted. Does NOT bump the revision;
        caller must call bump_market_history_revision separately.
        """
        if factor <= 0 or factor >= 100:
            raise DomainValidationError("price factor must be positive and reasonable")
        with sqlite_connection(self.path) as connection:
            cursor = connection.execute(
                """UPDATE market_bars SET
                   open = CAST(CAST(open AS REAL) * ? AS TEXT),
                   high = CAST(CAST(high AS REAL) * ? AS TEXT),
                   low  = CAST(CAST(low AS REAL) * ? AS TEXT),
                   close = CAST(CAST(close AS REAL) * ? AS TEXT)
                   WHERE instrument_id = ? AND as_of_date < ?""",
                (factor, factor, factor, factor, instrument_id, ex_date.isoformat()),
            )
        return cursor.rowcount

    def indicators_for_date(
        self, indicator_set: str, as_of_date: date
    ) -> dict[str, dict[str, object]]:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT instrument_id, values_json FROM market_indicators
                   WHERE indicator_set=? AND as_of_date=?""",
                (indicator_set, as_of_date.isoformat()),
            ).fetchall()
        return {str(row["instrument_id"]): json.loads(row["values_json"]) for row in rows}

    def indicator_series(
        self, indicator_set: str, start_date: date, end_date: date
    ) -> dict[str, dict[str, dict[str, object]]]:
        """Return cached raw indicators grouped by instrument and date."""
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT instrument_id, as_of_date, values_json FROM market_indicators
                   WHERE indicator_set=? AND as_of_date BETWEEN ? AND ?
                   ORDER BY instrument_id, as_of_date""",
                (indicator_set, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        grouped: dict[str, dict[str, dict[str, object]]] = {}
        for row in rows:
            grouped.setdefault(str(row["instrument_id"]), {})[str(row["as_of_date"])] = (
                json.loads(row["values_json"])
            )
        return grouped

    def upsert_indicators(
        self, indicator_set: str, as_of_date: date,
        values: dict[str, dict[str, object]], source_snapshot_id: str
    ) -> int:
        if not values:
            return 0
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """INSERT INTO market_indicators
                   (indicator_set, instrument_id, as_of_date, values_json,
                    source_snapshot_id, calculated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(indicator_set, instrument_id, as_of_date) DO UPDATE SET
                   values_json=excluded.values_json, source_snapshot_id=excluded.source_snapshot_id,
                   calculated_at=excluded.calculated_at""",
                [
                    (indicator_set, instrument_id, as_of_date.isoformat(),
                     json.dumps(item, sort_keys=True), source_snapshot_id, now)
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
        self, start_date: date, end_date: date, *, isins: set[str] | None = None,
        instrument_ids: set[str] | None = None,
    ) -> dict[str, tuple[list[dict[str, object]], dict[str, object]]]:
        """Read complete per-instrument warm-up series without future bars."""
        if start_date > end_date:
            raise DomainValidationError("market history range is invalid")
        selected_isins = sorted(isins) if isins is not None else None
        selected_ids = sorted(instrument_ids) if instrument_ids is not None else None
        if selected_isins is not None and not selected_isins:
            return {}
        if selected_ids is not None and not selected_ids:
            return {}
        membership_clause = (
            f" AND i.isin IN ({','.join('?' for _ in selected_isins)})"
            if selected_isins is not None else ""
        )
        identity_clause = (
            f" AND i.instrument_id IN ({','.join('?' for _ in selected_ids)})"
            if selected_ids is not None else " AND i.preferred_row = 1"
        )
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
                   ON i.instrument_id = b.instrument_id
                   WHERE b.as_of_date BETWEEN ? AND ?""" + membership_clause + identity_clause +
                " ORDER BY b.instrument_id, b.as_of_date",
                (start_date.isoformat(), end_date.isoformat(), *(selected_isins or []), *(selected_ids or [])),
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
            connection.executemany(
                """INSERT OR IGNORE INTO market_index_quote_history
                   (instrument_id, observed_at, last_price, prev_close, change_percent, snapshot_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (item["instrument_id"], item["observed_at"], item["last_price"],
                     item["prev_close"], item["change_percent"], snapshot_id)
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
                     FROM market_index_quote_history
                   ) WHERE row_number <= ? ORDER BY instrument_id, observed_at""",
                (sessions,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Corporate action event repository (Phase 3)
    # ------------------------------------------------------------------

    def upsert_corporate_action_event(self, event: dict[str, object]) -> bool:
        """Insert or update a corporate action event. Returns True if a new row was inserted."""
        required = {"event_id", "isin", "symbol", "action_type", "ex_date", "raw_source_json"}
        if not required.issubset(event):
            raise DomainValidationError("corporate action event is missing required fields")
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.path) as connection:
            existing = connection.execute(
                "SELECT 1 FROM corporate_action_events WHERE isin=? AND action_type=? AND ex_date=?",
                (str(event["isin"]), str(event["action_type"]), str(event["ex_date"])),
            ).fetchone()
            connection.execute(
                """INSERT INTO corporate_action_events
                   (event_id, instrument_id, isin, symbol, action_type, ex_date,
                    ratio_numerator, ratio_denominator, raw_source_json,
                    state, baseline_revision, applied_factor,
                    attempt_count, last_attempt_at, last_attempt_outcome,
                    verified_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL, ?, ?)
                   ON CONFLICT(isin, action_type, ex_date) DO UPDATE SET
                   raw_source_json = excluded.raw_source_json,
                   updated_at = excluded.updated_at""",
                (
                    str(event["event_id"]),
                    event.get("instrument_id"),
                    str(event["isin"]),
                    str(event["symbol"]),
                    str(event["action_type"]),
                    str(event["ex_date"]),
                    event.get("ratio_numerator"),
                    event.get("ratio_denominator"),
                    str(event["raw_source_json"]),
                    event.get("state", "DETECTED"),
                    event.get("baseline_revision"),
                    event.get("applied_factor"),
                    now, now,
                ),
            )
        return existing is None

    def actionable_corporate_events(self, *, states: tuple[str, ...] | None = None) -> list[dict[str, object]]:
        """Return corporate action events that need processing."""
        target_states = states or ("DETECTED", "SELF_ADJUSTED", "MONITORING")
        placeholders = ",".join("?" * len(target_states))
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                f"SELECT * FROM corporate_action_events WHERE state IN ({placeholders}) ORDER BY ex_date",
                target_states,
            ).fetchall()
        return [dict(row) for row in rows]

    def corporate_action_event(self, event_id: str) -> dict[str, object] | None:
        """Return a single corporate action event by ID."""
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM corporate_action_events WHERE event_id=?", (event_id,)
            ).fetchone()
        return dict(row) if row else None

    def transition_corporate_action(
        self, event_id: str, new_state: str, *,
        attempt_outcome: str | None = None,
        applied_factor: float | None = None,
        baseline_revision: str | None = None,
    ) -> bool:
        """Transition a corporate action event to a new state."""
        valid_states = {"DETECTED", "SELF_ADJUSTED", "MONITORING", "VERIFIED", "FAILED"}
        if new_state not in valid_states:
            raise DomainValidationError(f"invalid CA state: {new_state}")
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.path) as connection:
            cursor = connection.execute(
                """UPDATE corporate_action_events SET
                   state=?, attempt_count=attempt_count+1,
                   last_attempt_at=?, last_attempt_outcome=?,
                   applied_factor=COALESCE(?, applied_factor),
                   baseline_revision=COALESCE(?, baseline_revision),
                   verified_at=CASE WHEN ?='VERIFIED' THEN ? ELSE verified_at END,
                   updated_at=?
                   WHERE event_id=?""",
                (new_state, now, attempt_outcome, applied_factor, baseline_revision,
                 new_state, now, now, event_id),
            )
        return cursor.rowcount == 1

    def corporate_action_watermark(self) -> date | None:
        """Return the last checked date for corporate action detection."""
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT last_checked_date FROM corporate_action_watermark WHERE singleton=1"
            ).fetchone()
        return date.fromisoformat(str(row["last_checked_date"])) if row else None

    def advance_corporate_action_watermark(self, checked_date: date) -> None:
        """Advance the detection watermark to the given date."""
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.path) as connection:
            connection.execute(
                """INSERT INTO corporate_action_watermark (singleton, last_checked_date, updated_at)
                   VALUES (1, ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET
                   last_checked_date=CASE WHEN excluded.last_checked_date > last_checked_date
                                          THEN excluded.last_checked_date
                                          ELSE last_checked_date END,
                   updated_at=excluded.updated_at""",
                (checked_date.isoformat(), now),
            )

