"""Local manual portfolio commands and read models."""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, jsonify, request, stream_with_context

from src.domains.portfolio_accounting import Fill, FillSide, Ledger
from src.domains.portfolio_engine import RiskGuardLimits
from src.gates.repositories import MarketRepository
from src.gates.workflows.portfolio_history import portfolio_history
from src.gates.workflows.portfolio_ticker import live_portfolio_ticker
from src.gates.workflows.portfolio_valuation import portfolio_valuation
from src.platform_kernel import DomainValidationError, Money, Quantity
from src.platform_kernel.sqlite_read_cache import SqliteReadCache


def _money(value: object, field: str) -> Money:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise DomainValidationError(f"{field} must be numeric")
    try:
        return Money(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise DomainValidationError(f"{field} must be numeric") from exc


def create_portfolio_blueprint(
    ledger: Ledger, market: MarketRepository, risk_reader=None, risk_config=None, broker_sync=None,
    live_quotes=None, intraday_stream=None, history_rebuilder=None,
) -> Blueprint:
    blueprint = Blueprint("portfolio", __name__, url_prefix="/api/portfolio")
    read_cache = SqliteReadCache((ledger.path, market.path))

    @blueprint.get("/accounts")
    def accounts():
        return jsonify({"accounts": ledger.accounts()})

    @blueprint.get("/risk-config")
    def get_risk_config():
        if risk_config is None:
            return jsonify({"error": "risk configuration is unavailable"}), 404
        version, limits = risk_config.get_limits()
        return jsonify({"version": version, "limits": limits.__dict__})

    @blueprint.put("/risk-config")
    def update_risk_config():
        if risk_config is None:
            return jsonify({"error": "risk configuration is unavailable"}), 404
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"expected_version", "limits"}:
            return jsonify({"error": "expected_version and limits are required"}), 400
        try:
            expected = body["expected_version"]
            if (
                isinstance(expected, bool)
                or not isinstance(expected, int)
                or not isinstance(body["limits"], dict)
            ):
                raise DomainValidationError("risk configuration payload is invalid")
            current, _ = risk_config.get_limits()
            if current != expected:
                raise DomainValidationError("stale risk configuration version")
            allowed = set(RiskGuardLimits.__dataclass_fields__)
            if set(body["limits"]) - allowed:
                raise DomainValidationError("risk configuration contains unsupported limits")
            version = risk_config.update_limits(RiskGuardLimits(**body["limits"]), expected)
        except (TypeError, DomainValidationError) as exc:
            status = 409 if "stale" in str(exc) else 400
            return jsonify({"error": str(exc)}), status
        return jsonify({"version": version}), 200

    @blueprint.post("/accounts")
    def open_account():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {"opening_date"} != {
            "account_id",
            "opening_cash",
        }:
            return jsonify({"error": "account_id and opening_cash are required"}), 400
        try:
            account_id = body["account_id"]
            if not isinstance(account_id, str):
                raise DomainValidationError("account_id must be a string")
            opened = date.fromisoformat(body["opening_date"]) if "opening_date" in body else None
            ledger.open_account(account_id, _money(body["opening_cash"], "opening_cash"), opened)
        except (ValueError, TypeError, DomainValidationError) as exc:
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
                **summary,
                "account_id": account_id,
                "version": summary["version"],
                "cash": str(projection.cash.amount),
                "currency": projection.cash.currency,
                "realised_pnl": str(projection.realised_pnl.amount),
                "open_lots": holdings,
            }
        )

    @blueprint.put("/accounts/<account_id>")
    def edit_account(account_id):
        body = request.get_json(silent=True)
        fields = {
            "display_name",
            "opening_date",
            "opening_cash",
            "expected_version",
            "expected_details_version",
        }
        if not isinstance(body, dict) or set(body) != fields:
            return jsonify(
                {"error": "name, opening date, initial balance and current versions are required"}
            ), 400
        try:
            for field in ("expected_version", "expected_details_version"):
                if (
                    isinstance(body[field], bool)
                    or not isinstance(body[field], int)
                    or body[field] < 0
                ):
                    raise DomainValidationError("account version is invalid")
            ledger.update_account_details(
                account_id,
                display_name=body["display_name"],
                opening_date=date.fromisoformat(body["opening_date"]),
                opening_cash=_money(body["opening_cash"], "opening_cash"),
                expected_version=body["expected_version"],
                expected_details_version=body["expected_details_version"],
            )
            return jsonify(
                next(row for row in ledger.accounts() if row["account_id"] == account_id)
            )
        except (ValueError, TypeError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 409

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
                    "broker_trade_id",
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
                        str(row["broker_trade_id"])
                        if row.get("broker_trade_id") is not None
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
        if (
            not isinstance(body, dict)
            or set(body)
            - {
                "idempotency_key",
                "expected_version",
                "direction",
                "amount",
                "occurred_at",
                "reason",
            }
            or not {
                "idempotency_key",
                "expected_version",
                "direction",
                "amount",
                "reason",
            }.issubset(body)
        ):
            return jsonify(
                {
                    "error": "idempotency_key, expected_version, direction, amount and reason are required"
                }
            ), 400
        try:
            key = body["idempotency_key"]
            expected = body["expected_version"]
            if (
                not isinstance(key, str)
                or not key.strip()
                or isinstance(expected, bool)
                or not isinstance(expected, int)
            ):
                raise DomainValidationError("cash transfer command is invalid")
            occurred_at = (
                datetime.fromisoformat(body["occurred_at"]) if body.get("occurred_at") else None
            )
            version = ledger.record_cash_transfer(
                account_id,
                key,
                expected,
                str(body["direction"]),
                _money(body["amount"], "amount"),
                occurred_at,
                body["reason"],
            )
        except (KeyError, TypeError, ValueError, DomainValidationError) as exc:
            error = (
                str(exc)
                if isinstance(exc, DomainValidationError)
                else "cash transfer command is invalid"
            )
            status = (
                409 if "stale" in error or "idempotency" in error or "exceeds" in error else 400
            )
            return jsonify({"error": error}), status
        return jsonify({"account_id": account_id, "version": version}), 201

    @blueprint.get("/accounts/<account_id>/valuation")
    def valuation(account_id: str):
        try:
            as_of = date.fromisoformat(request.args["as_of_date"])
            risk_projections = risk_reader(account_id) if risk_reader else []
            broker_snapshot = broker_sync.holding_snapshot(account_id) if broker_sync else None
            inputs = json.dumps([risk_projections, broker_snapshot], sort_keys=True, default=str)
            today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
            result = read_cache.get_or_compute(
                ("valuation", account_id, as_of, today, inputs),
                lambda: portfolio_valuation(
                    ledger, market, account_id, as_of,
                    lambda _: risk_projections, broker_snapshot=broker_snapshot,
                ),
            )
        except (KeyError, ValueError):
            return jsonify({"error": "as_of_date must be an ISO date"}), 400
        except DomainValidationError:
            return jsonify({"error": "account not found"}), 404
        if request.args.get("persist") == "1":
            import hashlib

            snapshot_id = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
            saved = ledger.save_valuation(account_id, snapshot_id, as_of, result)
            result["snapshot_id"] = saved["snapshot_id"]
            result["checksum_sha256"] = saved["checksum_sha256"]
        return jsonify(result)

    @blueprint.get("/accounts/<account_id>/ticker")
    def ticker(account_id: str):
        """Return the non-mutating current portfolio ticker read model."""
        if request.args.get("live") == "1":
            try:
                return jsonify(live_portfolio_ticker(
                    ledger, market, live_quotes, intraday_stream, account_id
                ))
            except DomainValidationError:
                return jsonify({"error": "account not found"}), 404
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
            holdings.append(
                {
                    "instrument_id": lot.instrument_id,
                    "symbol": identity["symbol"] if identity else None,
                    "exchange": identity["exchange"] if identity else None,
                    "units": lot.remaining_units.units,
                    "price": str(price) if price is not None else None,
                    "price_date": price_date,
                    "fresh": price_date == as_of.isoformat(),
                    "market_value": str(value),
                }
            )
        return jsonify(
            {
                "account_id": account_id,
                "observed_on": as_of.isoformat(),
                "cash": str(projection.cash.amount),
                "market_value": str(market_value),
                "equity": str(projection.cash.amount + market_value),
                "realised_pnl": str(projection.realised_pnl.amount),
                "stale_prices": stale_prices,
                "holdings": holdings,
                "basis": "latest_available_market_bar",
            }
        )

    @blueprint.get("/accounts/<account_id>/ticker/stream")
    def ticker_stream(account_id: str):
        """Deliver current prices; continuous clients reconnect after a bounded stream."""
        snapshot = ticker(account_id)
        if snapshot.status_code != 200:
            return snapshot
        continuous = request.args.get("continuous") == "1"
        try:
            interval = int(request.args.get("interval", "2"))
            if not 2 <= interval <= 60:
                raise ValueError
        except ValueError:
            return jsonify({"error": "ticker interval must be 2..60 seconds"}), 400

        @stream_with_context
        def events():
            yield "retry: 2000\n\n"
            data = snapshot.get_json()
            for index in range(30 if continuous else 1):
                if index:
                    time.sleep(interval)
                    data = ticker(account_id).get_json()
                yield f"event: portfolio-ticker\ndata: {json.dumps(data, sort_keys=True)}\n\n"

        response = Response(events(), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Ticker-Delivery"] = "account-live-sse" if continuous else "durable-snapshot-sse"
        return response

    @blueprint.get("/accounts/<account_id>/valuation/snapshots")
    def valuation_snapshots(account_id: str):
        try:
            limit = int(request.args.get("limit", "100"))
            return jsonify(
                {"account_id": account_id, "snapshots": ledger.valuations(account_id, limit)}
            )
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
        return jsonify(
            {
                "account_id": account_id,
                "as_of_date": snapshot["as_of_date"],
                "summary_basis": "checksum_verified_valuation_snapshot",
                "snapshot": snapshot,
            }
        )

    @blueprint.post("/accounts/<account_id>/valuation/history/backfill")
    def backfill_history(account_id: str):
        if history_rebuilder is None:
            return jsonify({"error": "Historical price backfill unavailable"}), 503
        try:
            body = request.get_json(silent=True) or {}
            as_of = date.fromisoformat(body.get("as_of_date", datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()))
            return jsonify(history_rebuilder(account_id, as_of))
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/accounts/<account_id>/valuation/history")
    def valuation_history(account_id: str):
        if request.args.get("as_of_date"):
            try:
                as_of = date.fromisoformat(request.args["as_of_date"])
                limit = int(request.args.get("limit", "500"))
                snapshot = broker_sync.holding_snapshot(account_id) if broker_sync else None
                snapshot_key = json.dumps(snapshot, sort_keys=True, default=str)
                return jsonify(
                    read_cache.get_or_compute(
                        ("history", account_id, as_of, limit, snapshot_key),
                        lambda: portfolio_history(ledger, market, account_id, as_of, limit, snapshot),
                    )
                )
            except (ValueError, DomainValidationError) as exc:
                return jsonify({"error": str(exc)}), 400
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
            history.append(
                {
                    "as_of_date": snapshot["as_of_date"],
                    "equity": str(equity),
                    "drawdown": str(drawdown),
                    "snapshot_id": snapshot["snapshot_id"],
                    "checksum_sha256": snapshot["checksum_sha256"],
                }
            )
        return jsonify(
            {"account_id": account_id, "basis": "valuation_snapshots", "history": history}
        )

    @blueprint.get("/accounts/<account_id>/journal")
    def journal(account_id: str):
        try:
            long_term_days = int(request.args.get("long_term_days", "365"))
            entries = ledger.journal(account_id, long_term_days=long_term_days)
            grouped = {}
            for entry in entries:
                key = (entry["instrument_id"], entry["sell_date"])
                if key not in grouped:
                    grouped[key] = {
                        **entry,
                        "units": 0,
                        "realised_pnl": "0",
                        "buy_charges": {}, "sell_charges": {}, "total_charges": "0",
                        "tax_deductible_charges": "0", "charge_sources": [], "charge_lots": [],
                        "charges_complete": True,
                        "buy_date_end": entry["buy_date"],
                        "holding_days_min": entry["holding_days"],
                        "_buy_value": Decimal(0),
                        "_gross_buy_value": Decimal(0),
                        "_sell_value": Decimal(0),
                    }
                combined = grouped[key]
                combined["units"] += entry["units"]
                combined["_buy_value"] += Decimal(entry["buy_price"]) * entry["units"]
                combined["_gross_buy_value"] += Decimal(entry["buy_gross_price"]) * entry["units"]
                combined["_sell_value"] += Decimal(entry["sell_price"]) * entry["units"]
                combined["realised_pnl"] = str(
                    Decimal(combined["realised_pnl"]) + Decimal(entry["realised_pnl"])
                )
                for side in ("buy_charges", "sell_charges"):
                    for component, value in entry[side].items():
                        combined[side][component] = str(Decimal(combined[side].get(component, "0")) + Decimal(value))
                for field in ("total_charges", "tax_deductible_charges"):
                    combined[field] = str(Decimal(combined[field]) + Decimal(entry[field]))
                combined["charges_complete"] &= entry["charges_complete"]
                combined["charge_sources"].extend(entry["charge_sources"])
                combined["charge_lots"].append({k: entry[k] for k in (
                    "buy_version", "sell_version", "buy_date", "sell_date", "units",
                    "buy_charges", "sell_charges", "total_charges",
                )})
                combined["buy_date"] = min(combined["buy_date"], entry["buy_date"])
                combined["buy_date_end"] = max(combined["buy_date_end"], entry["buy_date"])
                combined["holding_days"] = max(combined["holding_days"], entry["holding_days"])
                combined["holding_days_min"] = min(
                    combined["holding_days_min"], entry["holding_days"]
                )
                if combined["tax_holding_period"] != entry["tax_holding_period"]:
                    combined["tax_holding_period"] = "MIXED"
                    combined["hold_recommendation"] = "MIXED_LOTS"
            entries = list(grouped.values())
            for entry in entries:
                entry["buy_price"] = str(entry.pop("_buy_value") / entry["units"])
                entry["buy_gross_price"] = str(entry.pop("_gross_buy_value") / entry["units"])
                entry["sell_price"] = str(entry.pop("_sell_value") / entry["units"])
                identity = market.instrument_by_id(str(entry["instrument_id"]))
                entry["symbol"] = identity["symbol"] if identity else None
            return jsonify(
                {
                    "account_id": account_id,
                    "long_term_days": long_term_days,
                    "journal": entries,
                }
            )
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
