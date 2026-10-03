"""Content-addressed indicator node cache in SQLite.

Stores computed indicator series keyed by ``(node_hash, instrument_id, date)``
rather than by strategy.  Two strategies that reference the same EMA(50) node
share a single cached result because the node content hash is identical.

The cache is additive.  Rows are inserted or replaced; they are never deleted
except by an explicit administrative wipe.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime
from pathlib import Path

from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


class IndicatorNodeCache:
    """Persistent content-addressed indicator cache.

    The primary key is ``(node_hash, instrument_id, as_of_date)``.
    ``node_hash`` is the deterministic SHA-256 of a ``DagNode``'s computation
    definition (provider, function, parameters, inputs), making the cache
    agnostic to which strategy declared the node.
    """

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        migrate_sqlite(
            self.database,
            "indicator_node_cache",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS indicator_node_cache (
                        node_hash TEXT NOT NULL,
                        instrument_id TEXT NOT NULL,
                        as_of_date TEXT NOT NULL,
                        value_json TEXT NOT NULL,
                        source_snapshot_id TEXT NOT NULL,
                        calculated_at TEXT NOT NULL,
                        market_revision TEXT NOT NULL DEFAULT '',
                        implementation_revision TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (node_hash, instrument_id, as_of_date)
                    )""",
                    ("CREATE INDEX IF NOT EXISTS idx_node_cache_hash_date "
                     "ON indicator_node_cache(node_hash, as_of_date)"),
                    ("CREATE INDEX IF NOT EXISTS idx_node_cache_instrument "
                     "ON indicator_node_cache(instrument_id, as_of_date)"),
                    "CREATE INDEX IF NOT EXISTS idx_node_cache_revisions ON indicator_node_cache(instrument_id, market_revision, implementation_revision)",
                ),
            },
        )

    @staticmethod
    def _require_revisions(market_revision: str, implementation_revision: str) -> None:
        if (not isinstance(market_revision, str) or not market_revision.strip()
                or not isinstance(implementation_revision, str) or not implementation_revision.strip()):
            raise DomainValidationError("cache requires market and implementation revisions")

    # ------------------------------------------------------------------
    # Single-value operations
    # ------------------------------------------------------------------

    def get(
        self,
        node_hash: str,
        instrument_id: str,
        as_of_date: date,
        *,
        market_revision: str,
        implementation_revision: str,
    ) -> float | None:
        """Return a cached scalar value, or ``None`` if absent."""
        self._require_revisions(market_revision, implementation_revision)
        with sqlite_connection(self.database, read_only=True, row_factory=True) as conn:
            sql = "SELECT value_json FROM indicator_node_cache WHERE node_hash=? AND instrument_id=? AND as_of_date=?"
            args: list[object] = [node_hash, instrument_id, as_of_date.isoformat()]
            if market_revision is not None:
                sql += " AND market_revision=?"
                args.append(market_revision)
            if implementation_revision is not None:
                sql += " AND implementation_revision=?"
                args.append(implementation_revision)
            row = conn.execute(sql, args).fetchone()
        if row is None:
            return None
        return float(json.loads(row["value_json"]))

    def put(
        self,
        node_hash: str,
        instrument_id: str,
        as_of_date: date,
        value: float,
        source_snapshot_id: str,
        *,
        market_revision: str,
        implementation_revision: str,
    ) -> None:
        """Insert or replace a single cached value."""
        self._require_revisions(market_revision, implementation_revision)
        try:
            finite = math.isfinite(float(value))
        except (TypeError, ValueError):
            finite = False
        if not finite:
            raise DomainValidationError("cache value must be finite")
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as conn:
            conn.execute(
                """INSERT INTO indicator_node_cache
                   (node_hash, instrument_id, as_of_date, value_json,
                    source_snapshot_id, calculated_at, market_revision, implementation_revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(node_hash, instrument_id, as_of_date) DO UPDATE SET
                   value_json = excluded.value_json,
                   source_snapshot_id = excluded.source_snapshot_id,
                   calculated_at = excluded.calculated_at,
                   market_revision = excluded.market_revision,
                   implementation_revision = excluded.implementation_revision""",
                (
                    node_hash,
                    instrument_id,
                    as_of_date.isoformat(),
                    json.dumps(value),
                    source_snapshot_id,
                    now,
                    market_revision,
                    implementation_revision,
                ),
            )

    # ------------------------------------------------------------------
    # Bulk operations (used by research jobs)
    # ------------------------------------------------------------------

    def get_series(
        self,
        node_hash: str,
        instrument_id: str,
        start_date: date,
        end_date: date,
        *,
        market_revision: str,
        implementation_revision: str,
    ) -> dict[str, float]:
        """Return cached values for one node + instrument over a date range.

        Returns ``{iso_date_string: value}`` for each cached row.
        """
        self._require_revisions(market_revision, implementation_revision)
        with sqlite_connection(self.database, read_only=True, row_factory=True) as conn:
            sql = """SELECT as_of_date, value_json FROM indicator_node_cache
                     WHERE node_hash=? AND instrument_id=? AND as_of_date BETWEEN ? AND ?"""
            args: list[object] = [node_hash, instrument_id, start_date.isoformat(), end_date.isoformat()]
            if market_revision is not None:
                sql += " AND market_revision=?"
                args.append(market_revision)
            if implementation_revision is not None:
                sql += " AND implementation_revision=?"
                args.append(implementation_revision)
            rows = conn.execute(sql + " ORDER BY as_of_date", args).fetchall()
        return {str(row["as_of_date"]): float(json.loads(row["value_json"])) for row in rows}

    def get_bulk(
        self,
        node_hashes: set[str],
        start_date: date,
        end_date: date,
        *,
        revisions: dict[str, str],
        implementation_revision: str,
    ) -> dict[str, dict[str, dict[str, float]]]:
        """Return cached values for multiple nodes across all instruments.

        Returns ``{node_hash: {instrument_id: {iso_date: value}}}``.
        """
        if not isinstance(revisions, dict) or not isinstance(implementation_revision, str) or not implementation_revision.strip():
            raise DomainValidationError("bulk cache requires market and implementation revisions")
        for revision in revisions.values():
            self._require_revisions(revision, implementation_revision)
        if not node_hashes:
            return {}
        result: dict[str, dict[str, dict[str, float]]] = {h: {} for h in node_hashes}
        # SQLite parameter limit is 999; batch if needed
        hash_list = sorted(node_hashes)
        for batch_start in range(0, len(hash_list), 900):
            batch = hash_list[batch_start : batch_start + 900]
            placeholders = ",".join("?" * len(batch))
            with sqlite_connection(self.database, read_only=True, row_factory=True) as conn:
                rows = conn.execute(
                    f"""SELECT node_hash, instrument_id, as_of_date, value_json,
                               market_revision, implementation_revision
                        FROM indicator_node_cache
                        WHERE node_hash IN ({placeholders}) AND as_of_date BETWEEN ? AND ?
                        ORDER BY node_hash, instrument_id, as_of_date""",
                    (*batch, start_date.isoformat(), end_date.isoformat()),
                ).fetchall()
            for row in rows:
                nh = str(row["node_hash"])
                iid = str(row["instrument_id"])
                if str(row["market_revision"]) != revisions.get(iid):
                    continue
                if str(row["implementation_revision"]) != implementation_revision:
                    continue
                day = str(row["as_of_date"])
                result.setdefault(nh, {}).setdefault(iid, {})[day] = float(
                    json.loads(row["value_json"])
                )
        return result

    def put_bulk(
        self,
        node_hash: str,
        values: dict[str, dict[str, float]],
        source_snapshot_id: str,
        *,
        market_revisions: dict[str, str],
        implementation_revision: str,
    ) -> int:
        """Bulk insert cached values for one node across instruments and dates.

        Parameters
        ----------
        node_hash : str
            The content hash of the DAG node.
        values : dict[str, dict[str, float]]
            ``{instrument_id: {iso_date: value}}``.
        source_snapshot_id : str
            Provenance identifier.

        Returns
        -------
        int
            Number of rows written.
        """
        if not isinstance(market_revisions, dict) or not isinstance(implementation_revision, str) or not implementation_revision.strip():
            raise DomainValidationError("bulk cache requires market and implementation revisions")
        for instrument_id in values:
            self._require_revisions(market_revisions.get(instrument_id), implementation_revision)
        if not values:
            return 0
        now = datetime.now(UTC).isoformat()
        rows: list[tuple[str, str, str, str, str, str, str, str]] = []
        for instrument_id, series in values.items():
            for day, value in series.items():
                try:
                    finite = math.isfinite(float(value))
                except (TypeError, ValueError):
                    finite = False
                if not finite:
                    raise DomainValidationError("cache value must be finite")
                rows.append((
                    node_hash,
                    instrument_id,
                    day,
                    json.dumps(value),
                    source_snapshot_id,
                    now,
                    market_revisions[instrument_id],
                    implementation_revision,
                ))
        with sqlite_connection(self.database) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                """INSERT INTO indicator_node_cache
                   (node_hash, instrument_id, as_of_date, value_json,
                    source_snapshot_id, calculated_at, market_revision, implementation_revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(node_hash, instrument_id, as_of_date) DO UPDATE SET
                   value_json = excluded.value_json,
                   source_snapshot_id = excluded.source_snapshot_id,
                   calculated_at = excluded.calculated_at,
                   market_revision = excluded.market_revision,
                   implementation_revision = excluded.implementation_revision""",
                rows,
            )
        return len(rows)

    def has_coverage(
        self,
        node_hash: str,
        instrument_id: str,
        dates: set[str], *, market_revision: str, implementation_revision: str,
    ) -> bool:
        """Return whether all requested dates match both cache identities."""
        self._require_revisions(market_revision, implementation_revision)
        if not dates:
            return True
        sorted_dates = sorted(dates)
        with sqlite_connection(self.database, read_only=True, row_factory=True) as conn:
            rows = conn.execute(
                """SELECT as_of_date FROM indicator_node_cache
                   WHERE node_hash = ? AND instrument_id = ?
                   AND market_revision = ? AND implementation_revision = ?
                   AND as_of_date BETWEEN ? AND ?""",
                (node_hash, instrument_id, market_revision, implementation_revision,
                 sorted_dates[0], sorted_dates[-1]),
            ).fetchall()
        cached = {str(row["as_of_date"]) for row in rows}
        return dates.issubset(cached)

    def cached_node_hashes(self) -> set[str]:
        """Return the set of distinct node hashes that have cached data."""
        with sqlite_connection(self.database, read_only=True, row_factory=True) as conn:
            rows = conn.execute(
                "SELECT DISTINCT node_hash FROM indicator_node_cache"
            ).fetchall()
        return {str(row["node_hash"]) for row in rows}

    def row_count(self, node_hash: str | None = None) -> int:
        """Return the total number of cached rows, optionally filtered by node."""
        with sqlite_connection(self.database, read_only=True, row_factory=True) as conn:
            if node_hash is not None:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM indicator_node_cache WHERE node_hash = ?",
                    (node_hash,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM indicator_node_cache"
                ).fetchone()
        return int(row["cnt"]) if row else 0

    def invalidate_instrument(self, instrument_id: str) -> int:
        """Remove cached values for a changed market history only."""
        if not instrument_id:
            raise ValueError("instrument_id is required")
        with sqlite_connection(self.database) as conn:
            cursor = conn.execute(
                "DELETE FROM indicator_node_cache WHERE instrument_id=?", (instrument_id,)
            )
        return int(cursor.rowcount)
