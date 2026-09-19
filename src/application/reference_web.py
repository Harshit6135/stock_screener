"""Read-only HTTP adapter for published reference snapshots."""

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.platform_kernel import ArtifactStore, DomainValidationError


def create_reference_blueprint(
    store: ArtifactStore, repository: MarketRepository | None = None, publisher: ArtifactPublisher | None = None
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

    @blueprint.post("/sectors")
    def publish_sectors():
        if publisher is None:
            return jsonify({"error": "reference publisher is unavailable"}), 503
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"as_of_date", "values"} or not isinstance(body["values"], dict) or not body["values"]:
            return jsonify({"error": "as_of_date and non-empty values are required"}), 400
        try:
            as_of = date.fromisoformat(str(body["as_of_date"]))
        except ValueError:
            return jsonify({"error": "as_of_date must be an ISO date"}), 400
        if as_of >= datetime.now(UTC).date() or any(not isinstance(key, str) or not isinstance(value, str) or not value.strip() for key, value in body["values"].items()):
            return jsonify({"error": "sector classification is invalid"}), 400
        normalized = {"as_of_date": as_of.isoformat(), "values": dict(sorted(body["values"].items()))}
        artifact_id = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
        if not publisher.catalog.has(artifact_id):
            publisher.publish_json("reference/sectors", artifact_id, {"snapshot_id": artifact_id, **normalized})
        return jsonify({"artifact_id": artifact_id, **normalized}), 201

    @blueprint.post("/macro-indicators")
    def publish_macro_indicators():
        if publisher is None:
            return jsonify({"error": "reference publisher is unavailable"}), 503
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"as_of_date", "values"} or not isinstance(body["values"], dict) or not body["values"]:
            return jsonify({"error": "as_of_date and non-empty values are required"}), 400
        try:
            as_of = date.fromisoformat(str(body["as_of_date"]))
        except ValueError:
            return jsonify({"error": "as_of_date must be an ISO date"}), 400
        try:
            parsed_values = {str(key): Decimal(str(value)) for key, value in body["values"].items()}
        except (InvalidOperation, TypeError, ValueError):
            return jsonify({"error": "macro indicator values must be numeric"}), 400
        if as_of >= datetime.now(UTC).date() or any(not key.strip() or not value.is_finite() for key, value in parsed_values.items()):
            return jsonify({"error": "macro indicator snapshot is invalid"}), 400
        values = {key: str(value) for key, value in parsed_values.items()}
        normalized = {"as_of_date": as_of.isoformat(), "values": dict(sorted(values.items()))}
        artifact_id = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
        if not publisher.catalog.has(artifact_id):
            publisher.publish_json("reference/macro-indicators", artifact_id, {"snapshot_id": artifact_id, **normalized})
        return jsonify({"artifact_id": artifact_id, **normalized}), 201

    @blueprint.post("/market-capitalization")
    def publish_market_capitalization():
        if publisher is None:
            return jsonify({"error": "reference publisher is unavailable"}), 503
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"as_of_date", "values"} or not isinstance(body["values"], dict) or not body["values"]:
            return jsonify({"error": "as_of_date and non-empty values are required"}), 400
        try:
            as_of = date.fromisoformat(str(body["as_of_date"]))
            parsed: dict[str, Decimal | dict[str, Decimal]] = {}
            for key, value in body["values"].items():
                if isinstance(value, dict) and set(value) == {"market_cap", "free_float"}:
                    market_cap = Decimal(str(value["market_cap"]))
                    free_float = Decimal(str(value["free_float"]))
                    parsed[str(key)] = {"market_cap": market_cap, "free_float": free_float}
                else:
                    parsed[str(key)] = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return jsonify({"error": "market capitalization values are numeric"}), 400
        if as_of >= datetime.now(UTC).date() or any(
            not key.strip()
            or isinstance(value, Decimal) and (not value.is_finite() or value <= 0)
            or isinstance(value, dict) and (
                not value["market_cap"].is_finite() or value["market_cap"] <= 0
                or not value["free_float"].is_finite() or not 0 < value["free_float"] <= 1
            )
            for key, value in parsed.items()
        ):
            return jsonify({"error": "market capitalization snapshot is invalid"}), 400
        normalized = {"as_of_date": as_of.isoformat(), "values": {key: ({field: str(number) for field, number in value.items()} if isinstance(value, dict) else str(value)) for key, value in sorted(parsed.items())}}
        artifact_id = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
        if not publisher.catalog.has(artifact_id):
            publisher.publish_json("reference/market-capitalization", artifact_id, {"snapshot_id": artifact_id, **normalized})
        return jsonify({"artifact_id": artifact_id, **normalized}), 201

    @blueprint.post("/fundamentals")
    def publish_fundamentals():
        if publisher is None:
            return jsonify({"error": "reference publisher is unavailable"}), 503
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"as_of_date", "values"} or not isinstance(body["values"], dict) or not body["values"]:
            return jsonify({"error": "as_of_date and non-empty values are required"}), 400
        try:
            as_of = date.fromisoformat(str(body["as_of_date"]))
        except ValueError:
            return jsonify({"error": "as_of_date must be an ISO date"}), 400
        normalized_values: dict[str, dict[str, str]] = {}
        try:
            for key, value in body["values"].items():
                if not isinstance(key, str) or not key.strip() or not isinstance(value, dict) or set(value) - {"eps", "debt_equity"} or not value:
                    raise ValueError("fundamental row")
                parsed = {field: Decimal(str(raw)) for field, raw in value.items()}
                if any(not number.is_finite() for number in parsed.values()):
                    raise ValueError("non-finite fundamental")
                normalized_values[key] = {field: str(number) for field, number in sorted(parsed.items())}
        except (InvalidOperation, TypeError, ValueError):
            return jsonify({"error": "fundamental values are invalid"}), 400
        if as_of >= datetime.now(UTC).date():
            return jsonify({"error": "fundamental snapshot is invalid"}), 400
        normalized = {"as_of_date": as_of.isoformat(), "values": dict(sorted(normalized_values.items()))}
        artifact_id = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
        if not publisher.catalog.has(artifact_id):
            publisher.publish_json("reference/fundamentals", artifact_id, {"snapshot_id": artifact_id, **normalized})
        return jsonify({"artifact_id": artifact_id, **normalized}), 201

    def _read_snapshot(category: str, artifact_id: str):
        try:
            manifest, payload = store.read_json(category, artifact_id)
        except DomainValidationError:
            return jsonify({"error": "reference snapshot not found"}), 404
        return jsonify({
            "artifact": {
                "artifact_id": manifest.artifact_id,
                "category": manifest.category,
                "quality": manifest.quality.value,
                "upstream_ids": manifest.upstream_ids,
                "created_at": manifest.created_at,
            },
            "snapshot": payload,
        })

    @blueprint.get("/macro-indicators/<artifact_id>")
    def read_macro_indicators(artifact_id: str):
        return _read_snapshot("reference/macro-indicators", artifact_id)

    @blueprint.get("/market-capitalization/<artifact_id>")
    def read_market_capitalization(artifact_id: str):
        return _read_snapshot("reference/market-capitalization", artifact_id)

    @blueprint.get("/fundamentals/<artifact_id>")
    def read_fundamentals(artifact_id: str):
        return _read_snapshot("reference/fundamentals", artifact_id)

    return blueprint
