"""
Actions Service

Handles investment action generation, approval, and processing.
Renamed from strategy_service.py - all methods are action-related.
"""
from datetime import timedelta, date
from decimal import Decimal
import math
from typing import Dict, List, Optional, Union
import pandas as pd

from repositories import (RankingRepository, IndicatorsRepository, MarketDataRepository, 
                          InvestmentRepository, ConfigRepository, ActionsRepository)
from config import setup_logger

logger = setup_logger(name="ActionsService")

ranking = RankingRepository()
indicators = IndicatorsRepository()
marketdata = MarketDataRepository()
investment = InvestmentRepository()
config = ConfigRepository()
actions = ActionsRepository()


class ActionsService:
    """
    Investment action service for SELL/SWAP/BUY decisions.
    
    Renamed from Strategy class to better reflect its purpose.
    """

    def __init__(self, strategy_name: str):
        self.config = config.get_config(strategy_name)

    def generate_actions(self, action_date: date) -> Union[str, List[Dict]]:
        """
        Generate trading actions (BUY/SELL/SWAP) for a given date.
        
        Parameters:
            action_date (date): Date to generate actions for
        
        Returns:
            Union[str, List[Dict]]: Error message if actions pending, 
                                    otherwise list of action dictionaries
        
        Raises:
            ValueError: If action_date is None
        """
        if action_date is None:
            raise ValueError("action_date cannot be None")

        pending_actions = investment.check_other_pending_actions(action_date)
        if pending_actions:
            return 'Actions pending from another date, please take action before proceeding'

        top_n = ranking.get_top_n_by_date(self.config.max_positions, action_date)
        top_n_symbols = [item.tradingsymbol for item in top_n]
        current_holdings = investment.get_holdings()
        new_actions = []
        if not current_holdings:
            for item in top_n:
                action = self.buy_action(item.tradingsymbol, action_date, 'top 10 buys')
                new_actions.append(action)
        else:
            i = 0
            while i < len(current_holdings):
                low = self.fetch_low(current_holdings[i].symbol, action_date)
                if current_holdings[i].current_sl >= low:
                    action = self.sell_action(current_holdings[i].symbol, action_date, current_holdings[i].units, 'stoploss hit')
                    new_actions.append(action)
                    current_holdings.pop(i)
                elif current_holdings[i].symbol in top_n_symbols:
                    current_holdings.pop(i)
                else:
                    i += 1

            remaining_buys = self.config.max_positions - len(current_holdings)
            i = 0
            while i < remaining_buys:
                action = self.buy_action(top_n[i].tradingsymbol, action_date, 'top 10 buys')
                new_actions.append(action)
                i += 1

            i = 0
            while i < len(top_n):
                buy_flag = False
                j = 0
                while j < len(current_holdings):
                    current_score = ranking.get_rankings_by_date_and_symbol(action_date, current_holdings[j].symbol).composite_score

                    if top_n[i].composite_score > (1 + (self.config.buffer_percent/100)) * current_score:
                        action = self.sell_action(current_holdings[j].symbol, action_date, current_holdings[j].units, f'swap current score {current_score}')
                        new_actions.append(action)
                        current_holdings.pop(j)

                        action = self.buy_action(top_n[i].tradingsymbol, action_date, f'swap current score {top_n[i].composite_score}')
                        new_actions.append(action)
                        buy_flag = True
                        break
                    else:
                        j += 1
                if buy_flag:
                    top_n.pop(i)
                else:
                    i += 1
        actions.bulk_insert_actions(new_actions)
        return new_actions

    @staticmethod
    def approve_all_actions(action_date: date) -> int:
        """
        Approve all pending actions for a given date.
        
        Parameters:
            action_date (date): Date of actions to approve
        
        Returns:
            int: Number of actions approved
        
        Raises:
            ValueError: If action_date is None
        """
        if action_date is None:
            raise ValueError("action_date cannot be None")
            
        actions = actions.get_actions(action_date)
        for item in actions:
            execution_price = marketdata.get_marketdata_next_day(item.symbol, action_date).open

            action_data = {
                'action_id' : item.action_id,
                'status' : 'Approved',
                'execution_price' : execution_price
            }

            actions.update_action(action_data)
        return len(actions)

    @staticmethod
    def process_actions(action_date: date) -> Optional[List[Dict]]:
        """
        Process approved actions and update holdings.
        
        Parameters:
            action_date (date): Date of actions to process
        
        Returns:
            Optional[List[Dict]]: List of updated holdings, or None if error
        
        Raises:
            ValueError: If action_date is None
        """
        holdings = investment.get_holdings(action_date)
        if holdings:
            investment.delete_holdings(action_date)
            investment.delete_summary(action_date)

        holdings = investment.get_holdings()
        actions = actions.get_actions(action_date)

        if not holdings:
            holdings_date = date(2000,1,1)
        else:
            holdings_date = holdings[0].action_date
        if holdings_date >= action_date:
            logger.warning(f'Holdings {holdings_date} have data beyond the actions {action_date}')
            return None

        buy_symbols = []
        sell_symbols = []
        for items in actions:
            if items.status == 'Pending':
                logger.warning(f'Pending Actions for {items.symbol} on {items.action_date}. Please approve/reject before proceeding')
                return None
            elif items.status == 'Approved':
                if items.type == 'sell':
                    sell_symbols.append(items.symbol)
                elif items.type == 'buy':
                    buy_symbols.append(items.symbol)
        sold = 0
        i = 0
        while i < len(holdings):
            if holdings[i].symbol in sell_symbols:
                sold += self.sell_holding(holdings[i].symbol)
                holdings.pop(i)
            else:
                i += 1
        week_holdings = []
        for item in buy_symbols:
            week_holdings.append(self.buy_holding(item))
        for item in holdings:
            week_holdings.append(self.update_holding(item.symbol, action_date))
        investment.bulk_insert_holdings(week_holdings)
        summary = self.get_summary(week_holdings, sold)
        investment.insert_summary(summary)
        return  week_holdings

    @staticmethod
    def get_summary(week_holdings, sold):
        prev_summary = investment.get_summary()
        starting_capital = prev_summary.remaining_capital if prev_summary else self.config.initial_capital
        starting_capital = Decimal(starting_capital)
        day0_cap = self.config.initial_capital
        # Convert list of holdings to DataFrame for fast/vectorized calculations
        df = pd.DataFrame(week_holdings)
        # Bought: sum(entry_price * units) where entry_date == action_date
        bought_mask = df['entry_date'] == df['date']
        bought = (df.loc[bought_mask, 'entry_price'] * df.loc[bought_mask, 'units']).sum()
        # Capital risk: sum(units * (entry_price - current_sl))
        capital_risk = (df['units'] * (df['entry_price'] - df['current_sl'])).sum()
        # Portfolio value: sum(units * current_price)
        portfolio_value = Decimal((df['units'] * df['current_price']).sum())
        # Portfolio risk: sum(units * (current_price - current_sl))
        portfolio_risk = (df['units'] * (df['current_price'] - df['current_sl'])).sum()
        # Prepare summary with rounded numbers
        summary = {
            'date': week_holdings[0]['action_date'],
            'starting_capital': round(starting_capital, 2),
            'sold': round(sold, 2),
            'bought': round(float(bought), 2),
            'capital_risk': round(float(capital_risk), 2),
            'portfolio_value': round(float(portfolio_value), 2),
            'portfolio_risk': round(float(portfolio_risk), 2),
            'gain' : round(portfolio_value - starting_capital,2),
            'gain_percentage' : round((portfolio_value - starting_capital) / starting_capital * 100,2)
        }
        return summary


    @staticmethod
    def fetch_low(symbol: str, action_date: date) -> float:
        """
        Fetch the lowest price for a symbol over the past week.
        
        Parameters:
            symbol (str): Trading symbol
            action_date (date): Reference date
        
        Returns:
            float: Lowest price in the 7-day period
        
        Raises:
            ValueError: If symbol is empty
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")
            
        filter_data = {
            'tradingsymbol' : symbol,
            'start_date' : action_date - timedelta(days=6),
            'end_date' : action_date
        }
        weekly_data = marketdata.query(filter_data)
        low = 0
        for item in weekly_data:
            if low==0:
                low = item.low
            elif item.low < low:
                low = item.low
        return low


    @staticmethod
    def buy_action(symbol: str, action_date: date, reason: str) -> Dict:
        """
        Generate a BUY action with position sizing.
        
        Parameters:
            symbol (str): Trading symbol
            action_date (date): Action date
            reason (str): Action reason (e.g., 'top 10 buys')
        
        Returns:
            Dict: BUY action with units, risk, ATR, capital needed
        
        Raises:
            ValueError: If symbol is empty or ATR unavailable
        
        Example:
            >>> action = self.buy_action("RELIANCE", date(2024,1,15), "top 10")
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")
        if not reason:
            reason = "Unknown reason"
            
        atr = indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, action_date)
        if atr is None:
            raise ValueError(f"ATR not available for {symbol} on {action_date}")
        atr = round(atr, 2)
        
        closing_price = marketdata.get_marketdata_by_trading_symbol(symbol, action_date).close
        risk_per_unit = self.config.sl_multiplier*atr

        summary = investment.get_summary()

        if not summary:
            capital = self.config.initial_capital
        else:
            capital = summary.portfolio_value + summary.remaining_capital

        max_risk = Decimal(capital) * Decimal(self.config.risk_threshold / 100)
        units = math.floor(Decimal(max_risk) / Decimal(risk_per_unit))

        capital_needed = units * closing_price

        action = {
            'action_date' : action_date,
            'type' : 'buy',
            'reason' : reason,
            'symbol' : symbol,
            'risk' : risk_per_unit,
            'atr' : atr,
            'units' : units,
            'prev_close' : closing_price,
            'capital' : capital_needed
        }
        return action


    @staticmethod
    def sell_action(symbol: str, action_date: date, units: int, reason: str) -> Dict:
        """
        Generate a SELL action.
        
        Parameters:
            symbol (str): Trading symbol
            action_date (date): Action date
            units (int): Number of units to sell
            reason (str): Sell reason (e.g., 'stoploss', 'swap')
        
        Returns:
            Dict: SELL action details
        
        Raises:
            ValueError: If symbol is empty or units <= 0
        
        Example:
            >>> action = self.sell_action("RELIANCE", date(2024,1,15), 100, "stoploss")
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")
        if units <= 0:
            raise ValueError(f"Units must be positive, got {units}")
        if not reason:
            reason = "Unknown reason"
            
        closing_price = marketdata.get_marketdata_by_trading_symbol(symbol, action_date).close

        capital_available = units * closing_price
        action = {
            'action_date' : action_date,
            'type' : 'sell',
            'reason' : reason,
            'symbol' : symbol,
            'units' : units,
            'prev_close' : closing_price,
            'capital' : capital_available
        }
        return action


    @staticmethod
    def sell_holding(symbol: str) -> float:
        """
        Calculate sold value for a holding.
        
        Parameters:
            symbol (str): Trading symbol
        
        Returns:
            float: Total sold value (units * execution_price)
        """
        action_data = investment.get_action_by_symbol(symbol)
        sold_value = action_data.units * action_data.execution_price
        return sold_value


    @staticmethod
    def buy_holding(symbol: str) -> Dict:
        """
        Create holding record from a BUY action.
        
        Parameters:
            symbol (str): Trading symbol
        
        Returns:
            Dict: Holding data with entry price, units, stop-loss
        """
        action_data = investment.get_action_by_symbol(symbol)
        action_date = action_data.action_date
        atr = round(indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, action_date),2)
        sl_multiplier = Decimal(str(self.config.sl_multiplier))
        atr_decimal = Decimal(str(atr))
        holding_data = {
            'symbol' : symbol,
            'date' : action_date,
            'entry_date' : action_date,
            'entry_price' : action_data.execution_price,
            'units' : action_data.units,
            'atr' : atr,
            'score' : round(ranking.get_rankings_by_date_and_symbol(action_date, symbol).composite_score,2),
            'entry_sl' : action_data.execution_price - (sl_multiplier * atr_decimal),
            'current_price' : action_data.execution_price,
            'current_sl' : Decimal(action_data.execution_price) - (sl_multiplier * atr_decimal)
        }
        return holding_data


    @staticmethod
    def update_holding(symbol: str, action_date: date) -> Dict:
        """
        Update an existing holding with current prices.
        
        Parameters:
            symbol (str): Trading symbol
            action_date (date): Current action date
        
        Returns:
            Dict: Updated holding data with new price/stop-loss
        """
        holding_data = investment.get_holdings_by_symbol(symbol)
        atr = round(indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, action_date),2)
        sl_multiplier = Decimal(str(self.config.sl_multiplier))
        atr_decimal = Decimal(str(atr))
        current_price = marketdata.get_marketdata_by_trading_symbol(symbol, action_date).close
        holding_data = {
            'symbol' : symbol,
            'date' : action_date,
            'entry_date' : holding_data.entry_date,
            'entry_price' : holding_data.entry_price,
            'units' : holding_data.units,
            'atr' : atr,
            'score' : round(ranking.get_rankings_by_date_and_symbol(action_date, symbol).composite_score,2),
            'entry_sl' : holding_data.entry_sl,
            'current_price' : current_price,
            'current_sl' : Decimal(current_price) - (sl_multiplier * atr_decimal)
        }
        return holding_data
