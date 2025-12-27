from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from datetime import datetime
from repositories import RankingRepository, PortfolioRepository, MarketDataRepository
from schemas import RankingSchema, TopNSchema, MessageSchema, RankingAllSchema
from services import RankingService


blp = Blueprint("ranking", __name__, url_prefix="/api/v1/ranking", description="Operations on Ranking")
ranking_repository = RankingRepository()
portfolio_repository = PortfolioRepository()
marketdata_repository = MarketDataRepository()

@blp.route("/")
class RankingList(MethodView):
    @blp.arguments(RankingSchema(many=True))
    @blp.response(201, MessageSchema)
    def post(self, ranking_data):
        """Bulk insert ranking data"""
        response = ranking_repository.bulk_insert(ranking_data)
        if not response:
            abort(500, message="Failed to insert ranking data")
        return {"message": f"Inserted {len(response)} ranking records"}


@blp.route("/top/<int:top>")
class TopRanking(MethodView):
    @blp.response(200, TopNSchema(many=True))
    def get(self, top):
        """Get top N ranked stocks. Optionally pass ?date=YYYY-MM-DD for a specific date."""
        # Parse optional date query parameter
        date_str = request.args.get('date', None)
        ranking_date = None
        if date_str:
            try:
                ranking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                abort(400, message="Invalid date format. Use YYYY-MM-DD")
        
        if ranking_repository.get_max_ranking_date() is None:
            return []

        rankings = ranking_repository.get_top_n_rankings_by_date(top, date=ranking_date)
        invested_symbols = portfolio_repository.get_invested()
        invested_symbols = [i.tradingsymbol for i in invested_symbols]
        
        # Get actual ranking date used (for fetching prices)
        actual_date = ranking_date if ranking_date else ranking_repository.get_max_ranking_date()

        result = []
        for i, r in enumerate(rankings, 1):
            # Fetch close price from market data for this date
            price_data = marketdata_repository.query({
                "tradingsymbol": r.tradingsymbol,
                "start_date": actual_date,
                "end_date": actual_date
            })
            close_price = price_data[0].close if price_data else None
            
            result.append({
                'tradingsymbol': r.tradingsymbol,
                'composite_score': r.composite_score,
                'rank': i,
                'is_invested': r.tradingsymbol in invested_symbols,
                'ranking_date': r.ranking_date,
                'close_price': close_price
            })
        return result

@blp.route("/update")
class RankingUpdateAll(MethodView):
    @blp.arguments(RankingAllSchema())
    @blp.response(201, MessageSchema)
    def post(self, ranking_data):
        rank_date = ranking_data.get("date", None)
        """Generate latest rankings and scores"""
        ranking_service = RankingService()
        ranking_service.generate_score(rank_date)
        return "Ranking completed and saved."


@blp.route("/update/<string:rank_date>")
class RankingUpdateByDate(MethodView):
    @blp.response(201, MessageSchema)
    def post(self, rank_date):
        """Generate latest rankings and scores"""
        ranking_service = RankingService()
        ranking_service.generate_score(rank_date)
        return "Ranking completed and saved."


@blp.route("/symbol/<string:symbol>")
class RankingBySymbol(MethodView):
    @blp.response(200, TopNSchema)
    def get(self, symbol):
        """Get ranking for a specific symbol. Optionally pass ?date=YYYY-MM-DD for specific date."""
        date_str = request.args.get('date', None)
        ranking_date = None
        if date_str:
            try:
                ranking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                abort(400, message="Invalid date format. Use YYYY-MM-DD")
        
        # Determine the date to use for fetching ranking/price
        if ranking_date:
            actual_date = ranking_date
            rankings = ranking_repository.get_rankings_by_date_and_symbol(ranking_date, symbol)
            ranking = rankings[0] if rankings else None
        else:
            ranking = ranking_repository.get_latest_rank_by_symbol(symbol)
            actual_date = ranking.ranking_date if ranking else marketdata_repository.get_latest_date_by_symbol(symbol).date
        
        # Fetch close price for the determined date
        price_data = marketdata_repository.query({
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