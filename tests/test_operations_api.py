from src.application.web import create_operations_blueprint


def test_operations_job_api_is_idempotent_and_cursor_based(tmp_path):
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(create_operations_blueprint(tmp_path / "operations.db"))
    client = app.test_client()

    first = client.post(
        "/api/v2/operations/jobs", json={"fingerprint": "backtest:alpha"}
    )
    repeat = client.post(
        "/api/v2/operations/jobs", json={"fingerprint": "backtest:alpha"}
    )
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
    assert (
        client.post(
            "/api/v2/operations/jobs", json={"fingerprint": ""}
        ).status_code
        == 400
    )


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
    assert (
        client.post(f"/api/v2/operations/jobs/{job_id}/cancel").status_code == 202
    )
    assert (
        client.post(f"/api/v2/operations/jobs/{job_id}/cancel").status_code == 409
    )
    assert client.post("/api/v2/operations/jobs/999/cancel").status_code == 404
