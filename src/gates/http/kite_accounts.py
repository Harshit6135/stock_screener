"""Local account/setup/reconciliation API; credential values never read back."""

import time

from flask import Blueprint, jsonify, request, session

from src.platform_kernel import DomainValidationError


def create_kite_accounts_blueprint(accounts, sync, history_scheduler=None) -> Blueprint:
    blueprint = Blueprint("kite_accounts", __name__, url_prefix="/api/broker-accounts")

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

    @blueprint.put("/<broker_account_id>")
    def update_details(broker_account_id):
        body = request.get_json(silent=True) or {}
        try:
            if set(body) - {"account_name", "api_key", "api_secret"} or not body.get(
                "account_name"
            ):
                raise DomainValidationError(
                    "account name and optional replacement API credentials are required"
                )
            if bool(body.get("api_key")) != bool(body.get("api_secret")):
                raise DomainValidationError("enter both replacement API key and secret")
            previous = accounts.get_credentials(broker_account_id)
            accounts.register_account(
                broker_account_id,
                body["account_name"],
                body.get("api_key") or previous["api_key"],
                body.get("api_secret") or previous["api_secret"],
            )
            return jsonify(
                {
                    "broker_account_id": broker_account_id,
                    "login_required": bool(body.get("api_key")),
                }
            )
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
            return jsonify(
                accounts.authenticate(
                    broker_account_id, (request.get_json(silent=True) or {}).get("request_token")
                )
            )
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/<broker_account_id>/validate")
    def validate(broker_account_id):
        try:
            return jsonify(accounts.validate(broker_account_id))
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/<broker_account_id>/authorize")
    def authorize(broker_account_id):
        try:
            login_url = accounts.login_url(broker_account_id)
            session.pop("kite_authorization_started_at:market-data", None)
            session.pop("kite_authorization_started_at:portfolio", None)
            session["portfolio_broker_authorization"] = {
                "broker_account_id": broker_account_id,
                "started_at": time.time(),
            }
            return jsonify({"authorization_url": login_url})
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/<broker_account_id>/holdings")
    def holdings(broker_account_id):
        try:
            accounts.validate(broker_account_id)
            rows = accounts.client(broker_account_id).holdings()
            return jsonify(
                {
                    "broker_account_id": broker_account_id,
                    "holdings": [
                        {
                            key: row.get(key)
                            for key in (
                                "tradingsymbol",
                                "exchange",
                                "isin",
                                "quantity",
                                "t1_quantity",
                                "average_price",
                            )
                        }
                        for row in rows
                    ],
                }
            )
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:  # noqa: BLE001
            return jsonify({"error": "selected broker holdings read failed"}), 400

    @blueprint.post("/reconcile")
    def reconcile():
        try:
            return jsonify(sync.reconcile(request.get_json(silent=True) or {})), 201
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/<broker_account_id>/import-holdings")
    def import_holdings(broker_account_id):
        try:
            body = request.get_json(silent=True)
            if body is not None and (
                not isinstance(body, dict)
                or set(body) - {"purchase_dates"} != {"selected_instrument_ids"}
                or not isinstance(body["selected_instrument_ids"], list)
            ):
                raise DomainValidationError(
                    "selected_instrument_ids is required for a selected import"
                )
            result = sync.import_holdings(
                    broker_account_id,
                    body["selected_instrument_ids"] if body else None,
                    purchase_dates=body.get("purchase_dates") if body else None,
                )
            if history_scheduler and result.get('imported_positions'):
                result['history_backfill_job_id'] = history_scheduler(broker_account_id)
            return jsonify(result)
        except (KeyError, TypeError, ValueError, DomainValidationError) as exc:
            error = (
                str(exc)
                if isinstance(exc, DomainValidationError)
                else "broker holdings payload is invalid"
            )
            return jsonify({"error": error}), 400

    @blueprint.get("/<broker_account_id>/import-preview")
    def import_preview(broker_account_id):
        try:
            return jsonify(sync.preview_holdings(broker_account_id))
        except (KeyError, TypeError, ValueError, DomainValidationError) as exc:
            error = (
                str(exc)
                if isinstance(exc, DomainValidationError)
                else "broker holdings payload is invalid"
            )
            return jsonify({"error": error}), 400

    return blueprint
