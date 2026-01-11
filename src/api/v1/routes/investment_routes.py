from flask.views import MethodView
from flask_smorest import Blueprint

from schemas import (
    MessageSchema, ActionDateSchema, ActionQuerySchema, ActionSchema,
    ActionUpdateSchema, HoldingDateSchema, HoldingSchema, SummarySchema
)
from repositories import InvestmentRepository


blp = Blueprint(
    "investment",
    __name__,
    url_prefix="/api/v1/investment",
    description="Investment Operations"
)


@blp.route("/actions/dates")
class ActionDates(MethodView):
    @blp.response(200, ActionDateSchema)
    def get(self):
        """Get all distinct action dates"""
        dates = InvestmentRepository.get_action_dates()
        return {"dates": dates}


@blp.route("/actions")
class Actions(MethodView):
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, ActionSchema(many=True))
    def get(self, args):
        """Get actions for a specific date"""
        working_date = args.get('date')
        actions = InvestmentRepository.get_actions(working_date)
        return [a.to_dict() for a in actions]


@blp.route("/actions/<action_id>")
class ActionUpdate(MethodView):
    @blp.arguments(ActionUpdateSchema)
    @blp.response(200, MessageSchema)
    def put(self, data, action_id):
        """Update an action (approve/reject/update units)"""
        action_data = {
            'action_id': action_id,
            'status': data['status'],
        }

        if 'units' in data:
            action_data['units'] = data['units']

        if 'execution_price' in data:
            action_data['execution_price'] = data['execution_price']

        result = InvestmentRepository.update_action(action_data)

        if result:
            return {"message": f"Action {action_id} updated successfully"}
        return {"message": f"Failed to update action {action_id}"}, 400


@blp.route("/holdings/dates")
class HoldingDates(MethodView):
    @blp.response(200, HoldingDateSchema)
    def get(self):
        """Get all distinct holding dates"""
        dates = InvestmentRepository.get_holdings_dates()
        return {"dates": dates}


@blp.route("/holdings")
class Holdings(MethodView):
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, HoldingSchema(many=True))
    def get(self, args):
        """Get holdings for a specific date"""
        working_date = args.get('date')
        holdings = InvestmentRepository.get_holdings(working_date)
        return [h.to_dict() for h in holdings]


@blp.route("/summary")
class Summary(MethodView):
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, SummarySchema)
    def get(self, args):
        """Get summary for a specific date"""
        working_date = args.get('date')
        summary = InvestmentRepository.get_summary(working_date)
        if summary:
            return summary.to_dict()
        return {}
