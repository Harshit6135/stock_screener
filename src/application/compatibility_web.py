"""Small v1 compatibility surface for operations retained from the legacy app."""

from datetime import date

from flask import Blueprint, Response, jsonify, request, stream_with_context

from src.application.web import require_operator_token
from src.market_data import NormalizedBar
from src.platform_kernel import DomainValidationError


def create_compatibility_blueprint(services) -> Blueprint:
    bp = Blueprint("v1_compatibility", __name__, url_prefix="/api/v1")

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
        return jsonify({"message": f"Deleted data after {cutoff}", "deleted_counts": deleted})

    @bp.get("/app/logs/stream")
    def logs_stream():
        def events():
            yield "data: [v4 compatibility stream ready]\n\n"
            while True:
                yield "data: [PING]\n\n"
                import time
                time.sleep(30)
        return Response(stream_with_context(events()), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @bp.post("/init/sync")
    def init_sync():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        job = services.jobs.submit("v1-init-sync", "reference.sync-kite-instruments", {})
        return jsonify({"job_id": job.job_id, "status": job.status.value}), 202

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

    @bp.post("/marketdata")
    def insert_marketdata():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("symbol"), str) or not isinstance(body.get("bars"), list):
            return jsonify({"error": "symbol and bars are required"}), 400
        try:
            instrument = services.market.instrument(body["symbol"], body.get("exchange", "NSE"))
            bars = tuple(NormalizedBar(str(instrument["instrument_id"]), date.fromisoformat(str(item["as_of_date"])), item["open"], item["high"], item["low"], item["close"], int(item["volume"])) for item in body["bars"])
            count = services.market.upsert_bars(str(instrument["instrument_id"]), bars, "compatibility-import")
        except (KeyError, TypeError, ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"symbol": body["symbol"], "inserted": count}), 201

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
        return jsonify({"message": f"Recalculation from {cutoff} queued", "job_ids": jobs}), 202

    @bp.get("/ranking/symbol/<symbol>")
    def ranking_symbol(symbol: str):
        try:
            requested = date.fromisoformat(request.args.get("date", ""))
        except ValueError:
            return jsonify({"error": "date must be an ISO date"}), 400
        # Friday on or before the requested date.
        week_end = requested.fromordinal(requested.toordinal() - (requested.weekday() - 4) % 7)
        try:
            rows = services.research.top_rankings(week_end, 500, request.args.get("strategy_id", "strategy1"))
        except DomainValidationError:
            rows = []
        item = next((row for row in rows if row.get("symbol") == symbol), None)
        return jsonify(item or {"symbol": symbol, "composite_score": 0, "rank": 0, "week_end": week_end.isoformat()})

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

    @bp.get("/openapi.json")
    def openapi():
        return jsonify({"openapi": "3.0.3", "info": {"title": "Stock Screener", "version": "v4"}, "paths": {}})

    return bp
