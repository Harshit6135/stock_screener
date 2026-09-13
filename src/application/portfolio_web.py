"""Operator-protected manual paper-account commands and read models."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, jsonify, request

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


def _xirr(flows: list[tuple[date, Decimal]]) -> Decimal | None:
    if not flows or not any(value < 0 for _, value in flows) or not any(value > 0 for _, value in flows):
        return None
    origin = flows[0][0]
    rate = Decimal("0.1")
    for _ in range(50):
        value = sum(amount / (Decimal(1) + rate) ** (Decimal((day - origin).days) / Decimal(365)) for day, amount in flows)
        derivative = sum(-Decimal((day - origin).days) / Decimal(365) * amount / (Decimal(1) + rate) ** (Decimal((day - origin).days) / Decimal(365) + 1) for day, amount in flows)
        if not derivative:
            return None
        next_rate = rate - value / derivative
        if next_rate <= Decimal("-0.999999") or not isfinite(float(next_rate)):
            return None
        if abs(next_rate - rate) < Decimal("0.00000001"):
            return next_rate
        rate = next_rate
    return None


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

    @blueprint.post("/accounts/<account_id>/cash-transfers")
    def cash_transfer(account_id: str):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {
            "idempotency_key", "expected_version", "direction", "amount", "occurred_at"
        } or not {"idempotency_key", "expected_version", "direction", "amount"}.issubset(body):
            return jsonify({"error": "idempotency_key, expected_version, direction and amount are required"}), 400
        try:
            key = body["idempotency_key"]
            expected = body["expected_version"]
            if not isinstance(key, str) or not key.strip() or isinstance(expected, bool) or not isinstance(expected, int):
                raise DomainValidationError("cash transfer command is invalid")
            occurred_at = datetime.fromisoformat(body["occurred_at"]) if body.get("occurred_at") else None
            version = ledger.record_cash_transfer(
                account_id, key, expected, str(body["direction"]), _money(body["amount"], "amount"), occurred_at
            )
        except (KeyError, TypeError, ValueError, DomainValidationError) as exc:
            error = str(exc) if isinstance(exc, DomainValidationError) else "cash transfer command is invalid"
            status = 409 if "stale" in error or "idempotency" in error or "exceeds" in error else 400
            return jsonify({"error": error}), status
        return jsonify({"account_id": account_id, "version": version}), 201

    @blueprint.get("/accounts/<account_id>/valuation")
    def valuation(account_id: str):
        try:
            as_of = date.fromisoformat(request.args["as_of_date"])
            projection = ledger.projection_at(account_id, as_of)
        except (KeyError, ValueError):
            return jsonify({"error": "as_of_date must be an ISO date"}), 400
        except DomainValidationError:
            return jsonify({"error": "account not found"}), 404
        holdings = []
        market_value = Decimal(0)
        invested = Decimal(0)
        stop_risk = Decimal(0)
        for lot in projection.open_lots:
            bars = market.bars(lot.instrument_id, date.min, as_of, limit=1000)
            latest = bars[-1] if bars else None
            value = Decimal(str(latest["close"])) * lot.remaining_units.units if latest else Decimal(0)
            cost = lot.unit_cost.amount * lot.remaining_units.units
            entry_stop = lot.unit_cost.amount * Decimal("0.9")
            lot_risk = max(Decimal(0), value - entry_stop * lot.remaining_units.units)
            stop_risk += lot_risk
            market_value += value
            invested += cost
            identity = market.instrument_by_id(lot.instrument_id)
            holdings.append({
                "instrument_id": lot.instrument_id,
                "symbol": identity["symbol"] if identity else None,
                "units": lot.remaining_units.units,
                "cost": str(cost),
                "price": str(latest["close"]) if latest else None,
                "price_date": latest["as_of_date"] if latest else None,
                "fresh": bool(latest and latest["as_of_date"] == as_of.isoformat()),
                "market_value": str(value),
                "entry_stop": str(entry_stop),
                "current_trailing_stop": str(entry_stop),
                "stop_risk": str(lot_risk),
            })
        flows: list[tuple[date, Decimal]] = [(as_of, -Decimal(str(next(
            item["opening_cash"] for item in ledger.accounts() if item["account_id"] == account_id
        ))))]
        for item in ledger.events(account_id):
            event_day = date.fromisoformat(str(item["occurred_at"][:10]))
            if event_day > as_of:
                continue
            event = item["event"]
            if item["event_type"] == "CASH_TRANSFER":
                flows.append((event_day, Decimal(str(event["amount"])) * (-1 if event["direction"] == "DEPOSIT" else 1)))
            elif item["event_type"] == "FILL_RECORDED":
                value = Decimal(str(event["price"])) * Decimal(str(event["units"]))
                fee = Decimal(str(event.get("fee", "0")))
                flows.append((event_day, value - fee if event["side"] == "SELL" else -(value + fee)))
        flows.append((as_of, projection.cash.amount + market_value))
        result = {
            "account_id": account_id,
            "as_of_date": as_of.isoformat(),
            "cash": str(projection.cash.amount),
            "invested_cost": str(invested),
            "market_value": str(market_value),
            "unrealised_gain": str(market_value - invested),
            "equity": str(projection.cash.amount + market_value),
            "realised_pnl": str(projection.realised_pnl.amount),
            "stop_based_risk": str(stop_risk),
            "xirr": str(_xirr(sorted(flows),)) if _xirr(sorted(flows)) is not None else None,
            "stale_prices": sum(not item["fresh"] for item in holdings),
            "holdings": holdings,
        }
        if request.args.get("persist") == "1":
            import hashlib
            import json
            snapshot_id = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
            saved = ledger.save_valuation(account_id, snapshot_id, as_of, result)
            result["snapshot_id"] = saved["snapshot_id"]
            result["checksum_sha256"] = saved["checksum_sha256"]
        return jsonify(result)

    @blueprint.get("/accounts/<account_id>/ticker")
    def ticker(account_id: str):
        """Return the non-mutating current portfolio ticker read model."""
        as_of = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        try:
            projection = ledger.projection_at(account_id, as_of)
        except DomainValidationError:
            return jsonify({"error": "account not found"}), 404
        holdings = []
        market_value = Decimal(0)
        stale_prices = 0
        for lot in projection.open_lots:
            bars = market.bars(lot.instrument_id, date.min, as_of, limit=1000)
            latest = bars[-1] if bars else None
            if latest is None:
                stale_prices += 1
                price = None
                value = Decimal(0)
                price_date = None
            else:
                price = Decimal(str(latest["close"]))
                value = price * lot.remaining_units.units
                price_date = str(latest["as_of_date"])
                if price_date != as_of.isoformat():
                    stale_prices += 1
            market_value += value
            identity = market.instrument_by_id(lot.instrument_id)
            holdings.append({
                "instrument_id": lot.instrument_id,
                "symbol": identity["symbol"] if identity else None,
                "exchange": identity["exchange"] if identity else None,
                "units": lot.remaining_units.units,
                "price": str(price) if price is not None else None,
                "price_date": price_date,
                "fresh": price_date == as_of.isoformat(),
                "market_value": str(value),
            })
        return jsonify({
            "account_id": account_id,
            "observed_on": as_of.isoformat(),
            "cash": str(projection.cash.amount),
            "market_value": str(market_value),
            "equity": str(projection.cash.amount + market_value),
            "realised_pnl": str(projection.realised_pnl.amount),
            "stale_prices": stale_prices,
            "holdings": holdings,
            "basis": "latest_available_market_bar",
        })

    @blueprint.get("/accounts/<account_id>/ticker/stream")
    def ticker_stream(account_id: str):
        """Deliver one current ticker snapshot through a browser-safe SSE readback."""
        snapshot = ticker(account_id)
        if snapshot.status_code != 200:
            return snapshot
        response = Response(
            f"event: portfolio-ticker\ndata: {json.dumps(snapshot.get_json(), sort_keys=True)}\n\n",
            mimetype="text/event-stream",
        )
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Ticker-Delivery"] = "durable-snapshot-sse"
        return response

    @blueprint.get("/accounts/<account_id>/valuation/snapshots")
    def valuation_snapshots(account_id: str):
        try:
            limit = int(request.args.get("limit", "100"))
            return jsonify({"account_id": account_id, "snapshots": ledger.valuations(account_id, limit)})
        except ValueError:
            return jsonify({"error": "limit must be an integer"}), 400
        except DomainValidationError:
            return jsonify({"error": "account not found"}), 404

    @blueprint.get("/accounts/<account_id>/summary")
    def summary(account_id: str):
        try:
            as_of = date.fromisoformat(request.args["as_of_date"])
            snapshots = ledger.valuations(account_id, 100)
        except (KeyError, ValueError):
            return jsonify({"error": "as_of_date must be an ISO date"}), 400
        except DomainValidationError:
            return jsonify({"error": "account not found"}), 404
        candidates = [item for item in snapshots if str(item["as_of_date"]) <= as_of.isoformat()]
        if not candidates:
            return jsonify({"error": "valuation snapshot not found"}), 404
        snapshot = candidates[0]
        return jsonify({
            "account_id": account_id,
            "as_of_date": snapshot["as_of_date"],
            "summary_basis": "checksum_verified_valuation_snapshot",
            "snapshot": snapshot,
        })

    @blueprint.get("/accounts/<account_id>/valuation/history")
    def valuation_history(account_id: str):
        try:
            limit = int(request.args.get("limit", "100"))
            snapshots = list(reversed(ledger.valuations(account_id, limit)))
        except (ValueError, DomainValidationError):
            return jsonify({"error": "limit must be 1..100"}), 400
        peak = Decimal(0)
        history = []
        for snapshot in snapshots:
            equity = Decimal(str(snapshot["payload"]["equity"]))
            peak = max(peak, equity)
            drawdown = (equity / peak - Decimal(1)) if peak else Decimal(0)
            history.append({
                "as_of_date": snapshot["as_of_date"], "equity": str(equity),
                "drawdown": str(drawdown), "snapshot_id": snapshot["snapshot_id"],
                "checksum_sha256": snapshot["checksum_sha256"],
            })
        return jsonify({"account_id": account_id, "basis": "valuation_snapshots", "history": history})

    @blueprint.get("/accounts/<account_id>/journal")
    def journal(account_id: str):
        try:
            long_term_days = int(request.args.get("long_term_days", "365"))
            return jsonify({"account_id": account_id, "long_term_days": long_term_days, "journal": ledger.journal(account_id, long_term_days=long_term_days)})
        except ValueError:
            return jsonify({"error": "long_term_days must be an integer"}), 400
        except DomainValidationError:
            return jsonify({"error": "account not found"}), 404

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
