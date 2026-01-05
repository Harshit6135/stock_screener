from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from datetime import datetime
from repositories import PercentileRepository
from schemas import PercentileSchema, MessageSchema, PercentileAllSchema
from services import PercentileService


blp = Blueprint("percentile", __name__, url_prefix="/api/v1/percentile", description="Operations on Percentile Ranks")
percentile_repository = PercentileRepository()


@blp.route("/")
class PercentileList(MethodView):
    @blp.arguments(PercentileSchema(many=True))
    @blp.response(201, MessageSchema)
    def post(self, percentile_data):
        """Bulk insert percentile data"""
        response = percentile_repository.bulk_insert(percentile_data)
        if not response:
            abort(500, message="Failed to insert percentile data")
        return {"message": f"Inserted {len(response)} percentile records"}


@blp.route("/update")
class PercentileUpdateAll(MethodView):
    @blp.arguments(PercentileAllSchema())
    @blp.response(201, MessageSchema)
    def post(self, percentile_data):
        """Generate percentiles for a specific date"""
        percentile_date = percentile_data.get("date", None)
        percentile_service = PercentileService()
        percentile_service.generate_percentile(percentile_date)
        return {"message": "Percentile calculation completed and saved."}


@blp.route("/update/<string:percentile_date>")
class PercentileUpdateByDate(MethodView):
    @blp.response(201, MessageSchema)
    def post(self, percentile_date):
        """Generate percentiles for a specific date"""
        percentile_service = PercentileService()
        percentile_service.generate_percentile(percentile_date)
        return {"message": "Percentile calculation completed and saved."}


@blp.route("/update_all")
class UpdateAllPercentiles(MethodView):
    @blp.response(201, MessageSchema)
    def post(self):
        """Backfill percentiles for all available historical dates"""
        percentile_service = PercentileService()
        percentile_service.backfill_percentiles()
        return {"message": "All percentiles updated successfully."}


@blp.route("/query/<string:percentile_date>")
class PercentilesQuery(MethodView):
    @blp.response(200, PercentileSchema(many=True))
    def get(self, percentile_date):
        """Fetch percentiles for a specific date"""
        return percentile_repository.get_percentiles_by_date(percentile_date)
