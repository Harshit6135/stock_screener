"""
Investment Routes

API endpoints for investment holdings and summary.
Actions consolidated in actions_routes.py.
"""
from flask.views import MethodView
from flask_smorest import Blueprint

from schemas import (
    ActionQuerySchema, HoldingDateSchema, HoldingSchema, SummarySchema
)
from repositories import InvestmentRepository


blp = Blueprint(
    "Investments",
    __name__,
    url_prefix="/api/v1/investment",
    description="Investment Operations"
)


@blp.route("/holdings/dates")
class HoldingDates(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.response(200, HoldingDateSchema)
    def get(self):
        """Get all distinct holding dates"""
        dates = InvestmentRepository.get_holdings_dates()
        return {"dates": dates}


@blp.route("/holdings")
class Holdings(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, HoldingSchema(many=True))
    def get(self, args):
        """Get holdings for a specific date"""
        working_date = args.get('date')
        holdings = InvestmentRepository.get_holdings(working_date)
        return [h.to_dict() for h in holdings]


@blp.route("/summary")
class Summary(MethodView):
    @blp.doc(tags=["Investments"])
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, SummarySchema)
    def get(self, args):
        """Get summary for a specific date"""
        working_date = args.get('date')
        summary = InvestmentRepository.get_summary(working_date)
        if summary:
            return summary.to_dict()
        return {}

