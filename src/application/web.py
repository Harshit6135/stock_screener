"""Small, additive HTTP adapter for durable local operation jobs.

This is deliberately separate from the legacy v1 blueprints.  A submitted job
is durable and observable here; a worker is responsible for claiming and
executing its domain-specific work.
"""

import secrets
from collections.abc import Collection
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from src.application.jobs import Job, JobStore
from src.application.worker import BackgroundWorker, JobWorker
from src.platform_kernel import DomainValidationError


def _job_response(job: Job) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "fingerprint": job.fingerprint,
        "status": job.status.value,
        "attempts": job.attempts,
        "cancel_requested": job.cancel_requested,
        "result": job.result,
    }


def require_operator_token() -> tuple[dict[str, str], int] | None:
    """Require an explicit local operator secret for every state change."""
    configured = current_app.config.get("OPERATOR_TOKEN")
    if not configured:
        return {
            "error": "mutating operations are disabled until SCREENER_OPERATOR_TOKEN is configured"
        }, 503
    supplied = request.headers.get("X-Operator-Token", "")
    if not secrets.compare_digest(supplied, configured):
        return {"error": "operator token is required"}, 401
    return None


def create_operations_blueprint(
    job_database: str | Path | JobStore,
    allowed_job_kinds: Collection[str] | None = None,
    worker: JobWorker | None = None,
    background_worker: BackgroundWorker | None = None,
) -> Blueprint:
    """Create the v2 operations API over a local durable :class:`JobStore`."""
    jobs = job_database if isinstance(job_database, JobStore) else JobStore(job_database)
    blueprint = Blueprint("operations_v2", __name__, url_prefix="/api/v2/operations")

    @blueprint.post("/jobs")
    def submit_job():
        authorization_error = require_operator_token()
        if authorization_error:
            body, status = authorization_error
            return jsonify(body), status
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("fingerprint"), str):
            return jsonify({"error": "fingerprint must be a non-empty string"}), 400
        try:
            kind = payload.get("kind", "generic")
            if (
                not isinstance(kind, str)
                or allowed_job_kinds is not None
                and kind not in allowed_job_kinds
            ):
                raise DomainValidationError("unsupported job kind")
            if not isinstance(payload.get("payload", {}), dict):
                raise DomainValidationError("job payload must be an object")
            job = jobs.submit(
                payload["fingerprint"].strip(),
                kind,
                payload.get("payload", {}),
            )
        except DomainValidationError as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(_job_response(job)), 202

    @blueprint.get("/jobs/<int:job_id>")
    def get_job(job_id: int):
        try:
            return jsonify(_job_response(jobs.get(job_id)))
        except DomainValidationError:
            return jsonify({"error": "job not found"}), 404

    @blueprint.get("/jobs/<int:job_id>/events")
    def job_events(job_id: int):
        raw_cursor = request.args.get("after", "0")
        try:
            cursor = int(raw_cursor)
            if cursor < 0:
                raise ValueError
            jobs.get(job_id)
        except DomainValidationError:
            return jsonify({"error": "job not found"}), 404
        except ValueError:
            return jsonify({"error": "after must be a non-negative integer"}), 400
        return jsonify({"events": jobs.events_after(job_id, cursor)})

    @blueprint.post("/jobs/<int:job_id>/cancel")
    def cancel_job(job_id: int):
        authorization_error = require_operator_token()
        if authorization_error:
            body, status = authorization_error
            return jsonify(body), status
        try:
            return jsonify(_job_response(jobs.request_cancel(job_id))), 202
        except DomainValidationError as error:
            status = 404 if str(error) == "job does not exist" else 409
            return jsonify({"error": str(error)}), status

    @blueprint.get("/worker/status")
    def worker_status():
        if background_worker is not None:
            return jsonify(background_worker.status()), 200
        return jsonify({"worker_id": worker.worker_id if worker else None, "running": False}), 200

    @blueprint.post("/worker/start")
    def start_worker():
        authorization_error = require_operator_token()
        if authorization_error:
            body, status = authorization_error
            return jsonify(body), status
        if background_worker is None:
            return jsonify({"error": "background worker is not configured"}), 503
        background_worker.start()
        return jsonify(background_worker.status()), 200

    @blueprint.post("/worker/stop")
    def stop_worker():
        authorization_error = require_operator_token()
        if authorization_error:
            body, status = authorization_error
            return jsonify(body), status
        if background_worker is None:
            return jsonify({"error": "background worker is not configured"}), 503
        background_worker.stop()
        return jsonify(background_worker.status()), 200

    @blueprint.post("/worker/work-once")
    def work_once():
        authorization_error = require_operator_token()
        if authorization_error:
            body, status = authorization_error
            return jsonify(body), status
        target_worker = worker or (background_worker.worker if background_worker else None)
        if target_worker is None:
            return jsonify({"error": "worker is not configured"}), 503
        job = target_worker.run_once()
        return jsonify({"executed": job is not None, "job": _job_response(job) if job else None}), 200

    return blueprint
