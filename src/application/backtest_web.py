"""Read-only endpoints for cataloged paper backtest runs."""

from flask import Blueprint, jsonify, request

from src.application.backtest_jobs import BacktestJobs
from src.platform_kernel import ArtifactStore, DomainValidationError


def create_backtest_blueprint(jobs: BacktestJobs, store: ArtifactStore) -> Blueprint:
    blueprint = Blueprint("backtests_v2", __name__, url_prefix="/api/v2/backtests")

    @blueprint.get("/runs")
    def list_runs():
        try:
            limit = int(request.args.get("limit", "50"))
            return jsonify({"runs": jobs.runs(limit)})
        except (ValueError, DomainValidationError):
            return jsonify({"error": "limit must be 1..100"}), 400

    @blueprint.get("/runs/<run_id>")
    def read_run(run_id: str):
        try:
            artifact_id = jobs.run_artifact_id(run_id)
            manifest, payload = store.read_json("runs/backtests", artifact_id)
        except DomainValidationError:
            return jsonify({"error": "backtest run not found"}), 404
        return jsonify(
            {
                "artifact": {
                    "artifact_id": artifact_id,
                    "quality": manifest.quality.value,
                    "upstream_ids": manifest.upstream_ids,
                },
                "run": payload,
            }
        )

    return blueprint
