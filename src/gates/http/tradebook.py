"""CSV upload review and explicit application to open portfolio lots."""

from flask import Blueprint, jsonify, request

from src.platform_kernel import DomainValidationError


def create_tradebook_blueprint(importer, history_scheduler=None):
    blueprint = Blueprint("tradebook", __name__, url_prefix="/api/portfolio/accounts")

    @blueprint.post("/<account_id>/tradebook/preview")
    def preview(account_id):
        request.max_content_length = 5 * 1024 * 1024
        upload = request.files.get("file")
        if upload is None or not (upload.filename or "").lower().endswith(".csv"):
            return jsonify({"error": "choose a tradebook CSV file"}), 400
        try:
            return jsonify(
                importer.preview(
                    account_id,
                    upload.read(4 * 1024 * 1024 + 1),
                    request.form.get("mode", "open_lots"),
                )
            )
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/<account_id>/tradebook/refresh-preview")
    def refresh_preview(account_id):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) - {"upload_id", "mode"}:
            return jsonify({"error": "tradebook preview request is invalid"}), 400
        try:
            return jsonify(
                importer.refresh_preview(
                    account_id, payload.get("upload_id"), payload.get("mode", "open_lots")
                )
            )
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/<account_id>/tradebook/apply")
    def apply(account_id):
        try:
            result = importer.apply(account_id, request.get_json(silent=True))
            if history_scheduler:
                result['history_backfill_job_id'] = history_scheduler(account_id)
            return jsonify(result)
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    return blueprint
