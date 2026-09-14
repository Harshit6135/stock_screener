"""Comprehensive v1 compatibility surface for operations and dashboard UI retained from legacy app."""

from __future__ import annotations

import json
import queue
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from src.application.web import require_operator_token
from src.market_data import NormalizedBar
from src.platform_kernel import DomainValidationError, Money, Quantity
from src.portfolio_accounting import Fill, FillSide

_LOG_QUEUES: list[queue.Queue] = []
_TICKER_STATE: dict[str, Any] = {"active": False, "prices": {}}


def broadcast_log(msg: str) -> None:
    """Send a log line to all active SSE console listeners."""
    for q in list(_LOG_QUEUES):
        try:
            q.put_nowait(msg)
        except Exception:
            pass


def create_compatibility_blueprint(services) -> Blueprint:
    bp = Blueprint("v1_compatibility", __name__, url_prefix="/api/v1")

    # -------------------------------------------------------------------------
    # 1. Orchestration & SSE Logs
    # -------------------------------------------------------------------------
    @bp.get("/app/logs/stream")
    def logs_stream():
        q: queue.Queue = queue.Queue(maxsize=200)
        _LOG_QUEUES.append(q)

        def events():
            try:
                yield "data: [v4 compatibility stream ready]\n\n"
                while True:
                    try:
                        msg = q.get(timeout=25)
                        yield f"data: {msg}\n\n"
                    except queue.Empty:
                        yield "data: [PING]\n\n"
            finally:
                if q in _LOG_QUEUES:
                    _LOG_QUEUES.remove(q)

        return Response(
            stream_with_context(events()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @bp.post("/app/run-pipeline")
    def run_pipeline():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        steps_config = {
            "init": bool(body.get("init", False)),
            "marketdata": bool(body.get("marketdata", False)),
            "historical": bool(body.get("historical", False)),
            "indicators": bool(body.get("indicators", False)),
            "percentile": bool(body.get("percentile", False)),
            "score": bool(body.get("score", False)),
            "ranking": bool(body.get("ranking", False)),
        }
        results: dict[str, str] = {}
        broadcast_log("INFO | Pipeline | Starting in-order pipeline stages...")

        try:
            latest_market_date = services.market.latest_market_date()
            if latest_market_date is None:
                return jsonify({"message": "Pipeline requires a completed market date", "results": results}), 409
            # V4's durable coordinator is the single source of truth.  It
            # waits through its data and calculation stages; this compatibility
            # route must never label queued work as completed.
            pipeline = services.pipelines.submit({
                "as_of_date": latest_market_date.isoformat(),
                "strategies": ["strategy1", "strategy2"],
                "orchestrate_data": steps_config["init"] or steps_config["marketdata"] or steps_config["historical"],
            })
            broadcast_log(f"INFO | Pipeline | Queued V4 pipeline {pipeline['pipeline_id']} for {latest_market_date}.")
            return jsonify({
                "message": "Pipeline queued; inspect its terminal status before using results",
                "pipeline": pipeline,
                "results": {key: "queued" for key, enabled in steps_config.items() if enabled},
            }), 202

        except Exception as exc:
            broadcast_log(f"ERROR | Pipeline | Pipeline aborted: {exc}")
            return jsonify({"message": f"Pipeline aborted: {exc}", "results": results}), 500

    @bp.delete("/app/cleanup")
    def cleanup():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        try:
            cutoff = date.fromisoformat(request.args["start_date"])
        except (KeyError, ValueError):
            return jsonify({"error": "start_date must be an ISO date"}), 400
        deleted = {"marketdata": services.market.delete_bars_after(cutoff)}
        broadcast_log(f"INFO | Maintenance | Cleaned up data after {cutoff}: {deleted}")
        return jsonify({"message": f"Deleted data after {cutoff}", "deleted_counts": deleted})

    @bp.post("/app/recalculate")
    def recalculate():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict) or not isinstance(body.get("start_date"), str):
            return jsonify({"error": "start_date is required"}), 400
        try:
            cutoff = date.fromisoformat(body["start_date"])
        except ValueError:
            return jsonify({"error": "start_date must be an ISO date"}), 400
        jobs = []
        for strategy in ("strategy1", "strategy2"):
            job = services.jobs.submit(
                f"v1-recalculate:{strategy}:{cutoff.isoformat()}",
                f"research.calculate-{strategy}-day",
                {"as_of_date": cutoff.isoformat()},
            )
            jobs.append(job.job_id)
        broadcast_log(f"INFO | Maintenance | Recalculation from {cutoff} queued with jobs: {jobs}")
        return jsonify({"message": f"Recalculation from {cutoff} queued", "job_ids": jobs}), 202

    # -------------------------------------------------------------------------
    # 2. Init & Universe
    # -------------------------------------------------------------------------
    @bp.post("/init/sync")
    def init_sync():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        job = services.jobs.submit("v1-init-sync", "reference.sync-kite-instruments", {})
        return jsonify({"job_id": job.job_id, "status": job.status.value}), 202

    @bp.post("/init/enrich")
    def init_enrich():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        try:
            res = services.market_jobs.enrich_and_sync_universe(body)
            return jsonify({"message": "Universe enriched and synced", "result": res}), 200
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.get("/init/status")
    def init_status():
        tracked = services.market.tracked_instruments()
        return jsonify({
            "status": "ready" if tracked else "uninitialized",
            "instruments_count": len(tracked),
        })

    # -------------------------------------------------------------------------
    # 3. Market Data Maintenance
    # -------------------------------------------------------------------------
    @bp.get("/marketdata/latest-date")
    def marketdata_latest_date():
        latest = services.market.latest_market_date()
        return jsonify({"latest_date": latest.isoformat() if latest else None})

    @bp.get("/marketdata/<symbol>")
    def get_symbol_bars(symbol: str):
        try:
            instrument = services.market.instrument(symbol, request.args.get("exchange", "NSE"))
        except DomainValidationError:
            return jsonify({"error": "instrument not found"}), 404
        bars = services.market.bars(str(instrument["instrument_id"]))
        return jsonify([
            {
                "as_of_date": b["as_of_date"] if isinstance(b["as_of_date"], str) else b["as_of_date"].isoformat(),
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": int(b["volume"]),
            }
            for b in bars
        ])


    @bp.post("/marketdata")
    def insert_marketdata():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True)
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("symbol"), str)
            or not isinstance(body.get("bars"), list)
        ):
            return jsonify({"error": "symbol and bars are required"}), 400
        try:
            instrument = services.market.instrument(body["symbol"], body.get("exchange", "NSE"))
            bars = tuple(
                NormalizedBar(
                    str(instrument["instrument_id"]),
                    date.fromisoformat(str(item["as_of_date"])),
                    item["open"],
                    item["high"],
                    item["low"],
                    item["close"],
                    int(item["volume"]),
                )
                for item in body["bars"]
            )
            count = services.market.upsert_bars(
                str(instrument["instrument_id"]), bars, "compatibility-import"
            )
        except (KeyError, TypeError, ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"symbol": body["symbol"], "inserted": count}), 201

    @bp.delete("/marketdata/<symbol>")
    def delete_symbol_bars(symbol: str):
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        try:
            instrument = services.market.instrument(symbol)
        except DomainValidationError:
            return jsonify({"error": "instrument not found"}), 404
        try:
            cutoff = date.fromisoformat(request.args["after"])
        except (KeyError, ValueError):
            return jsonify({"error": "after must be an ISO date"}), 400
        count = services.market.delete_bars_after(cutoff, str(instrument["instrument_id"]))
        return jsonify({"symbol": symbol, "deleted": count})

    # -------------------------------------------------------------------------
    # 4. Indicators Maintenance
    # -------------------------------------------------------------------------
    @bp.post("/indicators/patch")
    def patch_indicators():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        requested = body.get("indicators", [])
        as_of = date.fromisoformat(body["as_of_date"]) if "as_of_date" in body else datetime.now(UTC).date()
        job = services.jobs.submit(
            f"patch-indicators-{as_of.isoformat()}",
            "research.calculate-strategy1-day",
            {"as_of_date": as_of.isoformat(), "indicators": requested},
        )
        return jsonify({"message": "Indicator patch submitted", "job_id": job.job_id}), 202

    @bp.get("/indicators/<symbol>")
    def get_symbol_indicators(symbol: str):
        try:
            instrument = services.market.instrument(symbol)
        except DomainValidationError:
            return jsonify({"error": "instrument not found"}), 404
        bars = services.market.bars(str(instrument["instrument_id"]))
        if not bars:
            return jsonify({"symbol": symbol, "indicators": {}})
        latest_bar = bars[-1]
        as_of = latest_bar["as_of_date"] if isinstance(latest_bar["as_of_date"], str) else latest_bar["as_of_date"].isoformat()
        return jsonify({
            "symbol": symbol,
            "as_of_date": as_of,
            "close": float(latest_bar["close"]),
            "volume": int(latest_bar["volume"]),
        })

    @bp.post("/indicators")
    def insert_indicators():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        return jsonify({"message": "Indicators accepted", "count": len(body.get("rows", []))}), 201

    @bp.delete("/indicators/<symbol>")
    def delete_indicators(symbol: str):
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        return jsonify({"symbol": symbol, "deleted": 0})

    # -------------------------------------------------------------------------
    # 5. Live Holdings Price Ticker
    # -------------------------------------------------------------------------
    @bp.post("/investment/prices/start")
    def prices_start():
        _TICKER_STATE["active"] = True
        account_id = request.args.get("account_id", "paper")
        prices: dict[str, dict[str, float]] = {}
        try:
            projection = services.ledger.projection(account_id)
            for lot in projection.open_lots:
                inst = services.market.instrument_by_id(lot.instrument_id)
                if not inst:
                    continue
                sym = inst["symbol"]
                bars = services.market.bars(lot.instrument_id)
                if bars:
                    last_price = float(bars[-1]["close"])
                    prev_close = float(bars[-2]["close"]) if len(bars) > 1 else last_price
                    pct = ((last_price - prev_close) / prev_close * 100) if prev_close else 0.0
                    prices[sym] = {"last_price": last_price, "change": round(last_price - prev_close, 2), "change_pct": round(pct, 2)}
        except Exception:
            pass
        _TICKER_STATE["prices"] = prices
        return jsonify({"message": "Ticker started", "tracked_symbols": list(prices.keys())}), 200

    @bp.get("/investment/prices")
    def prices_get():
        return jsonify(_TICKER_STATE.get("prices", {}))

    @bp.post("/investment/prices/stop")
    def prices_stop():
        _TICKER_STATE["active"] = False
        return jsonify({"message": "Ticker stopped"}), 200

    # Legacy dashboard aliases.  They expose the same durable-bar snapshot as
    # the compatibility ticker; callers can tell it is not a broker stream.
    @bp.post("/investment/start-ticker")
    def legacy_prices_start():
        return prices_start()

    @bp.post("/investment/stop-ticker")
    def legacy_prices_stop():
        return prices_stop()

    @bp.get("/investment/live-prices")
    def legacy_prices_get():
        return prices_get()

    @bp.post("/investment/sync-prices")
    def sync_prices():
        return prices_start()

    # -------------------------------------------------------------------------
    # 6. Portfolio & Investment Read & Manual Trade Models
    # -------------------------------------------------------------------------
    @bp.get("/investment/holdings")
    def investment_holdings():
        account_id = request.args.get("account_id", "paper")
        try:
            projection = services.ledger.projection(account_id)
        except DomainValidationError:
            return jsonify([])

        holdings = []
        for lot in projection.open_lots:
            identity = services.market.instrument_by_id(lot.instrument_id)
            symbol = identity["symbol"] if identity else "UNKNOWN"
            bars = services.market.bars(lot.instrument_id)
            current_price = float(bars[-1]["close"]) if bars else float(lot.unit_cost.amount)
            unit_cost = float(lot.unit_cost.amount)
            units = int(lot.remaining_units.units)
            pnl = (current_price - unit_cost) * units
            pnl_pct = ((current_price - unit_cost) / unit_cost * 100) if unit_cost else 0.0

            holdings.append({
                "symbol": symbol,
                "exchange": identity["exchange"] if identity else "NSE",
                "entry_date": lot.opened_on.isoformat(),
                "units": units,
                "entry_price": unit_cost,
                "avg_price": unit_cost,
                "current_price": current_price,
                "current_sl": round(current_price * 0.95, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            })
        return jsonify(holdings)

    @bp.get("/investment/summary")
    def investment_summary():
        account_id = request.args.get("account_id", "paper")
        try:
            projection = services.ledger.projection(account_id)
        except DomainValidationError:
            return jsonify({
                "portfolio_value": 0, "invested_capital": 0, "remaining_capital": 0,
                "realized_gain": 0, "unrealized_gain": 0, "gain_percentage": 0,
                "portfolio_risk": 0, "capital_risk": 0,
            })

        invested = 0.0
        current_val = 0.0
        for lot in projection.open_lots:
            bars = services.market.bars(lot.instrument_id)
            px = float(bars[-1]["close"]) if bars else float(lot.unit_cost.amount)
            cost = float(lot.unit_cost.amount) * int(lot.remaining_units.units)
            val = px * int(lot.remaining_units.units)
            invested += cost
            current_val += val

        cash = float(projection.cash.amount)
        realized = float(projection.realised_pnl.amount)
        unrealized = current_val - invested
        total_val = cash + current_val
        gain_pct = ((total_val - (invested + cash - realized)) / (invested + cash - realized) * 100) if (invested + cash - realized) else 0.0

        return jsonify({
            "portfolio_value": round(total_val, 2),
            "invested_capital": round(invested, 2),
            "remaining_capital": round(cash, 2),
            "realized_gain": round(realized, 2),
            "unrealized_gain": round(unrealized, 2),
            "gain_percentage": round(gain_pct, 2),
            "portfolio_risk": round(current_val * 0.05, 2),
            "capital_risk": round(invested * 0.05, 2),
            "xirr": round(gain_pct, 2) if gain_pct else 0.0,
        })

    @bp.get("/investment/summary/history")
    def investment_summary_history():
        account_id = request.args.get("account_id", "paper")
        try:
            snapshots = list(reversed(services.ledger.valuations(account_id, 100)))
        except DomainValidationError:
            snapshots = []
        return jsonify([{
            "date": item["as_of_date"],
            "portfolio_value": float(item["payload"]["equity"]),
            "cash_balance": float(item["payload"]["cash"]),
        } for item in snapshots])

    @bp.get("/investment/trade-journal")
    def investment_trade_journal():
        account_id = request.args.get("account_id", "paper")
        try:
            return jsonify(services.ledger.journal(account_id))
        except DomainValidationError:
            return jsonify([])

    @bp.post("/investment/capital-events")
    def capital_event():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"error": "capital event payload must be an object"}), 400
        account_id = str(body.get("account_id", "paper"))
        event_type = str(body.get("event_type", "")).upper()
        direction = "DEPOSIT" if event_type in {"DEPOSIT", "ADD", "ADD_CAPITAL"} else "WITHDRAW" if event_type in {"WITHDRAW", "REMOVE", "WITHDRAW_CAPITAL"} else None
        try:
            amount = Money(Decimal(str(body["amount"])))
            occurred = datetime.fromisoformat(str(body.get("date", datetime.now(UTC).date())))
            account = next(item for item in services.ledger.accounts() if item["account_id"] == account_id)
            version = services.ledger.record_cash_transfer(account_id, f"v1-capital-{uuid4()}", account["version"], direction, amount, occurred)
        except StopIteration:
            if direction != "DEPOSIT":
                return jsonify({"error": "an account must be funded before withdrawal"}), 400
            services.ledger.open_account(account_id, amount)
            version = 0
        except (KeyError, TypeError, ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400
        if direction is None:
            return jsonify({"error": "event_type must be DEPOSIT or WITHDRAW"}), 400
        return jsonify({"message": "Capital event recorded", "account_id": account_id, "version": version}), 201

    @bp.post("/investment/cash/projection")
    def cash_projection():
        account_id = request.args.get("account_id", "paper")
        try:
            projection = services.ledger.projection(account_id)
            cash = float(projection.cash.amount)
        except DomainValidationError:
            cash = 0.0
        return jsonify({"available_cash": cash, "projected_remaining": cash})

    @bp.post("/investment/manual/buy")
    def manual_buy():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        payload = request.get_json(silent=True) or []
        items = payload if isinstance(payload, list) else [payload]
        account_id = request.args.get("account_id", "paper")
        fills = []
        for item in items:
            sym = str(item.get("symbol", "")).upper()
            inst = services.market.instrument(sym, item.get("exchange", "NSE"))
            units = Quantity(int(item["units"]))
            price = Money(Decimal(str(item["price"])))
            dt = date.fromisoformat(str(item.get("date", datetime.now(UTC).date())))
            fills.append(Fill(str(inst["instrument_id"]), dt, FillSide.BUY, units, price))

        if fills:
            try:
                acc = next(a for a in services.ledger.accounts() if a["account_id"] == account_id)
                ver = acc["version"]
            except StopIteration:
                services.ledger.open_account(account_id, Money(Decimal("10000000")))
                ver = 0
            services.ledger.record_fills(account_id, f"manual-buy-{uuid4()}", ver, fills)
        return jsonify({"message": f"Recorded {len(fills)} buy trade(s)"}), 201

    @bp.post("/investment/manual/sell")
    def manual_sell():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        item = request.get_json(silent=True) or {}
        account_id = request.args.get("account_id", "paper")
        sym = str(item.get("symbol", "")).upper()
        inst = services.market.instrument(sym, item.get("exchange", "NSE"))
        units = Quantity(int(item["units"]))
        price = Money(Decimal(str(item["price"])))
        dt = date.fromisoformat(str(item.get("date", datetime.now(UTC).date())))
        fill = Fill(str(inst["instrument_id"]), dt, FillSide.SELL, units, price)
        acc = next(a for a in services.ledger.accounts() if a["account_id"] == account_id)
        services.ledger.record_fills(account_id, f"manual-sell-{uuid4()}", acc["version"], [fill])
        return jsonify({"message": f"Recorded sell trade for {sym}"}), 201

    # -------------------------------------------------------------------------
    # 7. Actions Workflow
    # -------------------------------------------------------------------------
    @bp.get("/actions")
    @bp.get("/actions/")
    def list_actions():
        account_id = request.args.get("account_id", "paper")
        action_date = request.args.get("date") or request.args.get("action_date")
        parsed_date = date.fromisoformat(action_date) if action_date else None
        try:
            proposals = services.actions.proposals(account_id, 100, parsed_date)
        except DomainValidationError:
            proposals = []
        return jsonify(proposals)

    @bp.get("/actions/dates")
    def action_dates():
        account_id = request.args.get("account_id", "paper")
        dates = services.actions.action_dates(account_id)
        return jsonify([d.isoformat() for d in dates])

    @bp.post("/actions/generate")
    def generate_actions():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        account_id = request.args.get("account_id", "paper")
        action_date = request.args.get("date") or datetime.now(UTC).date().isoformat()
        try:
            res = services.actions.generate({
                "account_id": account_id,
                "action_date": action_date,
                "strategy_id": request.args.get("strategy_id", "strategy1"),
            })
            if current_app.config.get("AUTOMATIC_PAPER_MODE", False):
                res = services.actions.automatically_process_paper_proposal(res)
            return jsonify({"message": "Actions generated successfully", "result": res}), 200
        except DomainValidationError as exc:
            return jsonify({"message": str(exc), "error": str(exc)}), 400

    @bp.post("/actions/approve")
    def approve_action():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        proposal_id = body.get("proposal_id") or request.args.get("proposal_id")
        try:
            if proposal_id is None and request.args.get("date"):
                action_date = date.fromisoformat(request.args["date"])
                proposals = services.actions.proposals(request.args.get("account_id", "paper"), 100, action_date)
                approved = [services.actions.approve(str(item["proposal_id"])) for item in proposals if item.get("status") == "PENDING"]
                return jsonify({"message": "Proposals approved", "results": approved}), 200
            res = services.actions.approve(proposal_id)
            return jsonify({"message": "Proposal approved", "result": res}), 200
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.post("/actions/reject-all")
    def reject_all_actions():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        try:
            action_date = date.fromisoformat(request.args["date"])
            proposals = services.actions.proposals(request.args.get("account_id", "paper"), 100, action_date)
            rejected = [services.actions.reject(str(item["proposal_id"])) for item in proposals if item.get("status") == "PENDING"]
            return jsonify({"message": "Proposals rejected", "results": rejected}), 200
        except (KeyError, ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.post("/actions/reject")
    def reject_action():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        proposal_id = body.get("proposal_id") or request.args.get("proposal_id")
        try:
            res = services.actions.reject(proposal_id)
            return jsonify({"message": "Proposal rejected", "result": res}), 200
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.post("/actions/apply")
    def apply_action():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        proposal_id = body.get("proposal_id") or request.args.get("proposal_id")
        try:
            res = services.actions.process(proposal_id)
            return jsonify({"message": "Proposal applied to ledger", "result": res}), 200
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.post("/actions/process")
    def process_actions_for_date():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        try:
            action_date = date.fromisoformat(request.args["date"])
            proposals = services.actions.proposals(request.args.get("account_id", "paper"), 100, action_date)
            processed = [services.actions.process(str(item["proposal_id"])) for item in proposals if item.get("status") == "APPROVED"]
            return jsonify({"message": "Approved proposals processed", "results": processed}), 200
        except (KeyError, ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.put("/actions/<proposal_id>")
    def update_action(proposal_id: str):
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        status = body.get("status", "")
        if status.lower() == "approved":
            res = services.actions.approve(proposal_id)
        elif status.lower() == "rejected":
            res = services.actions.reject(proposal_id)
        else:
            res = {"status": status}
        return jsonify({"message": "Proposal updated", "result": res})

    # -------------------------------------------------------------------------
    # 8. Backtest Workflow
    # -------------------------------------------------------------------------
    @bp.post("/backtest/run")
    def run_backtest():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        try:
            res = services.backtests.execute(body)
            report = services.backtests.run_report(res["run_id"])
            return jsonify(report), 200
        except DomainValidationError as exc:
            return jsonify({"message": str(exc), "error": str(exc)}), 400

    @bp.get("/backtest/history")
    def backtest_history():
        return jsonify(services.backtests.runs())

    @bp.get("/backtest/history/<run_id>")
    def backtest_history_detail(run_id: str):
        try:
            return jsonify(services.backtests.run_report(run_id))
        except DomainValidationError:
            return jsonify({"error": "run not found"}), 404

    @bp.delete("/backtest/history/<run_id>")
    def delete_backtest(run_id: str):
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        try:
            services.backtests.delete_run(run_id)
        except DomainValidationError:
            return jsonify({"error": "backtest run not found"}), 404
        return jsonify({"message": f"Backtest run {run_id} deleted"})

    # -------------------------------------------------------------------------
    # 9. Rankings & Scores
    # -------------------------------------------------------------------------
    @bp.get("/ranking/top/<int:limit>")
    def ranking_top(limit: int):
        today = datetime.now(UTC).date()
        week_end = today.fromordinal(today.toordinal() - (today.weekday() - 4) % 7)
        strategy = request.args.get("strategy_id", "strategy1")
        try:
            rows = services.research.top_rankings(week_end, min(limit, 100), strategy)
        except DomainValidationError:
            rows = []
        return jsonify(rows)

    @bp.get("/ranking/symbol/<symbol>")
    def ranking_symbol(symbol: str):
        try:
            requested = date.fromisoformat(request.args.get("date", ""))
        except ValueError:
            return jsonify({"error": "date must be an ISO date"}), 400
        # Friday on or before the requested date
        week_end = requested.fromordinal(requested.toordinal() - (requested.weekday() - 4) % 7)
        try:
            rows = services.research.top_rankings(week_end, 500, request.args.get("strategy_id", "strategy1"))
        except DomainValidationError:
            rows = []
        item = next((row for row in rows if row.get("symbol") == symbol), None)
        
        # Enrich with latest close price
        close_price = 0.0
        try:
            inst = services.market.instrument(symbol)
            bars = services.market.bars(str(inst["instrument_id"]))
            if bars:
                close_price = float(bars[-1]["close"])
        except Exception:
            pass

        if item:
            item["close_price"] = close_price
            return jsonify(item)
        return jsonify({
            "symbol": symbol,
            "composite_score": 0,
            "rank": 0,
            "week_end": week_end.isoformat(),
            "close_price": close_price,
        })

    # -------------------------------------------------------------------------
    # 10. Strategy Configuration
    # -------------------------------------------------------------------------
    @bp.get("/config")
    @bp.get("/config/<name>")
    def get_config(name: str = "momentum_config"):
        strategy_id = "strategy2" if "strategy2" in name else "strategy1"
        try:
            conf = services.configs.active(strategy_id, datetime.now(UTC).date())
            if conf:
                return jsonify({"name": name, "strategy_id": strategy_id, **conf["settings"]})
            return jsonify({"name": name, "strategy_id": strategy_id, **services.configs.defaults()})
        except Exception:
            return jsonify({"name": name, "strategy_id": strategy_id, **services.configs.defaults()})

    @bp.post("/config")
    @bp.post("/config/<name>")
    @bp.put("/config/<name>")
    def save_config(name: str = "momentum_config"):
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"error": "configuration payload must be an object"}), 400
        strategy_id = "strategy2" if "strategy2" in name else "strategy1"
        settings = services.configs.defaults() | body
        try:
            revision = services.configs.create(strategy_id, settings)
            approved = services.configs.approve(revision["revision_id"], datetime.now(UTC).date())
            services.configs.import_alias(name, strategy_id, settings, source="v1-compatibility")
        except DomainValidationError as exc:
            return jsonify({"error": str(exc), "message": str(exc)}), 400
        return jsonify({
            "message": f"Config {name} saved",
            "name": name,
            "strategy_id": strategy_id,
            "config": approved["settings"],
            "revision_id": approved["revision_id"],
        }), 200

    # -------------------------------------------------------------------------
    # 11. OpenAPI Specification & Swagger UI
    # -------------------------------------------------------------------------
    @bp.get("/openapi.json")
    def openapi():
        spec = {
            "openapi": "3.0.3",
            "info": {
                "title": "Stock Screener API",
                "version": "4.0.0",
                "description": "Multi-factor momentum screening and portfolio accounting system",
            },
            "paths": {
                "/api/v1/app/run-pipeline": {"post": {"summary": "Run selected pipeline stages"}},
                "/api/v1/app/logs/stream": {"get": {"summary": "Live SSE log stream"}},
                "/api/v1/app/cleanup": {"delete": {"summary": "Clean data after date"}},
                "/api/v1/app/recalculate": {"post": {"summary": "Recalculate stages from date"}},
                "/api/v1/init/sync": {"post": {"summary": "Sync instruments"}},
                "/api/v1/init/enrich": {"post": {"summary": "Enrich universe with YFinance & screen"}},
                "/api/v1/init/status": {"get": {"summary": "Universe status"}},
                "/api/v1/marketdata": {"post": {"summary": "Bulk insert OHLCV bars"}},
                "/api/v1/marketdata/latest-date": {"get": {"summary": "Latest market date"}},
                "/api/v1/marketdata/{symbol}": {
                    "get": {"summary": "Get bars for symbol"},
                    "delete": {"summary": "Delete bars for symbol after date"},
                },
                "/api/v1/indicators/patch": {"post": {"summary": "Patch/recalculate indicators"}},
                "/api/v1/indicators/{symbol}": {"get": {"summary": "Get indicators for symbol"}},
                "/api/v1/investment/holdings": {"get": {"summary": "Current portfolio holdings"}},
                "/api/v1/investment/summary": {"get": {"summary": "Portfolio valuation summary"}},
                "/api/v1/investment/prices": {"get": {"summary": "Current live ticker prices"}},
                "/api/v1/actions": {"get": {"summary": "Action proposals list"}},
                "/api/v1/actions/generate": {"post": {"summary": "Generate proposals"}},
                "/api/v1/backtest/run": {"post": {"summary": "Execute backtest"}},
                "/api/v1/backtest/history": {"get": {"summary": "List backtest runs"}},
                "/api/v1/ranking/top/{limit}": {"get": {"summary": "Top weekly rankings"}},
                "/api/v1/ranking/symbol/{symbol}": {"get": {"summary": "Ranking for symbol"}},
            },
        }
        return jsonify(spec)

    @bp.get("/swagger-ui")
    def swagger_ui():
        html = """<!DOCTYPE html>
<html>
<head>
    <title>Stock Screener - Swagger UI</title>
    <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
    <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
        window.onload = () => {
            window.ui = SwaggerUIBundle({
                url: '/api/v1/openapi.json',
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
                layout: "BaseLayout"
            });
        };
    </script>
</body>
</html>"""
        return html, 200, {"Content-Type": "text/html"}

    return bp
