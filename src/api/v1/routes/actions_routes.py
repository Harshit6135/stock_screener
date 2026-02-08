"""
Actions Routes

API endpoints for trading actions (BUY/SELL/SWAP).
Uses dedicated actions module (models/actions.py, schemas/actions.py, repositories/actions_repository.py).
"""
from datetime import datetime
from flask.views import MethodView
from flask_smorest import Blueprint

from schemas import MessageSchema, BacktestInputSchema
from repositories import ConfigRepository, ActionsRepository
from services import ActionsService


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


@blp.route("/backtesting")
class ActionsBackTest(MethodView):
    @blp.doc(tags=["Trading"])
    @blp.arguments(BacktestInputSchema)
    @blp.response(200, MessageSchema)
    def post(self, data):
        """Run backtesting strategy using new backtesting module.
        
        Results are written to backtest.db for analysis.
        """
        from src.backtesting import run_backtest
        
        start_date = datetime.strptime(str(data['start_date']), '%Y-%m-%d').date()
        end_date = datetime.strptime(str(data['end_date']), '%Y-%m-%d').date()
        
        results, summary = run_backtest(start_date, end_date)
        
        return {
            "message": f"Backtest completed. Final value: {summary.get('final_value', 0)}, "
                      f"Total return: {summary.get('total_return', 0):.2f}%"
        }


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
        from flask_smorest import abort
        from config import setup_logger
        logger = setup_logger(name="ActionsRoutes")
        
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


@blp.route("/update")
class UpdateActions(MethodView):
    @blp.doc(tags=["Trading"])
    @blp.response(201, MessageSchema)
    def post(self):
        """Update trading actions"""
        pass
