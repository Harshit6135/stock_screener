from datetime import date, timedelta
from uuid import uuid4

from run import create_app


def _command() -> dict[str, object]:
    instrument_id = str(uuid4())
    as_of_date = date(2026, 3, 27)
    return {
        "as_of_date": as_of_date.isoformat(),
        "policy": {
            "policy_id": str(uuid4()),
            "name": "Liquidity v1",
            "lookback_sessions": 60,
            "minimum_valid_sessions": 54,
            "minimum_median_daily_turnover": 1500,
        },
        "instruments": [
            {
                "instrument_id": instrument_id,
                "isin": "INE000000001",
                "symbol": "ABC",
                "exchange": "NSE",
            }
        ],
        "bars": [
            {
                "instrument_id": instrument_id,
                "as_of_date": (as_of_date - timedelta(days=53 - offset)).isoformat(),
                "open": 99,
                "high": 101,
                "low": 98,
                "close": 100,
                "volume": 20,
            }
            for offset in range(54)
        ],
    }


def test_reference_api_reads_checksum_verified_liquidity_universe(tmp_path):
    class TestConfig:
        TESTING = True
        SECRET_KEY = "test"
        DATA_DIRECTORY = tmp_path
        OPERATOR_TOKEN = "operator"

    app = create_app(TestConfig)
    services = app.extensions["screener_services"]
    job = services.jobs.submit(
        "liquidity:2026-03-27",
        "research.build-liquidity-universe",
        _command(),
        max_attempts=1,
    )
    completed = services.worker.run_once()
    assert completed is not None and completed.result is not None

    response = app.test_client().get(
        f"/api/v2/reference/liquidity-universes/{completed.result['artifact_id']}"
    )

    assert job.job_id == completed.job_id
    assert response.status_code == 200
    assert response.json["artifact"]["quality"] == "COMPLETE"
    assert response.json["universe"]["members"][0]["eligible"] is True
