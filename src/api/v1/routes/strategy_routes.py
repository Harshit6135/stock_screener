from datetime import datetime
from flask.views import MethodView
from flask_smorest import Blueprint

from schemas import MessageSchema, BacktestInputSchema
from repositories import ConfigRepository
from services import Strategy


blp = Blueprint(
    "strategy",
    __name__,
    url_prefix="/api/v1/strategy",
    description="Strategy Operations"
)


@blp.route("/config")
class StrategyConfig(MethodView):
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
class StrategyBackTest(MethodView):
    @blp.arguments(BacktestInputSchema)
    @blp.response(200, MessageSchema)
    def post(self, data):
        """Run backtesting strategy"""
        strategy = Strategy()
        start_date = datetime.strptime(str(data['start_date']), '%Y-%m-%d').date()
        end_date = datetime.strptime(str(data['end_date']), '%Y-%m-%d').date()
        #print(start_date, end_date)
        strategy.backtesting(start_date, end_date)

        return {"message": "Strategy backtesting completed successfully"}


# @blp.route("/actions")
# class StrategyActions(MethodView):
#     @blp.response(200, MessageSchema)
#     def post(self):
#         """Get strategy actions"""
#         strategy_actions('strategy_one')
#         return {"message": "Strategy actions completed successfully"}

# @blp.route("/update_actions")
# class UpdateActions(MethodView):
#     @blp.response(201, MessageSchema)
#     def post(self):
#         """Update strategy actions"""