"""Submission and readback for Positional Trend Following daily signal artifacts."""

from datetime import date

from flask import Blueprint, jsonify, request

from src.domains.operations import JobStore
from src.gates.workflows.positional_trend import PositionalTrendJobs
from src.platform_kernel import DomainValidationError


def create_positional_trend_blueprint(positional_trend: PositionalTrendJobs, jobs: JobStore) -> Blueprint:
    blueprint = Blueprint("positional_trend", __name__, url_prefix="/api/positional-trend")

    @blueprint.post("/signals/build")
    def build_signals():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {"as_of_date", "universe"} or "as_of_date" not in body:
            return jsonify({"error": "as_of_date is required; universe is optional"}), 400
        try:
            day = date.fromisoformat(str(body["as_of_date"]))
            universe = body.get("universe", "SNAPSHOT_NIFTY500")
            if universe not in {"SNAPSHOT_NIFTY500", "APPLICATION_MCAP500"}:
                raise DomainValidationError("universe is invalid")
            payload = {"as_of_date": day.isoformat(), "universe": universe}
            fingerprint = "positional-trend-signals:" + positional_trend.input_fingerprint(day, universe)
            job = jobs.submit(fingerprint, "research.positional-trend-build-signals", payload)
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
        universe = request.args.get("universe", "SNAPSHOT_NIFTY500")
        if universe not in {"SNAPSHOT_NIFTY500", "APPLICATION_MCAP500"}:
            return jsonify({"error": "universe is invalid"}), 400
        try:
            found = positional_trend.read_signals(day, universe)
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        if found is None:
            return jsonify({"error": "positional trend signals not found"}), 404
        artifact_id, payload = found
        return jsonify({"artifact_id": artifact_id, "signals": payload})

    return blueprint
