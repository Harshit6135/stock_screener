"""
Backtest Routes

API endpoints for backtesting operations.
"""
from datetime import datetime
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from config import setup_logger
from schemas import MessageSchema, BacktestInputSchema
from backtesting import run_backtest


logger = setup_logger(name="BacktestRoutes")

blp = Blueprint(
    "Backtest",
    __name__,
    url_prefix="/api/v1/backtest",
    description="Backtesting Operations"
)


@blp.route("/run")
class RunBacktest(MethodView):
    @blp.doc(tags=["Backtest"])
    @blp.arguments(BacktestInputSchema)
    @blp.response(200, MessageSchema)
    def post(self, data):
        """
        Run backtesting strategy using new backtesting module.
        
        Results are written to backtest.db for analysis.
        
        Parameters:
            data: BacktestInputSchema with start_date and end_date
            
        Returns:
            dict: Message with backtest results summary
        """
        try:
            start_date = datetime.strptime(str(data['start_date']), '%Y-%m-%d').date()
            end_date = datetime.strptime(str(data['end_date']), '%Y-%m-%d').date()
            config_name = data.get('config_name', 'momentum_config')
            
            results, summary = run_backtest(start_date, end_date, config_name)
            
            return {
                "message": f"Backtest completed. Final value: {summary.get('final_value', 0)}, "
                          f"Total return: {summary.get('total_return', 0):.2f}%"
            }
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            abort(500, message=f"Backtest failed: {str(e)}")
