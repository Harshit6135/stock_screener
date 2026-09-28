"""Local account/setup/reconciliation API; credential values never read back."""
from flask import Blueprint, jsonify, request
from src.platform_kernel import DomainValidationError


def create_kite_accounts_blueprint(accounts, sync) -> Blueprint:
    blueprint = Blueprint("kite_accounts_v2", __name__, url_prefix="/api/v2/broker-accounts")

    @blueprint.get("")
    def list_accounts():
        return jsonify({"accounts": accounts.list_accounts()})

    @blueprint.post("")
    def register():
        body = request.get_json(silent=True) or {}
        try:
            if set(body) != {"broker_account_id", "account_name", "api_key", "api_secret"}:
                raise DomainValidationError("broker account payload is invalid")
            accounts.register_account(**body)
            return jsonify({"broker_account_id": body["broker_account_id"]}), 201
        except (TypeError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/setup")
    def setup():
        try:
            return jsonify(sync.setup(request.get_json(silent=True) or {})), 201
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/reconcile")
    def reconcile():
        try:
            return jsonify(sync.reconcile(request.get_json(silent=True) or {})), 201
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400
    return blueprint
