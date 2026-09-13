from run import create_app
from src.application.runtime import RuntimeConfig

SETTINGS = {
    "initial_capital": "100000",
    "risk_threshold": "1",
    "max_positions": 10,
    "min_position_percent": "0.05",
    "exit_threshold": "40",
    "buffer_percent": "0.25",
    "sl_multiplier": "2",
    "hard_sl_percent": "0.03",
    "atr_fallback_percent": "0.06",
    "max_concentration_pct": "0.25",
}


def test_versioned_strategy_configuration_lifecycle(tmp_path):
    class TestConfig(RuntimeConfig):
        DATA_DIRECTORY = tmp_path
        OPERATOR_TOKEN = "test-secret"
        KITE_API_KEY = None
        KITE_API_SECRET = None

    client = create_app(TestConfig).test_client()
    base = "/api/v2/configs/strategy1"
    assert client.get(f"{base}/active?as_of_date=2026-09-01").status_code == 404
    assert client.post(f"{base}/revisions", json=SETTINGS).status_code == 401
    headers = {"X-Operator-Token": "test-secret"}
    created = client.post(f"{base}/revisions", json=SETTINGS, headers=headers)
    assert created.status_code == 201
    revision_id = created.json["revision_id"]
    assert created.json["status"] == "DRAFT"
    assert (
        client.post(
            f"/api/v2/configs/revisions/{revision_id}/approve",
            json={"effective_from": "2026-09-01"},
            headers=headers,
        ).json["status"]
        == "APPROVED"
    )
    active = client.get(f"{base}/active?as_of_date=2026-09-01")
    assert active.status_code == 200
    assert active.json["revision"]["revision_id"] == revision_id
    assert active.json["revision"]["settings"]["max_positions"] == 10
    assert (
        client.post(
            f"/api/v2/configs/revisions/{revision_id}/approve",
            json={"effective_from": "2026-09-02"},
            headers=headers,
        ).status_code
        == 409
    )


def test_config_rejects_partial_and_conflicting_revisions(tmp_path):
    class TestConfig(RuntimeConfig):
        DATA_DIRECTORY = tmp_path
        OPERATOR_TOKEN = "test-secret"
        KITE_API_KEY = None
        KITE_API_SECRET = None

    client = create_app(TestConfig).test_client()
    headers = {"X-Operator-Token": "test-secret"}
    assert (
        client.post("/api/v2/configs/strategy1/revisions", json={}, headers=headers).status_code
        == 400
    )
    first = client.post("/api/v2/configs/strategy1/revisions", json=SETTINGS, headers=headers)
    second_settings = {**SETTINGS, "max_positions": 9}
    second = client.post(
        "/api/v2/configs/strategy1/revisions", json=second_settings, headers=headers
    )
    approve = "/api/v2/configs/revisions/{}/approve"
    assert (
        client.post(
            approve.format(first.json["revision_id"]),
            json={"effective_from": "2026-09-01"},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            approve.format(second.json["revision_id"]),
            json={"effective_from": "2026-09-01"},
            headers=headers,
        ).status_code
        == 409
    )
