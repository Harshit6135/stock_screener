from run import create_app


def test_backend_shell_exposes_only_new_api_and_health(tmp_path):
    class TestConfig:
        TESTING = True
        SECRET_KEY = "test"
        DATA_DIRECTORY = tmp_path
        OPERATOR_TOKEN = "operator"

    app = create_app(TestConfig)
    client = app.test_client()
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/").status_code == 404
    assert client.post("/api/v2/operations/jobs", json={"fingerprint": "run-1"}).status_code == 401
    created = client.post(
        "/api/v2/operations/jobs", json={"fingerprint": "run-1"}, headers={"X-Operator-Token": "operator"}
    )
    assert created.status_code == 202
