"""Operator-protected review and processing of paper action proposals."""

from flask import Blueprint, jsonify, request

from src.application.action_jobs import ActionJobs
from src.application.web import require_operator_token
from src.platform_kernel import DomainValidationError


def create_actions_blueprint(actions: ActionJobs) -> Blueprint:
    blueprint = Blueprint("actions_v2", __name__, url_prefix="/api/v2/actions")

    @blueprint.before_request
    def authorize():
        error = require_operator_token()
        if error:
            body, status = error
            return jsonify(body), status
        return None

    @blueprint.get("/proposals")
    def proposals():
        account_id = request.args.get("account_id", "")
        if not account_id:
            return jsonify({"error": "account_id is required"}), 400
        try:
            limit = int(request.args.get("limit", "50"))
            return jsonify({"proposals": actions.proposals(account_id, limit)})
        except (ValueError, DomainValidationError):
            return jsonify({"error": "limit must be 1..100"}), 400

    @blueprint.get("/proposals/<proposal_id>")
    def proposal(proposal_id: str):
        try:
            return jsonify(actions.proposal(proposal_id))
        except DomainValidationError:
            return jsonify({"error": "action proposal not found"}), 404

    @blueprint.get("/proposals/<proposal_id>/events")
    def events(proposal_id: str):
        try:
            return jsonify({"events": actions.events(proposal_id)})
        except DomainValidationError:
            return jsonify({"error": "action proposal not found"}), 404

    @blueprint.post("/proposals/<proposal_id>/approve")
    def approve(proposal_id: str):
        try:
            return jsonify(actions.decide(proposal_id, "APPROVED"))
        except DomainValidationError as exc:
            status = 404 if "not found" in str(exc) else 409
            return jsonify({"error": str(exc)}), status

    @blueprint.post("/proposals/<proposal_id>/reject")
    def reject(proposal_id: str):
        try:
            return jsonify(actions.decide(proposal_id, "REJECTED"))
        except DomainValidationError as exc:
            status = 404 if "not found" in str(exc) else 409
            return jsonify({"error": str(exc)}), status

    @blueprint.post("/proposals/<proposal_id>/process")
    def process(proposal_id: str):
        try:
            return jsonify(actions.process(proposal_id))
        except DomainValidationError as exc:
            status = 404 if "not found" in str(exc) else 409
            return jsonify({"error": str(exc)}), status

    return blueprint
