"""Submission and readback for Strategy 4 daily signal artifacts."""

from datetime import date

from flask import Blueprint, jsonify, request

from src.application.jobs import JobStore
from src.application.positional_trend_jobs import PositionalTrendJobs
from src.platform_kernel import DomainValidationError


def create_positional_trend_blueprint(strategy4: PositionalTrendJobs, jobs: JobStore) -> Blueprint:
    blueprint = Blueprint("strategy4_v2", __name__, url_prefix="/api/v2/strategy4")

    @blueprint.post("/signals/build")
    def build_signals():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {"as_of_date", "universe"} or "as_of_date" not in body:
            return jsonify({"error": "as_of_date is required; universe is optional"}), 400
        try:
            day = date.fromisoformat(str(body["as_of_date"]))
            universe = body.get("universe", "NIFTY500")
            if universe not in {"NIFTY500", "NIFTY_TOTAL_MARKET", "APPLICATION_MCAP500"}:
                raise DomainValidationError("universe is invalid")
            payload = {"as_of_date": day.isoformat(), "universe": universe}
            fingerprint = "strategy4-signals:" + strategy4.input_fingerprint(day, universe)
            job = jobs.submit(fingerprint, "research.strategy4-build-signals", payload)
        except (TypeError, ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc) or "as_of_date must be an ISO date"}), 400
        return jsonify({"job_id": job.job_id, "status": job.status.value,
                        "as_of_date": day.isoformat()}), 202

    @blueprint.get("/signals")
    def read_signals():
        try:
            day = date.fromisoformat(request.args["as_of_date"])
        except (KeyError, ValueError):
            return jsonify({"error": "as_of_date must be an ISO date"}), 400
        universe = request.args.get("universe", "NIFTY500")
        if universe not in {"NIFTY500", "NIFTY_TOTAL_MARKET", "APPLICATION_MCAP500"}:
            return jsonify({"error": "universe is invalid"}), 400
        try:
            found = strategy4.read_signals(day, universe)
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        if found is None:
            return jsonify({"error": "Strategy 4 signals not found"}), 404
        artifact_id, payload = found
        return jsonify({"artifact_id": artifact_id, "signals": payload})

    return blueprint
