"""Gate-owned repository composition for the shared SQLite application store."""

import json
import math
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from src.domains.market_data import MarketRepository as MarketDataRepository
from src.domains.market_data import NormalizedBar
from src.domains.reference_data import ReferenceDataRepository, TrackedInstrument
from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import sqlite_connection


class MarketRepository(MarketDataRepository, ReferenceDataRepository):
    """Compose current market and reference operations for cross-owner workflows."""

    def __init__(self, path: str | Path, *, price_gap_threshold: float = 0.15):
        ReferenceDataRepository.__init__(self, path)
        MarketDataRepository.__init__(self, path, price_gap_threshold=price_gap_threshold)

    def upsert_bars(
        self,
        instrument_id: str,
        bars: Iterable[NormalizedBar],
        snapshot_id: str,
        *,
        transaction_connection=None,
    ) -> int:
        identity = self.instrument_by_id(instrument_id)
        if identity is None:
            raise DomainValidationError("market bar instrument is not registered")
        return super().upsert_bars(
            instrument_id,
            bars,
            snapshot_id,
            has_traded_volume=not str(identity["isin"]).startswith("INDEX:"),
            transaction_connection=transaction_connection,
        )

    def resolve_pending_exit_sessions(self) -> int:
        """Resolve exit dates by joining reference eligibility with market bars."""
        with sqlite_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT instrument_id, decision_snapshot_id, decision_date "
                "FROM universe_exit_eligibility WHERE target_session_date IS NULL"
            ).fetchall()
            resolved = 0
            for instrument_id, snapshot_id, decision_day in rows:
                target = connection.execute(
                    """SELECT MIN(b.as_of_date) FROM market_bars b
                       JOIN reference_instruments i ON i.instrument_id=b.instrument_id
                       WHERE i.exchange='NSE' AND i.symbol='NIFTY 500' AND b.as_of_date>?""",
                    (decision_day,),
                ).fetchone()[0]
                if target is not None:
                    connection.execute(
                        """UPDATE universe_exit_eligibility SET target_session_date=?,
                           session_source='observed_market' WHERE instrument_id=?
                           AND decision_snapshot_id=? AND target_session_date IS NULL""",
                        (target, instrument_id, snapshot_id),
                    )
                    resolved += 1
            return resolved
    def _capture_corporate_baseline(self, connection, event) -> dict[str, object] | None:
        """Preserve selected stored prices without inventing an older price basis."""
        baseline = (
            json.loads(event["baseline_prices_json"]) if event["baseline_prices_json"] else None
        )
        if baseline is None:
            pre = connection.execute(
                """SELECT as_of_date, close, snapshot_id FROM market_bars
                WHERE instrument_id=? AND as_of_date<? ORDER BY as_of_date DESC LIMIT 1""",
                (event["instrument_id"], event["ex_date"]),
            ).fetchone()
            if pre is None:
                return None
            revision = connection.execute(
                "SELECT revision FROM market_history_revisions WHERE instrument_id=?",
                (event["instrument_id"],),
            ).fetchone()
            baseline = {
                "captured_state": event["state"],
                "history_revision": str(revision[0] if revision else 0),
                "pre": dict(pre),
                "post": None,
            }
        if baseline["post"] is None:
            post = connection.execute(
                """SELECT as_of_date, open, close, snapshot_id FROM market_bars
                WHERE instrument_id=? AND as_of_date=?""",
                (event["instrument_id"], event["ex_date"]),
            ).fetchone()
            if post is not None:
                baseline["post"] = dict(post)
        connection.execute(
            """UPDATE corporate_action_events SET
            baseline_prices_json=?, baseline_revision=COALESCE(baseline_revision, ?) WHERE event_id=?""",
            (json.dumps(baseline, sort_keys=True), baseline["history_revision"], event["event_id"]),
        )
        return baseline

    def preserve_corporate_action_baseline(self, event_id: str) -> dict[str, object]:
        """Capture the baseline before a provider call can replace stored history."""
        with sqlite_connection(self.path, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            event = connection.execute(
                "SELECT * FROM corporate_action_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if event is None:
                raise DomainValidationError("corporate action event not found")
            self._capture_corporate_baseline(connection, event)
            return dict(
                connection.execute(
                    "SELECT * FROM corporate_action_events WHERE event_id=?", (event_id,)
                ).fetchone()
            )

    def adjust_corporate_event(self, event_id: str, factor: float) -> int:
        """Commit baseline, prices, revision, invalidation and state as one unit."""
        if not math.isfinite(factor) or not 0 < factor < 100:
            raise DomainValidationError("invalid corporate action factor")
        now = datetime.now(UTC).isoformat()
        with sqlite_connection(self.path, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            event = connection.execute(
                "SELECT * FROM corporate_action_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if event is None or not event["instrument_id"]:
                raise DomainValidationError("corporate action instrument is unresolved")
            if event["state"] == "SELF_ADJUSTED":
                return 0
            if event["state"] != "DETECTED":
                raise DomainValidationError("corporate action is not adjustable")
            instrument_id = event["instrument_id"]
            baseline = self._capture_corporate_baseline(connection, event)
            current = connection.execute(
                """SELECT as_of_date, close FROM market_bars
                WHERE instrument_id=? AND as_of_date<? ORDER BY as_of_date DESC LIMIT 1""",
                (instrument_id, event["ex_date"]),
            ).fetchone()
            post = connection.execute(
                """SELECT close FROM market_bars
                WHERE instrument_id=? AND as_of_date=?""",
                (instrument_id, event["ex_date"]),
            ).fetchone()
            if baseline is None or current is None:
                raise DomainValidationError("no pre-ex-date bars to adjust")
            evidence = {
                "source": "stored_history",
                "factor": str(factor),
                "pre_date": current["as_of_date"],
                "pre_close": current["close"],
                "post_close": post["close"] if post else None,
            }
            if post is None:
                outcome = "incomplete_ex_date_window"
            else:
                pre_close, post_close = Decimal(current["close"]), Decimal(post["close"])
                observed_gap = abs(post_close / pre_close - 1)
                adjusted_gap = abs(post_close / (pre_close * Decimal(str(factor))) - 1)
                evidence.update(
                    {
                        "observed_gap_pct": float(observed_gap * 100),
                        "adjusted_gap_pct": float(adjusted_gap * 100),
                    }
                )
                threshold = Decimal(str(self.price_gap_threshold))
                if observed_gap <= threshold:
                    outcome = "stored_history_appears_adjusted"
                elif adjusted_gap > threshold:
                    outcome = "adjustment_basis_not_confirmed"
                else:
                    outcome = None
            if outcome is not None:
                self.transition_corporate_action(
                    event_id,
                    "DETECTED",
                    attempt_outcome=outcome,
                    verification_evidence=evidence,
                    transaction_connection=connection,
                )
                return 0
            count = connection.execute(
                """UPDATE market_bars SET
                open=CAST(CAST(open AS REAL)*? AS TEXT), high=CAST(CAST(high AS REAL)*? AS TEXT),
                low=CAST(CAST(low AS REAL)*? AS TEXT), close=CAST(CAST(close AS REAL)*? AS TEXT)
                WHERE instrument_id=? AND as_of_date<?""",
                (factor, factor, factor, factor, instrument_id, event["ex_date"]),
            ).rowcount
            connection.execute(
                """INSERT INTO market_history_revisions VALUES (?, 1, ?)
                ON CONFLICT(instrument_id) DO UPDATE SET revision=revision+1, updated_at=excluded.updated_at""",
                (instrument_id, now),
            )
            connection.execute(
                "DELETE FROM market_indicators WHERE instrument_id=?", (instrument_id,)
            )
            self.transition_corporate_action(
                event_id,
                "SELF_ADJUSTED",
                applied_factor=factor,
                attempt_outcome="self_adjusted",
                verification_evidence=evidence,
                transaction_connection=connection,
            )
            return count


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
        self,
        start_date: date,
        end_date: date,
        *,
        isins: set[str] | None = None,
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
            if selected_isins is not None
            else ""
        )
        identity_clause = (
            f" AND i.instrument_id IN ({','.join('?' for _ in selected_ids)})"
            if selected_ids is not None
            else " AND i.preferred_row = 1"
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
                   WHERE b.as_of_date BETWEEN ? AND ?"""
                + membership_clause
                + identity_clause
                + " ORDER BY b.instrument_id, b.as_of_date",
                (
                    start_date.isoformat(),
                    end_date.isoformat(),
                    *(selected_isins or []),
                    *(selected_ids or []),
                ),
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
    def nifty500_session_dates(self, start_date: date, end_date: date) -> list[str]:
        """Observed NSE benchmark sessions used for next-open universe exits."""
        if start_date > end_date:
            raise DomainValidationError("NIFTY 500 session range is invalid")
        with sqlite_connection(self.path, read_only=True) as connection:
            rows = connection.execute(
                """SELECT DISTINCT b.as_of_date FROM market_bars b
                   JOIN reference_instruments i ON i.instrument_id=b.instrument_id
                   WHERE i.exchange='NSE' AND i.symbol='NIFTY 500'
                   AND b.as_of_date BETWEEN ? AND ? ORDER BY b.as_of_date""",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return [str(row[0]) for row in rows]
    def session_dates(
        self, start_date: date, end_date: date, *, exchange: str = "NSE"
    ) -> list[str]:
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

__all__ = ["MarketRepository", "TrackedInstrument"]
