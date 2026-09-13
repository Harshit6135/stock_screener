from flask import Flask

from src.application.catalog import ArtifactCatalog
from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.application.research_jobs import ResearchJobs
from src.application.research_web import create_research_blueprint
from src.platform_kernel import ArtifactStore


def test_protected_strategy_parity_publishes_deltas_and_reads_back(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    feature_id = "feature-frozen-1"
    publisher.publish_json(
        "features/strategy2",
        feature_id,
        {
            "snapshot_id": feature_id,
            "as_of_date": "2026-03-27",
            "strategy_id": "strategy2",
            "formula_revision": "strategy2-v4-port-1",
            "values": {
                "instrument-1": {
                    "symbol": "ABC",
                    "factors": {
                        "trend": 60,
                        "momentum": 70,
                        "efficiency": 80,
                        "volume": 90,
                        "structure": 50,
                    },
                }
            },
        },
    )
    research = ResearchJobs(database, MarketRepository(database), publisher)
    app = Flask(__name__)
    app.config["OPERATOR_TOKEN"] = "operator"
    app.register_blueprint(create_research_blueprint(publisher.store, research))
    client = app.test_client()
    command = {
        "as_of_date": "2026-03-27",
        "strategy_id": "strategy2",
        "feature_artifact_id": feature_id,
        "legacy_factors": {
            "instrument-1": {
                "factor_trend": 55,
                "factor_momentum": 65,
                "factor_efficiency": 80,
                "factor_volume": 100,
                "factor_structure": 45,
            }
        },
    }
    assert client.post("/api/v2/research/parity", json=command).status_code == 401
    response = client.post(
        "/api/v2/research/parity",
        json=command,
        headers={"X-Operator-Token": "operator"},
    )
    assert response.status_code == 201
    artifact_id = response.json["artifact_id"]
    readback = client.get(f"/api/v2/research/parity/{artifact_id}")
    assert readback.status_code == 200
    assert readback.json["data"]["factor_deltas"]["instrument-1"] == {
        "trend": 5.0,
        "momentum": 5.0,
        "efficiency": 0.0,
        "volume": -10.0,
        "structure": 5.0,
    }
    assert client.post(
        "/api/v2/research/parity",
        json=command,
        headers={"X-Operator-Token": "operator"},
    ).json["artifact_id"] == artifact_id


def test_protected_candidate_parity_records_added_removed_and_rank_delta(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    ranking_id = "ranking-frozen-1"
    publisher.publish_json(
        "research/rankings",
        ranking_id,
        {
            "snapshot_id": ranking_id,
            "week_end": "2026-03-27",
            "strategy_id": "strategy2",
            "formula_revision": "strategy2-v4-port-1",
            "tie_policy": "composite_score_desc_symbol_asc",
            "members": [
                {"instrument_id": "a", "symbol": "AAA", "rank": 1},
                {"instrument_id": "c", "symbol": "CCC", "rank": 2},
            ],
        },
    )
    research = ResearchJobs(database, MarketRepository(database), publisher)
    app = Flask(__name__)
    app.config["OPERATOR_TOKEN"] = "operator"
    app.register_blueprint(create_research_blueprint(publisher.store, research))
    client = app.test_client()
    command = {
        "week_end": "2026-03-27",
        "ranking_artifact_id": ranking_id,
        "legacy_candidates": [
            {"instrument_id": "a", "symbol": "AAA", "rank": 2},
            {"instrument_id": "b", "symbol": "BBB", "rank": 1},
        ],
    }
    response = client.post(
        "/api/v2/research/candidate-parity",
        json=command,
        headers={"X-Operator-Token": "operator"},
    )
    assert response.status_code == 201
    readback = client.get(
        f"/api/v2/research/candidate-parity/{response.json['artifact_id']}"
    )
    assert readback.status_code == 200
    assert readback.json["data"]["added"] == ["c"]
    assert readback.json["data"]["removed"] == ["b"]
    assert readback.json["data"]["comparisons"][0]["rank_delta"] == -1
