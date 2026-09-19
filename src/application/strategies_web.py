"""API for declarative strategy authoring; UI is intentionally separate."""

from flask import Blueprint, jsonify, request

from src.application.strategy_definitions import StrategyDefinitions
from src.platform_kernel import DomainValidationError


def create_strategies_blueprint(strategies: StrategyDefinitions) -> Blueprint:
    blueprint = Blueprint("strategies_v2", __name__, url_prefix="/api/v2/strategies")

    @blueprint.post("/revisions")
    def create_revision():
        body = request.get_json(silent=True)
        try:
            if not isinstance(body, dict) or set(body) != {"source_yaml"}:
                raise DomainValidationError("source_yaml is required")
            return jsonify(strategies.create_from_yaml(body["source_yaml"])), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/<strategy_id>/revisions")
    def revisions(strategy_id: str):
        return jsonify({"revisions": strategies.revisions(strategy_id)})

    @blueprint.get("/active")
    def active_revisions():
        return jsonify({"strategies": strategies.active_revisions()})

    @blueprint.get("/revisions/<revision_id>")
    def revision(revision_id: str):
        try:
            return jsonify(strategies.get(revision_id))
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 404

    @blueprint.post("/revisions/<revision_id>/activate")
    def activate(revision_id: str):
        try:
            return jsonify(strategies.activate(revision_id))
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 404 if "not found" in str(exc) else 409

    return blueprint
