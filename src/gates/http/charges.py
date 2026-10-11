"""Account-scoped multi-document charge review and reconciliation endpoints."""

from flask import Blueprint, Response, jsonify, request

from src.platform_kernel import DomainValidationError


def create_charges_blueprint(importer):
    blueprint = Blueprint("charges", __name__, url_prefix="/api/portfolio/accounts")

    @blueprint.post("/<account_id>/charges/preview")
    def preview(account_id):
        request.max_content_length = 65 * 1024 * 1024
        files = request.files.getlist("files")
        try:
            return jsonify(
                importer.preview(
                    account_id,
                    [(f.filename or "", f.read(8 * 1024 * 1024 + 1)) for f in files],
                    request.form.get("password", ""),
                    request.form.get("kind", "contract"),
                )
            )
        except DomainValidationError as exc:
            return jsonify({"error": str(exc)}), 400

    @blueprint.post("/<account_id>/charges/apply")
    def apply(account_id):
        try:
            return jsonify(importer.apply(account_id, request.get_json(silent=True)))
        except DomainValidationError as exc:
            status = 409 if "ledger changed" in str(exc) else 400
            return jsonify({"error": str(exc)}), status

    @blueprint.get("/charges/template.csv")
    def template():
        return Response(
            "symbol,date,side,quantity,price,trade_id,exchange,brokerage,exchange_charges,sebi,gst,stt,stamp_duty,dp,charges\n",
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=charges-template.csv"},
        )

    return blueprint
