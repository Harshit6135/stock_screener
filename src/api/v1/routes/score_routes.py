from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from datetime import datetime

from schemas import MessageSchema
from services import ScoreService
from repositories import ScoreRepository, RankingRepository


blp = Blueprint("Scores", __name__, url_prefix="/api/v1/score", description="Operations on Score calculations")
score_repo = ScoreRepository()
ranking_repo = RankingRepository()


# ========== Score Generation Endpoints ==========

@blp.route("/generate")
class GenerateScores(MethodView):
    @blp.doc(tags=["Scores"])
    @blp.response(201, MessageSchema)
    def post(self):
        """Generate composite scores incrementally from last calculated date"""
        score_service = ScoreService()
        result = score_service.generate_composite_scores()
        return {"message": result["message"]}


@blp.route("/recalculate")
class RecalculateScores(MethodView):
    @blp.doc(tags=["Scores"])
    @blp.response(201, MessageSchema)
    def post(self):
        """Recalculate ALL composite scores from scratch (use when weights updated)"""
        score_service = ScoreService()
        result = score_service.recalculate_all_scores()
        return {"message": result["message"]}


# ========== Score Query Endpoints ==========

@blp.route("/<string:tradingsymbol>")
class ScoreBySymbol(MethodView):
    @blp.doc(tags=["Scores"])
    def get(self, tradingsymbol: str):
        """
        Get composite score for a stock on a date.
        
        Used by backtesting API client.
        
        Parameters:
            tradingsymbol: Stock symbol (path param)
            date: Query param - Date (YYYY-MM-DD), normalized to Friday
            
        Returns:
            Dict with composite_score
        """
        date_str = request.args.get('date')
        
        as_of_date = None
        if date_str:
            try:
                as_of_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                abort(400, message="Invalid date format. Use YYYY-MM-DD")
        
        ranking = ranking_repo.get_by_symbol(tradingsymbol, as_of_date)
        
        if not ranking:
            return {"composite_score": None, "rank": None}
        
        return {
            "composite_score": ranking.composite_score,
            "rank": ranking.rank
        }
