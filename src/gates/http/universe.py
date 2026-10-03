"""Read and refresh interfaces for immutable universe snapshots."""

from datetime import UTC, date, datetime

from flask import Blueprint, jsonify, request

from src.domains.operations import JobStore
from src.gates.repositories import MarketRepository
from src.platform_kernel import DomainValidationError


def create_universe_blueprint(repository: MarketRepository, jobs: JobStore) -> Blueprint:
    blueprint = Blueprint("universe_v2", __name__, url_prefix="/api/v2/universe")

    @blueprint.get("/snapshots")
    def snapshots():
        try:
            index_name = request.args.get("index_name", "NIFTY 500")
            limit, offset = int(request.args.get("limit", "100")), int(request.args.get("offset", "0"))
            return jsonify({"snapshots": repository.list_universe_snapshots(index_name, limit=limit, offset=offset), "limit": limit, "offset": offset})
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/members")
    def members():
        try:
            snapshot_id = request.args.get("snapshot_id")
            if snapshot_id is None:
                index_name = request.args.get("index_name", "NIFTY 500")
                as_of = date.fromisoformat(request.args.get("as_of", datetime.now(UTC).date().isoformat()))
                snapshot = repository.universe_snapshot_as_of(index_name, as_of)
                if snapshot is None:
                    return jsonify({"error": "universe snapshot not found"}), 404
                snapshot_id = str(snapshot["snapshot_id"])
            limit, offset = int(request.args.get("limit", "500")), int(request.args.get("offset", "0"))
            return jsonify({"snapshot_id": snapshot_id, "members": repository.universe_snapshot_members(snapshot_id, limit=limit, offset=offset), "limit": limit, "offset": offset})
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.get("/diff")
    def diff():
        try:
            return jsonify(repository.universe_snapshot_diff(request.args["from_snapshot_id"], request.args["to_snapshot_id"]))
        except (KeyError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/refresh")
    def refresh():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict) or set(body) - {"snapshot_date"}:
            return jsonify({"error": "universe refresh payload is invalid"}), 400
        try:
            snapshot_date = str(body.get("snapshot_date", datetime.now(UTC).date().isoformat()))
            if body:
                date.fromisoformat(snapshot_date)
            job = jobs.submit(f"universe:nifty500:{snapshot_date}", "reference.download-nifty500-constituents", body)
            return jsonify({"job_id": job.job_id, "status": job.status.value}), 202
        except (ValueError, DomainValidationError) as exc:
            return jsonify({"error": str(exc)}), 400

    return blueprint
