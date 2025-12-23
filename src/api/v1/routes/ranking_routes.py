from flask.views import MethodView
from flask_smorest import Blueprint, abort
from repositories import RankingRepository, PortfolioRepository
from schemas import RankingSchema, TopNSchema, MessageSchema, RankingAllSchema
from services import RankingService


blp = Blueprint("ranking", __name__, url_prefix="/api/v1/ranking", description="Operations on Ranking")
ranking_repository = RankingRepository()
portfolio_repository = PortfolioRepository()

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
        """Get top 20 ranked stocks (including invested)"""
        if ranking_repository.get_max_ranking_date() is None:
            return []

        rankings = ranking_repository.get_top_n_rankings_by_date(top)
        invested_symbols = portfolio_repository.get_invested()
        invested_symbols = [i.tradingsymbol for i in invested_symbols]

        result = []
        for i, r in enumerate(rankings, 1):
            result.append({
                'tradingsymbol': r.tradingsymbol,
                'composite_score': r.composite_score,
                'rank': i,
                'is_invested': r.tradingsymbol in invested_symbols,
                'ranking_date': r.ranking_date
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