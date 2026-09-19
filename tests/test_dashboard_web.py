from run import create_app
from src.application.runtime import RuntimeConfig


def test_minimal_app_page_and_kite_navigation(tmp_path):
    class TestConfig(RuntimeConfig):
        DATA_DIRECTORY = tmp_path
        KITE_API_KEY = None
        KITE_API_SECRET = None
        OPERATOR_TOKEN = "test-secret"

    app = create_app(TestConfig)
    client = app.test_client()
    assert client.get("/").headers["Location"].endswith("/app")
    response = client.get("/app")
    assert response.status_code == 200
    assert b"Weekly rankings" in response.data
    assert b"Index quotes" in response.data
    assert b"Portfolio account" in response.data
    assert b"Portfolio action proposals" in response.data
    assert client.get("/health/ready").status_code == 200
    assert client.get("/api/v2/actions/proposals?account_id=paper").status_code == 200
    assert (
        client.get(
            "/api/v2/actions/proposals?account_id=paper",
            headers={"X-Operator-Token": "test-secret"},
        ).status_code
        == 200
    )
    assert client.get("/integrations/kite").status_code == 200


def test_real_app_has_no_legacy_dashboard_or_config_api(tmp_path):
    class TestConfig(RuntimeConfig):
        DATA_DIRECTORY = tmp_path
        KITE_API_KEY = None
        KITE_API_SECRET = None
        OPERATOR_TOKEN = "test-secret"

    app = create_app(TestConfig)
    client = app.test_client()
    assert client.get("/dashboard").status_code == 404
    response = client.put(
        "/api/v1/config/momentum_config",
        json={"initial_capital": 125000, "max_positions": 10},
        headers={"X-Operator-Token": "test-secret"},
    )
    assert response.status_code == 404
