"""Operator-protected HTTP API for immutable strategy settings."""

from flask import Blueprint, jsonify, request

from src.application.strategy_configs import StrategyConfigs
from src.application.web import require_operator_token
from src.platform_kernel import DomainValidationError


def create_configs_blueprint(configs: StrategyConfigs) -> Blueprint:
    blueprint = Blueprint("configs_v2", __name__, url_prefix="/api/v2/configs")

    @blueprint.get("/<strategy_id>/revisions")
    def revisions(strategy_id: str):
        try:
            return jsonify({"revisions": configs.revisions(strategy_id)})
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/<strategy_id>/active")
    def active(strategy_id: str):
        try:
            revision = configs.active(strategy_id, request.args.get("as_of_date", ""))
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"revision": revision}) if revision else (jsonify({"revision": None}), 404)

    @blueprint.post("/<strategy_id>/revisions")
    def create(strategy_id: str):
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        try:
            return jsonify(configs.create(strategy_id, request.get_json(silent=True))), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/revisions/<revision_id>/approve")
    def approve(revision_id: str):
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True)
        try:
            if not isinstance(body, dict) or set(body) != {"effective_from"}:
                raise DomainValidationError("effective_from is required")
            return jsonify(configs.approve(revision_id, body["effective_from"]))
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 404 if "not found" in str(exc) else 409

    return blueprint
