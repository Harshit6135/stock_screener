"""Small, additive HTTP adapter for durable local operation jobs.

Submitted jobs are durable and observable here; a worker is responsible for
claiming and executing its domain-specific work.
"""

import json
import time
from collections.abc import Collection
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, stream_with_context

from src.domains.operations import BackgroundWorker, Job, JobStore, JobWorker
from src.gates.job_catalog import job_catalog
from src.platform_kernel import DomainValidationError


def _job_response(job: Job) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "fingerprint": job.fingerprint,
        "kind": job.kind,
        "status": job.status.value,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "payload": job.payload,
        "lease_owner": job.lease_owner,
        "lease_until": job.lease_until,
        "cancel_requested": job.cancel_requested,
        "last_error": job.last_error,
        "result": job.result,
    }


def create_operations_blueprint(
    job_database: str | Path | JobStore,
    allowed_job_kinds: Collection[str] | None = None,
    worker: JobWorker | None = None,
    background_worker: BackgroundWorker | None = None,
) -> Blueprint:
    """Create the operations API over a local durable :class:`JobStore`."""
    jobs = job_database if isinstance(job_database, JobStore) else JobStore(job_database)
    blueprint = Blueprint("operations", __name__, url_prefix="/api/operations")

    @blueprint.get("/job-types")
    def job_types():
        catalog = job_catalog()
        return jsonify(
            {
                "jobs": [
                    job
                    for job in catalog["jobs"]
                    if allowed_job_kinds is None or job["kind"] in allowed_job_kinds
                ],
                "pipeline": catalog["pipeline"],
            }
        )

    @blueprint.get("/jobs")
    def recent_jobs():
        try:
            limit = int(request.args.get("limit", "50"))
            if not 1 <= limit <= 100:
                raise ValueError
        except ValueError:
            return jsonify({"error": "limit must be between 1 and 100"}), 400
        recent = []
        for job in jobs.recent(limit):
            response = _job_response(job)
            if job.status.value == "RUNNING":
                progress = next(
                    (
                        event["payload"]
                        for event in reversed(jobs.recent_events(job.job_id))
                        if event["event_type"] == "progress"
                    ),
                    None,
                )
                response["current_progress"] = progress
            recent.append(response)
        return jsonify({"jobs": recent})

    @blueprint.post("/jobs/<int:job_id>/retry")
    def retry_job(job_id):
        try:
            job = jobs.get(job_id)
            retried = (
                jobs.retry_cancelled(job_id)
                if job.status.value == "CANCELLED"
                else jobs.retry_failed(job_id)
            )
            return jsonify(_job_response(retried)), 202
        except DomainValidationError as error:
            return jsonify({"error": str(error)}), 404 if str(
                error
            ) == "job does not exist" else 409

    @blueprint.post("/jobs")
    def submit_job():
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
            job = jobs.get(job_id)
            events = jobs.recent_events(job_id)
            progress = next(
                (item for item in reversed(events) if item["event_type"] == "progress"),
                None,
            )
            return jsonify(
                {
                    **_job_response(job),
                    "current_progress": progress["payload"] if progress else None,
                    "events": events,
                }
            )
        except DomainValidationError:
            return jsonify({"error": "job not found"}), 404

    @blueprint.get("/jobs/<int:job_id>/events")
    def job_events(job_id: int):
        raw_cursor = request.headers.get("Last-Event-ID") or request.args.get("after", "0")
        try:
            cursor = int(raw_cursor)
            if cursor < 0:
                raise ValueError
            jobs.get(job_id)
        except DomainValidationError:
            return jsonify({"error": "job not found"}), 404
        except ValueError:
            return jsonify({"error": "after must be a non-negative integer"}), 400
        if (
            request.args.get("stream") == "1"
            or request.accept_mimetypes.best == "text/event-stream"
        ):

            @stream_with_context
            def stream_events():
                after = cursor
                iterations = 0
                max_iterations = 25
                yield "retry: 1000\n\n"
                while iterations < max_iterations:
                    events = jobs.events_after(job_id, after)
                    for event in events:
                        after = event["event_id"]
                        yield f"id: {after}\nevent: job-event\ndata: {json.dumps(event)}\n\n"
                    state = jobs.get(job_id).status.value
                    if state in {"SUCCEEDED", "FAILED", "CANCELLED"} and not events:
                        yield f"event: terminal\ndata: {json.dumps({'status': state})}\n\n"
                        return
                    yield ": heartbeat\n\n"
                    time.sleep(1)
                    iterations += 1

            return Response(
                stream_events(),
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return jsonify({"events": jobs.events_after(job_id, cursor)})

    @blueprint.post("/jobs/<int:job_id>/cancel")
    def cancel_job(job_id: int):
        try:
            return jsonify(_job_response(jobs.request_cancel(job_id))), 202
        except DomainValidationError as error:
            status = 404 if str(error) == "job does not exist" else 409
            return jsonify({"error": str(error)}), status

    @blueprint.get("/worker/status")
    def worker_status():
        if background_worker is not None:
            return jsonify(
                {
                    **background_worker.status(),
                    "active_jobs": [_job_response(job) for job in jobs.active()],
                    "queued_by_kind": jobs.queued_by_kind(),
                }
            ), 200
        return jsonify({"worker_id": worker.worker_id if worker else None, "running": False}), 200

    @blueprint.post("/worker/start")
    def start_worker():
        if background_worker is None:
            return jsonify({"error": "background worker is not configured"}), 503
        background_worker.start()
        return jsonify(background_worker.status()), 200

    @blueprint.post("/worker/stop")
    def stop_worker():
        if background_worker is None:
            return jsonify({"error": "background worker is not configured"}), 503
        background_worker.stop()
        return jsonify(background_worker.status()), 200

    @blueprint.post("/worker/work-once")
    def work_once():
        target_worker = worker or (background_worker.worker if background_worker else None)
        if target_worker is None:
            return jsonify({"error": "worker is not configured"}), 503
        job = target_worker.run_once()
        return jsonify(
            {"executed": job is not None, "job": _job_response(job) if job else None}
        ), 200

    return blueprint
