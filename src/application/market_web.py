"""Bounded, read-only market bar API."""

import json
from datetime import UTC, date, datetime, timedelta

from flask import Blueprint, Response, jsonify, request

from src.application.catalog import ArtifactCatalog
from src.application.corporate_actions import CorporateActions
from src.application.index_poller import IndexQuotePoller
from src.application.intraday_alerts import IntradayStopAlerts
from src.application.intraday_stream import IntradayStreamLease
from src.application.market_refresh import MarketRefreshPlanner
from src.application.market_repository import MarketRepository
from src.application.web import require_operator_token
from src.platform_kernel import DomainValidationError


def create_market_blueprint(
    repository: MarketRepository, catalog: ArtifactCatalog, poller: IndexQuotePoller | None = None,
    refresh: MarketRefreshPlanner | None = None, actions: CorporateActions | None = None,
    intraday_alerts: IntradayStopAlerts | None = None, stream: IntradayStreamLease | None = None,
) -> Blueprint:
    blueprint = Blueprint("market_v2", __name__, url_prefix="/api/v2/market")

    @blueprint.get("/coverage")
    def coverage():
        try:
            limit = int(request.args.get("limit", "100"))
            offset = int(request.args.get("offset", "0"))
            rows = repository.coverage(
                symbol=request.args.get("symbol"),
                exchange=request.args.get("exchange"),
                limit=limit,
                offset=offset,
            )
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400
        identifiers = tuple(
            str(row["latest_snapshot_id"]) for row in rows if row["latest_snapshot_id"] is not None
        )
        summaries = catalog.summaries(identifiers)
        for row in rows:
            artifact_id = row.pop("latest_snapshot_id")
            row["latest_source_artifact"] = (
                {
                    "artifact_id": artifact_id,
                    **summaries.get(str(artifact_id), {"quality": None, "status": "UNCATALOGED"}),
                }
                if artifact_id is not None
                else None
            )
        return jsonify({"coverage": rows, "limit": limit, "offset": offset})

    @blueprint.get("/indices/quotes")
    def index_quotes():
        now = datetime.now(UTC)
        quotes = []
        for quote in repository.index_quotes():
            observed_at = datetime.fromisoformat(str(quote["observed_at"]))
            age_seconds = (now - observed_at).total_seconds()
            quote["age_seconds"] = max(0, round(age_seconds))
            quote["freshness"] = (
                "CLOCK_SKEW" if age_seconds < -5 else "FRESH" if age_seconds <= 60 else "STALE"
            )
            quotes.append(quote)
        return jsonify({"quotes": quotes, "refresh_job_kind": "market.fetch-kite-index-quotes"})

    @blueprint.get("/indices/poller")
    def poller_state():
        if poller is None:
            return jsonify({"error": "index poller unavailable"}), 503
        return jsonify(poller.state())

    @blueprint.post("/intraday/stop-alerts")
    def ingest_intraday_alerts():
        if intraday_alerts is None:
            return jsonify({"error": "intraday alert service unavailable"}), 503
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        try:
            return jsonify(intraday_alerts.ingest(request.get_json(silent=True) or {})), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/intraday/stop-alerts")
    def read_intraday_alerts():
        if intraday_alerts is None:
            return jsonify({"error": "intraday alert service unavailable"}), 503
        account_id = request.args.get("account_id", "")
        try:
            limit = int(request.args.get("limit", "100"))
            return jsonify({"account_id": account_id, "alerts": intraday_alerts.read(account_id, limit)})
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/intraday/stream")
    def intraday_stream_state():
        if stream is None:
            return jsonify({"error": "intraday stream supervision unavailable"}), 503
        return jsonify(stream.state())

    @blueprint.post("/intraday/stream")
    def intraday_stream_command():
        if stream is None:
            return jsonify({"error": "intraday stream supervision unavailable"}), 503
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get("action") not in {"start", "stop", "connected", "error", "heartbeat"}:
            return jsonify({"error": "stream action must be start, stop, connected, error or heartbeat"}), 400
        try:
            if body["action"] == "stop":
                return jsonify(stream.stop()), 202
            if body["action"] == "heartbeat":
                if set(body) != {"action"}:
                    raise DomainValidationError("stream heartbeat fields are invalid")
                return jsonify(stream.heartbeat()), 202
            if body["action"] == "connected":
                if set(body) - {"action", "token_count"}:
                    raise DomainValidationError("stream connected fields are invalid")
                return jsonify(stream.connected(body.get("token_count"))), 202
            if body["action"] == "error":
                if set(body) != {"action", "message"}:
                    raise DomainValidationError("stream error requires message")
                return jsonify(stream.mark_error(body["message"])), 202
            if set(body) != {"action", "account_id", "token_count"}:
                raise DomainValidationError("stream start requires account_id and token_count")
            return jsonify(stream.start(body["account_id"], body["token_count"])), 202
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/intraday/stop-alerts/stream")
    def stream_intraday_alerts():
        if intraday_alerts is None:
            return jsonify({"error": "intraday alert service unavailable"}), 503
        account_id = request.args.get("account_id", "")
        try:
            limit = int(request.args.get("limit", "100"))
            alerts = intraday_alerts.read(account_id, limit)
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400
        body = "".join(f"event: stop-alert\ndata: {json.dumps(alert, sort_keys=True)}\n\n" for alert in alerts)
        response = Response(body, mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Alert-Delivery"] = "durable-snapshot-sse"
        return response

    @blueprint.post("/refresh")
    def refresh_market():
        if refresh is None:
            return jsonify({"error": "market refresh planner unavailable"}), 503
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "market refresh payload must be an object"}), 400
        try:
            return jsonify(refresh.schedule(body)), 202
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/reconcile")
    def reconcile():
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        if refresh is None:
            return jsonify({"error": "market refresh service is unavailable"}), 503
        try:
            return jsonify(refresh.reconcile(request.get_json(silent=True) or {})), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/indices/poller")
    def poller_command():
        if poller is None:
            return jsonify({"error": "index poller unavailable"}), 503
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict) or body.get("action") not in {"start", "stop", "tick", "reconcile"}:
            return jsonify({"error": "action must be start, stop, tick or reconcile"}), 400
        try:
            if body["action"] == "start":
                result = poller.set_enabled(True)
            elif body["action"] == "stop":
                result = poller.set_enabled(False)
            elif body["action"] == "tick":
                result = poller.tick()
            else:
                result = poller.reconcile()
            return jsonify(result), 202
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/bars/<symbol>")
    def bars(symbol: str):
        try:
            end_date = date.fromisoformat(
                request.args.get("end", datetime.now(UTC).date().isoformat())
            )
            start_date = date.fromisoformat(
                request.args.get("start", (end_date - timedelta(days=365)).isoformat())
            )
            limit = int(request.args.get("limit", "400"))
            exchange = request.args.get("exchange", "NSE")
            if exchange not in {"NSE", "BSE"}:
                raise DomainValidationError("exchange must be NSE or BSE")
            instrument = repository.instrument(symbol, exchange)
            return jsonify(
                {
                    "instrument": instrument,
                    "bars": repository.bars(
                        str(instrument["instrument_id"]), start_date, end_date, limit=limit
                    ),
                }
            )
        except ValueError:
            return jsonify(
                {"error": "start/end must be ISO dates and limit must be an integer"}
            ), 400
        except DomainValidationError as exc:
            status = 404 if "not found" in str(exc) else 400
            return jsonify({"error": str(exc)}), status

    @blueprint.post("/corporate-actions")
    def record_action():
        if actions is None:
            return jsonify({"error": "corporate-action service unavailable"}), 503
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True)
        try:
            return jsonify(actions.record(body)), 201
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/corporate-actions/liquidation-plan")
    def liquidation_plan():
        if actions is None:
            return jsonify({"error": "corporate-action service unavailable"}), 503
        error = require_operator_token()
        if error:
            return jsonify(error[0]), error[1]
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict) or set(body) != {"account_id", "as_of_date"}:
            return jsonify({"error": "account_id and as_of_date are required"}), 400
        try:
            as_of = date.fromisoformat(str(body["as_of_date"]))
            return jsonify(actions.liquidation_plan(str(body["account_id"]), as_of))
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/bars/<symbol>/adjusted")
    def adjusted_bars(symbol: str):
        if actions is None:
            return jsonify({"error": "corporate-action service unavailable"}), 503
        try:
            end = date.fromisoformat(request.args["end"])
            start = date.fromisoformat(request.args.get("start", (end - timedelta(days=365)).isoformat()))
            exchange = request.args.get("exchange", "NSE")
            instrument = repository.instrument(symbol, exchange)
            return jsonify(actions.adjusted_bars(str(instrument["instrument_id"]), start, end))
        except (KeyError, ValueError):
            return jsonify({"error": "start/end must be ISO dates"}), 400
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 404

    return blueprint
