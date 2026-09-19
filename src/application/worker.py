"""Single-writer local worker for durable, typed application jobs."""

import inspect
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from src.application.jobs import Job, JobExecutionContext, JobStore
from src.application.security import sanitize_error
from src.platform_kernel import DomainValidationError

JobHandler = Callable[..., dict[str, Any]]


class JobWorker:
    # Research calculations over the full universe can exceed one minute.
    # A short lease causes the same job to be reclaimed while its original
    # handler is still running, producing duplicate work and stale RUNNING rows.
    LEASE_SECONDS = 3600

    def __init__(self, jobs: JobStore, worker_id: str, handlers: Mapping[str, JobHandler]):
        if not worker_id:
            raise DomainValidationError("worker id must be non-empty")
        self.jobs, self.worker_id, self.handlers = jobs, worker_id, dict(handlers)

    def run_once(self) -> Job | None:
        job = self.jobs.claim_next(self.worker_id, lease_seconds=self.LEASE_SECONDS)
        if job is None:
            return None
        handler = self.handlers.get(job.kind)
        if handler is None:
            return self.jobs.fail(
                job.job_id,
                f"unsupported job kind: {job.kind}",
                job.claim_token,
                retryable=False,
            )
        try:
            payload = dict(job.payload or {})
            # Keep the original one-argument handler contract while allowing
            # new handlers to opt into cooperative lease/cancel controls.
            if len(inspect.signature(handler).parameters) >= 2:
                result = handler(payload, JobExecutionContext(self.jobs, job, self.LEASE_SECONDS))
            else:
                result = handler(payload)
            return self.jobs.complete(job.job_id, result, job.claim_token)
        except Exception as exc:  # noqa: BLE001 - handler boundary converts failures to durable state
            # A cooperative checkpoint may have resolved the job as cancelled
            # while the handler unwound.  Do not turn that terminal state into
            # a spurious worker failure.
            current = self.jobs.get(job.job_id)
            if current.status.value == "CANCELLED":
                return current
            return self.jobs.fail(
                job.job_id,
                sanitize_error(exc),
                job.claim_token,
                retryable=not isinstance(exc, DomainValidationError),
            )


class BackgroundWorker:
    """Continuous thread-based worker for processing queued jobs in the background."""

    def __init__(self, worker: JobWorker, poll_interval: float = 1.0, concurrency: int = 1) -> None:
        if concurrency < 1:
            raise DomainValidationError("worker concurrency must be positive")
        self.worker = worker
        self.poll_interval = poll_interval
        self.concurrency = concurrency
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._threads: list[threading.Thread] = []
        self._processed_count: int = 0
        self._failed_count: int = 0
        self._last_active_at: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._threads = [
            threading.Thread(
                target=self._run_loop,
                name=f"BackgroundWorker-{self.worker.worker_id}-{index + 1}",
                daemon=True,
            )
            for index in range(self.concurrency)
        ]
        self._thread = self._threads[0]
        for thread in self._threads:
            thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=timeout)

    @property
    def is_alive(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def status(self) -> dict[str, object]:
        durable = self.worker.jobs.status_counts()
        return {
            "worker_id": self.worker.worker_id,
            "running": self.is_alive,
            "processed_count": self._processed_count,
            "processed_attempts": self._processed_count,
            "failed_count": self._failed_count,
            "last_active_at": self._last_active_at,
            "total_jobs": durable.get("total_jobs", 0),
            "total_attempts": durable.get("total_attempts", 0),
            "succeeded_jobs": durable.get("succeeded_jobs", 0),
            "failed_jobs": durable.get("failed_jobs", 0),
            "failed_execution_jobs": durable.get("failed_execution_jobs", 0),
            "data_unavailable_jobs": durable.get("data_unavailable_jobs", 0),
            "data_unavailable_attempts": durable.get("data_unavailable_attempts", 0),
            "queued_jobs": durable.get("queued_jobs", 0),
            "running_jobs": durable.get("running_jobs", 0),
            "cancelled_jobs": durable.get("cancelled_jobs", 0),
        }

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self.worker.run_once()
                if job is not None:
                    self._processed_count += 1
                    self._last_active_at = datetime.now(UTC).isoformat()
                    if job.status.value in {"FAILED", "CANCELLED"}:
                        self._failed_count += 1
                else:
                    self._stop_event.wait(self.poll_interval)
            except Exception:  # noqa: BLE001
                self._failed_count += 1
                self._stop_event.wait(self.poll_interval)
