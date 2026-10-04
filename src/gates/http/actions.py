"""Reviewable portfolio action proposals and manually confirmed transactions."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

from src.gates.workflows.portfolio_actions import ActionJobs
from src.platform_kernel import DomainValidationError


def create_actions_blueprint(actions: ActionJobs) -> Blueprint:
    blueprint = Blueprint("actions", __name__, url_prefix="/api/actions")

    @blueprint.get("/proposals")
    def proposals():
        account_id = request.args.get("account_id", "")
        if not account_id:
            return jsonify({"error": "account_id is required"}), 400
        try:
            limit = int(request.args.get("limit", "50"))
            action_date = request.args.get("action_date")
            parsed_date = date.fromisoformat(action_date) if action_date else None
            strategy_id = request.args.get("strategy_id") or None
            return jsonify({"proposals": actions.proposals(account_id, limit, parsed_date, strategy_id)})
        except (ValueError, DomainValidationError):
            return jsonify({"error": "limit must be 1..100"}), 400

    @blueprint.get("/sessions/latest")
    def latest_signal_session():
        try:
            target = date.fromisoformat(request.args["action_date"])
        except (KeyError, ValueError):
            return jsonify({"error": "action_date must be an ISO date"}), 400
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        end = min(target - timedelta(days=1), today - timedelta(days=1))
        sessions = actions.market.session_dates(end - timedelta(days=30), end, exchange="NSE")
        if not sessions:
            return jsonify({"error": "no completed stored NSE session was found before that date"}), 404
        return jsonify({"as_of_date": sessions[-1], "action_date": target.isoformat()})

    @blueprint.get("/proposals/dates")
    def proposal_dates():
        account_id = request.args.get("account_id", "")
        if not account_id:
            return jsonify({"error": "account_id is required"}), 400
        return jsonify({"account_id": account_id, "action_dates": [item.isoformat() for item in actions.action_dates(account_id)]})

    @blueprint.get("/risk")
    def risk():
        account_id = request.args.get("account_id", "")
        if not account_id:
            return jsonify({"error": "account_id is required"}), 400
        try:
            action_date = date.fromisoformat(request.args["action_date"]) if request.args.get("action_date") else None
        except ValueError:
            return jsonify({"error": "action_date must be an ISO date"}), 400
        return jsonify({"account_id": account_id, "projections": actions.risk_projection(account_id, action_date)})

    @blueprint.post("/risk/update")
    def update_risk():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "risk update payload must be an object"}), 400
        try:
            return jsonify(actions.update_risk_projection(body)), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/manual")
    def manual():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "manual action payload must be an object"}), 400
        try:
            return jsonify(actions.create_manual(body)), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/execution-policy-parity")
    def execution_policy_parity():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "execution policy parity payload must be an object"}), 400
        try:
            return jsonify(actions.compare_execution_policy(body)), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/execution-policy-parity/<artifact_id>")
    def execution_policy_parity_readback(artifact_id: str):
        try:
            manifest, payload = actions.publisher.store.read_json(
                "actions/execution-policy-parity", artifact_id
            )
        except DomainValidationError:
            return jsonify({"error": "execution policy parity artifact not found"}), 404
        return jsonify({
            "artifact": {
                "artifact_id": manifest.artifact_id,
                "category": manifest.category,
                "quality": manifest.quality.value,
                "upstream_ids": manifest.upstream_ids,
            },
            "data": payload,
        })

    @blueprint.post("/midweek-stop")
    def midweek_stop():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "midweek stop payload must be an object"}), 400
        try:
            return jsonify(actions.generate_midweek_stop(body)), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

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

    @blueprint.post("/proposals/<proposal_id>/amend")
    def amend(proposal_id: str):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"decisions", "reason"}:
            return jsonify({"error": "decisions and reason are required"}), 400
        try:
            return jsonify(actions.amend(proposal_id, body["decisions"], body["reason"])), 201
        except DomainValidationError as exc:
            status = 404 if "not found" in str(exc) else 409
            return jsonify({"error": str(exc)}), status

    @blueprint.post("/proposals/bulk-decision")
    def bulk_decision():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"proposal_ids", "action"} or body["action"] not in {"APPROVED", "REJECTED"}:
            return jsonify({"error": "proposal_ids and action are required"}), 400
        if not isinstance(body["proposal_ids"], list) or not 1 <= len(body["proposal_ids"]) <= 100:
            return jsonify({"error": "proposal_ids must contain 1..100 items"}), 400
        try:
            results = [actions.decide(str(proposal_id), body["action"]) for proposal_id in body["proposal_ids"]]
            return jsonify({"proposals": results}), 200
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 409

    return blueprint
