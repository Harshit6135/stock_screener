"""
Actions Routes

API endpoints for trading actions (BUY/SELL/SWAP).
"""
from datetime import datetime
from flask import request
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from config import setup_logger
from schemas import (
    MessageSchema, ActionDateSchema, ActionQuerySchema,
    ActionSchema, ActionUpdateSchema
)
from repositories import ActionsRepository
from services import ActionsService


logger = setup_logger(name="ActionsRoutes")
actions_repo = ActionsRepository()

blp = Blueprint(
    "Actions",
    __name__,
    url_prefix="/api/v1/actions",
    description="Trading Actions Operations"
)


@blp.route("/generate")
class GenerateActions(MethodView):
    @blp.doc(tags=["Actions"])
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, MessageSchema)
    def post(self, args) -> dict:
        """
        Generate trading actions for current week.
        
        Parameters:
            config_name: Query param - Strategy name (default: momentum_config)
        
        Returns:
            dict: Message with generated actions
        
        Raises:
            HTTPException: 400 for validation errors, 500 for failures
        """
        try:
            config_name = args.get('config_name', 'momentum_config')
            actions = ActionsService(config_name)
            action_date = args.get('date', datetime.now().date())
            new_actions = actions.generate_actions(action_date)
            return {"message": f"Generated {len(new_actions)} actions"}
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Failed to generate actions: {e}")
            abort(500, message=f"Action generation failed: {str(e)}")


@blp.route("/dates")
class ActionDates(MethodView):
    @blp.doc(tags=["Actions"])
    @blp.response(200, ActionDateSchema)
    def get(self):
        """Get all distinct action dates"""
        dates = actions_repo.get_action_dates()
        return {"dates": dates}


@blp.route("/")
class ActionsList(MethodView):
    @blp.doc(tags=["Actions"])
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
        actions = actions_repo.get_actions(working_date)
        return [a.to_dict() for a in actions]


@blp.route("/<action_id>")
class ActionDetail(MethodView):
    @blp.doc(tags=["Actions"])
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

        result = actions_repo.update_action(action_data)

        if result:
            return {"message": f"Action {action_id} updated successfully"}
        abort(400, message=f"Failed to update action {action_id}")


@blp.route("/approve")
class ApproveActions(MethodView):
    @blp.doc(tags=["Actions"])
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, MessageSchema)
    def post(self, args):
        """
        Approve all pending actions for a given date.
        
        Sets execution_price to next-day open and calculates sell costs.
        
        Parameters:
            date: Query param - Action date (YYYY-MM-DD)
            
        Returns:
            Message with count of approved actions
        """
        try:
            working_date = args.get('date')
            if not working_date:
                abort(400, message="date query parameter is required")
            count = ActionsService.approve_all_actions(working_date)
            return {"message": f"Approved {count} actions"}
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Failed to approve actions: {e}")
            abort(500, message=f"Approval failed: {str(e)}")


@blp.route("/process")
class ProcessActions(MethodView):
    @blp.doc(tags=["Actions"])
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, MessageSchema)
    def post(self, args):
        """
        Process approved actions and update holdings.
        
        Creates/updates holding records from approved buy/sell actions.
        
        Parameters:
            date: Query param - Action date (YYYY-MM-DD)
            config_name: Query param - Strategy name (default: momentum_config)
            
        Returns:
            Message with processing result
        """
        try:
            working_date = args.get('date')
            if not working_date:
                abort(400, message="date query parameter is required")
            config_name = args.get('config_name', 'momentum_config')
            service = ActionsService(config_name)
            holdings = service.process_actions(working_date)
            if holdings is None:
                abort(400, message="Processing failed - check pending actions or date conflicts")
            return {"message": f"Processed actions, {len(holdings)} holdings updated"}
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Failed to process actions: {e}")
            abort(500, message=f"Processing failed: {str(e)}")

