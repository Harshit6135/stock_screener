"""
Actions Service

Handles investment action generation, approval, and processing.
Renames from strategy_service.py - all methods are action-related.
"""
from datetime import timedelta, date
from decimal import Decimal
from typing import Dict, List, Optional, Union
import pandas as pd

from repositories import (RankingRepository, IndicatorsRepository, MarketDataRepository, 
                          InvestmentRepository, ConfigRepository, ActionsRepository)
from config import setup_logger
from utils.transaction_costs_utils import calculate_round_trip_cost
from utils.tax_utils import calculate_capital_gains_tax
from utils.sizing_utils import calculate_position_size
from utils.stoploss_utils import calculate_initial_stop_loss, calculate_effective_stop
from config.strategies_config import PositionSizingConfig
from services.trading_engine import TradingEngine, HoldingSnapshot, CandidateInfo

logger = setup_logger(name="ActionsService")

ranking = RankingRepository()
indicators = IndicatorsRepository()
marketdata = MarketDataRepository()
investment = InvestmentRepository()
config = ConfigRepository()
actions_repo = ActionsRepository()


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
        
        Delegates core decision logic to TradingEngine.generate_decisions(),
        which implements the shared SELL → BUY → SWAP algorithm.
        
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

        pending_actions = actions_repo.check_other_pending_actions(action_date)
        if pending_actions:
            return 'Actions pending from another date, please take action before proceeding'

        top_n = ranking.get_top_n_by_date(self.config.max_positions, action_date)
        current_holdings = investment.get_holdings()
        new_actions = []

        if not current_holdings:
            # Route through TradingEngine for consistency with backtesting
            candidates = [
                CandidateInfo(symbol=item.tradingsymbol, score=item.composite_score)
                for item in top_n
            ]
            prices = {}
            for item in top_n:
                md = marketdata.get_marketdata_by_trading_symbol(item.tradingsymbol, action_date)
                if md:
                    prices[item.tradingsymbol] = float(md.close)
            decisions = TradingEngine.generate_decisions(
                holdings=[],
                candidates=candidates,
                prices=prices,
                max_positions=self.config.max_positions,
                swap_buffer=1 + self.config.buffer_percent,
                exit_threshold=self.config.exit_threshold,
            )
            for d in decisions:
                if d.action_type == 'BUY':
                    action = self.buy_action(d.symbol, action_date, d.reason)
                    new_actions.append(action)
        else:
            # Build normalized inputs for TradingEngine
            holdings_snap = []
            prices = {}
            for h in current_holdings:
                # Fetch weekly low for stop-loss check
                low = self.fetch_low(h.symbol, action_date)
                prices[h.symbol] = low

                # Fetch current score
                rank_data = ranking.get_rankings_by_date_and_symbol(action_date, h.symbol)
                score = rank_data.composite_score if rank_data else 0

                holdings_snap.append(HoldingSnapshot(
                    symbol=h.symbol,
                    units=h.units,
                    stop_loss=float(h.current_sl),
                    score=score,
                ))

            candidates = [
                CandidateInfo(symbol=item.tradingsymbol, score=item.composite_score)
                for item in top_n
            ]

            # Use config-driven swap buffer and exit threshold
            swap_buffer = 1 + self.config.buffer_percent
            exit_threshold = self.config.exit_threshold

            decisions = TradingEngine.generate_decisions(
                holdings=holdings_snap,
                candidates=candidates,
                prices=prices,
                max_positions=self.config.max_positions,
                swap_buffer=swap_buffer,
                exit_threshold=exit_threshold,
            )

            # Convert decisions to action dicts
            for d in decisions:
                if d.action_type == 'SELL':
                    action = self.sell_action(d.symbol, action_date, d.units, d.reason)
                    new_actions.append(action)
                elif d.action_type == 'BUY':
                    action = self.buy_action(d.symbol, action_date, d.reason)
                    new_actions.append(action)
                elif d.action_type == 'SWAP':
                    # Sell incumbent
                    sell_act = self.sell_action(d.symbol, action_date, d.swap_sell_units, d.reason)
                    new_actions.append(sell_act)
                    # Buy challenger
                    buy_act = self.buy_action(d.swap_for, action_date, d.reason)
                    new_actions.append(buy_act)

        actions_repo.bulk_insert_actions(new_actions)
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
            
        actions_list = actions_repo.get_actions(action_date)
        for item in actions_list:
            execution_price = marketdata.get_marketdata_next_day(item.symbol, action_date).open

            action_data = {
                'action_id' : item.action_id,
                'status' : 'Approved',
                'execution_price' : execution_price
            }

            # Populate sell_cost and tax for SELL actions
            if item.type == 'sell':
                costs = calculate_round_trip_cost(float(item.units * execution_price))
                action_data['sell_cost'] = costs.get('sell_costs', 0)
                action_data['tax'] = 0  # Tax calculated at processing time

            actions_repo.update_action(action_data)
        return len(actions_list)

    def process_actions(self, action_date: date) -> Optional[List[Dict]]:
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
        actions_list = actions_repo.get_actions(action_date)

        if not holdings:
            holdings_date = date(2000,1,1)
        else:
            holdings_date = holdings[0].action_date
        if holdings_date >= action_date:
            logger.warning(f'Holdings {holdings_date} have data beyond the actions {action_date}')
            return None

        buy_symbols = []
        sell_symbols = []
        for items in actions_list:
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

    def get_summary(self, week_holdings, sold):
        prev_summary = investment.get_summary()
        starting_capital = prev_summary.remaining_capital if prev_summary else self.config.initial_capital
        starting_capital = Decimal(starting_capital)

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


    def buy_action(self, symbol: str, action_date: date, reason: str) -> Dict:
        """
        Generate a BUY action with position sizing.
        
        Uses shared sizing_utils.calculate_position_size for consistent
        sizing across live and backtesting.
        
        Parameters:
            symbol (str): Trading symbol
            action_date (date): Action date
            reason (str): Action reason (e.g., 'top 10 buys')
        
        Returns:
            Dict: BUY action with units, risk, ATR, capital needed
        
        Raises:
            ValueError: If symbol is empty or ATR unavailable
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

        summary = investment.get_summary()
        if not summary:
            portfolio_value = self.config.initial_capital
        else:
            portfolio_value = float(summary.portfolio_value) + float(summary.remaining_capital)

        # Use shared position sizing util
        sizing = calculate_position_size(
            atr=atr,
            current_price=float(closing_price),
            portfolio_value=portfolio_value
        )
        
        units = sizing['shares']
        capital_needed = units * closing_price
        risk_per_unit = sizing.get('stop_distance', atr * self.config.sl_multiplier)

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
        action_data = actions_repo.get_action_by_symbol(symbol)
        sold_value = action_data.units * action_data.execution_price
        return sold_value


    def buy_holding(self, symbol: str) -> Dict:
        """
        Create holding record from a BUY action.
        
        Uses shared calculate_initial_stop_loss for consistency with backtesting.
        
        Parameters:
            symbol (str): Trading symbol
        
        Returns:
            Dict: Holding data with entry price, units, stop-loss
        """
        action_data = actions_repo.get_action_by_symbol(symbol)
        action_date = action_data.action_date
        atr = round(indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, action_date), 2)
        entry_price = float(action_data.execution_price)
        
        # Use shared stop-loss calculation (same as backtesting)
        initial_stop = calculate_initial_stop_loss(
            buy_price=entry_price,
            atr=atr,
            stop_multiplier=self.config.sl_multiplier
        )
        
        holding_data = {
            'symbol': symbol,
            'date': action_date,
            'entry_date': action_date,
            'entry_price': action_data.execution_price,
            'units': action_data.units,
            'atr': atr,
            'score': round(ranking.get_rankings_by_date_and_symbol(action_date, symbol).composite_score, 2),
            'entry_sl': round(initial_stop, 2),
            'current_price': action_data.execution_price,
            'current_sl': round(initial_stop, 2)
        }
        return holding_data


    def update_holding(self, symbol: str, action_date: date) -> Dict:
        """
        Update an existing holding with current prices.
        
        Uses shared calculate_effective_stop for consistency with backtesting.
        Uses weekly low price for stop-loss trigger check.
        
        Parameters:
            symbol (str): Trading symbol
            action_date (date): Current action date
        
        Returns:
            Dict: Updated holding data with new price/stop-loss
        """
        holding = investment.get_holdings_by_symbol(symbol)
        atr = round(indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, action_date), 2)
        current_price = marketdata.get_marketdata_by_trading_symbol(symbol, action_date).close
        
        # Use shared stop-loss calculation (same as backtesting)
        stops = calculate_effective_stop(
            buy_price=float(holding.entry_price),
            current_price=float(current_price),
            current_atr=atr,
            initial_stop=float(holding.entry_sl),
            stop_multiplier=self.config.sl_multiplier,
            sl_step_percent=PositionSizingConfig().sl_step_percent,
            previous_stop=float(holding.current_sl) if holding.current_sl else float(holding.entry_sl)
        )
        
        holding_data = {
            'symbol': symbol,
            'date': action_date,
            'entry_date': holding.entry_date,
            'entry_price': holding.entry_price,
            'units': holding.units,
            'atr': atr,
            'score': round(ranking.get_rankings_by_date_and_symbol(action_date, symbol).composite_score, 2),
            'entry_sl': holding.entry_sl,
            'current_price': current_price,
            'current_sl': stops['effective_stop']
        }
        return holding_data
