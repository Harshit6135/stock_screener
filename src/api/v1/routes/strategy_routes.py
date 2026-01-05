from flask.views import MethodView
from flask_smorest import Blueprint

from schemas import MessageSchema
from repositories import ConfigRepository
from strategies.main import strategy_backtesting


blp = Blueprint("strategy", __name__, url_prefix="/api/v1/strategy", description="Strategy Operations")


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


@blp.route("/run")
class StrategyRun(MethodView):
    @blp.response(200, MessageSchema)
    def post(self):
        """Run backtesting strategy"""
        strategy_backtesting('strategy_one')
        return {"message": "Strategy backtesting completed successfully"}