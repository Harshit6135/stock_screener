"""Single-writer local worker for durable, typed application jobs."""

import inspect
from collections.abc import Callable, Mapping
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
