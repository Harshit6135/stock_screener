"""Durable, leased local jobs with idempotent submissions and cursor events."""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.application.security import sanitize_sensitive
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Job:
    job_id: int
    fingerprint: str
    status: JobStatus
    kind: str = "generic"
    payload: dict[str, Any] | None = None
    attempts: int = 0
    lease_until: str | None = None
    result: dict[str, Any] | None = None
    lease_owner: str | None = None
    claim_token: str | None = None
    cancel_requested: bool = False
    max_attempts: int = 3
    last_error: str | None = None


class JobExecutionContext:
    """Cooperative controls exposed to long-running job handlers.

    Handlers may call ``checkpoint`` between provider/page operations.  The
    method renews the lease and raises a domain error when an operator has
    requested cancellation, allowing the worker to resolve the job safely.
    """

    def __init__(self, jobs: "JobStore", job: Job, lease_seconds: int = 60) -> None:
        self.jobs, self.job_id, self.claim_token = jobs, job.job_id, job.claim_token
        self.lease_seconds = lease_seconds

    def checkpoint(self, *, progress: dict[str, Any] | None = None) -> Job:
        job = self.jobs.heartbeat(self.job_id, str(self.claim_token), self.lease_seconds)
        if progress:
            self.jobs.emit(self.job_id, "progress", progress)
        if job.cancel_requested:
            raise DomainValidationError("job cancellation requested")
        return job

    def heartbeat(self) -> Job:
        return self.checkpoint()

    def cancelled(self) -> bool:
        return self.jobs.get(self.job_id).cancel_requested


class JobStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._initialize()

    def _connect(self):
        return sqlite_connection(self.path, row_factory=True)

    def _initialize(self) -> None:
        migrate_sqlite(
            self.path,
            "ops",
            {
                1: (
                    "CREATE TABLE IF NOT EXISTS ops_jobs (job_id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS ops_job_events (event_id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(job_id) REFERENCES ops_jobs(job_id))",
                ),
                2: (
                    "ALTER TABLE ops_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'generic'",
                    "ALTER TABLE ops_jobs ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'",
                    "ALTER TABLE ops_jobs ADD COLUMN payload_checksum TEXT NOT NULL DEFAULT ''",
                    "ALTER TABLE ops_jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE ops_jobs ADD COLUMN lease_until TEXT",
                    "ALTER TABLE ops_jobs ADD COLUMN result_json TEXT",
                    "ALTER TABLE ops_jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0",
                    "CREATE INDEX IF NOT EXISTS ops_jobs_claim_index ON ops_jobs(status, lease_until, created_at)",
                ),
                3: (
                    "ALTER TABLE ops_jobs ADD COLUMN lease_owner TEXT",
                    "ALTER TABLE ops_jobs ADD COLUMN claim_token TEXT",
                    "ALTER TABLE ops_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3",
                    "ALTER TABLE ops_jobs ADD COLUMN next_attempt_at TEXT",
                    "ALTER TABLE ops_jobs ADD COLUMN last_error TEXT",
                ),
            },
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
        value = sanitize_sensitive(dict(payload or {}))
        try:
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("job payload must be JSON serializable") from exc
        return value, hashlib.sha256(encoded.encode()).hexdigest()

    @staticmethod
    def _row(row: sqlite3.Row) -> Job:
        return Job(
            row["job_id"],
            row["fingerprint"],
            JobStatus(row["status"]),
            row["kind"],
            json.loads(row["payload_json"]),
            row["attempts"],
            row["lease_until"],
            json.loads(row["result_json"]) if row["result_json"] else None,
            row["lease_owner"],
            row["claim_token"],
            bool(row["cancel_requested"]),
            row["max_attempts"],
            row["last_error"],
        )

    def submit(
        self,
        fingerprint: str,
        kind: str = "generic",
        payload: dict[str, Any] | None = None,
        *,
        max_attempts: int = 3,
    ) -> Job:
        if not fingerprint.strip() or not kind.strip() or max_attempts < 1:
            raise DomainValidationError("job fingerprint and kind must be non-empty")
        payload, checksum = self._payload(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM ops_jobs WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            if row:
                if row["kind"] != kind or row["payload_checksum"] not in {"", checksum}:
                    raise DomainValidationError(
                        "idempotency fingerprint was reused with a different command"
                    )
                return self._row(row)
            now = self._now()
            cursor = connection.execute(
                "INSERT INTO ops_jobs(fingerprint, kind, payload_json, payload_checksum, status, created_at, updated_at, max_attempts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fingerprint,
                    kind,
                    json.dumps(payload, sort_keys=True),
                    checksum,
                    JobStatus.QUEUED.value,
                    now,
                    now,
                    max_attempts,
                ),
            )
            job = Job(
                cursor.lastrowid,
                fingerprint,
                JobStatus.QUEUED,
                kind,
                payload,
                max_attempts=max_attempts,
            )
            self._append(
                connection,
                job.job_id,
                "submitted",
                {"fingerprint": fingerprint, "kind": kind, "payload_checksum": checksum},
            )
            return job

    def get(self, job_id: int) -> Job:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ops_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise DomainValidationError("job does not exist")
        return self._row(row)

    def claim_next(self, worker_id: str, lease_seconds: int = 60) -> Job | None:
        if not worker_id or lease_seconds < 1:
            raise DomainValidationError("worker lease is invalid")
        now = datetime.now(UTC)
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
        claim_token = str(uuid4())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT * FROM ops_jobs
                   WHERE cancel_requested = 0
                     AND attempts < max_attempts
                     AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                     AND (status = ? OR (status = ? AND lease_until < ?))
                   ORDER BY created_at, job_id LIMIT 1""",
                (
                    now.isoformat(),
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    now.isoformat(),
                ),
            ).fetchone()
            if row is None:
                return None
            previous = JobStatus(row["status"])
            connection.execute(
                "UPDATE ops_jobs SET status = ?, attempts = attempts + 1, lease_until = ?, lease_owner = ?, claim_token = ?, updated_at = ? WHERE job_id = ?",
                (
                    JobStatus.RUNNING.value,
                    lease_until,
                    worker_id,
                    claim_token,
                    self._now(),
                    row["job_id"],
                ),
            )
            self._append(
                connection,
                row["job_id"],
                "claimed",
                {"worker_id": worker_id, "reclaimed": previous == JobStatus.RUNNING},
            )
            claimed = connection.execute(
                "SELECT * FROM ops_jobs WHERE job_id = ?", (row["job_id"],)
            ).fetchone()
            return self._row(claimed)

    def transition(self, job_id: int, target: JobStatus) -> Job:
        """Compatibility boundary: only cancellation can bypass a worker claim."""
        if target != JobStatus.CANCELLED:
            raise DomainValidationError("worker transitions require a claim")
        return self.request_cancel(job_id)

    def complete(self, job_id: int, result: dict[str, Any], claim_token: str | None = None) -> Job:
        result, _ = self._payload(result)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, claim_token, cancel_requested, lease_until FROM ops_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None or JobStatus(row["status"]) != JobStatus.RUNNING:
                raise DomainValidationError("only a running job can complete")
            self._require_claim(row, claim_token)
            if row["cancel_requested"]:
                return self._cancel_claimed(connection, job_id, claim_token)
            connection.execute(
                "UPDATE ops_jobs SET status = ?, result_json = ?, lease_until = NULL, lease_owner = NULL, claim_token = NULL, updated_at = ? WHERE job_id = ?",
                (
                    JobStatus.SUCCEEDED.value,
                    json.dumps(result, sort_keys=True),
                    self._now(),
                    job_id,
                ),
            )
            self._append(connection, job_id, "completed", result)
        return self.get(job_id)

    def fail(
        self,
        job_id: int,
        error: str,
        claim_token: str | None = None,
        *,
        retryable: bool = True,
    ) -> Job:
        if not error:
            raise DomainValidationError("job failure requires an error")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, claim_token, cancel_requested, attempts, max_attempts, lease_until FROM ops_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None or JobStatus(row["status"]) != JobStatus.RUNNING:
                raise DomainValidationError("only a running job can fail")
            self._require_claim(row, claim_token)
            if row["cancel_requested"]:
                return self._cancel_claimed(connection, job_id, claim_token)
            will_retry = retryable and row["attempts"] < row["max_attempts"]
            status = JobStatus.QUEUED if will_retry else JobStatus.FAILED
            next_attempt_at = (
                (datetime.now(UTC) + timedelta(seconds=min(2 ** row["attempts"], 60))).isoformat()
                if will_retry
                else None
            )
            connection.execute(
                "UPDATE ops_jobs SET status = ?, lease_until = NULL, lease_owner = NULL, claim_token = NULL, next_attempt_at = ?, last_error = ?, updated_at = ? WHERE job_id = ?",
                (status.value, next_attempt_at, error, self._now(), job_id),
            )
            self._append(
                connection, job_id, "retry_scheduled" if will_retry else "failed", {"error": error}
            )
        return self.get(job_id)

    def request_cancel(self, job_id: int) -> Job:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM ops_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError("job does not exist")
            if JobStatus(row["status"]) == JobStatus.QUEUED:
                connection.execute(
                    "UPDATE ops_jobs SET status = ?, cancel_requested = 1, updated_at = ? WHERE job_id = ?",
                    (JobStatus.CANCELLED.value, self._now(), job_id),
                )
            elif JobStatus(row["status"]) == JobStatus.RUNNING:
                connection.execute(
                    "UPDATE ops_jobs SET cancel_requested = 1, updated_at = ? WHERE job_id = ?",
                    (self._now(), job_id),
                )
            else:
                raise DomainValidationError("terminal jobs cannot be cancelled")
            self._append(connection, job_id, "cancel_requested", {})
        return self.get(job_id)

    def retry_failed(self, job_id: int) -> Job:
        """Requeue exactly one terminal failed job for an operator retry.

        A retry is an explicit state transition.  It does not create a second
        job or reset the event history, and it is intentionally unavailable for
        queued, running, or successful jobs.
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM ops_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise DomainValidationError("job does not exist")
            if JobStatus(row["status"]) != JobStatus.FAILED:
                raise DomainValidationError("only failed jobs can be retried")
            connection.execute(
                """UPDATE ops_jobs SET status = ?, attempts = 0,
                   next_attempt_at = NULL, last_error = NULL, result_json = NULL,
                   cancel_requested = 0, updated_at = ? WHERE job_id = ?""",
                (JobStatus.QUEUED.value, self._now(), job_id),
            )
            self._append(connection, job_id, "retry_requested", {})
        return self.get(job_id)

    def heartbeat(self, job_id: int, claim_token: str, lease_seconds: int = 60) -> Job:
        if lease_seconds < 1:
            raise DomainValidationError("worker lease is invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, claim_token, cancel_requested, lease_until FROM ops_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None or JobStatus(row["status"]) != JobStatus.RUNNING:
                raise DomainValidationError("only a running job can renew a lease")
            self._require_claim(row, claim_token)
            if row["cancel_requested"]:
                return self._cancel_claimed(connection, job_id, claim_token)
            lease_until = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
            connection.execute(
                "UPDATE ops_jobs SET lease_until = ?, updated_at = ? WHERE job_id = ? AND claim_token = ?",
                (lease_until, self._now(), job_id, claim_token),
            )
            self._append(connection, job_id, "heartbeat", {})
        return self.get(job_id)

    @staticmethod
    def _require_claim(row: sqlite3.Row, claim_token: str | None) -> None:
        if row["claim_token"] and row["claim_token"] != claim_token:
            raise DomainValidationError("job claim is stale or belongs to another worker")
        if row["lease_until"] and datetime.fromisoformat(row["lease_until"]) <= datetime.now(UTC):
            raise DomainValidationError("job claim lease has expired")

    def _cancel_claimed(
        self,
        connection: sqlite3.Connection,
        job_id: int,
        claim_token: str | None,
    ) -> Job:
        cursor = connection.execute(
            """UPDATE ops_jobs
               SET status = ?, lease_until = NULL, lease_owner = NULL,
                   claim_token = NULL, updated_at = ?
               WHERE job_id = ? AND status = ? AND claim_token IS ?""",
            (
                JobStatus.CANCELLED.value,
                self._now(),
                job_id,
                JobStatus.RUNNING.value,
                claim_token,
            ),
        )
        if cursor.rowcount != 1:
            raise DomainValidationError("job claim is stale or belongs to another worker")
        self._append(connection, job_id, "cancelled", {})
        row = connection.execute("SELECT * FROM ops_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row(row)

    def emit(self, job_id: int, event_type: str, payload: dict[str, Any]) -> None:
        payload, _ = self._payload(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute(
                "SELECT 1 FROM ops_jobs WHERE job_id = ?", (job_id,)
            ).fetchone():
                raise DomainValidationError("job does not exist")
            self._append(connection, job_id, event_type, payload)

    def events_after(
        self, job_id: int, event_id: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        if event_id < 0 or not 1 <= limit <= 500:
            raise DomainValidationError("event cursor or limit is invalid")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_id, event_type, payload_json, created_at FROM ops_job_events WHERE job_id = ? AND event_id > ? ORDER BY event_id LIMIT ?",
                (job_id, event_id, limit),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _append(
        self, connection: sqlite3.Connection, job_id: int, event_type: str, payload: dict[str, Any]
    ) -> None:
        payload = sanitize_sensitive(payload)
        connection.execute(
            "INSERT INTO ops_job_events(job_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (job_id, event_type, json.dumps(payload, sort_keys=True), self._now()),
        )
