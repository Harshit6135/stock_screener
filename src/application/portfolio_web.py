"""Operator-protected manual paper-account commands and read models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from src.application.market_repository import MarketRepository
from src.application.web import require_operator_token
from src.execution_gateway import Ledger
from src.platform_kernel import DomainValidationError, Money, Quantity
from src.portfolio_accounting import Fill, FillSide


def _money(value: object, field: str) -> Money:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise DomainValidationError(f"{field} must be numeric")
    try:
        return Money(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise DomainValidationError(f"{field} must be numeric") from exc


def create_portfolio_blueprint(ledger: Ledger, market: MarketRepository) -> Blueprint:
    blueprint = Blueprint("portfolio_v2", __name__, url_prefix="/api/v2/portfolio")

    @blueprint.before_request
    def authorize():
        error = require_operator_token()
        if error:
            body, status = error
            return jsonify(body), status
        return None

    @blueprint.get("/accounts")
    def accounts():
        return jsonify({"accounts": ledger.accounts()})

    @blueprint.post("/accounts")
    def open_account():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"account_id", "opening_cash"}:
            return jsonify({"error": "account_id and opening_cash are required"}), 400
        try:
            account_id = body["account_id"]
            if not isinstance(account_id, str):
                raise DomainValidationError("account_id must be a string")
            ledger.open_account(account_id, _money(body["opening_cash"], "opening_cash"))
        except DomainValidationError as exc:
            status = 409 if "already exists" in str(exc) else 400
            return jsonify({"error": str(exc)}), status
        return jsonify({"account_id": account_id, "version": 0}), 201

    @blueprint.get("/accounts/<account_id>")
    def account(account_id: str):
        try:
            projection = ledger.projection(account_id)
        except DomainValidationError:
            return jsonify({"error": "account not found"}), 404
        summary = next(item for item in ledger.accounts() if item["account_id"] == account_id)
        holdings = []
        for lot in projection.open_lots:
            identity = market.instrument_by_id(lot.instrument_id)
            holdings.append(
                {
                    "instrument_id": lot.instrument_id,
                    "symbol": identity["symbol"] if identity else None,
                    "exchange": identity["exchange"] if identity else None,
                    "opened_on": lot.opened_on.isoformat(),
                    "units": lot.remaining_units.units,
                    "unit_cost": str(lot.unit_cost.amount),
                }
            )
        return jsonify(
            {
                "account_id": account_id,
                "version": summary["version"],
                "cash": str(projection.cash.amount),
                "currency": projection.cash.currency,
                "realised_pnl": str(projection.realised_pnl.amount),
                "open_lots": holdings,
            }
        )

    @blueprint.post("/accounts/<account_id>/fills")
    def record_fills(account_id: str):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {
            "idempotency_key",
            "expected_version",
            "fills",
        }:
            return jsonify(
                {"error": "idempotency_key, expected_version and fills are required"}
            ), 400
        try:
            key = body["idempotency_key"]
            expected = body["expected_version"]
            rows = body["fills"]
            if (
                not isinstance(key, str)
                or not key.strip()
                or isinstance(expected, bool)
                or not isinstance(expected, int)
                or not isinstance(rows, list)
                or not 1 <= len(rows) <= 100
            ):
                raise DomainValidationError("fill command is invalid")
            fills = []
            for row in rows:
                if not isinstance(row, dict) or set(row) - {
                    "symbol",
                    "exchange",
                    "fill_date",
                    "executed_at",
                    "side",
                    "units",
                    "price",
                    "fee",
                    "correlation_id",
                }:
                    raise DomainValidationError("fill entry contains invalid fields")
                symbol = row.get("symbol")
                exchange = row.get("exchange", "NSE")
                if not isinstance(symbol, str) or not isinstance(exchange, str):
                    raise DomainValidationError("fill symbol and exchange are required")
                identity = market.instrument(symbol, exchange)
                fill_date = date.fromisoformat(row["fill_date"])
                executed_at = (
                    datetime.fromisoformat(row["executed_at"])
                    if row.get("executed_at") is not None
                    else None
                )
                fills.append(
                    Fill(
                        str(identity["instrument_id"]),
                        fill_date,
                        FillSide(row["side"]),
                        Quantity(row["units"]),
                        _money(row["price"], "price"),
                        _money(row.get("fee", "0"), "fee"),
                        executed_at,
                        str(row["correlation_id"])
                        if row.get("correlation_id") is not None
                        else None,
                    )
                )
            version = ledger.record_fills(account_id, key, expected, fills)
        except (KeyError, TypeError, ValueError, DomainValidationError) as exc:
            error = (
                str(exc) if isinstance(exc, DomainValidationError) else "fill command is invalid"
            )
            status = 409 if "stale ledger version" in error or "idempotency key" in error else 400
            return jsonify({"error": error}), status
        return jsonify({"account_id": account_id, "version": version}), 201

    @blueprint.get("/accounts/<account_id>/events")
    def events(account_id: str):
        try:
            after = int(request.args.get("after_version", "0"))
            return jsonify({"events": ledger.events(account_id, after_version=after)})
        except ValueError:
            return jsonify({"error": "after_version must be an integer"}), 400
        except DomainValidationError as exc:
            status = 404 if "account does not exist" in str(exc) else 400
            return jsonify({"error": str(exc)}), status

    return blueprint
