from src.application.web import create_operations_blueprint


def test_operations_job_api_is_idempotent_and_cursor_based(tmp_path):
    from flask import Flask

    app = Flask(__name__)
    app.config["OPERATOR_TOKEN"] = "test-token"
    app.register_blueprint(create_operations_blueprint(tmp_path / "operations.db"))
    client = app.test_client()

    headers = {"X-Operator-Token": "test-token"}
    assert client.post("/api/v2/operations/jobs", json={"fingerprint": "backtest:alpha"}).status_code == 401
    first = client.post("/api/v2/operations/jobs", json={"fingerprint": "backtest:alpha"}, headers=headers)
    repeat = client.post("/api/v2/operations/jobs", json={"fingerprint": "backtest:alpha"}, headers=headers)
    assert first.status_code == repeat.status_code == 202
    job_id = first.json["job_id"]
    assert repeat.json["job_id"] == job_id

    events = client.get(f"/api/v2/operations/jobs/{job_id}/events?after=0")
    assert events.status_code == 200
    assert events.json["events"][0]["event_type"] == "submitted"

    cursor = events.json["events"][-1]["event_id"]
    assert client.get(f"/api/v2/operations/jobs/{job_id}/events?after={cursor}").json == {"events": []}
    assert client.post("/api/v2/operations/jobs", json={"fingerprint": ""}, headers=headers).status_code == 400
