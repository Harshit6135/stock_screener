from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from datetime import datetime
from repositories import RankingRepository
from schemas import RankingSchema, MessageSchema, RankingAllSchema
from services import RankingService


blp = Blueprint("ranking", __name__, url_prefix="/api/v1/ranking", description="Operations on Percentile Rankings")
ranking_repository = RankingRepository()


@blp.route("/")
class RankingList(MethodView):
    @blp.arguments(RankingSchema(many=True))
    @blp.response(201, MessageSchema)
    def post(self, ranking_data):
        """Bulk insert percentile ranking data"""
        response = ranking_repository.bulk_insert(ranking_data)
        if not response:
            abort(500, message="Failed to insert ranking data")
        return {"message": f"Inserted {len(response)} ranking records"}


@blp.route("/update")
class RankingUpdateAll(MethodView):
    @blp.arguments(RankingAllSchema())
    @blp.response(201, MessageSchema)
    def post(self, ranking_data):
        """Generate percentile rankings for a specific date"""
        rank_date = ranking_data.get("date", None)
        ranking_service = RankingService()
        ranking_service.generate_score(rank_date)
        return {"message": "Percentile ranking completed and saved."}


@blp.route("/update/<string:rank_date>")
class RankingUpdateByDate(MethodView):
    @blp.response(201, MessageSchema)
    def post(self, rank_date):
        """Generate percentile rankings for a specific date"""
        ranking_service = RankingService()
        ranking_service.generate_score(rank_date)
        return {"message": "Percentile ranking completed and saved."}


@blp.route("/update_all")
class UpdateAllRankings(MethodView):
    @blp.response(201, MessageSchema)
    def post(self):
        """Backfill percentile rankings for all available historical dates"""
        ranking_service = RankingService()
        ranking_service.backfill_rankings()
        return {"message": "All percentile rankings updated successfully."}


@blp.route("/query/<string:rank_date>")
class RankingsQuery(MethodView):
    @blp.response(200, RankingSchema(many=True))
    def get(self, rank_date):
        """Fetch percentile rankings for a specific date"""
        return ranking_repository.get_rankings_by_date(rank_date)
