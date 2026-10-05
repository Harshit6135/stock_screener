"""Portfolio-owned persistence for reviewable action proposals."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


class PortfolioProposalStore:
    """Owns proposal projections and their append-only lifecycle events."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        migrate_sqlite(
            self.database,
            "actions",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS action_proposals (
                        proposal_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                        strategy_id TEXT NOT NULL, action_date TEXT NOT NULL,
                        ranking_week_end TEXT NOT NULL, expected_ledger_version INTEGER NOT NULL,
                        status TEXT NOT NULL, artifact_id TEXT NOT NULL,
                        decision_json TEXT NOT NULL, resulting_ledger_version INTEGER,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
                    "CREATE INDEX IF NOT EXISTS action_proposals_account_date ON action_proposals(account_id, action_date)",
                    """CREATE TABLE IF NOT EXISTS action_proposal_events (
                        event_id INTEGER PRIMARY KEY, proposal_id TEXT NOT NULL,
                        event_type TEXT NOT NULL, occurred_at TEXT NOT NULL,
                        detail_json TEXT NOT NULL,
                        FOREIGN KEY(proposal_id) REFERENCES action_proposals(proposal_id))""",
                ),
                2: (
                    "ALTER TABLE action_proposals ADD COLUMN decision_status_json TEXT NOT NULL DEFAULT '[]'",
                ),
            },
        )

    def insert_pending(
        self,
        *,
        proposal_id: str,
        account_id: str,
        strategy_id: str,
        action_date: str,
        ranking_week_end: str,
        expected_ledger_version: int,
        artifact_id: str,
        decisions: list[dict[str, object]],
        timestamp: str,
        event_type: str,
        event_detail: dict[str, object],
    ) -> None:
        """Insert the initial proposal and its first event atomically."""
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO action_proposals
                   (proposal_id, account_id, strategy_id, action_date, ranking_week_end,
                    expected_ledger_version, status, artifact_id, decision_json,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)""",
                (
                    proposal_id,
                    account_id,
                    strategy_id,
                    action_date,
                    ranking_week_end,
                    expected_ledger_version,
                    artifact_id,
                    json.dumps(decisions, sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """INSERT INTO action_proposal_events
                   (proposal_id, event_type, occurred_at, detail_json)
                   VALUES (?, ?, ?, ?)""",
                (proposal_id, event_type, timestamp, json.dumps(event_detail, sort_keys=True)),
            )

    def recover_pending(
        self,
        *,
        proposal_id: str,
        account_id: str,
        strategy_id: str,
        action_date: str,
        ranking_week_end: str,
        expected_ledger_version: int,
        artifact_id: str,
        decisions: list[dict[str, object]],
        timestamp: str,
        event_type: str,
    ) -> None:
        """Idempotently rebuild SQL projection after artifact publication."""
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT OR IGNORE INTO action_proposals
                   (proposal_id, account_id, strategy_id, action_date, ranking_week_end,
                    expected_ledger_version, status, artifact_id, decision_json,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)""",
                (
                    proposal_id,
                    account_id,
                    strategy_id,
                    action_date,
                    ranking_week_end,
                    expected_ledger_version,
                    artifact_id,
                    json.dumps(decisions, sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] == 1:
                connection.execute(
                    """INSERT INTO action_proposal_events
                       (proposal_id, event_type, occurred_at, detail_json)
                       VALUES (?, ?, ?, '{}')""",
                    (proposal_id, event_type, timestamp),
                )

    def append_event(
        self,
        proposal_id: str,
        event_type: str,
        timestamp: str,
        detail: dict[str, object],
    ) -> None:
        with sqlite_connection(self.database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO action_proposal_events
                   (proposal_id, event_type, occurred_at, detail_json)
                   VALUES (?, ?, ?, ?)""",
                (proposal_id, event_type, timestamp, json.dumps(detail, sort_keys=True)),
            )

    def get(self, proposal_id: str) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute(
                "SELECT * FROM action_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise DomainValidationError("action proposal was not found")
        return self._decode(row)

    @staticmethod
    def _decode(row: Any) -> dict[str, object]:
        result = dict(row)
        result["decisions"] = json.loads(result.pop("decision_json"))
        statuses = json.loads(result.pop("decision_status_json", "[]"))
        if not statuses:
            statuses = [
                result["status"] if result["status"] in {"APPROVED", "REJECTED", "PROCESSED"} else "PENDING"
                for _ in result["decisions"]
            ]
        result["decision_statuses"] = statuses
        return result

    def list_for_account(
        self,
        account_id: str,
        limit: int = 50,
        action_date: date | None = None,
        strategy_id: str | None = None,
    ) -> list[dict[str, object]]:
        if not 1 <= limit <= 100:
            raise DomainValidationError("action proposal limit must be 1..100")
        encoded_date = action_date.isoformat() if action_date else None
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                  """SELECT * FROM action_proposals WHERE account_id=?
                     AND (? IS NULL OR action_date=?)
                     AND (? IS NULL OR strategy_id=?)
                   ORDER BY action_date DESC, created_at DESC LIMIT ?""",
                  (account_id, encoded_date, encoded_date, strategy_id, strategy_id, limit),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def action_dates(self, account_id: str) -> list[date]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT DISTINCT action_date FROM action_proposals
                   WHERE account_id=? ORDER BY action_date DESC""",
                (account_id,),
            ).fetchall()
        return [date.fromisoformat(str(row["action_date"])) for row in rows]

    def events(self, proposal_id: str) -> list[dict[str, object]]:
        self.get(proposal_id)
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute(
                """SELECT event_type, occurred_at, detail_json
                   FROM action_proposal_events WHERE proposal_id=? ORDER BY event_id""",
                (proposal_id,),
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "occurred_at": row["occurred_at"],
                "detail": json.loads(row["detail_json"]),
            }
            for row in rows
        ]

    def transition_pending(self, proposal_id: str, action: str, timestamp: str) -> None:
        if action not in {"APPROVED", "REJECTED"}:
            raise DomainValidationError("proposal decision is invalid")
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM action_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError("action proposal was not found")
            if row["status"] != "PENDING":
                raise DomainValidationError("action proposal is not pending")
            decision_count = len(json.loads(connection.execute(
                "SELECT decision_json FROM action_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()[0]))
            connection.execute(
                "UPDATE action_proposals SET status=?, decision_status_json=?, updated_at=? WHERE proposal_id=?",
                (action, json.dumps([action] * decision_count), timestamp, proposal_id),
            )
            connection.execute(
                """INSERT INTO action_proposal_events
                   (proposal_id, event_type, occurred_at, detail_json)
                   VALUES (?, ?, ?, '{}')""",
                (proposal_id, action, timestamp),
            )

    def decide_stock(self, proposal_id: str, index: int, action: str, timestamp: str) -> dict[str, object]:
        if action not in {"APPROVED", "REJECTED"}:
            raise DomainValidationError("proposal decision is invalid")
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM action_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if row is None:
                raise DomainValidationError("action proposal was not found")
            proposal = self._decode(row)
            if proposal["status"] != "PENDING":
                raise DomainValidationError("action proposal is not pending")
            statuses = list(proposal["decision_statuses"])
            if not 0 <= index < len(statuses):
                raise DomainValidationError("proposal stock row was not found")
            if statuses[index] != "PENDING":
                raise DomainValidationError("proposal stock row is not pending")
            statuses[index] = action
            status = "PENDING" if "PENDING" in statuses else ("APPROVED" if "APPROVED" in statuses else "REJECTED")
            connection.execute(
                "UPDATE action_proposals SET status=?, decision_status_json=?, updated_at=? WHERE proposal_id=?",
                (status, json.dumps(statuses), timestamp, proposal_id),
            )
            connection.execute(
                "INSERT INTO action_proposal_events (proposal_id,event_type,occurred_at,detail_json) VALUES (?,?,?,?)",
                (proposal_id, f"STOCK_{action}", timestamp, json.dumps({"decision_index": index}, sort_keys=True)),
            )
        return self.get(proposal_id)

    def mark_processed(
        self,
        connection: sqlite3.Connection,
        proposal_id: str,
        resulting_ledger_version: int,
        timestamp: str,
        adjustments: list[dict[str, object]],
    ) -> bool:
        """Append proposal writes to an injected, caller-owned transaction."""
        changed = connection.execute(
            """UPDATE action_proposals SET status='PROCESSED',
               resulting_ledger_version=?, updated_at=?
               WHERE proposal_id=? AND status='APPROVED'""",
            (resulting_ledger_version, timestamp, proposal_id),
        )
        if changed.rowcount != 1:
            return False
        connection.execute(
            """INSERT INTO action_proposal_events
               (proposal_id, event_type, occurred_at, detail_json)
               VALUES (?, 'PROCESSED', ?, ?)""",
            (
                proposal_id,
                timestamp,
                json.dumps(
                    {
                        "resulting_ledger_version": resulting_ledger_version,
                        "adjustments": adjustments,
                    },
                    sort_keys=True,
                ),
            ),
        )
        return True
