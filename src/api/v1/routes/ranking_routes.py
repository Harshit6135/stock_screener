from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from datetime import datetime, timedelta

from repositories import ScoreRepository, MarketDataRepository
from schemas import RankingSchema, MessageSchema, TopNSchema
from services import RankingService


blp = Blueprint("ranking", __name__, url_prefix="/api/v1/ranking", description="Operations on Weekly Rankings")
score_repo = ScoreRepository()

marketdata_repo = MarketDataRepository()


def get_prev_friday(d):
    """
    Get the Friday for ranking lookup:
    - If d is Friday, return d
    - Otherwise, return the previous Friday before d
    """
    weekday = d.weekday()  # Monday=0, Friday=4
    if weekday == 4:  # Friday
        return d
    elif weekday < 4:  # Mon-Thu: go back to last Friday
        days_back = weekday + 3  # Mon=3, Tue=4, Wed=5, Thu=6
        return d - timedelta(days=days_back)
    else:  # Sat=5, Sun=6: go back to Friday
        days_back = weekday - 4  # Sat=1, Sun=2
        return d - timedelta(days=days_back)


# ========== Ranking Generation Endpoints ==========

@blp.route("/generate")
class GenerateRankings(MethodView):
    @blp.doc(tags=["Data Pipeline"])
    @blp.response(201, MessageSchema)
    def post(self):
        """Generate weekly rankings incrementally"""
        ranking_service = RankingService()
        result = ranking_service.generate_rankings()
        return {"message": result["message"]}


@blp.route("/recalculate")
class RecalculateRankings(MethodView):
    @blp.doc(tags=["Data Pipeline"])
    @blp.response(201, MessageSchema)
    def post(self):
        """Recalculate ALL weekly rankings from scratch"""
        ranking_service = RankingService()
        result = ranking_service.recalculate_all_rankings()
        return {"message": result["message"]}


# ========== Ranking Query Endpoints ==========

@blp.route("/top/<int:n>")
class TopRankings(MethodView):
    @blp.doc(tags=["Data Pipeline"])
    @blp.response(200, TopNSchema(many=True))
    def get(self, n):
        """Get top N stocks by ranking. Date is normalized to Friday."""
        date_str = request.args.get('date', None)
        ranking_date = None
        if date_str:
            try:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                # Normalize to Friday
                ranking_date = get_prev_friday(parsed_date)
            except ValueError:
                abort(400, message="Invalid date format. Use YYYY-MM-DD")
        
        # Get top N from ranking table
        rankings = score_repo.get_top_n_by_date(n, ranking_date)
        if not rankings:
            return []
        else:
            return rankings


@blp.route("/symbol/<string:symbol>")
class RankingBySymbol(MethodView):
    @blp.doc(tags=["Data Pipeline"])
    @blp.response(200, TopNSchema)
    def get(self, symbol):
        """Get ranking for a specific symbol. Date is normalized to Friday."""
        date_str = request.args.get('date', None)
        ranking_date = None
        if date_str:
            try:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                # Normalize to Friday
                ranking_date = get_prev_friday(parsed_date)
            except ValueError:
                abort(400, message="Invalid date format. Use YYYY-MM-DD")
        
        # Fetch from ranking table
        ranking = score_repo.get_by_symbol(symbol, ranking_date)
        actual_date = ranking.ranking_date if ranking else None
        
        if not actual_date:
            # Fallback to latest market data date
            md = marketdata_repo.get_latest_date_by_symbol(symbol)
            actual_date = md.date if md else None
        
        # Fetch close price for the determined date
        close_price = None
        if actual_date:
            price_data = marketdata_repo.query({
                "tradingsymbol": symbol,
                "start_date": actual_date,
                "end_date": actual_date
            })
            close_price = price_data[0].close if price_data else None
        
        return {
            'tradingsymbol': symbol,
            'composite_score': ranking.composite_score if ranking else 0.0,
            'rank': ranking.rank if ranking else 0,
            'is_invested': False,
            'ranking_date': actual_date,
            'close_price': close_price
        }


@blp.route("/query/<string:ranking_date_str>")
class RankingsQuery(MethodView):
    @blp.doc(tags=["Data Pipeline"])
    @blp.response(200, RankingSchema(many=True))
    def get(self, ranking_date_str):
        """Fetch all rankings for a specific date"""
        return score_repo.get_rankings_by_date(ranking_date_str)
