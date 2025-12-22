from datetime import date

from flask import jsonify
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from services import ActionsService
from repositories import ActionsRepository
from schemas import ActionsSchema, GenerateActionsInputSchema, ExecuteActionInputSchema


blp = Blueprint("actions", __name__, url_prefix="/actions", description="Action management operations")
actions_repo = ActionsRepository()


@blp.route("/")
class ActionsList(MethodView):
    @blp.response(200, ActionsSchema(many=True))
    def get(self):
        """Get all pending actions"""
        actions = actions_repo.get_pending_actions()
        return jsonify([{
            'id': a.id,
            'action_date': str(a.action_date),
            'action_type': a.action_type,
            'tradingsymbol': a.tradingsymbol,
            'composite_score': a.composite_score,
            'units': a.units,
            'expected_price': a.expected_price,
            'amount': a.amount,
            'swap_from_symbol': a.swap_from_symbol,
            'swap_from_units': a.swap_from_units,
            'swap_from_price': a.swap_from_price,
            'status': a.status
        } for a in actions])


@blp.route("/generate")
class GenerateActions(MethodView):
    @blp.arguments(GenerateActionsInputSchema, location="json")
    @blp.response(201, ActionsSchema(many=True))
    def post(self, input_data):
        """Generate trade actions based on current rankings and portfolio"""
        ranking_date = input_data.get('ranking_date') or date.today()
        actions_service = ActionsService()
        response = actions_service.generate_actions(action_date=ranking_date)
        if response is None:
            abort(500, message="Failed to generate actions")        
        return response


@blp.route("/<int:action_id>/execute")
class ExecuteAction(MethodView):
    @blp.arguments(ExecuteActionInputSchema, location="json")
    @blp.response(200, ActionsSchema)
    def post(self, exec_data, action_id):
        """Mark an action as executed with actual prices and update capital"""
        actions_service = ActionsService()
        response = actions_service.execute_action(action_id, exec_data)
        if response is None:
            abort(500, message="Failed to execute action")
        return response
