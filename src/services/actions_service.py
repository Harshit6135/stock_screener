"""
Actions Service

Handles investment action generation, approval, and processing.
"""
import pandas as pd
pd.set_option('future.no_silent_downcasting', True)

from sqlalchemy.orm import Session
from datetime import timedelta, date
from typing import Dict, List, Optional, Union

from config import setup_logger
from services import TradingEngine, HoldingSnapshot, CandidateInfo, InvestmentService
from repositories import (RankingRepository, IndicatorsRepository,
                          MarketDataRepository, InvestmentRepository,
                          ConfigRepository, ActionsRepository)
from utils import (calculate_position_size, calculate_capital_gains_tax,
                   calculate_transaction_costs, get_prev_friday)


logger = setup_logger(name="ActionsService")
config = ConfigRepository()
ranking = RankingRepository()
indicators = IndicatorsRepository()
marketdata = MarketDataRepository()


class ActionsService:
    """
    Investment action service for SELL/SWAP/BUY decisions.
    """
    def __init__(self, config_name: str = None,  session: Optional[Session] = None, config_info = None):
        if not config_info:
            self.config = config.get_config(config_name)
        else:
            self.config = config_info
        self.actions_repo = ActionsRepository(session)
        self.investment_repo = InvestmentRepository(session)
        self.investment_service = InvestmentService(session)

    def buy_action(self, symbol: str, action_date: date, prev_close: float, reason: str,
                   total_capital: float, remaining_capital: float = None, units: int = 0, price: float = 0) -> Dict:
        """
        Generate a BUY action with position sizing.

        Parameters:
            symbol (str): Trading symbol
            action_date (date): Action date
            prev_close (float): Current price/Previous close
            reason (str): Action reason (e.g., 'top 10 buys')
            total_capital (float): Total Capital Value (Invested + Cash) for risk calculation
            remaining_capital (float): Available Cash (to check affordability)
            units (int): Optional explicit units override (default 0 = auto-calculate)
        
        Returns:
            Dict: BUY action with units, risk, ATR, capital needed
        
        Raises:
            ValueError: If symbol is empty or ATR unavailable
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")
        if not reason:
            reason = "Unknown reason"

        # Resolve Friday for indicator lookup
        data_date = get_prev_friday(action_date)
        atr = indicators.get_indicator_by_tradingsymbol(
            'atrr_14', symbol, data_date
        )
        if atr is None:
            # Fallback if ATR is missing: assume 6% volatility (or config value)
            atr_percent = getattr(self.config, 'atr_fallback_percent')
            logger.warning(
                f"ATR not available for {symbol} on {data_date}. "
                f"Using fallback ATR {atr_percent*100}%"
            )
            atr = prev_close * atr_percent
        atr = round(atr, 2)

        if units > 0:
            capital_needed = units * float(price)
            risk_per_unit = round(atr * self.config.sl_multiplier, 2)
        else:
            sizing = calculate_position_size(
                atr=atr,
                current_price=float(prev_close),
                total_capital=total_capital,
                remaining_capital=remaining_capital,
                config=self.config
            )
            units = sizing['shares']
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
    def sell_action(symbol: str, action_date: date, prev_close: float, units: int, reason: str, price: float = 0) -> Dict:
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
        """
        if not symbol:
            raise ValueError("Symbol cannot be empty")
        if units <= 0:
            raise ValueError(f"Units must be positive, got {units}")
        if not reason:
            reason = "Unknown reason"

        price = price if price else prev_close
        capital_released = units * price
        action = {
            'action_date' : action_date,
            'type' : 'sell',
            'reason' : reason,
            'symbol' : symbol,
            'units' : units,
            'prev_close' : prev_close,
            'capital' : capital_released
        }
        return action

    def generate_actions(self, action_date: date, skip_pending_check: bool = False) -> Union[str, List[Dict]]:
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

        swap_buffer = 1 + self.config.buffer_percent
        exit_threshold = self.config.exit_threshold

        data_date = get_prev_friday(action_date)
        top_n = ranking.get_top_n_by_date(
            self.config.max_positions, data_date
        )
        candidates = [
            CandidateInfo(symbol=item.tradingsymbol, score=item.composite_score)
            for item in top_n
        ]

        current_holdings = self.investment_repo.get_holdings()
        total_capital = self.investment_repo.get_total_capital(
            action_date, include_realized=True
        )
        summary = self.investment_repo.get_summary()
        if not summary:
            remaining_capital = total_capital
        else:
            remaining_capital = float(summary.remaining_capital)

        #TODO Check for any investment on same or future date
        new_actions = []
        holdings_snap = []
        holdings_entry_prices = {}
        prices = {}

        if not current_holdings:
            for item in top_n:
                md = marketdata.get_marketdata_by_trading_symbol(
                    item.tradingsymbol, data_date
                )
                if md:
                    prices[item.tradingsymbol] = float(md.close)
        else:
            for h in current_holdings:
                holdings_entry_prices[h.symbol] = float(
                    h.entry_price
                )

                md_h = marketdata.get_marketdata_by_trading_symbol(
                    h.symbol, data_date
                )

                if md_h:
                    prices[h.symbol] = float(md_h.close)
                else:
                    prices[h.symbol] = float(h.current_price)

                holdings_snap.append(HoldingSnapshot(
                    symbol=h.symbol,
                    units=h.units,
                    stop_loss=h.current_sl,
                    score=h.score,
                ))

        decisions = TradingEngine.generate_decisions(
            holdings=holdings_snap,
            candidates=candidates,
            prices=prices,
            max_positions=self.config.max_positions,
            swap_buffer=swap_buffer,
            exit_threshold=exit_threshold,
        )

        sizing_base = total_capital
        if sizing_base <= 0:
            logger.warning(
                f"sizing_base is {sizing_base} — no capital "
                f"events found before {action_date}. "
                f"Position sizes will be 0."
            )

        for d in decisions:
            md = marketdata.get_marketdata_by_trading_symbol(
                d.symbol, data_date
            )
            if d.action_type == 'SELL':
                action = self.sell_action(
                    d.symbol, action_date, md.close,
                    d.units, d.reason
                )
                new_actions.append(action)
                remaining_capital += action['capital']
                if d.symbol in holdings_entry_prices:
                    entry_price = holdings_entry_prices[
                        d.symbol
                    ]
                    if entry_price > 0:
                        realized_gain = (
                            float(md.close) - entry_price
                        ) * d.units
                        sizing_base += realized_gain
            elif d.action_type == 'BUY':
                action = self.buy_action(
                    d.symbol, action_date, md.close,
                    d.reason,
                    total_capital=sizing_base,
                    remaining_capital=remaining_capital
                )
                
                new_actions.append(action)
                if action['units'] > 0:
                    remaining_capital -= action['capital']
            elif d.action_type == 'SWAP':
                sell_act = self.sell_action(
                    d.symbol, action_date, md.close,
                    d.swap_sell_units, d.reason
                )
                new_actions.append(sell_act)
                remaining_capital += (
                    d.swap_sell_units * float(md.close)
                )

                if d.symbol in holdings_entry_prices:
                    entry_price = holdings_entry_prices[
                        d.symbol
                    ]
                    if entry_price > 0:
                        realized_gain = (
                            float(md.close) - entry_price
                        ) * d.swap_sell_units
                        sizing_base += realized_gain

                md_swap_for = (
                    marketdata
                    .get_marketdata_by_trading_symbol(
                        d.swap_for, data_date
                    )
                )
                buy_act = self.buy_action(
                    d.swap_for, action_date,
                    md_swap_for.close, d.reason,
                    total_capital=sizing_base,
                    remaining_capital=remaining_capital
                )

                new_actions.append(buy_act)
                if buy_act['units'] > 0:
                    remaining_capital -= buy_act['capital']

        new_actions = [a for a in new_actions if a is not None]
        if new_actions:
            #TODO Check for symbol, if symbol exist then only delete
            self.actions_repo.delete_actions(new_actions[0]['action_date'])
            self.actions_repo.bulk_insert_actions(new_actions)

            pending_buys = [a for a in new_actions if a.get('units', 1) == 0]
            if pending_buys:
                logger.info(
                    f"Saved {len(pending_buys)} capital-constrained buys as Pending: "
                    f"{[a['symbol'] for a in pending_buys]}"
                )
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

        summary = self.investment_repo.get_summary()
        remaining_capital = (
            float(summary.remaining_capital) if summary
            else self.investment_repo.get_total_capital(
                action_date
            )
        )

        # Phase 1: Approve ALL sells first (always approved, at Monday open)
        for item in actions_list:
            if item.type == 'sell' and item.status == 'Pending':
                entry_data = self.investment_repo.get_holdings_by_symbol(item.symbol)
                execution_price = item.execution_price or marketdata.get_marketdata_first_day(item.symbol, action_date + timedelta(days=1)).open
                costs = calculate_transaction_costs(float(item.units * execution_price), 'sell')
                tax = calculate_capital_gains_tax(entry_data.entry_price, execution_price, entry_data.entry_date,
                                                  action_date, item.units)
                self.actions_repo.update_action({
                    'action_id': item.action_id,
                    'status': 'Approved',
                    'execution_price': execution_price,
                    'sell_cost': costs.get('sell_costs', 0),
                    'tax': tax
                })
                remaining_capital += float(item.units * execution_price)
                approved_count += 1

        for item in actions_list:
            if item.type == 'buy' and item.status == 'Pending':
                if item.units == 0:
                    logger.info(f"Keeping BUY {item.symbol} as Pending (capital-constrained, units=0)")
                    continue
                execution_price = item.execution_price or marketdata.get_marketdata_first_day(item.symbol, action_date + timedelta(days=1)).open
                capital_needed = float(item.units * execution_price)

                costs = calculate_transaction_costs(capital_needed, 'buy')
                self.actions_repo.update_action({
                    'action_id': item.action_id,
                    'status': 'Approved',
                    'execution_price': execution_price,
                    'buy_cost': costs.get('buy_costs', 0),
                    'tax': 0
                })
                remaining_capital -= capital_needed
                approved_count += 1

        return approved_count

    def process_actions(self, action_date: date, midweek: bool = False) -> Optional[List[Dict]]:
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

        self.investment_repo.delete_capital_events(date=action_date, event_type='realized_gain')

        buy_symbols = {}
        sell_symbols = {}
        for items in actions_list:
            if items.status == 'Approved':
                if items.type == 'sell':
                    sell_symbols[items.symbol] = items
                elif items.type == 'buy':
                    buy_symbols[items.symbol] = items

        sold = 0
        held_symbols = {h.symbol for h in holdings}
        holdings_map = {h.symbol: h for h in holdings}
        
        for symbol, action in sell_symbols.items():
            holding = holdings_map.get(symbol)
            if not holding:
                logger.warning(f"SELL {symbol}: not in current holdings, skipping")
                continue

            # Use action's own units for sell value (handles stock splits)
            sell_value = float(action.units * action.execution_price)
            sold += sell_value
            held_symbols.discard(symbol)

            #TODO Handle Split/Bonus
            buy_value = float(holding.entry_price) * holding.units
            pnl = sell_value - buy_value
            logger.info(
                f"SELL {symbol}: buy={holding.units}u@{holding.entry_price}={buy_value:.2f}"
                f" sell={action.units}u@{action.execution_price}={sell_value:.2f}"
                f" pnl={pnl:.2f}"
            )

            self.investment_repo.insert_capital_event({
                'date': action_date,
                'amount': pnl,
                'event_type': 'realized_gain',
                'note': (
                    f"Realized P&L for {symbol}"
                )
            })

        for symbol in list(buy_symbols.keys()):
            if symbol in held_symbols:
                logger.warning(
                    f"Skipping BUY {symbol}: already held, "
                    f"keeping existing position"
                )
                del buy_symbols[symbol]

        data_date = get_prev_friday(action_date)
        week_holdings = []
        for symbol, action in buy_symbols.items():
            initial_sl = round(action.execution_price - action.risk, 2)
            rank_data = ranking.get_rankings_by_date_and_symbol(data_date, symbol)
            score = round(rank_data.composite_score, 2) if rank_data else 0

            holding_data = {
                'symbol': symbol,
                'date': action_date,
                'entry_date': action_date,
                'entry_price': action.execution_price,
                'units': action.units,
                'atr': action.atr,
                'score': score,
                'entry_sl': initial_sl,
                'current_price': action.execution_price,
                'current_sl': initial_sl
            }
            week_holdings.append(holding_data)
        for symbol in held_symbols:
            week_holdings.append(
                self.investment_service.update_holding(symbol, action_date, midweek)
            )
        summary = self.investment_service.get_summary(week_holdings, sold, action_date=action_date)

        self.investment_repo.bulk_insert_holdings(week_holdings)
        self.investment_repo.insert_summary(summary)
        return  week_holdings

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

    def create_manual_buy(self, stocks: List[Dict]) -> str:

        actions = []
        total_capital = self.inv_repo.get_total_capital(include_realized=True)

        for stock in stocks:
            action = self.buy_action(
                symbol=stock['symbol'],
                action_date=stock['date'],
                prev_close=float(stock['price']),
                reason=stock['reason'],
                total_capital=total_capital,
                units=stock['units']
            )
            action['execution_price'] = float(stock['price'])
            actions.append(action)

        #TODO Check if symbol exist then only delete it
        self.actions_repo.bulk_insert_actions(actions)
        return f"Manual BUY actions created for {[s['symbol'] for s in stocks]}"

    def create_manual_sell(self, stocks: Dict) -> str:

        # Validate units against current holding
        holding = self.inv_repo.get_holdings_by_symbol(stocks['symbol'])
        if not holding:
            raise ValueError(
                f"Cannot sell {stocks['symbol']}: not in current holdings"
            )
        # if stocks['units'] > holding.units:
        #     raise ValueError(
        #         f"Cannot sell {data['units']} units of {data['symbol']}: "
        #         f"only {holding.units} held"
        #     )
        actions = []
        for stock in stocks:
            action = self.sell_action(
                stock['symbol'], 
                stock['date'], 
                float(stock['price']), 
                stock['units'], 
                stock['reason']
            )
            action['execution_price'] = float(stock['price'])
            actions.append(action)
        self.actions_repo.bulk_insert_actions([actions])
        return f"Manual SELL action created for {[s['symbol'] for s in stocks]}"
