"""Read-only endpoints for cataloged paper backtest runs."""

from flask import Blueprint, jsonify, request

from src.application.backtest_jobs import BacktestJobs
from src.application.web import require_operator_token
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

    @blueprint.get("/walk-forward/<walk_forward_id>")
    def read_walk_forward(walk_forward_id: str):
        try:
            manifest, payload = store.read_json("runs/backtest-walk-forward", walk_forward_id)
        except DomainValidationError:
            return jsonify({"error": "walk-forward report not found"}), 404
        return jsonify({"artifact": {"artifact_id": walk_forward_id, "quality": manifest.quality.value, "upstream_ids": manifest.upstream_ids}, "walk_forward": payload})

    @blueprint.get("/runs/<run_id>/attribution")
    def read_attribution(run_id: str):
        matches = []
        for manifest in store.manifests():
            if manifest.category != "runs/backtest-attribution":
                continue
            _, payload = store.read_json(manifest.category, manifest.artifact_id)
            if payload.get("run_id") == run_id:
                matches.append({"artifact": {"artifact_id": manifest.artifact_id, "quality": manifest.quality.value, "upstream_ids": manifest.upstream_ids}, "attribution": payload})
        return jsonify({"run_id": run_id, "reports": matches})

    @blueprint.get("/legacy-runs")
    def legacy_runs():
        try:
            limit = int(request.args.get("limit", "50"))
            return jsonify({"runs": jobs.legacy_runs(limit=limit), "legacy": True})
        except (ValueError, DomainValidationError):
            return jsonify({"error": "limit must be 1..100"}), 400

    @blueprint.get("/legacy-runs/<legacy_id>")
    def legacy_run(legacy_id: str):
        try:
            return jsonify(jobs.legacy_run(legacy_id))
        except DomainValidationError:
            return jsonify({"error": "legacy backtest run not found"}), 404

    @blueprint.get("/legacy-runs/<legacy_id>/compare/<run_id>")
    def compare_legacy(legacy_id: str, run_id: str):
        try:
            return jsonify(jobs.compare_legacy(legacy_id, run_id))
        except DomainValidationError:
            return jsonify({"error": "legacy or v4 backtest run not found or malformed"}), 404

    @blueprint.post("/legacy-runs/<legacy_id>/compare/<run_id>/publish")
    def publish_comparison(legacy_id: str, run_id: str):
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        try:
            return jsonify(jobs.publish_legacy_comparison(legacy_id, run_id)), 201
        except DomainValidationError:
            return jsonify({"error": "legacy or v4 backtest run not found or malformed"}), 404

    @blueprint.get("/parity/<artifact_id>")
    def read_parity(artifact_id: str):
        try:
            manifest, payload = store.read_json("runs/backtest-parity", artifact_id)
        except DomainValidationError:
            return jsonify({"error": "backtest parity artifact not found"}), 404
        return jsonify({
            "artifact": {
                "artifact_id": manifest.artifact_id,
                "category": manifest.category,
                "quality": manifest.quality.value,
                "upstream_ids": manifest.upstream_ids,
            },
            "comparison": payload,
        })

    return blueprint
