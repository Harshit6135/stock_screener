from flask import Flask

from src.domains.operations import JobExecutionContext, JobStore
from src.gates.http.operations import create_operations_blueprint
from src.platform_kernel import DomainValidationError


def test_terminal_progress_sse_reconnect_honors_cursor(tmp_path):

    store = JobStore(tmp_path / "jobs.db")
    job = store.submit("cursor", "echo", {})
    claimed = store.claim_next("worker")
    context = JobExecutionContext(store, claimed)
    context.checkpoint(progress={"stage": "first", "current": 1, "total": 2})
    first = [
        event for event in store.events_after(job.job_id) if event["event_type"] == "progress"
    ][-1]
    context.checkpoint(progress={"stage": "second", "current": 2, "total": 2})
    store.complete(job.job_id, {}, claimed.claim_token)
    app = Flask(__name__)
    app.register_blueprint(create_operations_blueprint(store))
    client = app.test_client()
    response = client.get(
        f"/api/v2/operations/jobs/{job.job_id}/events",
        headers={"Accept": "text/event-stream", "Last-Event-ID": str(first["event_id"])},
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "event: job-event" in body
    assert '"stage": "second"' in body
    assert '"stage": "first"' not in body
    assert "event: terminal" in body


def test_operations_job_api_is_idempotent_and_cursor_based(tmp_path):
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(create_operations_blueprint(tmp_path / "operations.db"))
    client = app.test_client()

    first = client.post("/api/v2/operations/jobs", json={"fingerprint": "backtest:alpha"})
    repeat = client.post("/api/v2/operations/jobs", json={"fingerprint": "backtest:alpha"})
    assert first.status_code == repeat.status_code == 202
    job_id = first.json["job_id"]
    assert repeat.json["job_id"] == job_id

    events = client.get(f"/api/v2/operations/jobs/{job_id}/events?after=0")
    assert events.status_code == 200
    assert events.json["events"][0]["event_type"] == "submitted"

    cursor = events.json["events"][-1]["event_id"]
    assert client.get(f"/api/v2/operations/jobs/{job_id}/events?after={cursor}").json == {
        "events": []
    }
    assert client.post("/api/v2/operations/jobs", json={"fingerprint": ""}).status_code == 400


def test_operations_api_validates_kinds_payload_cursors_and_cancellation(tmp_path):
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(create_operations_blueprint(tmp_path / "disabled.db", {"echo"}))
    client = app.test_client()
    assert client.post("/api/v2/operations/jobs", json=[]).status_code == 400
    assert (
        client.post(
            "/api/v2/operations/jobs",
            json={"fingerprint": "bad-kind", "kind": "unknown"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v2/operations/jobs",
            json={"fingerprint": "bad-payload", "kind": "echo", "payload": []},
        ).status_code
        == 400
    )
    submitted = client.post(
        "/api/v2/operations/jobs",
        json={"fingerprint": "cancel", "kind": "echo"},
    )
    job_id = submitted.json["job_id"]
    assert client.get("/api/v2/operations/jobs/999").status_code == 404
    assert client.get(f"/api/v2/operations/jobs/{job_id}/events?after=-1").status_code == 400
    assert client.get("/api/v2/operations/jobs/999/events").status_code == 404
    assert client.post(f"/api/v2/operations/jobs/{job_id}/cancel").status_code == 202
    assert client.post(f"/api/v2/operations/jobs/{job_id}/cancel").status_code == 409
    assert client.post("/api/v2/operations/jobs/999/cancel").status_code == 404


def test_worker_failure_and_event_api_redact_embedded_credentials(tmp_path):
    import json

    from flask import Flask

    from src.domains.operations import JobStore, JobWorker
    from src.gates.http.operations import create_operations_blueprint

    jobs = JobStore(tmp_path / "jobs.db")
    job = jobs.submit("phase1-redaction", "validate", {})
    jobs.emit(
        job.job_id, "progress", {"stage": "provider", "message": "request_token=DO_NOT_PERSIST"}
    )

    def invalid(payload):
        raise DomainValidationError("api_secret=DO_NOT_PERSIST invalid provider session")

    failed = JobWorker(jobs, "quality-review", {"validate": invalid}).run_once()
    assert "invalid provider session" in failed.last_error
    assert "DO_NOT_PERSIST" not in failed.last_error
    app = Flask(__name__)
    app.register_blueprint(create_operations_blueprint(jobs))
    client = app.test_client()
    path = f"/api/v2/operations/jobs/{job.job_id}/events"
    response = client.get(path)
    assert response.status_code == 200
    assert "DO_NOT_PERSIST" not in json.dumps(response.json)
    cursor = response.json["events"][0]["event_id"]
    continuation = client.get(path, headers={"Last-Event-ID": str(cursor)})
    assert all(event["event_id"] > cursor for event in continuation.json["events"])
