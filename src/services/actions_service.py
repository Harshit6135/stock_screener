"""
Actions Service

Handles investment action generation, approval, and processing.
"""
import pandas as pd

from decimal import Decimal
from datetime import timedelta, date
from sqlalchemy.orm import Session
from typing import Dict, List, Optional, Union

from repositories import (RankingRepository, IndicatorsRepository, MarketDataRepository, 
                          InvestmentRepository, ConfigRepository, ActionsRepository)

from utils import (calculate_round_trip_cost, calculate_capital_gains_tax, 
                   calculate_position_size, calculate_initial_stop_loss, 
                   calculate_effective_stop, calculate_transaction_costs)
from services import TradingEngine, HoldingSnapshot, CandidateInfo
from config import setup_logger


logger = setup_logger(name="ActionsService")
config = ConfigRepository()
ranking = RankingRepository()
indicators = IndicatorsRepository()
marketdata = MarketDataRepository()
pd.set_option('future.no_silent_downcasting', True)


class ActionsService:
    """
    Investment action service for SELL/SWAP/BUY decisions.
    """
    def __init__(self, config_name: str,  session: Optional[Session] = None, config_info = None):
        if not config_info:
            self.config = config.get_config(config_name)
        else:
            self.config = config_info
        self.actions_repo = ActionsRepository(session)
        self.investment_repo = InvestmentRepository(session)
    
    def buy_action(self, symbol: str, action_date: date, prev_close: float, reason: str,
                   remaining_capital: float = None) -> Dict:
        """
        Generate a BUY action with position sizing.
        
        Uses shared sizing_utils.calculate_position_size for consistent
        sizing across live and backtesting.
        
        Parameters:
            symbol (str): Trading symbol
            action_date (date): Action date
            reason (str): Action reason (e.g., 'top 10 buys')
            remaining_capital (float): Override portfolio value with remaining capital
                                       (used by generate_actions to track across batch)
        
        Returns:
            Dict: BUY action with units, risk, ATR, capital needed
        
        Raises:
            ValueError: If symbol is empty or ATR unavailable
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")
        if not reason:
            reason = "Unknown reason"
            
        ranking_date = action_date - timedelta(days=3)
        atr = indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, ranking_date)
        if atr is None:
            raise ValueError(f"ATR not available for {symbol} on {ranking_date}")
        atr = round(atr, 2)

        # Use shared position sizing util
        sizing = calculate_position_size(
            atr=atr,
            current_price=float(prev_close),
            portfolio_value=remaining_capital,
            config=self.config
        )
        units = sizing['shares']
        if units <= 0:
            logger.warning(f"Skipping BUY {symbol}: insufficient capital (shares={units})")
            return None

        capital_needed = sizing['position_value']
        risk_per_unit = sizing['stop_distance']

        action = {
            'action_date' : action_date,
            'type' : 'buy',
            'reason' : reason,
            'symbol' : symbol,
            'risk' : risk_per_unit,
            'atr' : atr,
            'units' : units,
            'prev_close' : prev_close,
            'capital' : capital_needed
        }
        return action

    @staticmethod
    def sell_action(symbol: str, action_date: date, prev_close: float, units: int, reason: str) -> Dict:
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

        capital_available = units * prev_close
        action = {
            'action_date' : action_date,
            'type' : 'sell',
            'reason' : reason,
            'symbol' : symbol,
            'units' : units,
            'prev_close' : prev_close,
            'capital' : capital_available
        }
        return action

    def generate_actions(self, action_date: date, skip_pending_check: bool = False, check_daily_sl: bool = True) -> Union[str, List[Dict]]:
        """
        Generate trading actions (BUY/SELL/SWAP) for a given date.
        
        Delegates core decision logic to TradingEngine.generate_decisions(),
        which implements the shared SELL → BUY → SWAP algorithm.
        
        Parameters:
            action_date (date): Date to generate actions for
            skip_pending_check (bool): Skip pending actions guard (for backtesting)

        Returns:
            Union[str, List[Dict]]: Error message if actions pending, 
                                    otherwise list of action dictionaries

        Raises:
            ValueError: If action_date is None
        """
        if action_date is None:
            raise ValueError("action_date cannot be None")

        if not skip_pending_check:
            pending_actions = self.actions_repo.check_other_pending_actions(action_date)
            if pending_actions:
                return 'Actions pending from another date, please take action before proceeding'

        ranking_date = action_date - timedelta(days=3)
        top_n = ranking.get_top_n_by_date(self.config.max_positions, ranking_date)
        current_holdings = self.investment_repo.get_holdings()
        new_actions = []
        candidates = [
            CandidateInfo(symbol=item.tradingsymbol, score=item.composite_score)
            for item in top_n
        ]

        swap_buffer = 1 + self.config.buffer_percent
        exit_threshold = self.config.exit_threshold
        holdings_snap = []
        prices = {}

        if not current_holdings:
            for item in top_n:
                md = marketdata.get_marketdata_by_trading_symbol(item.tradingsymbol, ranking_date)
                if md:
                    prices[item.tradingsymbol] = float(md.close)
        else:
            for h in current_holdings:
                low = self.fetch_low(h.symbol, ranking_date)

                # Bug 4 fix: compute fresh trailing stop using Friday data before SL check
                md_h = marketdata.get_marketdata_by_trading_symbol(h.symbol, ranking_date)
                atr_h = indicators.get_indicator_by_tradingsymbol('atrr_14', h.symbol, ranking_date)
                if md_h and atr_h:
                    stops = calculate_effective_stop(
                        buy_price=float(h.entry_price),
                        current_price=float(md_h.close),
                        current_atr=round(float(atr_h), 2),
                        initial_stop=float(h.entry_sl),
                        stop_multiplier=self.config.sl_multiplier,
                        sl_step_percent=self.config.sl_step_percent,
                        previous_stop=float(h.current_sl) if h.current_sl else float(h.entry_sl)
                    )
                    fresh_sl = stops['effective_stop']
                else:
                    fresh_sl = float(h.current_sl)

                # Price logic for SL checks:
                # Daily SL (True): Use Weekly Low to simulate intraday hit -> force price=SL if hit
                # Weekly SL (False): Use Friday Close -> check against SL, use Close as price
                
                if check_daily_sl:
                    # Daily SL: check against weekly low (intraday simulation)
                    price_to_check = low if low > 0 else float(h.current_price)
                    prices[h.symbol] = fresh_sl if price_to_check <= fresh_sl else price_to_check
                else:
                    # Weekly SL: check Friday Close against SL
                    if md_h:
                        prices[h.symbol] = float(md_h.close)
                    elif low > 0:
                         prices[h.symbol] = low
                    else:
                         prices[h.symbol] = float(h.current_price)

                rank_data = ranking.get_rankings_by_date_and_symbol(ranking_date, h.symbol)
                score = rank_data.composite_score if rank_data else 0

                holdings_snap.append(HoldingSnapshot(
                    symbol=h.symbol,
                    units=h.units,
                    stop_loss=fresh_sl,
                    score=score,
                ))

        decisions = TradingEngine.generate_decisions(
            holdings=holdings_snap,
            candidates=candidates,
            prices=prices,
            max_positions=self.config.max_positions,
            swap_buffer=swap_buffer,
            exit_threshold=exit_threshold,
        )

        # Track remaining capital across buys so each successive buy sizes against what's left
        summary = self.investment_repo.get_summary()
        if not summary:
            remaining_capital = self.config.initial_capital
        else:
            remaining_capital = float(summary.remaining_capital)

        for d in decisions:
            md = marketdata.get_marketdata_by_trading_symbol(d.symbol, ranking_date)
            if d.action_type == 'SELL':
                action = self.sell_action(d.symbol, action_date, md.close, d.units, d.reason)
                new_actions.append(action)
                remaining_capital += d.units * float(md.close)  # Freed capital from sell
            elif d.action_type == 'BUY':
                action = self.buy_action(d.symbol, action_date, md.close, d.reason,
                                         remaining_capital=remaining_capital)
                new_actions.append(action)
                if action:
                    remaining_capital -= action['capital']
            elif d.action_type == 'SWAP':
                # Sell incumbent
                sell_act = self.sell_action(d.symbol, action_date, md.close, d.swap_sell_units, d.reason)
                new_actions.append(sell_act)
                remaining_capital += d.swap_sell_units * float(md.close)
                # Buy challenger
                md_swap_for = marketdata.get_marketdata_by_trading_symbol(d.swap_for, ranking_date)
                buy_act = self.buy_action(d.swap_for, action_date, md_swap_for.close, d.reason,
                                          remaining_capital=remaining_capital)
                new_actions.append(buy_act)
                if buy_act:
                    remaining_capital -= buy_act['capital']

        new_actions = [a for a in new_actions if a is not None]
        if new_actions:
            self.actions_repo.delete_actions(new_actions[0]['action_date'])
            self.actions_repo.bulk_insert_actions(new_actions)
        return new_actions

    def approve_all_actions(self, action_date: date) -> int:
        """
        Approve actions for a given date with capital awareness.

        Approves ALL sell actions first (always), then approves buy actions
        only if remaining capital allows. Buys that exceed available capital
        stay as Pending for potential mid-week fill.

        Parameters:
            action_date (date): Date of actions to approve

        Returns:
            int: Number of actions approved

        Raises:
            ValueError: If action_date is None
        """
        if action_date is None:
            raise ValueError("action_date cannot be None")

        actions_list = self.actions_repo.get_actions(action_date)
        approved_count = 0

        # Track remaining capital
        summary = self.investment_repo.get_summary()
        remaining_capital = float(summary.remaining_capital) if summary else float(self.config.initial_capital)

        # Phase 1: Approve ALL sells first (always approved, at Monday open)
        for item in actions_list:
            if item.type == 'sell' and item.status == 'Pending':
                execution_price = item.execution_price or marketdata.get_marketdata_first_day(item.symbol, action_date).open
                costs = calculate_transaction_costs(float(item.units * execution_price), 'sell')
                self.actions_repo.update_action({
                    'action_id': item.action_id,
                    'status': 'Approved',
                    'execution_price': execution_price,
                    'sell_cost': costs.get('sell_costs', 0),
                    'tax': 0
                })
                remaining_capital += float(item.units * execution_price)
                approved_count += 1

        # Phase 2: Approve buys only if capital allows (at Monday open)
        for item in actions_list:
            if item.type == 'buy' and item.status == 'Pending':
                execution_price = item.execution_price or marketdata.get_marketdata_first_day(item.symbol, action_date).open
                cost = float(item.units * execution_price)
                if cost <= remaining_capital:
                    costs = calculate_transaction_costs(cost, 'buy')
                    self.actions_repo.update_action({
                        'action_id': item.action_id,
                        'status': 'Approved',
                        'execution_price': execution_price,
                        'buy_cost': costs.get('buy_costs', 0),
                        'tax': 0
                    })
                    remaining_capital -= cost
                    approved_count += 1
                else:
                    logger.info(f"Pending BUY {item.symbol}: insufficient capital ({cost:.0f} > {remaining_capital:.0f})")

        return approved_count

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
        holdings = self.investment_repo.get_holdings(action_date)
        if holdings:
            self.investment_repo.delete_holdings(action_date)
            self.investment_repo.delete_summary(action_date)

        holdings = self.investment_repo.get_holdings()
        actions_list = self.actions_repo.get_actions(action_date)
        if not holdings:
            holdings_date = date(2000,1,1)
        else:
            holdings_date = holdings[0].date
        if holdings_date >= action_date:
            logger.warning(f'Holdings {holdings_date} have data beyond the actions {action_date}')
            return None

        buy_symbols = {}
        sell_symbols = {}
        for items in actions_list:
            if items.status == 'Approved':
                if items.type == 'sell':
                    sell_symbols[items.symbol] = items
                elif items.type == 'buy':
                    buy_symbols[items.symbol] = items
            # Skip Pending/Rejected actions (Pending buys may fill mid-week)
        sold = 0
        i = 0
        held_symbols = {h.symbol for h in holdings}
        for symbol, action in sell_symbols.items():
            sold += action.units * action.execution_price
            held_symbols.remove(symbol)

        # Skip buys for symbols already held (prevent duplicate inserts)
        for symbol in list(buy_symbols.keys()):
            if symbol in held_symbols:
                logger.warning(
                    f"Skipping BUY {symbol}: already held, "
                    f"keeping existing position"
                )
                del buy_symbols[symbol]

        week_holdings = []
        for symbol, action in buy_symbols.items():
            rank_date = action_date - timedelta(days=3)
            initial_sl = round(action.execution_price - action.risk, 2)
            holding_data = {
                'symbol': symbol,
                'date': action_date,
                'entry_date': action_date,
                'entry_price': action.execution_price,
                'units': action.units,
                'atr': action.atr,
                'score': round(ranking.get_rankings_by_date_and_symbol(rank_date, symbol).composite_score, 2),
                'entry_sl': initial_sl,
                'current_price': action.execution_price,
                'current_sl': initial_sl
            }
            week_holdings.append(holding_data)
        for symbol in held_symbols:
            week_holdings.append(self.update_holding(symbol, action_date))
        self.investment_repo.delete_holdings(action_date)
        self.investment_repo.bulk_insert_holdings(week_holdings)
        summary = self.get_summary(week_holdings, sold)
        self.investment_repo.insert_summary(summary)
        return  week_holdings

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
        holding = self.investment_repo.get_holdings_by_symbol(symbol)
        # Bug 1 fix: use rank_date (Friday) for ATR and price, not action_date (Monday)
        rank_date = action_date - timedelta(days=3)
        atr = round(indicators.get_indicator_by_tradingsymbol('atrr_14', symbol, rank_date), 2)
        current_price = marketdata.get_marketdata_by_trading_symbol(symbol, rank_date).close
        
        # Use shared stop-loss calculation (same as backtesting)
        stops = calculate_effective_stop(
            buy_price=float(holding.entry_price),
            current_price=float(current_price),
            current_atr=atr,
            initial_stop=float(holding.entry_sl),
            stop_multiplier=self.config.sl_multiplier,
            sl_step_percent=self.config.sl_step_percent,
            previous_stop=float(holding.current_sl) if holding.current_sl else float(holding.entry_sl)
        )
        rank_date = action_date - timedelta(days=3)
        holding_data = {
            'symbol': symbol,
            'date': action_date,
            'entry_date': holding.entry_date,
            'entry_price': holding.entry_price,
            'units': holding.units,
            'atr': atr,
            'score': round(ranking.get_rankings_by_date_and_symbol( rank_date, symbol).composite_score, 2),
            'entry_sl': holding.entry_sl,
            'current_price': current_price,
            'current_sl': stops['effective_stop']
        }
        return holding_data

    def get_summary(self, week_holdings, sold, override_starting_capital=None):
        """
        Build weekly portfolio summary from holdings data.

        Parameters:
            week_holdings (List[Dict]): Current week's holdings
            sold (float): Total value of sold positions
            override_starting_capital (float): Optional override to prevent double-counting 
                                            when updating same-day summary

        Returns:
            Dict: Summary with capital, risk, and P&L metrics
        """
        if override_starting_capital is not None:
            starting_capital = float(override_starting_capital)
        else:
            prev_summary = self.investment_repo.get_summary()
            starting_capital = float(
                prev_summary.remaining_capital
                if prev_summary else self.config.initial_capital
            )
        sold = float(sold)
        initial = float(self.config.initial_capital)

        # Convert holdings to DataFrame for vectorized calculations
        df = pd.DataFrame(week_holdings)
        for col in ['entry_price', 'units', 'current_sl', 'current_price']:
            df[col] = df[col].astype(float)

        # Bought: cost of new positions this week
        bought_mask = df['entry_date'] == df['date']
        bought = float((
            df.loc[bought_mask, 'entry_price']
            * df.loc[bought_mask, 'units']
        ).sum())

        # Capital risk: total cost basis - total stop value
        capital_risk = float((
            df['units'] * (df['entry_price'] - df['current_sl'])
        ).sum())

        # Holdings value: market value of all positions
        holdings_value = float(
            (df['units'] * df['current_price']).sum()
        )

        # Remaining cash after buys/sells
        remaining_capital = starting_capital + sold - bought

        # Portfolio value: holdings + cash
        portfolio_value = holdings_value + remaining_capital

        # Portfolio risk: loss if all stops hit
        stop_value = float(
            (df['units'] * df['current_sl']).sum()
        )
        portfolio_risk = round(holdings_value - stop_value, 2)

        # Gain vs initial capital
        gain = round(portfolio_value - initial, 2)
        gain_pct = round(
            (portfolio_value - initial) / initial * 100, 2
        )

        summary = {
            'date': week_holdings[0]['date'],
            'starting_capital': round(starting_capital, 2),
            'sold': round(sold, 2),
            'bought': round(bought, 2),
            'capital_risk': round(capital_risk, 2),
            'portfolio_value': round(portfolio_value, 2),
            'portfolio_risk': portfolio_risk,
            'gain': gain,
            'gain_percentage': gain_pct,
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

    def reject_pending_actions(self) -> int:
        """Reject all pending actions (unfilled buys at end of week).

        Returns:
            int: Number of actions rejected
        """
        pending = self.actions_repo.get_pending_actions()
        for action in pending:
            self.actions_repo.update_action({
                'action_id': action.action_id,
                'status': 'Rejected'
            })
        return len(pending)
