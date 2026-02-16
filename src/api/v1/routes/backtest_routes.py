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
    def post(self, data):
        """
        Run backtesting strategy using new backtesting module.
        
        Results are written to backtest.db for analysis.
        
        Parameters:
            data: BacktestInputSchema with start_date and end_date
            
        Returns:
            dict: Rich backtest results including summary, trades, equity curve, and full report text.
        """
        try:
            start_date = datetime.strptime(str(data['start_date']), '%Y-%m-%d').date()
            end_date = datetime.strptime(str(data['end_date']), '%Y-%m-%d').date()
            config_name = data.get('config_name', 'momentum_config')
            check_daily_sl = data.get('check_daily_sl', True)
            mid_week_buy = data.get('mid_week_buy', True)
            
            # Now returns 4 values
            results, summary, risk_data, report_path = run_backtest(
                start_date, end_date, config_name,
                check_daily_sl, mid_week_buy
            )
            
            # Read report content
            report_text = ""
            if report_path:
                try:
                    with open(report_path, 'r', encoding='utf-8') as f:
                        report_text = f.read()
                except Exception as e:
                    logger.error(f"Failed to read report file {report_path}: {e}")
                    report_text = f"Error reading report file: {e}"
            
            return {
                "message": f"Backtest completed. Final: {summary.get('final_value', 0):.2f}",
                "summary": summary,
                "trades": risk_data.get('trades', []),
                "equity_curve": risk_data.get('portfolio_values', []),
                "report_text": report_text,
                "report_path": report_path
            }
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            # Log full traceback for debugging
            import traceback
            logger.error(traceback.format_exc())
            abort(500, message=f"Backtest failed: {str(e)}")
