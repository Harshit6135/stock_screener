"""
Actions Routes

API endpoints for trading actions (BUY/SELL/SWAP).
"""
from datetime import datetime
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from config import setup_logger
from schemas import (
    MessageSchema, ActionDateSchema, ActionQuerySchema,
    ActionSchema, ActionUpdateSchema
)
from repositories import ConfigRepository, InvestmentRepository
from services import ActionsService


logger = setup_logger(name="ActionsRoutes")

blp = Blueprint(
    "actions",
    __name__,
    url_prefix="/api/v1/actions",
    description="Trading Actions Operations"
)


@blp.route("/config")
class ActionsConfig(MethodView):
    @blp.doc(tags=["Trading"])
    @blp.response(200, MessageSchema)
    def post(self):
        """Initialize strategy configuration"""
        config = ConfigRepository()
        data = {
            'strategy_name': 'momentum_strategy_one',
            'initial_capital': 100000,
            'risk_threshold': 1,
            'max_positions': 10,
            'buffer_percent': 25,
            'exit_threshold': 40,
            'sl_multiplier': 2
        }
        config.post_config(data)
        return {"message": "Strategy configuration saved successfully"}


@blp.route("/generate")
class GenerateActions(MethodView):
    @blp.doc(tags=["Trading"])
    @blp.response(200, MessageSchema)
    def post(self) -> dict:
        """
        Generate trading actions for current week.
        
        Returns:
            dict: Message with generated actions
        
        Raises:
            HTTPException: 400 for validation errors, 500 for failures
        """
        try:
            actions = ActionsService()
            working_date = datetime.now().date()
            new_actions = actions.generate_actions(working_date)
            return {"actions": new_actions}
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Failed to generate actions: {e}")
            abort(500, message=f"Action generation failed: {str(e)}")


@blp.route("/dates")
class ActionDates(MethodView):
    @blp.doc(tags=["Trading"])
    @blp.response(200, ActionDateSchema)
    def get(self):
        """Get all distinct action dates"""
        dates = InvestmentRepository.get_action_dates()
        return {"dates": dates}


@blp.route("/")
class ActionsList(MethodView):
    @blp.doc(tags=["Trading"])
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, ActionSchema(many=True))
    def get(self, args):
        """
        Get actions for a specific date.
        
        Parameters:
            date: Query param - Working date (YYYY-MM-DD)
            
        Returns:
            List of actions for the specified date
        """
        working_date = args.get('date')
        actions = InvestmentRepository.get_actions(working_date)
        return [a.to_dict() for a in actions]


@blp.route("/<action_id>")
class ActionDetail(MethodView):
    @blp.doc(tags=["Trading"])
    @blp.arguments(ActionUpdateSchema)
    @blp.response(200, MessageSchema)
    def put(self, data, action_id):
        """
        Update an action (approve/reject/update units).
        
        Parameters:
            action_id: Path param - Action ID
            data: ActionUpdateSchema with status, units, execution_price
            
        Returns:
            Message confirming update
        """
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
        abort(400, message=f"Failed to update action {action_id}")

