"""
Actions Routes

API endpoints for trading actions (BUY/SELL/SWAP).
"""

from datetime import datetime

from flask.views import MethodView
from flask_smorest import Blueprint, abort

from config import setup_logger
from repositories import ActionsRepository
from schemas import (
    ActionDateSchema,
    ActionQuerySchema,
    ActionSchema,
    ActionUpdateSchema,
    MessageSchema,
)
from services.action_generator import ActionGenerator
from services.action_lifecycle import ActionLifecycle
from services.action_processor import ActionProcessor


logger = setup_logger(name="ActionsRoutes")
actions_repo = ActionsRepository()
blp = Blueprint(
    "Actions", __name__, url_prefix="/api/v1/actions", description="Trading Actions Operations"
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
            config_name = args.get("config_name", "momentum_config")
            generator = ActionGenerator(config_name)
            action_date = args.get("date")
            if action_date is None:
                action_date = datetime.now().date()
            enable_pyramiding = args.get("enable_pyramiding", False)
            check_daily_sl = args.get("check_daily_sl", False)
            mid_week_buy = args.get("mid_week_buy", False)
            new_actions = generator.generate_actions(
                action_date,
                enable_pyramiding=enable_pyramiding,
                check_daily_sl=check_daily_sl,
                mid_week_buy=mid_week_buy,
            )
            return {"message": f"Generated {len(new_actions)} actions"}
        except ValueError as e:
            logger.warning(f"generate_actions blocked: {e}")
            abort(409, message=str(e))
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
        working_date = args.get("date")
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
            "action_id": action_id,
            "status": data["status"],
        }

        if "units" in data:
            action_data["units"] = data["units"]

        if "execution_price" in data:
            action_data["execution_price"] = data["execution_price"]

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
            working_date = args.get("date")
            if not working_date:
                abort(400, message="date query parameter is required")

            config_name = args.get("config_name", "momentum_config")
            lifecycle = ActionLifecycle(config_name)
            count = lifecycle.approve_all_actions(working_date)
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
            working_date = args.get("date")
            if not working_date:
                abort(400, message="date query parameter is required")
            config_name = args.get("config_name", "momentum_config")
            processor = ActionProcessor(config_name)
            holdings = processor.process_actions(working_date)
            if holdings is None:
                abort(400, message="Processing failed - check pending actions or date conflicts")
            return {"message": f"Processed actions, {len(holdings)} holdings updated"}
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Failed to process actions: {e}")
            abort(500, message=f"Processing failed: {str(e)}")


@blp.route("/reject-all")
class RejectAllPending(MethodView):
    @blp.doc(tags=["Actions"])
    @blp.arguments(ActionQuerySchema, location="query")
    @blp.response(200, MessageSchema)
    def post(self, args):
        """
        Reject all pending actions.

        Marks every action with status='Pending' as 'Rejected'.
        Useful for clearing unfilled buys at end of week or resetting
        after a bad action generation run.

        Parameters:
            config_name: Query param - Strategy name (default: momentum_config)

        Returns:
            Message with count of rejected actions
        """
        try:
            config_name = args.get("config_name", "momentum_config")
            lifecycle = ActionLifecycle(config_name)
            count = lifecycle.reject_pending_actions()
            return {"message": f"Rejected {count} pending action(s)"}
        except Exception as e:
            logger.error(f"Failed to reject pending actions: {e}")
            abort(500, message=f"Reject all failed: {str(e)}")
