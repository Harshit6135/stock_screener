"""Local manual portfolio commands and read models."""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, jsonify, request, stream_with_context

from src.domains.portfolio_accounting import Fill, FillSide, Ledger, PortfolioPerformance
from src.domains.portfolio_accounting.portfolio_performance import (
    calculate_open_holdings_xirr,
    calculate_xirr,
)
from src.domains.portfolio_accounting.portfolio_tax import portfolio_tax_estimates
from src.domains.portfolio_engine import RiskGuardLimits
from src.gates.repositories import MarketRepository
from src.gates.workflows.portfolio_history import portfolio_history
from src.gates.workflows.portfolio_stops import portfolio_stops
from src.gates.workflows.portfolio_ticker import live_portfolio_ticker
from src.platform_kernel import DomainValidationError, Money, Quantity


def _money(value: object, field: str) -> Money:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise DomainValidationError(f"{field} must be numeric")
    try:
        return Money(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise DomainValidationError(f"{field} must be numeric") from exc


def create_portfolio_blueprint(
    ledger: Ledger, market: MarketRepository, risk_reader=None, risk_config=None, broker_sync=None,
    live_quotes=None, intraday_stream=None,
) -> Blueprint:
    blueprint = Blueprint("portfolio", __name__, url_prefix="/api/portfolio")

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
        import json
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
        capital_risk = Decimal(0)
        portfolio_risk = Decimal(0)
        capital_risk_complete = True
        risk_complete = True
        projections = (
            [
                item
                for item in risk_reader(account_id)
                if item.get("stop_model") == "ATR" and str(item["action_date"]) <= as_of.isoformat()
            ]
            if risk_reader
            else []
        )
        saved_stops = {}
        for projection_row in sorted(
            projections, key=lambda item: str(item["action_date"]), reverse=True
        ):
            for position in projection_row["positions"]:
                saved_stops.setdefault(
                    str(position["instrument_id"]),
                    {
                        "stop": Decimal(str(position["current_trailing_stop"])),
                        "date": str(projection_row["action_date"]),
                    },
                )
        calculated_stops = portfolio_stops(market, projection.open_lots, as_of, saved_stops)
        broker_snapshot = broker_sync.holding_snapshot(account_id) if broker_sync else None
        broker_rows = (
            {row["instrument_id"]: row for row in broker_snapshot["holdings"]}
            if broker_snapshot
            else {}
        )
        broker_date = broker_snapshot["observed_at"][:10] if broker_snapshot else None
        dated_ids = {
            event["event"]["instrument_id"]
            for event in ledger.events(account_id)
            if event["event_type"] == "OPEN_LOTS_RECONCILED"
            and event["occurred_at"][:10] <= as_of.isoformat()
        }
        for lot in projection.open_lots:
            bars = market.bars(lot.instrument_id, date.min, as_of, limit=1000)
            latest = bars[-1] if bars else None
            broker_row = broker_rows.get(lot.instrument_id)
            broker_price = bool(broker_row and broker_date == as_of.isoformat())
            if broker_price:
                latest = {"close": broker_row["price"], "as_of_date": broker_date}
            value = (
                Decimal(str(latest["close"])) * lot.remaining_units.units if latest else Decimal(0)
            )
            cost = lot.unit_cost.amount * lot.remaining_units.units
            stop_info = calculated_stops.get(lot.instrument_id, {})
            current_stop = stop_info.get("current_trailing_stop")
            if current_stop is not None:
                lot_capital_risk = cost - current_stop * lot.remaining_units.units
                capital_risk += lot_capital_risk
                portfolio_risk += max(Decimal(0), lot_capital_risk)
            else:
                capital_risk_complete = False
            hard_stop = current_stop * Decimal("0.97") if current_stop is not None else None
            current_price = Decimal(str(latest["close"])) if latest else None
            previous_bar = next(
                (bar for bar in reversed(bars) if str(bar["as_of_date"]) < as_of.isoformat()), None
            )
            previous_close = Decimal(str(previous_bar["close"])) if previous_bar else None
            holding_day_pnl = (
                (current_price - previous_close) * lot.remaining_units.units
                if current_price is not None and previous_close is not None
                and str(latest["as_of_date"]) == as_of.isoformat() else None
            )
            stop_status = (
                "unavailable"
                if current_stop is None or current_price is None
                else "below_hard_stop"
                if current_price <= hard_stop
                else "below_trailing_stop"
                if current_price <= current_stop
                else "above_stop"
            )
            lot_risk = (
                max(Decimal(0), value - current_stop * lot.remaining_units.units)
                if current_stop is not None and current_price is not None
                else None
            )
            if lot_risk is not None:
                stop_risk += lot_risk
            else:
                risk_complete = False
            market_value += value
            invested += cost
            identity = market.instrument_by_id(lot.instrument_id)
            holdings.append(
                {
                    "instrument_id": lot.instrument_id,
                    "acquisition_date": lot.opened_on.isoformat(),
                    "purchase_date_known": True
                    if lot.instrument_id in dated_ids
                    else broker_row.get("purchase_date_known", True)
                    if broker_row
                    else True,
                    "price_basis": "kite-portfolio-snapshot" if broker_price else "market-bar",
                    "symbol": identity["symbol"] if identity else None,
                    "units": lot.remaining_units.units,
                    "cost": str(cost),
                    "previous_close": str(previous_close) if previous_close is not None else None,
                    "day_pnl": str(holding_day_pnl) if holding_day_pnl is not None else None,
                    "price": str(latest["close"]) if latest else None,
                    "price_date": latest["as_of_date"] if latest else None,
                    "fresh": bool(latest and latest["as_of_date"] == as_of.isoformat()),
                    "market_value": str(value),
                    "entry_stop": str(stop_info["entry_stop"])
                    if stop_info.get("entry_stop") is not None
                    else None,
                    "atr": str(stop_info["atr"]) if stop_info.get("atr") is not None else None,
                    "risk_date": stop_info.get("risk_date"),
                    "risk_basis": stop_info.get("risk_basis"),
                    "risk_note": stop_info.get("risk_note"),
                    "stop_status": stop_status,
                    "current_trailing_stop": str(current_stop)
                    if current_stop is not None
                    else None,
                    "hard_stop": str(hard_stop) if hard_stop is not None else None,
                    "stop_risk": str(lot_risk) if lot_risk is not None else None,
                    "capital_risk": str(cost - current_stop * lot.remaining_units.units)
                    if current_stop is not None else None,
                }
            )
        # Display one position per instrument and acquisition day. Keep the
        # original execution lots in the ledger for FIFO sale accounting.
        grouped_holdings = {}
        for holding in holdings:
            key = (holding["instrument_id"], holding["acquisition_date"])
            if key not in grouped_holdings:
                grouped_holdings[key] = dict(holding)
                continue
            combined = grouped_holdings[key]
            combined["units"] += holding["units"]
            for field in ("cost", "market_value", "stop_risk", "day_pnl", "capital_risk"):
                combined[field] = (
                    str(Decimal(combined[field]) + Decimal(holding[field]))
                    if combined[field] is not None and holding[field] is not None
                    else None
                )
            combined["purchase_date_known"] = (
                combined["purchase_date_known"] and holding["purchase_date_known"]
            )
        holdings = list(grouped_holdings.values())
        portfolio_risk = sum(
            (max(Decimal(0), Decimal(h["capital_risk"])) for h in holdings
             if h["capital_risk"] is not None),
            Decimal(0),
        )
        # Only investor capital and original imported cost belong in the return
        # cash-flow basis.  Normal buys/sells are internal transfers and must
        # not be counted again as contributions or withdrawals.
        prices_complete = all(holding["price"] is not None for holding in holdings)
        xirr = (
            PortfolioPerformance(ledger).calculate_xirr(
                account_id, projection.cash.amount + market_value, as_of
            )
            if prices_complete
            else None
        )
        holdings_xirr = calculate_open_holdings_xirr(holdings, as_of)
        account = next(row for row in ledger.accounts() if row["account_id"] == account_id)
        events = [
            event
            for event in ledger.events(account_id)
            if event["occurred_at"][:10] <= as_of.isoformat()
        ]
        history_incomplete = False
        funded_versions = {
            version
            for event in events
            if event["event_type"] == "IMPORTED_POSITION_FUNDED"
            for version in event["event"]["import_versions"]
        }
        return_basis_incomplete = False
        for event in events:
            if event["event_type"] != "OPENING_POSITION_IMPORTED":
                continue
            try:
                provenance = json.loads(str(event["event"].get("broker_provenance", "{}")))
            except ValueError:
                continue
            if isinstance(provenance, dict) and provenance.get("history_incomplete"):
                history_incomplete = True
                # An additional purchase funded from this account is an internal
                # cash-to-stock transfer, not a new external contribution.
                # Snapshot-only imports without a dated funding basis remain
                # unsuitable for whole-account annualization.
                return_basis_incomplete |= not (
                    event["version"] in funded_versions
                    and provenance.get("purchase_date_known") is True
                    and account["opening_date"]
                    <= event["event"].get("acquisition_date", "")
                    <= as_of.isoformat()
                )
        if return_basis_incomplete:
            xirr = None
        transfers = [event for event in events if event["event_type"] == "CASH_TRANSFER"]
        net_capital = Decimal(account["opening_cash"]) + sum(
            (
                Decimal(e["event"]["amount"]) * (1 if e["event"]["direction"] == "DEPOSIT" else -1)
                for e in transfers
            ),
            Decimal(0),
        )
        equity = projection.cash.amount + market_value
        realised_flows = []
        closed_trades = ledger.journal(account_id, as_of=as_of)
        for trade in closed_trades:
            if trade["sell_date"] > as_of.isoformat():
                continue
            buy_value = Decimal(trade["buy_price"]) * trade["units"]
            # Journal buy cost includes allocated buy fees; realised P&L also
            # subtracts allocated sell fees. Derive actual net sale proceeds.
            realised_flows.extend(
                [
                    (date.fromisoformat(trade["buy_date"]), -buy_value),
                    (
                        date.fromisoformat(trade["sell_date"]),
                        buy_value + Decimal(trade["realised_pnl"]),
                    ),
                ]
            )
        realised_xirr = calculate_xirr(realised_flows)
        recorded_charges = sum(
            (Decimal(event["event"].get("fee", "0")) for event in events
             if event["event_type"] == "FILL_RECORDED"),
            Decimal(0),
        )
        net_gain = equity - net_capital
        elapsed = (as_of - date.fromisoformat(account["opening_date"])).days
        annualized = (
            (equity / Decimal(account["opening_cash"])) ** (Decimal(365) / elapsed) - 1
            if elapsed > 0
            and Decimal(account["opening_cash"]) > 0
            and equity > 0
            and not transfers
            and prices_complete
            and not return_basis_incomplete
            else None
        )
        day_pnl = None
        day_pnl_basis = "prior_session_valuation_unavailable"
        from datetime import timedelta

        from src.gates.workflows.trading_calendar import TradingCalendar

        prior_sessions = TradingCalendar(market.path).sessions(
            as_of - timedelta(days=14), as_of - timedelta(days=1)
        )
        prior_date = prior_sessions[-1] if prior_sessions else None
        snapshots = ledger.valuations(account_id, 100)
        previous = next(
            (
                row
                for row in snapshots
                if prior_date and row["as_of_date"] == prior_date.isoformat()
            ),
            None,
        )
        if previous:
            flows = Decimal(0)
            imports = False
            for event in ledger.events(account_id):
                event_day = date.fromisoformat(event["occurred_at"][:10])
                if prior_date < event_day <= as_of:
                    if event["event_type"] == "CASH_TRANSFER":
                        flow = event["event"]
                        flows += Decimal(flow["amount"]) * (
                            1 if flow["direction"] == "DEPOSIT" else -1
                        )
                    elif event["event_type"] == "OPENING_POSITION_IMPORTED":
                        imports = True
            if not imports:
                day_pnl = (
                    projection.cash.amount
                    + market_value
                    - Decimal(previous["payload"]["equity"])
                    - flows
                )
                day_pnl_basis = "prior_session_valuation_less_external_capital"
            else:
                day_pnl_basis = "opening_import_requires_prior_session_basis"
        result = {
            "account_id": account_id,
            "as_of_date": as_of.isoformat(),
            "cash": str(projection.cash.amount),
            "invested_cost": str(invested),
            "market_value": str(market_value),
            "unrealised_gain": str(market_value - invested) if prices_complete else None,
            "equity": str(projection.cash.amount + market_value),
            "realised_pnl": str(projection.realised_pnl.amount),
            "stop_based_risk": str(stop_risk) if risk_complete else None,
            "capital_risk": str(capital_risk) if capital_risk_complete else None,
            "portfolio_risk": str(portfolio_risk) if capital_risk_complete else None,
            "tax_estimates": portfolio_tax_estimates(closed_trades, as_of),
            "recorded_charges": str(recorded_charges),
            "realised_xirr": str(realised_xirr) if realised_xirr is not None else None,
            "stop_risk_fraction": str(stop_risk / equity) if risk_complete and equity > 0 else None,
            "breached_stop_holdings": len(
                {
                    h["instrument_id"]
                    for h in holdings
                    if h["stop_status"] in {"below_trailing_stop", "below_hard_stop"}
                }
            ),
            "xirr": str(xirr) if xirr is not None else None,
            "holdings_xirr": str(holdings_xirr) if holdings_xirr is not None else None,
            "annualized_return": str(annualized) if annualized is not None else None,
            "net_gain": str(net_gain) if prices_complete else None,
            "net_contributed_capital": str(net_capital),
            "total_return": str(net_gain / net_capital)
            if net_capital > 0 and prices_complete
            else None,
            "opening_date": account["opening_date"],
            "initial_balance": account["opening_cash"],
            "fees_note": "Some imported trades have no charges data; their gains exclude brokerage and taxes."
            if any(
                e["event_type"] == "FILL_RECORDED"
                and e["event"].get("correlation_id") == "tradebook:charges-unavailable"
                for e in events
            )
            else None,
            "history_complete": not history_incomplete,
            "return_basis": "recorded_capital_and_cash_funded_purchases"
            if history_incomplete and not return_basis_incomplete
            else "incomplete_import_history" if return_basis_incomplete else "recorded_history",
            "performance_note": "Direct Kite imports include current balances and purchase dates, but no prior sells. Realized gains and curves use recorded transactions only; whole-account XIRR and annualized return require complete trade history."
            if history_incomplete else None,
            "day_pnl": str(day_pnl) if day_pnl is not None else None,
            "day_pnl_basis": day_pnl_basis,
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

        @stream_with_context
        def events():
            yield "retry: 2000\n\n"
            data = snapshot.get_json()
            for index in range(30 if continuous else 1):
                if index:
                    time.sleep(2)
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

    @blueprint.get("/accounts/<account_id>/valuation/history")
    def valuation_history(account_id: str):
        if request.args.get("as_of_date"):
            try:
                as_of = date.fromisoformat(request.args["as_of_date"])
                limit = int(request.args.get("limit", "500"))
                snapshot = broker_sync.holding_snapshot(account_id) if broker_sync else None
                return jsonify(
                    portfolio_history(ledger, market, account_id, as_of, limit, snapshot)
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
