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
    assert b"Paper account" in response.data
    assert b"Paper action proposals" in response.data
    assert client.get("/health/ready").status_code == 200
    assert client.get("/api/v2/actions/proposals?account_id=paper").status_code == 401
    assert (
        client.get(
            "/api/v2/actions/proposals?account_id=paper",
            headers={"X-Operator-Token": "test-secret"},
        ).status_code
        == 200
    )
    assert client.get("/integrations/kite").status_code == 200
