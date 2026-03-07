"""
Backtest Routes

API endpoints for backtesting operations.
"""
from datetime import datetime
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from config import setup_logger
from schemas import BacktestInputSchema
from services import BacktestingService
from repositories import BacktestHistoryRepository


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
        Run backtesting strategy.

        Returns:
            dict: Rich backtest results including summary, trades, equity curve, and full report text.
        """
        try:
            start_date = datetime.strptime(str(data['start_date']), '%Y-%m-%d').date()
            end_date = datetime.strptime(str(data['end_date']), '%Y-%m-%d').date()
            config_name = data.get('config_name', 'momentum_config')
            check_daily_sl = data.get('check_daily_sl', True)
            mid_week_buy = data.get('mid_week_buy', True)
            run_label = data.get('run_label')
            enable_pyramiding = data.get('enable_pyramiding', False)

            results, summary, risk_data, report_path = BacktestingService().run_backtest(
                start_date, end_date, config_name,
                check_daily_sl, mid_week_buy,
                run_label=run_label,
                enable_pyramiding=enable_pyramiding
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

            # equity_curve already built as [{date, value}] in service
            equity_curve = risk_data.get('equity_curve', [])

            return {
                "message": f"Backtest completed. Final: {summary.get('final_value', 0):.2f}",
                "summary": summary,
                "trades": risk_data.get('trades', []),
                "equity_curve": equity_curve,
                "report_text": report_text,
                "report_path": report_path
            }
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            abort(400, message=str(e))
        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            abort(500, message=f"Backtest failed: {str(e)}")


@blp.route("/history")
class BacktestHistory(MethodView):
    @blp.doc(tags=["Backtest"])
    def get(self):
        """List all saved backtest runs (metadata only)."""
        try:
            repo = BacktestHistoryRepository()
            runs = repo.list_runs()
            return [r.to_dict() for r in runs]
        except Exception as e:
            logger.error(f"Failed to list backtest history: {e}")
            abort(500, message=str(e))


@blp.route("/history/<int:run_id>")
class BacktestHistoryDetail(MethodView):
    @blp.doc(tags=["Backtest"])
    def get(self, run_id):
        """Get full backtest run data (metadata + files)."""
        try:
            repo = BacktestHistoryRepository()
            result = repo.get_run(run_id)
            if not result:
                abort(404, message=f"Backtest run {run_id} not found")
            return result
        except Exception as e:
            logger.error(f"Failed to get backtest run {run_id}: {e}")
            abort(500, message=str(e))

    @blp.doc(tags=["Backtest"])
    def delete(self, run_id):
        """Delete a backtest run and its data files."""
        try:
            repo = BacktestHistoryRepository()
            deleted = repo.delete_run(run_id)
            if not deleted:
                abort(404, message=f"Backtest run {run_id} not found")
            return {"message": f"Backtest run {run_id} deleted"}
        except Exception as e:
            logger.error(f"Failed to delete backtest run {run_id}: {e}")
            abort(500, message=str(e))
