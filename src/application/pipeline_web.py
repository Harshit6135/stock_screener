"""Operator submission and readback for durable research pipelines."""

from flask import Blueprint, jsonify, request

from src.application.pipeline_jobs import ResearchPipelineJobs
from src.application.web import require_operator_token
from src.platform_kernel import DomainValidationError


def create_pipeline_blueprint(pipelines: ResearchPipelineJobs) -> Blueprint:
    blueprint = Blueprint("pipelines_v2", __name__, url_prefix="/api/v2/pipelines")

    @blueprint.post("/research")
    def submit():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "research pipeline payload must be an object"}), 400
        try:
            return jsonify(pipelines.submit(payload)), 202
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/research/<pipeline_id>")
    def status(pipeline_id: str):
        try:
            return jsonify(pipelines.status(pipeline_id))
        except DomainValidationError:
            return jsonify({"error": "research pipeline not found"}), 404

    return blueprint
