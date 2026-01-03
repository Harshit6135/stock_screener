from datetime import date
from strategies.strategy1.strategy import Strategy as StrategyOne
from repositories import ConfigRepository

config = ConfigRepository()

start_date = date(2025, 1, 3)
end_date = date(2025, 12, 28)

strategies = {
    'strategy_one' : 'momentum_strategy_one'
}

def strategy_backtesting(strategy_name):
    if strategies[strategy_name] == 'momentum_strategy_one':
        strategy = StrategyOne()
        # TODO - Find way to make this automated

    strategy_config_user = config.get_config(strategies[strategy_name])
    strategy.backtesting(start_date, end_date, strategy_config_user)

    return None