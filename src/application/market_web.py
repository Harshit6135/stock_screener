"""Bounded, read-only market bar API."""

from datetime import UTC, date, datetime, timedelta

from flask import Blueprint, jsonify, request

from src.application.catalog import ArtifactCatalog
from src.application.market_repository import MarketRepository
from src.platform_kernel import DomainValidationError


def create_market_blueprint(repository: MarketRepository, catalog: ArtifactCatalog) -> Blueprint:
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

    return blueprint
