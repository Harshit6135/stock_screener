from datetime import date, timedelta
from uuid import uuid4

from src.application.composition import ApplicationServices
from src.application.jobs import JobStatus


def _command() -> dict[str, object]:
    instrument_id = str(uuid4())
    as_of_date = date(2026, 3, 27)
    bars = []
    for offset in range(54):
        bars.append(
            {
                "instrument_id": instrument_id,
                "as_of_date": (as_of_date - timedelta(days=53 - offset)).isoformat(),
                "open": 99,
                "high": 101,
                "low": 98,
                "close": 100,
                "volume": 20,
            }
        )
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
        "bars": bars,
    }


def test_liquidity_universe_job_validates_command_and_catalogs_artifact(tmp_path):
    services = ApplicationServices.create(tmp_path)
    job = services.jobs.submit(
        "liquidity:2026-03-27",
        "research.build-liquidity-universe",
        _command(),
        max_attempts=1,
    )

    completed = services.worker.run_once()

    assert completed is not None
    assert completed.last_error is None, completed
    assert completed.status == JobStatus.SUCCEEDED
    assert completed.result is not None
    artifact_id = completed.result["artifact_id"]
    assert isinstance(artifact_id, str)
    assert services.catalog.has(artifact_id)
    _, payload = services.artifacts.read_json("reference/liquidity_universes", artifact_id)
    assert payload["members"][0]["eligible"] is True
    assert services.jobs.get(job.job_id) == completed
