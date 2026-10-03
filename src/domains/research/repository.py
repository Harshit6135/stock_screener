"""Research-owned SQLite schema and persisted read/write models."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


class ResearchRepository:
    """Own persisted daily scores, rankings, percentile caches, and lineage."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        migrate_sqlite(
            self.database,
            "research",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS research_daily_scores (
                        strategy_id TEXT NOT NULL, strategy_revision_id TEXT NOT NULL,
                        as_of_date TEXT NOT NULL, instrument_id TEXT NOT NULL,
                        symbol TEXT NOT NULL, score REAL NOT NULL, penalty REAL NOT NULL,
                        artifact_id TEXT NOT NULL,
                        PRIMARY KEY(strategy_revision_id, as_of_date, instrument_id))""",
                    "CREATE INDEX IF NOT EXISTS research_daily_scores_date ON research_daily_scores(strategy_revision_id, as_of_date)",
                    """CREATE TABLE IF NOT EXISTS research_weekly_rankings (
                        strategy_id TEXT NOT NULL, strategy_revision_id TEXT NOT NULL,
                        week_end TEXT NOT NULL, instrument_id TEXT NOT NULL,
                        symbol TEXT NOT NULL, score REAL NOT NULL, rank INTEGER NOT NULL,
                        artifact_id TEXT NOT NULL,
                        PRIMARY KEY(strategy_revision_id, week_end, instrument_id))""",
                    "CREATE INDEX IF NOT EXISTS research_weekly_rankings_date ON research_weekly_rankings(strategy_revision_id, week_end, rank)",
                    """CREATE TABLE IF NOT EXISTS research_percentiles (
                        snapshot_id TEXT NOT NULL, as_of_date TEXT NOT NULL,
                        instrument_id TEXT NOT NULL, symbol TEXT NOT NULL,
                        factor_name TEXT NOT NULL, raw_value REAL,
                        percentile_rank REAL NOT NULL,
                        PRIMARY KEY(snapshot_id, as_of_date, instrument_id, factor_name))""",
                    """CREATE TABLE IF NOT EXISTS research_percentile_snapshots (
                        snapshot_id TEXT PRIMARY KEY, strategy_revision_id TEXT NOT NULL,
                        as_of_date TEXT NOT NULL, universe_snapshot_id TEXT,
                        indicator_code_hash TEXT, input_fingerprint TEXT NOT NULL,
                        created_at TEXT NOT NULL)""",
                    "CREATE INDEX IF NOT EXISTS research_percentile_snapshots_date ON research_percentile_snapshots(strategy_revision_id, as_of_date)",
                    """CREATE TABLE IF NOT EXISTS research_lineage (
                        artifact_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL,
                        strategy_revision_id TEXT NOT NULL, indicator_code_hash TEXT,
                        universe_snapshot_id TEXT, market_data_start TEXT,
                        market_data_end TEXT, market_history_revision TEXT,
                        percentile_snapshot_id TEXT, computed_at TEXT NOT NULL)""",
                ),
            },
        )

    def upsert_percentile_snapshot(
        self,
        snapshot_id: str,
        strategy_revision_id: str,
        as_of_date: str,
        input_fingerprint: str,
        percentiles: dict[str, dict[str, tuple[float | None, float]]],
        symbols: dict[str, str],
        *,
        universe_snapshot_id: str | None = None,
        indicator_code_hash: str | None = None,
    ) -> dict[str, object]:
        """Persist a cross-sectional percentile snapshot atomically.

        ``percentiles`` maps instrument_id -> factor_name -> (raw_value, percentile_rank).
        """

        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR IGNORE INTO research_percentile_snapshots
                   (snapshot_id, strategy_revision_id, as_of_date, universe_snapshot_id,
                    indicator_code_hash, input_fingerprint, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    strategy_revision_id,
                    as_of_date,
                    universe_snapshot_id,
                    indicator_code_hash,
                    input_fingerprint,
                    now,
                ),
            )
            rows_written = 0
            for instrument_id, factors in percentiles.items():
                symbol = symbols.get(instrument_id, "")
                for factor_name, (raw_value, percentile_rank) in factors.items():
                    connection.execute(
                        """INSERT OR REPLACE INTO research_percentiles
                           (snapshot_id, as_of_date, instrument_id, symbol, factor_name,
                            raw_value, percentile_rank)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            snapshot_id,
                            as_of_date,
                            instrument_id,
                            symbol,
                            factor_name,
                            raw_value,
                            percentile_rank,
                        ),
                    )
                    rows_written += 1
        return {"snapshot_id": snapshot_id, "rows": rows_written}

    def read_percentile_snapshot(
        self, input_fingerprint: str, as_of_date: str
    ) -> dict[str, dict[str, float]] | None:
        """Look up a cached percentile snapshot by fingerprint and date.

        Returns instrument_id -> factor_name -> percentile_rank, or None if not found.
        """
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            meta = connection.execute(
                """SELECT snapshot_id FROM research_percentile_snapshots
                   WHERE input_fingerprint=? AND as_of_date=?""",
                (input_fingerprint, as_of_date),
            ).fetchone()
            if meta is None:
                return None
            rows = connection.execute(
                "SELECT * FROM research_percentiles WHERE snapshot_id=? AND as_of_date=?",
                (meta["snapshot_id"], as_of_date),
            ).fetchall()
        result: dict[str, dict[str, float]] = {}
        for row in rows:
            inst = str(row["instrument_id"])
            result.setdefault(inst, {})[str(row["factor_name"])] = float(row["percentile_rank"])
        return result

    def record_lineage(
        self,
        artifact_id: str,
        strategy_id: str,
        strategy_revision_id: str,
        *,
        indicator_code_hash: str | None = None,
        universe_snapshot_id: str | None = None,
        market_data_start: str | None = None,
        market_data_end: str | None = None,
        market_history_revision: str | None = None,
        percentile_snapshot_id: str | None = None,
    ) -> None:
        """Attach lineage metadata to a research artifact."""

        now = datetime.now(UTC).isoformat()
        values = (
            artifact_id,
            strategy_id,
            strategy_revision_id,
            indicator_code_hash,
            universe_snapshot_id,
            market_data_start,
            market_data_end,
            market_history_revision,
            percentile_snapshot_id,
        )
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """SELECT artifact_id, strategy_id, strategy_revision_id, indicator_code_hash,
                          universe_snapshot_id, market_data_start, market_data_end,
                          market_history_revision, percentile_snapshot_id
                   FROM research_lineage WHERE artifact_id=?""",
                (artifact_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != values:
                    raise DomainValidationError("published research lineage is immutable")
                return
            connection.execute(
                """INSERT INTO research_lineage
                   (artifact_id, strategy_id, strategy_revision_id, indicator_code_hash,
                    universe_snapshot_id, market_data_start, market_data_end,
                    market_history_revision, percentile_snapshot_id, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*values, now),
            )

    def read_lineage(self, artifact_id: str) -> dict[str, object] | None:
        """Retrieve lineage metadata for a research artifact."""
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM research_lineage WHERE artifact_id=?",
                (artifact_id,),
            ).fetchone()
        return dict(row) if row else None

    def replace_daily_score_range(
        self,
        strategy_revision_id: str,
        start_date: str,
        end_date: str,
        rows: list[tuple[object, ...]],
    ) -> None:
        """Atomically replace a revision’s complete daily-score range."""
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """DELETE FROM research_daily_scores
                   WHERE strategy_revision_id=? AND as_of_date BETWEEN ? AND ?""",
                (strategy_revision_id, start_date, end_date),
            )
            connection.executemany(
                """INSERT INTO research_daily_scores
                   (strategy_id, strategy_revision_id, as_of_date, instrument_id,
                    symbol, score, penalty, artifact_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

    def upsert_daily_scores_for_date(
        self,
        strategy_revision_id: str,
        as_of_date: str,
        rows: list[tuple[object, ...]],
        requested_symbols: tuple[str, ...] | None,
    ) -> None:
        """Replace selected date rows and upsert the newly computed score set."""
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if requested_symbols is None:
                connection.execute(
                    "DELETE FROM research_daily_scores WHERE strategy_revision_id=? AND as_of_date=?",
                    (strategy_revision_id, as_of_date),
                )
            else:
                connection.executemany(
                    """DELETE FROM research_daily_scores
                       WHERE strategy_revision_id=? AND as_of_date=?
                         AND (instrument_id=? OR symbol=?)""",
                    [
                        (strategy_revision_id, as_of_date, symbol, symbol)
                        for symbol in requested_symbols
                    ],
                )
            connection.executemany(
                """INSERT INTO research_daily_scores
                   (strategy_id, strategy_revision_id, as_of_date, instrument_id, symbol,
                    score, penalty, artifact_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(strategy_revision_id, as_of_date, instrument_id) DO UPDATE SET
                   score=excluded.score, penalty=excluded.penalty, artifact_id=excluded.artifact_id""",
                rows,
            )

    def daily_scores(
        self, strategy_revision_id: str, start_date: str, end_date: str
    ) -> list[dict[str, object]]:
        """Read stored daily score rows in date order for weekly ranking."""
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM research_daily_scores WHERE strategy_revision_id=?
                   AND as_of_date BETWEEN ? AND ? ORDER BY as_of_date, instrument_id""",
                (strategy_revision_id, start_date, end_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_weekly_rankings(
        self,
        strategy_id: str,
        strategy_revision_id: str,
        week_end: str,
        artifact_id: str,
        members: list[dict[str, object]],
    ) -> None:
        """Atomically replace a revision’s ranking projection for one week."""
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM research_weekly_rankings WHERE strategy_revision_id=? AND week_end=?",
                (strategy_revision_id, week_end),
            )
            connection.executemany(
                """INSERT INTO research_weekly_rankings
                   (strategy_id, strategy_revision_id, week_end, instrument_id, symbol,
                    score, rank, artifact_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(strategy_revision_id, week_end, instrument_id) DO UPDATE SET
                   score=excluded.score, rank=excluded.rank, artifact_id=excluded.artifact_id""",
                [
                    (
                        strategy_id,
                        strategy_revision_id,
                        week_end,
                        member["instrument_id"],
                        member["symbol"],
                        member["composite_score"],
                        member["rank"],
                        artifact_id,
                    )
                    for member in members
                ],
            )

    def top_rankings(
        self, strategy_revision_id: str, week_end: str, limit: int
    ) -> list[dict[str, object]]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM research_weekly_rankings WHERE strategy_revision_id=?
                   AND week_end=? ORDER BY rank LIMIT ?""",
                (strategy_revision_id, week_end, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_rankings(self, strategy_revision_id: str, week_end: str) -> list[dict[str, object]]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT * FROM research_weekly_rankings WHERE strategy_revision_id=?
                   AND week_end=? ORDER BY rank""",
                (strategy_revision_id, week_end),
            ).fetchall()
        return [dict(row) for row in rows]

    def ranking_weeks(self, strategy_revision_id: str) -> tuple[str, ...]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT DISTINCT week_end FROM research_weekly_rankings
                   WHERE strategy_revision_id=? ORDER BY week_end""",
                (strategy_revision_id,),
            ).fetchall()
        return tuple(str(row["week_end"]) for row in rows)
