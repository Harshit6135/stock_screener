"""Read-only query API for v4 feature, percentile, score and ranking artifacts."""

from datetime import date

from flask import Blueprint, jsonify, request

from src.application.research_jobs import ResearchJobs
from src.platform_kernel import ArtifactStore, DomainValidationError


def create_research_blueprint(store: ArtifactStore, research: ResearchJobs) -> Blueprint:
    blueprint = Blueprint("research_v2", __name__, url_prefix="/api/v2/research")

    categories = {
        "percentiles": "research/percentiles",
        "scores": "research/scores",
        "rankings": "research/rankings",
    }

    @blueprint.get("/<kind>/<artifact_id>")
    def artifact(kind: str, artifact_id: str):
        strategy_id = request.args.get("strategy_id", "strategy1")
        if strategy_id not in {"strategy1", "strategy2"}:
            return jsonify({"error": "strategy_id is invalid"}), 400
        category = f"features/{strategy_id}" if kind == "features" else categories.get(kind)
        if category is None:
            return jsonify({"error": "research artifact category not found"}), 404
        try:
            manifest, payload = store.read_json(category, artifact_id)
        except DomainValidationError:
            return jsonify({"error": "research artifact not found"}), 404
        return jsonify(
            {
                "artifact": {
                    "artifact_id": manifest.artifact_id,
                    "category": manifest.category,
                    "quality": manifest.quality.value,
                    "upstream_ids": manifest.upstream_ids,
                },
                "data": payload,
            }
        )

    @blueprint.get("/rankings")
    def top_rankings():
        try:
            week_end = date.fromisoformat(request.args["week_end"])
            limit = int(request.args.get("limit", "20"))
            strategy_id = request.args.get("strategy_id", "strategy1")
            return jsonify(
                {
                    "week_end": week_end.isoformat(),
                    "strategy_id": strategy_id,
                    "members": research.top_rankings(week_end, limit, strategy_id),
                }
            )
        except (KeyError, ValueError, DomainValidationError):
            return jsonify({"error": "week_end must be an ISO date and limit 1..500"}), 400

    return blueprint
