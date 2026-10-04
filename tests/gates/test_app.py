import sqlite3

from run import create_app


def test_fresh_app_initializes_current_owner_schemas_and_readback(tmp_path):

    class Config:
        TESTING = True
        SECRET_KEY = "app-startup-test"
        DATA_DIRECTORY = tmp_path

    app = create_app(Config)
    assert app.test_client().get("/health/ready").status_code == 200
    database = app.extensions["screener_services"].database
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT namespace, version FROM system_schema_migrations ORDER BY namespace, version"
        ).fetchall()
    assert rows
    assert all(version == 1 for _, version in rows)
    namespaces = {namespace for namespace, _ in rows}
    assert {"market_data", "reference_data", "indicator_node_cache", "ops", "research"} <= namespaces
    assert "market" not in namespaces
    assert app.test_client().get("/api/market/quality-events").status_code == 200


def test_backend_shell_exposes_only_new_api_and_health(tmp_path):

    class TestConfig:
        TESTING = True
        SECRET_KEY = "test"
        DATA_DIRECTORY = tmp_path

    app = create_app(TestConfig)
    client = app.test_client()
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/").status_code == 200
    assert client.post("/api/operations/jobs", json={"fingerprint": "run-1"}).status_code == 400
    created = client.post(
        "/api/operations/jobs",
        json={"fingerprint": "run-1", "kind": "system.echo", "payload": {"value": 1}},
    )
    assert created.status_code == 202
    assert (
        client.get("/api/reference/liquidity-universes/not-a-real-artifact").status_code == 404
    )
