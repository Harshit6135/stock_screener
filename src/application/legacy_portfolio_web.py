"""Operator endpoints for previewing and importing a v3 personal database."""

from flask import Blueprint, jsonify, request

from src.application.legacy_portfolio import LegacyPortfolioImporter
from src.application.web import require_operator_token
from src.platform_kernel import DomainValidationError


def create_legacy_portfolio_blueprint(importer: LegacyPortfolioImporter) -> Blueprint:
    blueprint = Blueprint("legacy_portfolio_v2", __name__, url_prefix="/api/v2/portfolio")

    @blueprint.post("/import-v3/preview")
    def preview():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "legacy preview payload must be an object"}), 400
        try:
            return jsonify(importer.preview(payload))
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/import-v3")
    def import_account():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "legacy import payload must be an object"}), 400
        try:
            return jsonify(importer.import_account(payload)), 201
        except DomainValidationError as exc:
            status = 409 if "already exists" in str(exc) or "unresolved" in str(exc) else 400
            return jsonify({"error": str(exc)}), status

    return blueprint
