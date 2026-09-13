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
    def __init__(self, jobs: JobStore, worker_id: str, handlers: Mapping[str, JobHandler]):
        if not worker_id:
            raise DomainValidationError("worker id must be non-empty")
        self.jobs, self.worker_id, self.handlers = jobs, worker_id, dict(handlers)

    def run_once(self) -> Job | None:
        job = self.jobs.claim_next(self.worker_id)
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
                result = handler(payload, JobExecutionContext(self.jobs, job))
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
            return self.jobs.fail(job.job_id, sanitize_error(exc), job.claim_token)


class BackgroundWorker:
    """Continuous thread-based worker for processing queued jobs in the background."""

    def __init__(self, worker: JobWorker, poll_interval: float = 1.0) -> None:
        self.worker = worker
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._processed_count: int = 0
        self._failed_count: int = 0
        self._last_active_at: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"BackgroundWorker-{self.worker.worker_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, object]:
        return {
            "worker_id": self.worker.worker_id,
            "running": self.is_alive,
            "processed_count": self._processed_count,
            "failed_count": self._failed_count,
            "last_active_at": self._last_active_at,
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

