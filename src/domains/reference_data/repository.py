"""Instrument identity, token history, and dated universe persistence."""

import hashlib
import json
from collections.abc import Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import sqlite_connection

from .schema import migrate_reference_data


@dataclass(frozen=True)
class TrackedInstrument:
    instrument_id: str
    isin: str
    symbol: str
    exchange: str
    provider_token: str
    observed_on: date
    series: str = "EQ"


class ReferenceDataRepository:
    """Own instrument identity, token, and universe snapshot operations."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        migrate_reference_data(self.path)

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
                        item.instrument_id, item.isin, item.symbol, item.exchange,
                        item.provider_token, item.observed_on.isoformat(), item.series,
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
                   ORDER BY snapshot_date DESC LIMIT 1""",
                (index_name, as_of.isoformat()),
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

    def universe_snapshot_members(
        self, snapshot_id: str, *, limit: int = 500, offset: int = 0
    ) -> list[dict[str, object]]:
        if not snapshot_id or not 1 <= limit <= 1000 or offset < 0:
            raise DomainValidationError("universe snapshot member query is invalid")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT isin, symbol, company_name, industry, series FROM universe_snapshot_members
                   WHERE snapshot_id=? ORDER BY symbol, isin LIMIT ? OFFSET ?""",
                (snapshot_id, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_universe_snapshots(
        self, index_name: str, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, object]]:
        if not index_name or not 1 <= limit <= 500 or offset < 0:
            raise DomainValidationError("universe snapshot query is invalid")
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                "SELECT snapshot_id, index_name, snapshot_date, source_url, source_hash, member_count, created_at FROM universe_snapshots WHERE index_name=? ORDER BY snapshot_date DESC LIMIT ? OFFSET ?",
                (index_name, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_universe_snapshot(
        self,
        *,
        snapshot_id: str,
        index_name: str,
        snapshot_date: date,
        source_url: str,
        raw_csv: bytes,
        members: Iterable[dict[str, object]],
    ) -> dict[str, object]:
        rows = tuple(members)
        required = {"isin", "symbol", "company_name", "industry", "series"}
        if (
            not snapshot_id
            or not index_name
            or not source_url
            or not raw_csv
            or not rows
            or any(
                set(row) != required
                or any(not isinstance(row[key], str) or not row[key].strip() for key in required)
                for row in rows
            )
            or len({str(row["isin"]).upper() for row in rows}) != len(rows)
        ):
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
                (
                    snapshot_id,
                    index_name,
                    snapshot_date.isoformat(),
                    source_url,
                    source_hash,
                    len(rows),
                    raw_csv,
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.executemany(
                """INSERT INTO universe_snapshot_members
                   (snapshot_id, isin, symbol, company_name, industry, series) VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        snapshot_id,
                        row["isin"].upper(),
                        row["symbol"].upper(),
                        row["company_name"],
                        row["industry"],
                        row["series"].upper(),
                    )
                    for row in rows
                ],
            )
        return self.universe_snapshot(index_name, snapshot_date) or {}

    def universe_snapshot_diff(
        self, older_snapshot_id: str, newer_snapshot_id: str
    ) -> dict[str, list[dict[str, object]]]:
        with sqlite_connection(self.path, read_only=True, row_factory=True) as connection:

            def members(snapshot_id: str) -> dict[str, dict[str, object]]:
                rows = connection.execute(
                    "SELECT isin, symbol, company_name, industry, series FROM universe_snapshot_members WHERE snapshot_id=?",
                    (snapshot_id,),
                ).fetchall()
                return {str(row["isin"]): dict(row) for row in rows}

            older, newer = members(older_snapshot_id), members(newer_snapshot_id)
        if not older and not newer:
            raise DomainValidationError("universe snapshots were not found")
        return {
            "additions": [newer[key] for key in sorted(newer.keys() - older.keys())],
            "removals": [older[key] for key in sorted(older.keys() - newer.keys())],
            "series_transitions": [
                {"isin": key, "from": older[key]["series"], "to": newer[key]["series"]}
                for key in sorted(older.keys() & newer.keys())
                if older[key]["series"] != newer[key]["series"]
            ],
        }

    def record_exit_eligibility(
        self,
        *,
        instrument_id: str,
        isin: str,
        symbol: str,
        decision_date: date,
        decision_snapshot_id: str,
        target_session_date: date | None,
        session_source: str = "declared",
    ) -> bool:
        """Persist a universe-exit eligibility record for one-session exit-only coverage."""
        if (
            not instrument_id
            or not isin
            or not symbol
            or not decision_snapshot_id
            or target_session_date is not None
            and decision_date >= target_session_date
            or session_source not in {"declared", "observed_market", "pending"}
        ):
            raise DomainValidationError("exit eligibility record is invalid")
        with sqlite_connection(self.path) as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO universe_exit_eligibility
                   (instrument_id, isin, symbol, decision_date, decision_snapshot_id,
                    target_session_date, exit_only, created_at, session_source)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    instrument_id,
                    isin,
                    symbol,
                    decision_date.isoformat(),
                    decision_snapshot_id,
                    target_session_date.isoformat() if target_session_date else None,
                    datetime.now(UTC).isoformat(),
                    session_source if target_session_date else "pending",
                ),
            )
        return cursor.rowcount == 1

    def exit_eligible_instruments(
        self, *, target_date: date | None = None
    ) -> list[dict[str, object]]:
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
                        item["isin"],
                        item["instrument_id"],
                        item["symbol"],
                        item["exchange"],
                        item["membership_type"],
                        item["first_eligible_date"],
                        item["initial_market_cap"],
                        item["threshold_crore"],
                        item["source"],
                        item["snapshot_date"],
                        item["last_market_cap"],
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
                        item["isin"],
                        item["instrument_id"],
                        item["symbol"],
                        item["exchange"],
                        item["membership_type"],
                        item["first_eligible_date"],
                        item["initial_market_cap"],
                        item["threshold_crore"],
                        item["source"],
                        item["snapshot_date"],
                        item["last_market_cap"],
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
                    snapshot_date,
                    threshold_crore,
                    source,
                    total_tracked,
                    resolved_count,
                    unresolved_count,
                    len(values),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return len(values)

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
                   instrument_id = COALESCE(corporate_action_events.instrument_id, excluded.instrument_id),
                   ratio_numerator = CASE WHEN corporate_action_events.state='DETECTED'
                       THEN COALESCE(excluded.ratio_numerator, corporate_action_events.ratio_numerator)
                       ELSE corporate_action_events.ratio_numerator END,
                   ratio_denominator = CASE WHEN corporate_action_events.state='DETECTED'
                       THEN COALESCE(excluded.ratio_denominator, corporate_action_events.ratio_denominator)
                       ELSE corporate_action_events.ratio_denominator END,
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
                    now,
                    now,
                ),
            )
        return existing is None
    def actionable_corporate_events(
        self, *, states: tuple[str, ...] | None = None
    ) -> list[dict[str, object]]:
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
        self,
        event_id: str,
        new_state: str,
        *,
        attempt_outcome: str | None = None,
        applied_factor: float | None = None,
        baseline_revision: str | None = None,
        verification_evidence: dict[str, object] | None = None,
        transaction_connection=None,
    ) -> bool:
        """Transition a corporate action event to a new state."""
        valid_states = {"DETECTED", "SELF_ADJUSTED", "MONITORING", "VERIFIED", "FAILED"}
        if new_state not in valid_states:
            raise DomainValidationError(f"invalid CA state: {new_state}")
        now = datetime.now(UTC).isoformat()
        with (
            nullcontext(transaction_connection)
            if transaction_connection is not None
            else sqlite_connection(self.path)
        ) as connection:
            cursor = connection.execute(
                """UPDATE corporate_action_events SET
                   state=?, attempt_count=attempt_count+1,
                   last_attempt_at=?, last_attempt_outcome=?,
                   applied_factor=COALESCE(?, applied_factor),
                   baseline_revision=COALESCE(?, baseline_revision),
                   verification_evidence_json=COALESCE(?, verification_evidence_json),
                   verified_at=CASE WHEN ?='VERIFIED' THEN ? ELSE verified_at END,
                   updated_at=?
                   WHERE event_id=?""",
                (
                    new_state,
                    now,
                    attempt_outcome,
                    applied_factor,
                    baseline_revision,
                    json.dumps(verification_evidence, sort_keys=True)
                    if verification_evidence is not None
                    else None,
                    new_state,
                    now,
                    now,
                    event_id,
                ),
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
