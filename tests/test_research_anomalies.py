from datetime import date, timedelta

from flask import Flask

from src.application.catalog import ArtifactCatalog
from src.application.publication import ArtifactPublisher
from src.application.research_jobs import ResearchJobs
from src.application.research_web import create_research_blueprint
from src.platform_kernel import ArtifactStore


class _Market:
    def histories(self, _start, _end):
        close = 100.0
        bars = []
        start = date(2026, 3, 1)
        for offset in range(24):
            day = start + timedelta(days=offset)
            bars.append({
                "as_of_date": day.isoformat(),
                "close": close,
                "snapshot_id": f"bar-{offset}",
            })
            close *= 1.01 if offset < 21 else 1.20
        return {"instrument-1": (bars, {"isin": "INE000000001", "symbol": "ABC"})}


def test_protected_anomaly_report_is_immutable_and_readable(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    research = ResearchJobs(database, _Market(), publisher)
    app = Flask(__name__)
    app.config["OPERATOR_TOKEN"] = "operator"
    app.register_blueprint(create_research_blueprint(publisher.store, research))
    client = app.test_client()
    command = {
        "as_of_date": "2026-03-24",
        "lookback_sessions": 20,
        "z_threshold": 2,
        "min_sessions": 20,
    }
    assert client.post("/api/v2/research/anomalies", json=command).status_code == 401
    response = client.post(
        "/api/v2/research/anomalies",
        json=command,
        headers={"X-Operator-Token": "operator"},
    )
    assert response.status_code == 201
    assert response.json["anomaly_count"] == 1
    artifact_id = response.json["artifact_id"]
    readback = client.get(f"/api/v2/research/anomalies/{artifact_id}")
    assert readback.status_code == 200
    assert readback.json["data"]["method"] == "latest-return-versus-prior-return-z-score"
    assert readback.json["data"]["rows"][0]["anomaly"] is True
    repeat = client.post(
        "/api/v2/research/anomalies",
        json=command,
        headers={"X-Operator-Token": "operator"},
    )
    assert repeat.json["artifact_id"] == artifact_id
