"""Read-only query API for v4 feature, percentile, score and ranking artifacts."""

import hashlib
import json
from datetime import date

from flask import Blueprint, jsonify, request

from src.application.jobs import JobStore
from src.application.research_jobs import ResearchJobs
from src.platform_kernel import ArtifactStore, DomainValidationError


def create_research_blueprint(store: ArtifactStore, research: ResearchJobs, jobs: JobStore | None = None) -> Blueprint:
    blueprint = Blueprint("research_v2", __name__, url_prefix="/api/v2/research")

    categories = {
        "percentiles": "research/percentiles",
        "scores": "research/scores",
        "rankings": "research/rankings",
    }

    @blueprint.get("/<kind>/<artifact_id>")
    def artifact(kind: str, artifact_id: str):
        strategy_id = request.args.get("strategy_id", research.runtime.strategy_ids()[0])
        if strategy_id not in research.runtime.strategy_ids():
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
            strategy_id = request.args.get("strategy_id", research.runtime.strategy_ids()[0])
            return jsonify(
                {
                    "week_end": week_end.isoformat(),
                    "strategy_id": strategy_id,
                    "members": research.top_rankings(week_end, limit, strategy_id),
                }
            )
        except (KeyError, ValueError, DomainValidationError):
            return jsonify({"error": "week_end must be an ISO date and limit 1..500"}), 400

    @blueprint.post("/recalculate")
    def recalculate():
        if jobs is None:
            return jsonify({"error": "research job service is unavailable"}), 503
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"as_of_date", "strategy_id", "symbols"}:
            return jsonify({"error": "as_of_date, strategy_id and symbols are required"}), 400
        strategy_id = body["strategy_id"]
        if strategy_id not in research.runtime.strategy_ids():
            return jsonify({"error": "strategy_id is invalid"}), 400
        try:
            day = date.fromisoformat(str(body["as_of_date"]))
        except ValueError:
            return jsonify({"error": "as_of_date must be an ISO date"}), 400
        symbols = body["symbols"]
        if not isinstance(symbols, list) or not symbols or len(symbols) > 500 or any(not isinstance(symbol, str) or not symbol.strip() for symbol in symbols):
            return jsonify({"error": "symbols must contain 1..500 names"}), 400
        normalized = {"as_of_date": day.isoformat(), "strategy_id": strategy_id, "symbols": sorted(set(symbols))}
        fingerprint = "research-patch:" + hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
        kind = "research.rebuild-range"
        job = jobs.submit(
            fingerprint,
            kind,
            {
                "start_date": day.isoformat(),
                "end_date": day.isoformat(),
                "strategies": [strategy_id],
                "trading_dates": [day.isoformat()],
            },
        )
        return jsonify({
            "job_id": job.job_id,
            "fingerprint": job.fingerprint,
            "status": job.status.value,
            "requested_symbols": normalized["symbols"],
            "execution_scope": "full-universe cross-section",
        }), 202

    @blueprint.post("/sector-rankings")
    def sector_rankings():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "sector ranking payload must be an object"}), 400
        try:
            return jsonify(research.sector_normalize(body)), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/correlations")
    def correlations():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "correlation payload must be an object"}), 400
        try:
            return jsonify(research.correlations(body)), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/anomalies")
    def anomalies():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "anomaly payload must be an object"}), 400
        try:
            return jsonify(research.anomalies(body)), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/anomalies/<artifact_id>")
    def anomaly_readback(artifact_id: str):
        try:
            manifest, payload = store.read_json("research/anomalies", artifact_id)
        except DomainValidationError:
            return jsonify({"error": "anomaly artifact not found"}), 404
        return jsonify({
            "artifact": {
                "artifact_id": manifest.artifact_id,
                "category": manifest.category,
                "quality": manifest.quality.value,
                "upstream_ids": manifest.upstream_ids,
            },
            "data": payload,
        })

    @blueprint.get("/<kind>")
    def read_snapshot(kind: str):
        if kind not in {"features", "percentiles", "scores", "rankings"}:
            return jsonify({"error": "research artifact category not found"}), 404
        strategy_id = request.args.get("strategy_id", research.runtime.strategy_ids()[0])
        symbol = request.args.get("symbol")
        date_text = request.args.get("as_of_date", request.args.get("week_end"))
        try:
            requested = date.fromisoformat(date_text) if date_text else None
            payload = research.read_snapshot(kind, strategy_id, requested, symbol)
        except (ValueError, DomainValidationError):
            return jsonify({"error": "research snapshot query is invalid"}), 400
        if payload is None:
            return jsonify({"error": "research snapshot not found"}), 404
        artifact_id = str(payload.get("snapshot_id", ""))
        category = f"features/{strategy_id}" if kind == "features" else f"research/{kind}"
        try:
            manifest, _ = store.read_json(category, artifact_id)
            summary = {
                "artifact_id": manifest.artifact_id,
                "category": manifest.category,
                "quality": manifest.quality.value,
                "upstream_ids": manifest.upstream_ids,
            }
        except DomainValidationError:
            return jsonify({"error": "research snapshot not found"}), 404
        return jsonify(
            {
                "kind": kind,
                "strategy_id": strategy_id,
                "as_of_date": payload.get("as_of_date", payload.get("week_end")),
                "source_artifact": summary,
                "data": payload,
            }
        )

    @blueprint.get("/ranking-weeks")
    def ranking_weeks():
        strategy_id = request.args.get("strategy_id", research.runtime.strategy_ids()[0])
        try:
            return jsonify(
                {
                    "strategy_id": strategy_id,
                    "week_ends": [
                        item.isoformat() for item in research.ranking_weeks(strategy_id)
                    ],
                }
            )
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    return blueprint
