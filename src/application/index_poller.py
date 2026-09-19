"""Durable intent and interval lease for the local index quote poller."""

import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.application.jobs import JobStore
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.platform_kernel import DomainValidationError

logger = logging.getLogger(__name__)


class IndexQuotePoller:
    def __init__(self, database: str | Path, jobs: JobStore, poller_name: str = "index-quotes"):
        self.database, self.jobs, self.poller_name = Path(database), jobs, poller_name
        migrate_sqlite(self.database, "index_poller", {1: (
            """CREATE TABLE IF NOT EXISTS index_poller_leases (
                poller_name TEXT PRIMARY KEY, interval_seconds INTEGER NOT NULL,
                enabled INTEGER NOT NULL, last_submitted_at TEXT, last_success TEXT, last_error TEXT)""",
        ), 2: ("ALTER TABLE index_poller_leases ADD COLUMN last_job_id INTEGER",)})
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO index_poller_leases(poller_name, interval_seconds, enabled) VALUES (?, 30, 0)",
                (self.poller_name,),
            )

    def state(self) -> dict[str, object]:
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            row = connection.execute("SELECT * FROM index_poller_leases WHERE poller_name=?", (self.poller_name,)).fetchone()
        return dict(row)

    def set_enabled(self, enabled: bool) -> dict[str, object]:
        with sqlite_connection(self.database) as connection:
            connection.execute("UPDATE index_poller_leases SET enabled=? WHERE poller_name=?", (int(enabled), self.poller_name))
        return self.state()

    def set_interval(self, seconds: int) -> dict[str, object]:
        if not 5 <= seconds <= 3600:
            raise DomainValidationError("poller interval must be between 5 and 3600 seconds")
        with sqlite_connection(self.database) as connection:
            connection.execute("UPDATE index_poller_leases SET interval_seconds=? WHERE poller_name=?", (seconds, self.poller_name))
        return self.state()

    def tick(self, now: datetime | None = None) -> dict[str, object]:
        now = now or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise DomainValidationError("poller time must be timezone-aware")
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM index_poller_leases WHERE poller_name=?", (self.poller_name,)).fetchone()
            if not row["enabled"]:
                return {"submitted": False, "reason": "disabled", **dict(row)}
            last = datetime.fromisoformat(row["last_submitted_at"]) if row["last_submitted_at"] else None
            if last and now < last + timedelta(seconds=row["interval_seconds"]):
                return {"submitted": False, "reason": "interval_not_elapsed", **dict(row)}
            fingerprint = f"index-quotes:{self.poller_name}:{now:%Y%m%dT%H%M%S}"
            connection.execute("UPDATE index_poller_leases SET last_submitted_at=?, last_error=NULL WHERE poller_name=?", (now.isoformat(), self.poller_name))
        job = self.jobs.submit(fingerprint, "market.fetch-kite-index-quotes", {}, max_attempts=1)
        with sqlite_connection(self.database) as connection:
            connection.execute("UPDATE index_poller_leases SET last_job_id=? WHERE poller_name=?", (job.job_id, self.poller_name))
        return {"submitted": True, "job_id": job.job_id, "fingerprint": job.fingerprint, **self.state()}

    def reconcile(self) -> dict[str, object]:
        state = self.state()
        job_id = state.get("last_job_id")
        if job_id is not None:
            job = self.jobs.get(int(job_id))
            if job.status.value == "SUCCEEDED":
                with sqlite_connection(self.database) as connection:
                    connection.execute("UPDATE index_poller_leases SET last_success=?, last_error=NULL WHERE poller_name=?", (datetime.now(UTC).isoformat(), self.poller_name))
            elif job.status.value == "FAILED":
                with sqlite_connection(self.database) as connection:
                    connection.execute("UPDATE index_poller_leases SET last_error=? WHERE poller_name=?", (job.last_error or "quote job failed", self.poller_name))
        return self.state()

    def record_error(self, error: BaseException) -> None:
        """Persist a background scheduling failure for operational visibility."""
        message = f"{type(error).__name__}: {error}"[:2000]
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "UPDATE index_poller_leases SET last_error=? WHERE poller_name=?",
                (message, self.poller_name),
            )


def market_is_open(now: datetime | None = None) -> bool:
    """Return whether the NSE cash session is open in Asia/Kolkata time."""
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Kolkata"))
    return local.weekday() < 5 and (local.hour, local.minute, local.second) >= (9, 15, 0) and (local.hour, local.minute, local.second) < (15, 30, 0)


class BackgroundIndexPoller:
    """Runs the durable index quote scheduler while the market is live."""

    def __init__(self, poller: IndexQuotePoller, interval_seconds: int = 15):
        self.poller = poller
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.poller.set_interval(self.interval_seconds)
        self.poller.set_enabled(True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="index-quote-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if market_is_open():
                    self.poller.tick(datetime.now(UTC))
                    self.poller.reconcile()
            except Exception as exc:
                logger.exception("index quote poller tick failed")
                try:
                    self.poller.record_error(exc)
                except Exception:
                    logger.exception("could not persist index quote poller failure")
            self._stop.wait(1)
