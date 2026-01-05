from flask.views import MethodView
from flask_smorest import Blueprint

from schemas import ScoreSchema, MessageSchema
from services import ScoreService


blp = Blueprint("score", __name__, url_prefix="/api/v1/score", description="Operations on Score calculations")


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
