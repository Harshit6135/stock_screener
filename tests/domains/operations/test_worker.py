import sqlite3
from contextlib import closing
from datetime import UTC, datetime

import pytest

from src.domains.operations import (
    BackgroundWorker,
    JobExecutionContext,
    JobStatus,
    JobStore,
    JobWorker,
)
from src.platform_kernel import DomainValidationError


def claimed_context(tmp_path, payload=None):
    jobs = JobStore(tmp_path / "jobs.db")
    job = jobs.submit("context-check", "verify", payload or {})
    claimed = jobs.claim_next("worker")
    return (jobs, job, JobExecutionContext(jobs, claimed))


def test_worker_claims_completes_and_detects_idempotency_payload_conflict(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    jobs.submit("feature-1", "echo", {"value": 1})
    with __import__("pytest").raises(DomainValidationError, match="different command"):
        jobs.submit("feature-1", "echo", {"value": 2})
    result = JobWorker(
        jobs, "worker-a", {"echo": lambda payload: {"echo": payload["value"]}}
    ).run_once()
    assert result.status == JobStatus.SUCCEEDED
    assert result.result == {"echo": 1}
    assert result.attempts == 1


def test_worker_records_unsupported_and_sanitized_handler_failures(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    jobs.submit("unsupported", "missing", max_attempts=1)
    result = JobWorker(jobs, "worker-a", {}).run_once()
    assert result.status == JobStatus.FAILED
    assert "unsupported job kind" in result.last_error
    jobs.submit("failure", "explode", max_attempts=1)

    def explode(payload):
        raise RuntimeError("password=secret")

    result = JobWorker(jobs, "worker-a", {"explode": explode}).run_once()
    assert result.status == JobStatus.FAILED
    assert result.last_error == "RuntimeError"


def test_progress_context_counter_normalization_and_cursor(tmp_path):
    jobs, job, context = claimed_context(
        tmp_path, {"account_id": "selected", "strategy_id": "momentum", "revision_id": "rev"}
    )
    context.checkpoint(progress={"stage": "bars", "processed": 2, "total": 4, "job_id": 999})
    progress = [
        event for event in jobs.events_after(job.job_id) if event["event_type"] == "progress"
    ][-1]
    assert {key: progress["payload"][key] for key in ("current", "total", "percent", "job_id")} == {
        "current": 2,
        "total": 4,
        "percent": 50,
        "job_id": job.job_id,
    }
    assert progress["payload"]["account_id"] == "selected"
    assert progress["payload"]["revision_id"] == "rev"
    context.checkpoint(progress={"stage": "done", "message": "complete"})
    continuation = jobs.events_after(job.job_id, progress["event_id"])
    assert any(event["event_type"] == "progress" for event in continuation)


@pytest.mark.parametrize(
    "progress",
    [
        {"current": True},
        {"current": float("nan")},
        {"total": -1},
        {"percent": float("inf")},
        {"stage": None},
        {"message": 123},
    ],
)
def test_invalid_progress_cannot_publish_unreadable_events(tmp_path, progress):
    jobs, job, context = claimed_context(tmp_path)
    with pytest.raises(DomainValidationError, match="progress"):
        context.checkpoint(progress=progress)
    assert not any(event["event_type"] == "progress" for event in jobs.events_after(job.job_id))


def test_cancelled_checkpoint_emits_no_later_progress(tmp_path):
    jobs, job, context = claimed_context(tmp_path)
    jobs.request_cancel(job.job_id)
    with pytest.raises(DomainValidationError, match="cancellation"):
        context.checkpoint(progress={"stage": "finished"})
    assert jobs.get(job.job_id).status == JobStatus.CANCELLED
    assert not any(event["event_type"] == "progress" for event in jobs.events_after(job.job_id))


def test_long_running_handler_can_checkpoint_and_cancel(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    jobs.submit("cooperative", "long")

    def handler(payload, context):
        jobs.request_cancel(context.job_id)
        context.checkpoint()
        return {}

    result = JobWorker(jobs, "worker", {"long": handler}).run_once()
    assert result is not None and result.status == JobStatus.CANCELLED


def test_cancelled_running_job_cannot_finish_successfully(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    jobs.submit("cancel", "cancel-self")
    worker = JobWorker(
        jobs,
        "worker-a",
        {"cancel-self": lambda payload: (jobs.request_cancel(1), {})[1]},
    )

    assert worker.run_once().status == JobStatus.CANCELLED


def test_stale_job_claim_cannot_complete_after_reclaim(tmp_path):
    database = tmp_path / "system.db"
    jobs = JobStore(database)
    jobs.submit("lease", "echo")
    first = jobs.claim_next("worker-a", lease_seconds=1)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE ops_jobs SET lease_until = ? WHERE job_id = ?",
            (datetime(2000, 1, 1, tzinfo=UTC).isoformat(), first.job_id),
        )
        connection.commit()
    second = jobs.claim_next("worker-b")

    assert second.claim_token != first.claim_token
    with pytest.raises(DomainValidationError, match="stale"):
        jobs.complete(first.job_id, {"wrong": True}, first.claim_token)
    assert (
        jobs.complete(second.job_id, {"right": True}, second.claim_token).status
        == JobStatus.SUCCEEDED
    )


def test_expired_claim_cannot_commit_before_reclaim(tmp_path):
    database = tmp_path / "system.db"
    jobs = JobStore(database)
    jobs.submit("expired", "echo")
    claimed = jobs.claim_next("worker-a", lease_seconds=1)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE ops_jobs SET lease_until = ? WHERE job_id = ?",
            (datetime(2000, 1, 1, tzinfo=UTC).isoformat(), claimed.job_id),
        )
        connection.commit()
    with pytest.raises(DomainValidationError, match="expired"):
        jobs.complete(claimed.job_id, {}, claimed.claim_token)
    with pytest.raises(DomainValidationError, match="expired"):
        jobs.heartbeat(claimed.job_id, claimed.claim_token)


def test_background_worker_lifecycle_and_status(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    job = jobs.submit("test:bg:1", "test.task", {"val": 42})
    handled = []

    def handle_task(payload):
        handled.append(payload["val"])
        return {"processed": True}

    worker = JobWorker(jobs, "test-bg-worker", {"test.task": handle_task})
    bg = BackgroundWorker(worker, poll_interval=0.05)

    assert not bg.is_alive
    st = bg.status()
    assert st["running"] is False
    assert st["processed_count"] == 0

    bg.start()
    assert bg.is_alive

    import time

    # Wait for background thread to process job
    for _ in range(50):
        if (
            jobs.get(job.job_id).status == JobStatus.SUCCEEDED
            and bg.status()["processed_count"] == 1
        ):
            break
        time.sleep(0.05)

    assert handled == [42]
    completed_job = jobs.get(job.job_id)
    assert completed_job.status == JobStatus.SUCCEEDED
    st = bg.status()
    assert st["processed_count"] == 1
    bg.stop(timeout=2.0)
    assert not bg.is_alive
