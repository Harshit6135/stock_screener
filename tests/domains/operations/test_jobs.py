import pytest

from src.domains.operations import JobStatus, JobStore
from src.platform_kernel import DomainValidationError


def test_jobs_are_idempotent_and_events_are_cursor_readable(tmp_path):
    jobs = JobStore(tmp_path / "ops.db")
    first = jobs.submit("same-inputs")
    assert jobs.submit("same-inputs") == first
    claim = jobs.claim_next("test-worker")
    assert claim.status == JobStatus.RUNNING
    jobs.emit(first.job_id, "progress", {"percent": 50})
    assert [event["event_type"] for event in jobs.events_after(first.job_id)] == [
        "submitted",
        "claimed",
        "progress",
    ]
    with pytest.raises(DomainValidationError, match="require a claim"):
        jobs.transition(first.job_id, JobStatus.QUEUED)


def test_store_connections_release_database_file(tmp_path):
    database = tmp_path / "system.db"
    jobs = JobStore(database)
    jobs.submit("one")
    jobs.get(1)
    moved = tmp_path / "moved.db"

    database.replace(moved)

    assert moved.is_file()
