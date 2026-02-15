"""
Backtest Runner

Simplified backtest engine that reuses ActionsService with DB injection.
All trading logic (generate/approve/process actions) is delegated to ActionsService
for consistency with live trading. Writes results to backtest.db.
"""
from datetime import date, timedelta
from typing import Dict, List, Optional
from dataclasses import asdict
from flask import current_app

from config import setup_logger
from config.strategies_config import PositionSizingConfig
from backtesting.models import Position, BacktestResult, BacktestRiskMonitor
from backtesting.config import BacktestConfigLoader
from backtesting.data_provider import BacktestDataProvider
from utils import (calculate_initial_stop_loss, calculate_effective_stop, calculate_round_trip_cost,
                   calculate_position_size as shared_calculate_position_size, calculate_equal_weight_position,
                   calculate_capital_gains_tax, DatabaseManager)
from repositories import InvestmentRepository, ActionsRepository
from services import TradingEngine, HoldingSnapshot, CandidateInfo, ActionsService


logger = setup_logger(name="BacktestRunner")


class WeeklyBacktester:
    """
    Weekly backtesting engine using ActionsService with DB injection.
    
    Delegates all trading logic to ActionsService (same code as live trading).
    Only keeps backtest-specific concerns: weekly loop, risk monitoring,
    and result tracking.
    """
    
    def __init__(self, start_date: date, end_date: date, config_name: str):
        self.start_date = start_date
        self.end_date = end_date
        self.config_name = config_name
        
        # Load config from repository
        self.config_loader = BacktestConfigLoader(config_name)
        self.config = self.config_loader.fetch()
        
        # Data provider for direct DB access (still needed for price lookups)
        self.data = BacktestDataProvider()
        
        # Risk monitor and results tracking
        self.risk_monitor = BacktestRiskMonitor(self.config['initial_capital'])
        self.weekly_results: List[BacktestResult] = []
        
        # Database session for backtest writes (set in run())
        self.backtest_session = None
        self.actions_service = None
    
    def get_week_mondays(self) -> List[date]:
        """Get all Mondays between start and end dates"""
        mondays = []
        current = self.start_date
        while current.weekday() != 0:
            current += timedelta(days=1)
        while current <= self.end_date:
            mondays.append(current)
            current += timedelta(weeks=1)
        return mondays
    
    def run(self) -> List[BacktestResult]:
        """
        Execute the backtest using ActionsService.
        
        For each Monday:
        1. generate_actions(monday) — creates Pending actions in backtest DB
        2. approve_all_actions(monday) — sets execution prices (Monday open)
        3. process_actions(monday) — updates holdings and summary
        4. Track risk metrics
        
        Returns:
            List of weekly BacktestResult objects
        """
        logger.info(f"Starting backtest: {self.start_date} to {self.end_date}")
        logger.info(f"Config: capital={self.config['initial_capital']}, "
                   f"max_positions={self.config['max_positions']}, "
                   f"exit_threshold={self.config['exit_threshold']}")
        
        # Initialize backtest database
        try:
            app = current_app._get_current_object()
            DatabaseManager.init_backtest_db(app)
            DatabaseManager.clear_backtest_db(app)
            self.backtest_session = DatabaseManager.get_backtest_session()
            logger.info("Backtest database initialized and cleared")
        except RuntimeError as e:
            logger.warning(f"No Flask app context, DB writes disabled: {e}")
            self.backtest_session = None
        
        # Create ActionsService with backtest session injection
        self.actions_service = ActionsService(self.config_name, self.backtest_session)
        inv_repo = InvestmentRepository(session=self.backtest_session)
        
        mondays = self.get_week_mondays()
        
        for week_date in mondays:
            logger.info(f"Processing week: {week_date}")
            
            # 1. Generate actions (SELL/BUY/SWAP decisions)
            actions = self.actions_service.generate_actions(
                week_date, skip_pending_check=True
            )
            
            if isinstance(actions, str):
                logger.warning(f"generate_actions returned message: {actions}")
                continue
            
            if not actions:
                logger.info(f"No actions for {week_date}")
            
            # 2. Approve all actions (sets execution prices from Monday open)
            if actions:
                approved_count = self.actions_service.approve_all_actions(week_date)
                logger.info(f"Approved {approved_count} actions for {week_date}")
                
                # 3. Process actions (updates holdings, creates summary)
                week_holdings = self.actions_service.process_actions(week_date)
                if week_holdings:
                    logger.info(f"Processed {len(week_holdings)} holdings for {week_date}")
            
            # 4. Track risk metrics
            # Read portfolio value from the summary just written by process_actions
            summary = inv_repo.get_summary(week_date)
            if summary:
                portfolio_value = float(summary.portfolio_value)
            else:
                portfolio_value = self.config['initial_capital']
            
            self.risk_monitor.update(portfolio_value)
            
            # 5. Get current holdings for result snapshot
            current_holdings = inv_repo.get_holdings(week_date)
            holdings_snapshot = []
            if current_holdings:
                holdings_snapshot = [
                    {
                        'symbol': h.symbol,
                        'units': h.units,
                        'entry_price': float(h.entry_price),
                        'current_price': float(h.current_price),
                        'current_sl': float(h.current_sl),
                    }
                    for h in current_holdings
                ]
            
            # 6. Fetch top rankings for the result record
            ranking_friday = week_date - timedelta(days=3)
            rankings = self.data.get_top_rankings(
                self.config['max_positions'], ranking_friday
            )
            top_stocks = [r['tradingsymbol'] for r in rankings] if rankings else []
            
            # 7. Record result
            result = BacktestResult(
                week_date=week_date,
                portfolio_value=portfolio_value,
                total_return=self.risk_monitor.get_total_return(),
                max_drawdown=self.risk_monitor.max_drawdown,
                actions=actions if isinstance(actions, list) else [],
                top_10_stocks=top_stocks,
                holdings=holdings_snapshot
            )
            self.weekly_results.append(result)
        
        if self.weekly_results:
            logger.info(f"Backtest complete. Final value: {self.weekly_results[-1].portfolio_value}")
        else:
            logger.info("Backtest complete. No weekly results generated.")
        
        return self.weekly_results
    
    def get_summary(self) -> dict:
        """Get comprehensive backtest summary"""
        risk_summary = self.risk_monitor.get_summary()
        return risk_summary
    
    # ============================================================
    # COMMENTED OUT: Old methods replaced by ActionsService
    # Kept for reference — remove once the refactor is validated.
    # ============================================================
    
    # @staticmethod
    # def _get_ranking_friday(monday_date: date) -> date:
    #     """Get the previous Friday for ranking lookup.
    #
    #     Rankings are always stored on calendar Fridays.
    #     Given a Monday, returns the Friday 3 days prior.
    #
    #     Parameters:
    #         monday_date: A Monday date from the backtest loop
    #
    #     Returns:
    #         The previous Friday date
    #     """
    #     weekday = monday_date.weekday()
    #     if weekday == 4:  # Already Friday
    #         return monday_date
    #     elif weekday < 4:  # Mon-Thu: go back to last Friday
    #         days_back = weekday + 3
    #         return monday_date - timedelta(days=days_back)
    #     else:  # Sat=5, Sun=6
    #         days_back = weekday - 4
    #         return monday_date - timedelta(days=days_back)
    
    # def calculate_position_size(self, atr: Optional[float], current_price: float) -> Dict:
    #     """
    #     Calculate position size using shared sizing util.
    #     
    #     Delegates to utils.sizing_utils.calculate_position_size which applies
    #     4 constraints: ATR-risk, liquidity, concentration, minimum.
    #     Falls back to equal-weight if ATR unavailable.
    #     
    #     Parameters:
    #         atr: Average True Range
    #         current_price: Current stock price
    #         
    #     Returns:
    #         Dict with shares, position_value, stop_distance
    #     """
    #     # Use actual portfolio value, not initial capital
    #     invested_value = sum(pos.entry_price * pos.units for pos in self.positions.values())
    #     portfolio_value = self.current_capital + invested_value
    #     
    #     if atr is None or atr <= 0:
    #         # Fallback to equal-weight position when no ATR
    #         result = calculate_equal_weight_position(
    #             portfolio_value, self.config.max_positions, current_price
    #         )
    #         result['stop_distance'] = round(current_price * self.config.sl_fallback_percent, 2)
    #         return result
    #     
    #     result = shared_calculate_position_size(
    #         atr=atr,
    #         current_price=current_price,
    #         portfolio_value=portfolio_value
    #     )
    #     return result
    
    # def calculate_portfolio_value(self, current_prices: Dict[str, float]) -> float:
    #     """Calculate total portfolio value"""
    #     positions_value = sum(
    #         pos.units * current_prices.get(pos.tradingsymbol, pos.entry_price)
    #         for pos in self.positions.values()
    #     )
    #     return self.current_capital + positions_value
    
    # def execute_sell(self, symbol: str, current_price: float, week_date: date, 
    #                  reason: str) -> Dict:
    #     """
    #     Execute a sell order. Tax and costs tracked separately, not deducted from proceeds.
    #     
    #     Capital receives gross_proceeds (matches live behavior).
    #     Tax and costs are recorded as separate fields for reporting.
    #     
    #     Returns:
    #         Action dict with all details
    #     """
    #     pos = self.positions[symbol]
    #     gross_proceeds = pos.units * current_price
    #     
    #     # Calculate transaction costs (tracked separately)
    #     costs = calculate_round_trip_cost(gross_proceeds)
    #     sell_costs = costs.get('sell_costs', 0)
    #     self.total_transaction_costs += sell_costs
    #     
    #     # Calculate taxes (tracked separately)
    #     tax_info = calculate_capital_gains_tax(
    #         purchase_price=pos.entry_price,
    #         current_price=current_price,
    #         purchase_date=pos.entry_date,
    #         current_date=week_date,
    #         quantity=pos.units
    #     )
    #     tax = tax_info.get('tax', 0)
    #     self.total_taxes_paid += tax
    #     
    #     # Gross PnL (before costs/tax)
    #     gross_pnl = (current_price - pos.entry_price) * pos.units
    #     
    #     # Update capital with gross proceeds (tax/costs tracked separately)
    #     self.current_capital += gross_proceeds
    #     
    #     action = {
    #         'action_date': week_date.isoformat(),
    #         'action_type': 'SELL',
    #         'tradingsymbol': symbol,
    #         'units': pos.units,
    #         'price': current_price,
    #         'gross_pnl': round(gross_pnl, 2),
    #         'transaction_costs': round(sell_costs, 2),
    #         'tax': round(tax, 2),
    #         'net_pnl': round(gross_pnl - sell_costs - tax, 2),
    #         'reason': reason
    #     }
    #     
    #     # Record and remove
    #     self.risk_monitor.record_trade({'type': 'SELL', 'symbol': symbol, 'pnl': gross_pnl})
    #     del self.positions[symbol]
    #     
    #     return action
    
    # def execute_buy(self, symbol: str, price: float, score: float, atr: float,
    #                 week_date: date, reason: str) -> Optional[Dict]:
    #     """
    #     Execute a buy order with transaction costs.
    #     
    #     Returns:
    #         Action dict or None if insufficient capital
    #     """
    #     sizing = self.calculate_position_size(atr, price)
    #     if sizing['shares'] == 0:
    #         return None
    #     
    #     position_cost = sizing['shares'] * price
    #     
    #     # Calculate transaction costs
    #     costs = calculate_round_trip_cost(position_cost)
    #     buy_costs = costs.get('buy_costs', 0)
    #     self.total_transaction_costs += buy_costs
    #     
    #     total_cost = position_cost + buy_costs
    #     
    #     if total_cost > self.current_capital:
    #         logger.warning(f"Insufficient capital for {symbol}: need {total_cost}, have {self.current_capital}")
    #         return None
    #     
    #     # Deduct capital
    #     self.current_capital -= total_cost
    #     
    #     # Calculate initial stop-loss
    #     initial_stop = calculate_initial_stop_loss(
    #         price, atr, self.config.stop_multiplier,
    #         PositionSizingConfig()
    #     )
    #     
    #     # Create position
    #     self.positions[symbol] = Position(
    #         tradingsymbol=symbol,
    #         entry_price=price,
    #         units=sizing['shares'],
    #         entry_date=week_date,
    #         composite_score=score,
    #         atr_at_entry=atr or 0,
    #         initial_stop_loss=initial_stop,
    #         current_stop_loss=initial_stop
    #     )
    #     
    #     return {
    #         'action_date': week_date.isoformat(),
    #         'action_type': 'BUY',
    #         'tradingsymbol': symbol,
    #         'units': sizing['shares'],
    #         'price': price,
    #         'transaction_costs': round(buy_costs, 2),
    #         'initial_stop': round(initial_stop, 2),
    #         'reason': reason
    #     }
    
    # def rebalance_portfolio(self, week_date: date, top_rankings: List[dict],
    #                         score_lookup: Dict[str, float],
    #                         price_lookup: Dict[str, float],
    #                         low_price_lookup: Dict[str, float] = None,
    #                         execution_price_lookup: Dict[str, float] = None) -> List[dict]:
    #     """
    #     Rebalance portfolio using shared TradingEngine.
    #     
    #     Delegates SELL/BUY/SWAP decisions to TradingEngine.generate_decisions(),
    #     then executes each decision.
    #     
    #     Parameters:
    #         week_date: Current Monday date
    #         top_rankings: Top ranked stocks from Friday
    #         score_lookup: Composite scores by symbol
    #         price_lookup: Close prices for valuation/stop-loss
    #         low_price_lookup: Low prices for stop-loss triggers
    #         execution_price_lookup: Monday open prices for trade execution
    #     """
    #     # Use open prices for execution, fall back to close prices
    #     if execution_price_lookup is None:
    #         execution_price_lookup = price_lookup
    #     
    #     # Update trailing stops using weekly low for stop-loss trigger (matches live fetch_low)
    #     if low_price_lookup is None:
    #         low_price_lookup = price_lookup
    #     
    #     for symbol, pos in self.positions.items():
    #         current_price = price_lookup.get(symbol, pos.entry_price)
    #         low_price = low_price_lookup.get(symbol, current_price)
    #         current_atr = self.data.get_indicator('atrr_14', symbol, week_date)
    #         if current_atr is None:
    #             current_atr = current_price * 0.02  # 2% fallback
    #         
    #         stops = calculate_effective_stop(
    #             buy_price=pos.entry_price,
    #             current_price=low_price,
    #             current_atr=current_atr,
    #             initial_stop=pos.initial_stop_loss,
    #             stop_multiplier=self.config.stop_multiplier,
    #             sl_step_percent=self.config.sl_step_percent,
    #             previous_stop=pos.current_stop_loss
    #         )
    #         pos.current_stop_loss = stops['effective_stop']
    #     
    #     # Build normalized inputs for TradingEngine
    #     holdings_snap = [
    #         HoldingSnapshot(
    #             symbol=symbol,
    #             units=pos.units,
    #             stop_loss=pos.current_stop_loss,
    #             score=score_lookup.get(symbol, pos.composite_score),
    #         )
    #         for symbol, pos in self.positions.items()
    #     ]
    #     
    #     candidates = [
    #         CandidateInfo(symbol=r['tradingsymbol'], score=r['composite_score'])
    #         for r in top_rankings
    #     ]
    #     
    #     # Use config-driven parameters
    #     swap_buffer = 1 + self.config.buffer_percent
    #     
    #     decisions = TradingEngine.generate_decisions(
    #         holdings=holdings_snap,
    #         candidates=candidates,
    #         prices=price_lookup,
    #         max_positions=self.config.max_positions,
    #         swap_buffer=swap_buffer,
    #         exit_threshold=self.config.exit_threshold,
    #     )
    #     
    #     # Execute decisions
    #     actions = []
    #     for d in decisions:
    #         if d.action_type == 'SELL':
    #             exec_price = execution_price_lookup.get(d.symbol, 0)
    #             action = self.execute_sell(
    #                 d.symbol, exec_price, week_date, d.reason
    #             )
    #             actions.append(action)
    #             
    #         elif d.action_type == 'BUY':
    #             exec_price = execution_price_lookup.get(d.symbol, 0)
    #             score = next(
    #                 (c.score for c in candidates
    #                  if c.symbol == d.symbol), 0
    #             )
    #             atr = self.data.get_indicator(
    #                 'atrr_14', d.symbol, week_date
    #             )
    #             buy_action = self.execute_buy(
    #                 d.symbol, exec_price, score,
    #                 atr or 0, week_date, d.reason
    #             )
    #             if buy_action:
    #                 actions.append(buy_action)
    #                 
    #         elif d.action_type == 'SWAP':
    #             # Sell incumbent at Monday open
    #             sell_price = execution_price_lookup.get(d.symbol, 0)
    #             sell_act = self.execute_sell(
    #                 d.symbol, sell_price, week_date, d.reason
    #             )
    #             
    #             # Buy challenger at Monday open
    #             buy_price = execution_price_lookup.get(
    #                 d.swap_for, 0
    #             )
    #             buy_score = next(
    #                 (c.score for c in candidates
    #                  if c.symbol == d.swap_for), 0
    #             )
    #             buy_atr = self.data.get_indicator(
    #                 'atrr_14', d.swap_for, week_date
    #             )
    #             buy_act = self.execute_buy(
    #                 d.swap_for, buy_price, buy_score,
    #                 buy_atr or 0, week_date, d.reason
    #             )
    #             
    #             if buy_act:
    #                 actions.append({
    #                     'action_date': week_date.isoformat(),
    #                     'action_type': 'SWAP',
    #                     'swap_from': d.symbol,
    #                     'swap_to': d.swap_for,
    #                     'sell_details': sell_act,
    #                     'buy_details': buy_act
    #                 })
    #     
    #     return actions
    
    # def _check_intraweek_stoploss(self, prev_monday: date, prev_friday: date) -> List[dict]:
    #     """
    #     Check intra-week stop-loss triggers for all held positions.
    #     
    #     Iterates each trading day of the prior week (Mon-Fri). On the
    #     first day where a stock's daily low breaches its stop-loss,
    #     sells the stock at the SL price and frees the slot.
    #     
    #     Parameters:
    #         prev_monday: Monday of the prior week
    #         prev_friday: Friday of the prior week
    #         
    #     Returns:
    #         List of sell action dicts from SL triggers
    #     """
    #     sl_actions = []
    #     # Snapshot symbol list — we'll mutate self.positions during iteration
    #     symbols_to_check = list(self.positions.keys())
    #     
    #     for symbol in symbols_to_check:
    #         if symbol not in self.positions:
    #             continue  # Already sold in this pass
    #         
    #         pos = self.positions[symbol]
    #         daily_lows = self.data.get_daily_lows_in_range(
    #             symbol, prev_monday, prev_friday
    #         )
    #         
    #         for day_date, day_low in daily_lows:
    #             if day_low <= pos.current_stop_loss:
    #                 # SL breached — sell at the stop-loss price on this day
    #                 logger.info(
    #                     f"INTRA-WEEK SL: {symbol} low {day_low:.2f} <= "
    #                     f"SL {pos.current_stop_loss:.2f} on {day_date}"
    #                 )
    #                 action = self.execute_sell(
    #                     symbol, pos.current_stop_loss, day_date,
    #                     f'intra-week stoploss hit on {day_date}'
    #                 )
    #                 sl_actions.append(action)
    #                 break  # First breach — stop checking further days
    #     
    #     return sl_actions
    
    # def _persist_weekly_result(self, week_date: date, actions: List[dict], 
    #                            portfolio_value: float, price_lookup: Dict[str, float] = None,
    #                            weekly_sold: float = 0.0):
    #     """
    #     Persist weekly results to backtest database.
    #     
    #     Writes actions, holdings, and summary for analysis.
    #     """
    #     if self.backtest_session is None:
    #         return  # DB writes disabled (no Flask context)
    #     
    #     # Convert actions to database format
    #     action_records = []
    #     for action in actions:
    #         if action.get('action_type') == 'SWAP':
    #             # Swap contains nested sell/buy
    #             sell = action.get('sell_details', {})
    #             buy = action.get('buy_details', {})
    #             action_records.extend([
    #                 {
    #                     'action_date': week_date,
    #                     'type': 'sell',
    #                     'symbol': sell.get('tradingsymbol', ''),
    #                     'units': sell.get('units', 0),
    #                     'prev_close': sell.get('price', 0),
    #                     'execution_price': sell.get('price', 0),
    #                     'capital': sell.get('gross_pnl', 0),
    #                     'reason': f"Swap to {buy.get('tradingsymbol', '')}",
    #                     'status': 'Approved'
    #                 },
    #                 {
    #                     'action_date': week_date,
    #                     'type': 'buy',
    #                     'symbol': buy.get('tradingsymbol', ''),
    #                     'units': buy.get('units', 0),
    #                     'prev_close': buy.get('price', 0),
    #                     'execution_price': buy.get('price', 0),
    #                     'capital': buy.get('units', 0) * buy.get('price', 0),
    #                     'reason': f"Swap from {sell.get('tradingsymbol', '')}",
    #                     'status': 'Approved'
    #                 }
    #             ])
    #         else:
    #             action_records.append({
    #                 'action_date': week_date,
    #                 'type': action.get('action_type', '').lower(),
    #                 'symbol': action.get('tradingsymbol', ''),
    #                 'units': action.get('units', 0),
    #                 'prev_close': action.get('price', 0),
    #                 'execution_price': action.get('price', 0),
    #                 'capital': action.get('units', 0) * action.get('price', 0),
    #                 'reason': action.get('reason', ''),
    #                 'status': 'Approved'
    #             })
    #     
    #     if action_records:
    #         actions_repo = ActionsRepository(session=self.backtest_session)
    #         actions_repo.bulk_insert_actions(action_records)
    #     
    #     # Convert holdings to database format
    #     holding_records = []
    #     for pos in self.positions.values():
    #         holding_records.append({
    #             'symbol': pos.tradingsymbol,
    #             'date': week_date,
    #             'entry_date': pos.entry_date,
    #             'entry_price': pos.entry_price,
    #             'units': pos.units,
    #             'atr': pos.atr_at_entry,
    #             'score': pos.composite_score,
    #             'entry_sl': pos.initial_stop_loss,
    #             'current_price': price_lookup.get(pos.tradingsymbol, pos.entry_price) if price_lookup else pos.entry_price,
    #             'current_sl': pos.current_stop_loss
    #         })
    #     
    #     inv_repo = InvestmentRepository(session=self.backtest_session)
    #     
    #     if holding_records:
    #         inv_repo.bulk_insert_holdings(holding_records)
    #     
    #     # Create summary record
    #     prev_summary = inv_repo.get_summary()
    #     starting_capital = prev_summary.starting_capital if prev_summary else self.config.initial_capital
    #     
    #     summary = {
    #         'date': week_date,
    #         'starting_capital': round(starting_capital, 2),
    #         'sold': round(weekly_sold, 2),
    #         'bought': 0,
    #         'capital_risk': 0,
    #         'portfolio_value': round(portfolio_value, 2),
    #         'portfolio_risk': 0,
    #         'gain': round(portfolio_value - self.config.initial_capital, 2),
    #         'gain_percentage': round(
    #             (portfolio_value - self.config.initial_capital) / self.config.initial_capital * 100, 2
    #         )
    #     }
    #     inv_repo.insert_summary(summary)


def run_backtest(start_date: date, end_date: date, config_name: str = "momentum_config"):
    """
    Convenience function to run a backtest.
    
    Parameters:
        start_date: Start date for backtest
        end_date: End date for backtest
        config_name: config name for config lookup
        
    Returns:
        Tuple of (results, summary)
    """
    backtester = WeeklyBacktester(start_date, end_date, config_name)
    results = backtester.run()
    summary = backtester.get_summary()
    return results, summary


if __name__ == "__main__":
    # Example usage
    from datetime import date
    from config import setup_logger
    
    logger = setup_logger(name="BacktestRunner")
    
    start = date(2024, 1, 1)
    end = date(2024, 12, 31)
    
    results, summary = run_backtest(start, end)
    logger.info(f"\n{'='*50}")
    logger.info("BACKTEST SUMMARY")
    logger.info(f"{'='*50}")
    for key, value in summary.items():
        logger.info(f"  {key}: {value}")
