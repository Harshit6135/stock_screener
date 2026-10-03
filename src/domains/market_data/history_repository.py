"""Market history, quality, indicator cache, and fetch-coverage persistence."""

import hashlib
import json
import math
import sqlite3
from collections.abc import Iterable
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from src.platform_kernel import DomainValidationError
from src.platform_kernel.security import sanitize_sensitive
from src.platform_kernel.sqlite import sqlite_connection

from .api import NormalizedBar


class MarketHistoryRepositoryMixin:
    """Market history operations over a database initialized by its composition root."""

    @staticmethod
    def _validate_bars(bars: tuple[NormalizedBar, ...]) -> None:
        """Reject impossible OHLCV rows before they can contaminate projections."""
        for bar in bars:
            values = (float(bar.open), float(bar.high), float(bar.low), float(bar.close))
            if not all(math.isfinite(value) and value > 0 for value in values):
                raise DomainValidationError("market bar prices must be positive finite values")
            if float(bar.low) > min(float(bar.open), float(bar.close)) or float(bar.high) < max(
                float(bar.open), float(bar.close)
            ):
                raise DomainValidationError("market bar OHLC bounds are invalid")
            if isinstance(bar.volume, bool) or int(bar.volume) < 0:
                raise DomainValidationError("market bar volume must be non-negative")

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
                """SELECT * FROM (SELECT * FROM market_bars WHERE instrument_id = ?
                   AND as_of_date BETWEEN ? AND ? ORDER BY as_of_date DESC LIMIT ?)
                   ORDER BY as_of_date""",
                (instrument_id, actual_start.isoformat(), actual_end.isoformat(), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def history_snapshot_rows(
        self, instrument_ids: Iterable[str], start_date: date, end_date: date
    ) -> list[tuple[str, str, str]]:
        """Read sorted source identities for reproducible replay fingerprints."""
        if start_date > end_date:
            raise DomainValidationError("market history fingerprint range is invalid")
        identifiers = tuple(sorted(set(instrument_ids)))
        if not identifiers:
            return []
        placeholders = ",".join("?" for _ in identifiers)
        with sqlite_connection(self.path, read_only=True) as connection:
            rows = connection.execute(
                """SELECT instrument_id, as_of_date, snapshot_id FROM market_bars
                   WHERE instrument_id IN ("""
                + placeholders
                + ") AND as_of_date BETWEEN ? AND ? ORDER BY instrument_id, as_of_date",
                (*identifiers, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]

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


    def delete_bars_after(self, cutoff: date, instrument_id: str | None = None) -> int:
        """Delete mutable bar projections before a cutoff."""
        if not isinstance(cutoff, date):
            raise DomainValidationError("cutoff must be a date")
        with sqlite_connection(self.path) as connection:
            if instrument_id is None:
                cursor = connection.execute(
                    "DELETE FROM market_bars WHERE as_of_date > ?", (cutoff.isoformat(),)
                )
                connection.execute(
                    "DELETE FROM market_indicators WHERE as_of_date > ?", (cutoff.isoformat(),)
                )
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

    def has_coverage(
        self,
        instrument_id: str,
        start_date: date,
        end_date: date,
        provider: str = "kite",
        coverage_context: str = "regular",
    ) -> bool:
        """Return whether completed provider windows cover the full calendar range."""
        if (
            start_date > end_date
            or not provider.strip()
            or coverage_context not in {"regular", "exit_only"}
        ):
            raise DomainValidationError("market fetch coverage range is invalid")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT start_date, end_date FROM market_fetch_coverage
                   WHERE instrument_id=? AND provider=? AND coverage_context=?
                   AND end_date>=? AND start_date<=?
                   ORDER BY start_date, end_date""",
                (
                    instrument_id,
                    provider,
                    coverage_context,
                    start_date.isoformat(),
                    end_date.isoformat(),
                ),
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
            grouped.setdefault(str(row["instrument_id"]), {})[str(row["as_of_date"])] = json.loads(
                row["values_json"]
            )
        return grouped

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

    def latest_market_date(self) -> date | None:
        """Return the latest as_of_date recorded across all market bars."""
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT MAX(as_of_date) AS max_date FROM market_bars"
            ).fetchone()
        if row is not None and row["max_date"]:
            return date.fromisoformat(row["max_date"])
        return None

    def market_history_revision(self, instrument_id: str) -> str:
        """Return the current input identity used by indicator-cache reads."""
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT revision FROM market_history_revisions WHERE instrument_id=?",
                (instrument_id,),
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


    def quality_events(
        self,
        *,
        instrument_id: str | None = None,
        check_type: str | None = None,
        severity: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 500
            or isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or any(
                value is not None and (not isinstance(value, str) or not value.strip())
                for value in (instrument_id, check_type)
            )
            or (
                severity is not None
                and (not isinstance(severity, str) or severity not in {"INFO", "WARNING", "ERROR"})
            )
        ):
            raise DomainValidationError("quality event filters are invalid")
        clauses: list[str] = []
        args: list[object] = []
        for column, value in (
            ("instrument_id", instrument_id),
            ("check_type", check_type),
            ("severity", severity),
        ):
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

    def record_fetch_coverage(
        self,
        instrument_id: str,
        start_date: date,
        end_date: date,
        *,
        provider: str,
        bar_count: int,
        coverage_context: str = "regular",
    ) -> None:
        """Record a completed provider request, including valid empty ranges."""
        if (
            start_date > end_date
            or not provider.strip()
            or bar_count < 0
            or coverage_context not in {"regular", "exit_only"}
        ):
            raise DomainValidationError("market fetch coverage is invalid")
        with sqlite_connection(self.path) as connection:
            connection.execute(
                """INSERT INTO market_fetch_coverage
                   (instrument_id, start_date, end_date, provider, coverage_context, fetched_at, bar_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(instrument_id, start_date, end_date, provider, coverage_context) DO UPDATE SET
                   fetched_at=excluded.fetched_at, bar_count=excluded.bar_count""",
                (
                    instrument_id,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    provider,
                    coverage_context,
                    datetime.now(UTC).isoformat(),
                    bar_count,
                ),
            )

    def record_quality_event(
        self,
        instrument_id: str,
        as_of_date: date,
        check_type: str,
        severity: str,
        detail: dict[str, object],
    ) -> bool:
        """Persist one idempotent, operator-visible data-quality observation."""
        if (
            not isinstance(instrument_id, str)
            or not instrument_id.strip()
            or not isinstance(as_of_date, date)
            or isinstance(as_of_date, datetime)
            or not isinstance(check_type, str)
            or not check_type.strip()
            or not isinstance(severity, str)
            or severity not in {"INFO", "WARNING", "ERROR"}
            or not isinstance(detail, dict)
        ):
            raise DomainValidationError("data quality event is invalid")
        encoded = json.dumps(
            sanitize_sensitive(detail), sort_keys=True, separators=(",", ":"), default=str
        )
        with sqlite_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO data_quality_events
                       (event_id, instrument_id, as_of_date, check_type, severity, detail_json, detected_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()),
                        instrument_id,
                        as_of_date.isoformat(),
                        check_type,
                        severity,
                        encoded,
                        datetime.now(UTC).isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DomainValidationError(
                    "quality event instrument is not registered"
                ) from exc
        return cursor.rowcount == 1


    def upsert_bars(
        self,
        instrument_id: str,
        bars: Iterable[NormalizedBar],
        snapshot_id: str,
        *,
        has_traded_volume: bool,
        transaction_connection=None,
    ) -> int:
        values = tuple(bars)
        if not isinstance(has_traded_volume, bool):
            raise DomainValidationError("market history requires instrument volume classification")
        if not values or len({bar.as_of_date for bar in values}) != len(values):
            raise DomainValidationError("market bar batch is empty or has duplicate dates")
        if any(bar.instrument_id != instrument_id for bar in values):
            raise DomainValidationError("market bar instrument identity does not match")
        self._validate_bars(values)
        with (
            nullcontext(transaction_connection)
            if transaction_connection is not None
            else sqlite_connection(self.path, row_factory=True)
        ) as connection:
            if transaction_connection is None:
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
                Decimal(str(row["open"])) != Decimal(str(incoming[row["as_of_date"]].open))
                or Decimal(str(row["high"])) != Decimal(str(incoming[row["as_of_date"]].high))
                or Decimal(str(row["low"])) != Decimal(str(incoming[row["as_of_date"]].low))
                or Decimal(str(row["close"])) != Decimal(str(incoming[row["as_of_date"]].close))
                or int(row["volume"]) != int(incoming[row["as_of_date"]].volume)
                for row in existing
            )
            if changed:
                connection.execute(
                    "DELETE FROM market_indicators WHERE instrument_id=?", (instrument_id,)
                )
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
            zero_run = 0
            for row in prior:
                if int(row["volume"]) != 0:
                    break
                zero_run += 1
            # Evaluate the resulting stored sequence, not only the incoming
            # dates. Sparse updates must include intervening stored sessions,
            # and a corrected historical close can affect its successor.
            sequence = connection.execute(
                """SELECT as_of_date, close, volume, snapshot_id FROM market_bars
                   WHERE instrument_id=? AND as_of_date BETWEEN ? AND ?
                   ORDER BY as_of_date""",
                (instrument_id, min(dates), max(dates)),
            ).fetchall()
            following = connection.execute(
                """SELECT as_of_date, close, volume, snapshot_id FROM market_bars
                   WHERE instrument_id=? AND as_of_date > ?
                   ORDER BY as_of_date LIMIT 6""",
                (instrument_id, max(dates)),
            ).fetchall()
            for row in [*sequence, *following]:
                bar_date = str(row["as_of_date"])
                close = float(row["close"])
                if (
                    preceding_close
                    and abs(close / preceding_close - 1.0) > self.price_gap_threshold
                ):
                    detail = json.dumps(
                        {
                            "expected_close": preceding_close,
                            "actual_close": close,
                            "source_snapshot_id": row["snapshot_id"],
                            "validation_snapshot_id": snapshot_id,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    connection.execute(
                        """INSERT OR IGNORE INTO data_quality_events
                           (event_id, instrument_id, as_of_date, check_type, severity, detail_json, detected_at)
                           VALUES (?, ?, ?, 'close_gap', 'WARNING', ?, ?)""",
                        (
                            hashlib.sha256(
                                f"close-gap:{instrument_id}:{bar_date}:{preceding_close}:{close}".encode()
                            ).hexdigest(),
                            instrument_id,
                            bar_date,
                            detail,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                zero_run = zero_run + 1 if int(row["volume"]) == 0 else 0
                if has_traded_volume and zero_run == 6:
                    detail = json.dumps(
                        {
                            "consecutive_sessions": zero_run,
                            "actual_volume": 0,
                            "source_snapshot_id": row["snapshot_id"],
                            "validation_snapshot_id": snapshot_id,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    connection.execute(
                        """INSERT OR IGNORE INTO data_quality_events
                           (event_id, instrument_id, as_of_date, check_type, severity, detail_json, detected_at)
                           VALUES (?, ?, ?, 'zero_volume_streak', 'WARNING', ?, ?)""",
                        (
                            hashlib.sha256(
                                f"zero-volume:{instrument_id}:{bar_date}:{zero_run}".encode()
                            ).hexdigest(),
                            instrument_id,
                            bar_date,
                            detail,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                preceding_close = close
        return len(values)

    def upsert_indicators(
        self,
        indicator_set: str,
        as_of_date: date,
        values: dict[str, dict[str, object]],
        source_snapshot_id: str,
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
                    (
                        indicator_set,
                        instrument_id,
                        as_of_date.isoformat(),
                        json.dumps(item, sort_keys=True),
                        source_snapshot_id,
                        now,
                    )
                    for instrument_id, item in values.items()
                ],
            )
        return len(values)
