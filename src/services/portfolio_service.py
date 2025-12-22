from datetime import date

from utils import calculate_initial_stop_loss
from repositories import (ConfigRepository, PortfolioRepository,
                          MarketDataRepository, IndicatorsRepository)

config_repo = ConfigRepository()
portfolio_repo = PortfolioRepository()
marketdata_repo = MarketDataRepository()
indicators_repo = IndicatorsRepository()


class PortfolioService:
    """Service for portfolio management and action generation"""
    
    def __init__(self):
        """
        Initialize with risk configuration.
        """
        self.config = config_repo.get_config()

    def generate_portfolio_summary(self):
        invested = portfolio_repo.get_invested()


        total_investment = 0.0
        current_value = 0.0

        for i in invested:
            investment_amount = i.buy_price * i.num_shares
            total_investment += investment_amount

            latest_data = marketdata_repo.get_latest_date_by_symbol(i.symbol)
            price = latest_data.close if latest_data else i.buy_price
            current_value += price * i.num_shares

        capital_left = self.config.current_capital if self.config else 0.0
        absolute_return = (current_value + capital_left) - (self.config.initial_capital if self.config else 0)

        return {
            "total_investment": round(total_investment, 2),
            "total_stocks": len(invested),
            "capital_left": round(capital_left, 2),
            "current_value": round(current_value, 2),
            "absolute_return": round(absolute_return, 2)
        }

    def add_new_stock(self, invest_data):
        symbol = invest_data['tradingsymbol']
        buy_price = invest_data['buy_price']
        num_shares = invest_data['num_shares']

        # Check if already invested
        existing = portfolio_repo.get_invested_by_symbol(symbol)
        atr = indicators_repo.get_indicator_by_tradingsymbol("atrr_14", symbol)
        stop_multiplier = self.config.stop_loss_multiplier if self.config else 2.0
        initial_stop = calculate_initial_stop_loss(buy_price, atr or (buy_price * 0.03), stop_multiplier)

        if existing:
            total_shares = num_shares + existing.num_shares
            buy_price =(buy_price * num_shares + existing.num_shares * existing.buy_price) / total_shares
            num_shares = total_shares

        invest_data = {
            "tradingsymbol": symbol,
            "buy_price": buy_price,
            "num_shares": num_shares,
            "buy_date": date.today(),
            "atr_at_entry": atr,
            "initial_stop_loss": round(initial_stop, 2),
            "current_stop_loss": round(initial_stop, 2),
            "include_in_strategy": invest_data.get('include_in_strategy', True)
        }
        invested = portfolio_repo.buy_stock(invest_data)
        return invested

