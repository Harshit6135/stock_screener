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

    @blueprint.get("/<broker_account_id>/login-url")
    def login_url(broker_account_id):
        try:
            return jsonify({"login_url": accounts.login_url(broker_account_id)})
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/<broker_account_id>/authenticate")
    def authenticate(broker_account_id):
        try:
            return jsonify(accounts.authenticate(broker_account_id, (request.get_json(silent=True) or {}).get("request_token")))
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/<broker_account_id>/validate")
    def validate(broker_account_id):
        try:
            return jsonify(accounts.validate(broker_account_id))
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/<broker_account_id>/holdings")
    def holdings(broker_account_id):
        try:
            accounts.validate(broker_account_id)
            rows = accounts.client(broker_account_id).holdings()
            return jsonify({"broker_account_id": broker_account_id, "holdings": [
                {key: row.get(key) for key in ("tradingsymbol", "exchange", "isin", "quantity", "t1_quantity", "average_price")}
                for row in rows]})
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            return jsonify({"error": "selected broker holdings read failed"}), 400

    @blueprint.post("/reconcile")
    def reconcile():
        try:
            return jsonify(sync.reconcile(request.get_json(silent=True) or {})), 201
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400
    return blueprint
