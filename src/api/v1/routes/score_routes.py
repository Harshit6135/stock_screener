from flask.views import MethodView
from flask_smorest import Blueprint, abort
from flask import request
from datetime import datetime, timedelta

from repositories import ScoreRepository, PortfolioRepository, MarketDataRepository
from schemas import ScoreSchema, AvgScoreSchema, MessageSchema, TopNSchema
from services import ScoreService


blp = Blueprint("score", __name__, url_prefix="/api/v1/score", description="Operations on Score calculations")
score_repo = ScoreRepository()
portfolio_repo = PortfolioRepository()
marketdata_repo = MarketDataRepository()


def get_prev_friday(d):
    """
    Get the Friday for score lookup:
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


# ========== Score Generation Endpoints ==========

@blp.route("/generate")
class GenerateScores(MethodView):
    @blp.response(201, MessageSchema)
    def post(self):
        """Generate composite scores incrementally from last calculated date"""
        score_service = ScoreService()
        result = score_service.generate_composite_scores()
        return {"message": result["message"]}


@blp.route("/recalculate")
class RecalculateScores(MethodView):
    @blp.response(201, MessageSchema)
    def post(self):
        """Recalculate ALL composite scores from scratch (use when weights updated)"""
        score_service = ScoreService()
        result = score_service.recalculate_all_scores()
        return {"message": result["message"]}


@blp.route("/generate_avg")
class GenerateAvgScores(MethodView):
    @blp.response(201, MessageSchema)
    def post(self):
        """Generate weekly average scores incrementally"""
        score_service = ScoreService()
        result = score_service.generate_avg_scores()
        return {"message": result["message"]}


@blp.route("/recalculate_avg")
class RecalculateAvgScores(MethodView):
    @blp.response(201, MessageSchema)
    def post(self):
        """Recalculate ALL weekly average scores from scratch"""
        score_service = ScoreService()
        result = score_service.recalculate_all_avg_scores()
        return {"message": result["message"]}


# ========== Score Query Endpoints ==========

@blp.route("/top/<int:n>")
class TopScores(MethodView):
    @blp.response(200, TopNSchema(many=True))
    def get(self, n):
        """Get top N stocks by avg composite score. Date is normalized to Friday."""
        date_str = request.args.get('date', None)
        score_date = None
        if date_str:
            try:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                # Normalize to Friday
                score_date = get_prev_friday(parsed_date)
            except ValueError:
                abort(400, message="Invalid date format. Use YYYY-MM-DD")
        
        # Get top N from avg_score table
        scores = score_repo.get_top_n_by_date(n, score_date)
        if not scores:
            return []
        
        invested_symbols = portfolio_repo.get_invested()
        invested_symbols = [i.tradingsymbol for i in invested_symbols]
        
        # Get actual score date used (for fetching prices)
        actual_date = score_date if score_date else score_repo.get_max_avg_score_date()

        result = []
        for i, s in enumerate(scores, 1):
            # Fetch close price from market data for this date
            price_data = marketdata_repo.query({
                "tradingsymbol": s.tradingsymbol,
                "start_date": actual_date,
                "end_date": actual_date
            })
            close_price = price_data[0].close if price_data else None
            
            result.append({
                'tradingsymbol': s.tradingsymbol,
                'composite_score': s.composite_score,
                'rank': i,
                'is_invested': s.tradingsymbol in invested_symbols,
                'ranking_date': s.score_date,
                'close_price': close_price
            })
        return result


@blp.route("/symbol/<string:symbol>")
class ScoreBySymbol(MethodView):
    @blp.response(200, TopNSchema)
    def get(self, symbol):
        """Get avg score for a specific symbol. Date is normalized to Friday."""
        date_str = request.args.get('date', None)
        score_date = None
        if date_str:
            try:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                # Normalize to Friday
                score_date = get_prev_friday(parsed_date)
            except ValueError:
                abort(400, message="Invalid date format. Use YYYY-MM-DD")
        
        # Fetch from avg_score table
        score = score_repo.get_by_symbol(symbol, score_date)
        actual_date = score.score_date if score else None
        
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
            'composite_score': score.composite_score if score else 0.0,
            'rank': 0,
            'is_invested': False,
            'ranking_date': actual_date,
            'close_price': close_price
        }
