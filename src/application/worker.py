"""Single-writer local worker for durable, typed application jobs."""

from collections.abc import Callable, Mapping
from typing import Any

from src.application.jobs import Job, JobStore
from src.application.security import sanitize_error
from src.platform_kernel import DomainValidationError

JobHandler = Callable[[dict[str, Any]], dict[str, Any]]


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
            result = handler(dict(job.payload or {}))
            return self.jobs.complete(job.job_id, result, job.claim_token)
        except Exception as exc:  # noqa: BLE001 - handler boundary converts failures to durable state
            return self.jobs.fail(job.job_id, sanitize_error(exc), job.claim_token)
