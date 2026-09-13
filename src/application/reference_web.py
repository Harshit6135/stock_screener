"""Read-only HTTP adapter for published reference snapshots."""

from datetime import date

from flask import Blueprint, jsonify, request

from src.application.market_repository import MarketRepository
from src.platform_kernel import ArtifactStore, DomainValidationError


def create_reference_blueprint(
    store: ArtifactStore, repository: MarketRepository | None = None
) -> Blueprint:
    blueprint = Blueprint("reference_v2", __name__, url_prefix="/api/v2/reference")

    @blueprint.get("/instruments")
    def get_instruments():
        if repository is None:
            return jsonify({"error": "instrument read model unavailable"}), 503
        try:
            limit = int(request.args.get("limit", "100"))
            offset = int(request.args.get("offset", "0"))
            return jsonify(
                {
                    "instruments": repository.instruments(
                        symbol=request.args.get("symbol"), limit=limit, offset=offset
                    )
                }
            )
        except (ValueError, DomainValidationError):
            return jsonify({"error": "instrument query is invalid"}), 400

    @blueprint.get("/tokens/<provider_token>")
    def get_token_assignments(provider_token: str):
        if repository is None:
            return jsonify({"error": "instrument read model unavailable"}), 503
        try:
            as_of_text = request.args.get("as_of")
            as_of = date.fromisoformat(as_of_text) if as_of_text is not None else None
            assignments = repository.token_assignments(
                provider_token, exchange=request.args.get("exchange"), as_of=as_of
            )
        except (ValueError, DomainValidationError):
            return jsonify({"error": "token lookup is invalid"}), 400
        return jsonify(
            {
                "provider_token": provider_token,
                "as_of": as_of.isoformat() if as_of else None,
                "assignments": assignments,
                "ambiguous": len(assignments) > 1,
            }
        )

    @blueprint.get("/instruments/<instrument_id>/token-history")
    def get_token_history(instrument_id: str):
        if repository is None:
            return jsonify({"error": "instrument read model unavailable"}), 503
        instrument = repository.instrument_by_id(instrument_id)
        if instrument is None:
            return jsonify({"error": "instrument not found"}), 404
        try:
            limit = int(request.args.get("limit", "100"))
            offset = int(request.args.get("offset", "0"))
            observations = repository.token_history(instrument_id, limit=limit, offset=offset)
        except (ValueError, DomainValidationError):
            return jsonify({"error": "token history query is invalid"}), 400
        return jsonify(
            {
                "instrument": instrument,
                "observations": observations,
                "limit": limit,
                "offset": offset,
            }
        )

    @blueprint.get("/liquidity-universes/<artifact_id>")
    def get_liquidity_universe(artifact_id: str):
        try:
            manifest, payload = store.read_json("reference/liquidity_universes", artifact_id)
        except DomainValidationError:
            return jsonify({"error": "liquidity universe not found"}), 404
        return jsonify(
            {
                "artifact": {
                    "artifact_id": manifest.artifact_id,
                    "category": manifest.category,
                    "quality": manifest.quality.value,
                    "created_at": manifest.created_at,
                },
                "universe": payload,
            }
        )

    return blueprint
