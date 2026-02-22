"""
Actions Service

Handles investment action generation, approval, and processing.
"""
import pandas as pd
pd.set_option('future.no_silent_downcasting', True)

from datetime import timedelta
from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, List, Optional, Union
from types import SimpleNamespace

from config import setup_logger, PyramidConfig
from services import TradingEngine, HoldingSnapshot, CandidateInfo, InvestmentService
from repositories import (RankingRepository, IndicatorsRepository,
                          MarketDataRepository, InvestmentRepository,
                          ConfigRepository, ActionsRepository)
from utils import (calculate_position_size, calculate_capital_gains_tax,
                   calculate_transaction_costs, get_prev_friday)


logger = setup_logger(name="ActionsService")


class ActionsService:
    """
    Investment action service for SELL/SWAP/BUY decisions.
    """
    def __init__(self, config_name: str = None,  session: Optional[Session] = None, config_info = None):
        self.config_repo = ConfigRepository()
        if not config_info:
            self.config = self.config_repo.get_config(config_name)
        else:
            self.config = config_info
        self.ranking_repo = RankingRepository()
        self.indicators_repo = IndicatorsRepository()
        self.marketdata_repo = MarketDataRepository()
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
        atr = self.indicators_repo.get_indicator_by_tradingsymbol(
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
        remaining_capital -= action['capital']
        return action, remaining_capital

    @staticmethod
    def sell_action(symbol: str, action_date: date, prev_close: float, units: int, reason: str, price: float = 0, remaining_capital = 0,
    entry_price = 0) -> Dict:
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
        remaining_capital += action['capital']
        realized_gain = (float(prev_close) - entry_price)*units

        return action, remaining_capital, realized_gain

    def generate_actions(self, action_date: date, skip_pending_check: bool = False, enable_pyramiding: bool = False) -> Union[str, List[Dict]]:
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

        if not skip_pending_check:
            pending_actions = self.actions_repo.check_other_pending_actions(action_date)
            if pending_actions:
                return 'Actions pending from another date, please take action before proceeding'

        swap_buffer = 1 + self.config.buffer_percent
        exit_threshold = self.config.exit_threshold

        data_date = get_prev_friday(action_date)
        top_n = self.ranking_repo.get_top_n_by_date(
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
                md = self.marketdata_repo.get_marketdata_by_trading_symbol(
                    item.tradingsymbol, data_date
                )
                if md:
                    prices[item.tradingsymbol] = float(md.close)
        else:
            ema_50_values = {}
            for h in current_holdings:
                holdings_entry_prices[h.symbol] = float(h.entry_price)
                md_h = self.marketdata_repo.get_marketdata_by_trading_symbol(h.symbol, data_date)

                if md_h:
                    prices[h.symbol] = float(md_h.close)
                else:
                    prices[h.symbol] = float(h.current_price)

                holdings_snap.append(HoldingSnapshot(
                    symbol=h.symbol,
                    units=h.units,
                    stop_loss=h.current_sl,
                    score=h.score,
                    entry_price=float(h.entry_price),
                ))

                # Fetch EMA 50 for pyramid check
                if enable_pyramiding:
                    ema_50 = self.indicators_repo.get_indicator_by_tradingsymbol('ema_50', h.symbol, data_date)
                    ema_50_values[h.symbol] = float(ema_50) if ema_50 else 0.0

        decisions = TradingEngine.generate_decisions(
            holdings=holdings_snap,
            candidates=candidates,
            prices=prices,
            max_positions=self.config.max_positions,
            swap_buffer=swap_buffer,
            exit_threshold=exit_threshold,
            ema_50_values=ema_50_values if current_holdings else None,
            enable_pyramiding=enable_pyramiding,
        )

        sizing_base = total_capital
        if sizing_base <= 0:
            logger.warning(
                f"sizing_base is {sizing_base} — no capital "
                f"events found before {action_date}. "
                f"Position sizes will be 0."
            )

        for d in decisions:
            md = self.marketdata_repo.get_marketdata_by_trading_symbol(
                d.symbol, data_date
            )
            if d.action_type == 'SELL':
                action, remaining_capital, realized_gain = self.sell_action(
                    d.symbol, action_date, md.close,
                    d.units, d.reason, remaining_capital=remaining_capital, 
                    entry_price=holdings_entry_prices[d.symbol]
                )
                new_actions.append(action)
                sizing_base += realized_gain
            elif d.action_type == 'BUY':
                action, remaining_capital = self.buy_action(
                    d.symbol, action_date, md.close,
                    d.reason,
                    total_capital=sizing_base,
                    remaining_capital=remaining_capital
                )
                
                new_actions.append(action)
            elif d.action_type == 'PYRAMID_ADD':
                pyramid_cfg = PyramidConfig()
                action, remaining_capital = self.buy_action(
                    d.symbol, action_date, md.close,
                    'pyramid_add',
                    total_capital=sizing_base * pyramid_cfg.pyramid_fraction,
                    remaining_capital=remaining_capital
                )
                new_actions.append(action)
                logger.info(f"PYRAMID_ADD {d.symbol}: adding {pyramid_cfg.pyramid_fraction:.0%} position")
            elif d.action_type == 'SWAP':
                action, remaining_capital, realized_gain = self.sell_action(
                    d.symbol, action_date, md.close,
                    d.swap_sell_units, d.reason,
                    entry_price=holdings_entry_prices[d.symbol]

                )
                new_actions.append(action)
                sizing_base += realized_gain

                md_swap_for = self.marketdata_repo.get_marketdata_by_trading_symbol(d.swap_for, data_date)
                action, remaining_capital = self.buy_action(
                    d.swap_for, action_date, md_swap_for.close, d.reason,
                    total_capital=sizing_base, remaining_capital=remaining_capital
                )
                new_actions.append(action)

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
        actions_list = self.actions_repo.get_actions(action_date)
        approved_count = 0

        summary = self.investment_repo.get_summary()
        remaining_capital = (
            float(summary.remaining_capital) if summary
            else self.investment_repo.get_total_capital(
                action_date
            )
        )
        sizing_base =  self.investment_repo.get_total_capital(
            action_date, include_realized=True
        )

        # Phase 1: Approve ALL sells first (always approved, at Monday open)
        for item in actions_list:
            if item.type == 'sell' and item.status == 'Pending':
                entry_data = self.investment_repo.get_holdings_by_symbol(item.symbol)
                execution_price = item.execution_price or self.marketdata_repo.get_marketdata_by_trading_symbol(item.symbol, action_date).open
                costs = calculate_transaction_costs(float(item.units * execution_price), 'sell')
                tax = calculate_capital_gains_tax(float(entry_data.entry_price), float(execution_price), entry_data.entry_date,
                                                  action_date, item.units)
                self.actions_repo.update_action({
                    'action_id': item.action_id,
                    'status': 'Approved',
                    'execution_price': execution_price,
                    'sell_cost': costs.get('total', 0),
                    'tax': tax['tax']
                })
                remaining_capital += float(item.units * execution_price)
                sizing_base += float(item.units * execution_price) - float(entry_data.entry_price * entry_data.units)
                approved_count += 1

        for item in actions_list:
            if item.type == 'buy' and item.status == 'Pending':
                execution_price = item.execution_price or self.marketdata_repo.get_marketdata_by_trading_symbol(item.symbol, action_date).open
                sizing = calculate_position_size(
                    atr=float(item.atr),
                    current_price=float(execution_price),
                    total_capital=sizing_base,
                    remaining_capital=remaining_capital,
                    config=self.config
                )
                units = sizing['shares']
                capital_needed = sizing['position_value']
                if units == 0:
                    logger.info(f"Keeping BUY {item.symbol} as Pending (capital-constrained, units=0)")
                    continue

                costs = calculate_transaction_costs(capital_needed, 'buy')
                self.actions_repo.update_action({
                    'action_id': item.action_id,
                    'status': 'Approved',
                    'execution_price': execution_price,
                    'buy_cost': costs.get('total', 0),
                    'tax': 0,
                    'units' : units,
                    'capital' : capital_needed
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
        bought_value = 0
        held_symbols = {h.symbol for h in holdings}
        holdings_map = {h.symbol: h for h in holdings}
        
        for symbol, action in sell_symbols.items():
            logger.info(f"SELL {symbol}: units={action.units}u@{action.execution_price}={action.units*action.execution_price:.2f}")
            if (symbol not in holdings_map) and symbol in buy_symbols:
                logger.info(f"Intraday sell of {symbol}")
                buy_action = buy_symbols.pop(symbol)
                # Create temporary holding object from buy action
                holding = SimpleNamespace(
                    entry_price=buy_action.execution_price,
                    units=buy_action.units
                )
            else:
                holding = holdings_map.get(symbol)

            if not holding:
                logger.warning(f"No holding found for {symbol} to sell.")
                continue

            # Use action's own units for sell value (handles stock splits)
            sell_value = float(action.units * action.execution_price)
            sold += sell_value
            held_symbols.discard(symbol)

            #TODO Handle Split/Bonus
            # Use avg_price if it exists (for pyramided positions), else entry_price
            cost_basis_price = float(getattr(holding, 'avg_price', None) or holding.entry_price)
            buy_value = cost_basis_price * holding.units
            pnl = sell_value - buy_value
            logger.info(
                f"SELL {symbol}: buy={holding.units}u@{cost_basis_price}={buy_value:.2f}"
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

        data_date = get_prev_friday(action_date)
        week_holdings = []
        pyramid_symbols = set()
        for symbol, action in buy_symbols.items():
            if symbol in sell_symbols:
                continue

            # Pyramid add: merge into existing holding
            if action.reason == 'pyramid_add' and symbol in holdings_map:
                old = holdings_map[symbol]
                old_avg = float(getattr(old, 'avg_price', None) or old.entry_price)
                old_value = old_avg * old.units
                new_value = float(action.execution_price) * action.units
                bought_value += new_value
                total_units = old.units + action.units
                avg_price = round((old_value + new_value) / total_units, 2)

                rank_data = self.ranking_repo.get_rankings_by_date_and_symbol(data_date, symbol)
                score = round(rank_data.composite_score, 2) if rank_data else 0

                # Keep old trailing SL — don't reset to a tight new SL
                old_sl = float(old.current_sl)
                old_entry_sl = float(getattr(old, 'entry_sl', old_sl))

                logger.info(
                    f"PYRAMID_ADD {symbol}: {old.units}u@{old_avg:.2f} + {action.units}u@{action.execution_price} "
                    f"= {total_units}u avg_price={avg_price:.2f} (keeping SL={old_sl:.2f})"
                )

                holding_data = {
                    'symbol': symbol,
                    'date': action_date,
                    'entry_date': old.entry_date,
                    'entry_price': old.entry_price,
                    'avg_price': avg_price,
                    'units': total_units,
                    'atr': getattr(old, 'atr', action.atr),
                    'score': score,
                    'entry_sl': old_entry_sl,
                    'current_price': action.execution_price,
                    'current_sl': old_sl
                }
                week_holdings.append(holding_data)
                pyramid_symbols.add(symbol)
                held_symbols.discard(symbol)
                continue

            # Normal buy
            initial_sl = round(action.execution_price - action.risk, 2)
            rank_data = self.ranking_repo.get_rankings_by_date_and_symbol(data_date, symbol)
            score = round(rank_data.composite_score, 2) if rank_data else 0
            buy_value = float(action.execution_price) * action.units
            bought_value += buy_value
            logger.info(
                f"BUY {symbol}: units={action.units}u@{action.execution_price}={buy_value:.2f}"
            )

            holding_data = {
                'symbol': symbol,
                'date': action_date,
                'entry_date': action_date,
                'entry_price': action.execution_price,
                'avg_price': float(action.execution_price),
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
                self.investment_service.update_holding(symbol, action_date, midweek, holdings_map[symbol])
            )
        summary = self.investment_service.get_summary(week_holdings, sold, bought=bought_value, action_date=action_date)

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
        total_capital = self.investment_repo.get_total_capital(include_realized=True)
        remaining_capital = self.investment_repo.get_summary()
    
        over_capital = []
        for stock in stocks:
            prev_close = float(self.marketdata_repo.get_marketdata_by_trading_symbol(stock['symbol'], stock['date'] - timedelta(days=1)).close)
            if remaining_capital < stock['units'] * stock['price']:
                over_capital.append(stock)
                continue

            action, remaining_capital = self.buy_action(
                symbol=stock['symbol'],
                action_date=stock['date'],
                prev_close=prev_close,
                price=float(stock['price']),
                reason=stock['reason'],
                total_capital=total_capital,
                remaining_capital=remaining_capital,
                units=stock['units']
            )
            action['execution_price'] = float(stock['price'])
            actions.append(action)

        if actions:
            self.actions_repo.bulk_insert_actions(actions)
        return f"Manual BUY actions created for {[s['symbol'] for s in stocks]} and over capital for {[s['symbol'] for s in over_capital]}, before creating buy action infuse capital"

    def create_manual_sell(self, stocks: List[Dict]) -> str:
        actions = []
        not_in_holding = []
        for stock in stocks:
            if stock['symbol'] not in holding_entry_prices:
                not_in_holding.append(stock['symbol'])
                continue
                
            md = self.marketdata_repo.get_marketdata_by_trading_symbol(stock['symbol'], stock['date'] - timedelta(days=1))
            prev_close = float(md.close) if md else float(stock['price'])

            action, _, _ = self.sell_action(
                symbol=stock['symbol'], 
                action_date=stock['date'], 
                prev_close=prev_close,
                units=stock['units'], 
                reason=stock['reason'],
                price=float(stock['price'])
            )
            action['execution_price'] = float(stock['price'])
            actions.append(action)
            
        if actions:
            self.actions_repo.bulk_insert_actions(actions)
        return f"Manual SELL action created for {[s['symbol'] for s in stocks]} and not in holding for {not_in_holding}"
