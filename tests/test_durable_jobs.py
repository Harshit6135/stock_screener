from src.application import JobStatus, JobStore, JobWorker
from src.platform_kernel import DomainValidationError


def test_worker_claims_completes_and_detects_idempotency_payload_conflict(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    job = jobs.submit("feature-1", "echo", {"value": 1})
    with __import__("pytest").raises(DomainValidationError, match="different command"):
        jobs.submit("feature-1", "echo", {"value": 2})
    result = JobWorker(jobs, "worker-a", {"echo": lambda payload: {"echo": payload["value"]}}).run_once()
    assert result.status == JobStatus.SUCCEEDED
    assert result.result == {"echo": 1}
    assert result.attempts == 1
