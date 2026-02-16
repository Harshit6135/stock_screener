"""
Backtest Runner

Simplified backtest engine that reuses ActionsService with DB injection.
All trading logic (generate/approve/process actions) is delegated to ActionsService
for consistency with live trading. Writes results to backtest.db.
"""
from datetime import date, timedelta
from typing import List
from flask import current_app

from config import setup_logger
from backtesting.models import BacktestResult, BacktestRiskMonitor
from backtesting.config import BacktestConfigLoader
from backtesting.data_provider import BacktestDataProvider
from utils import (calculate_effective_stop, calculate_round_trip_cost,
                   DatabaseManager)
from repositories import InvestmentRepository, ActionsRepository
from services import ActionsService


logger = setup_logger(name="BacktestRunner")


class WeeklyBacktester:
    """
    Weekly backtesting engine using ActionsService with DB injection.
    
    Delegates all trading logic to ActionsService (same code as live trading).
    Only keeps backtest-specific concerns: weekly loop, risk monitoring,
    and result tracking.
    """
    
    def __init__(self, start_date: date, end_date: date, config_name: str, check_daily_sl: bool = True):
        self.start_date = start_date
        self.end_date = end_date
        self.config_name = config_name
        self.check_daily_sl = check_daily_sl
        
        # Load config from repository
        self.config_loader = BacktestConfigLoader(config_name)
        self.config = self.config_loader.fetch()
        
        # Data provider for direct DB access (still needed for price lookups)
        self.data = BacktestDataProvider()
        
        # Risk monitor and results tracking
        self.risk_monitor = BacktestRiskMonitor(self.config.initial_capital)
        self.weekly_results: List[BacktestResult] = []
       
        # Database session for backtest writes (set in run())
        app = current_app._get_current_object()
        DatabaseManager.init_backtest_db(app)
        DatabaseManager.clear_backtest_db(app)
        self.backtest_session = DatabaseManager.get_backtest_session()
        self.actions_service = ActionsService(config_name=self.config_name, session=self.backtest_session, config_info=self.config)
        self.inv_repo = InvestmentRepository(session=self.backtest_session)
        self.actions_repo = ActionsRepository(session=self.backtest_session)

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
        Execute the backtest using ActionsService with daily stop-loss processing.
        
        For each Monday:
        1. generate_actions(monday) — creates Pending actions in backtest DB
        2. approve_all_actions(monday) — capital-aware: sells always, buys if budget allows
        3. process_actions(monday) — updates holdings and summary
        4. Daily SL check Mon→Fri — sells at SL price, fills pending buys at close
        5. Reject remaining pending actions
        6. Track risk metrics
        
        Returns:
            List of weekly BacktestResult objects
        """
        logger.info(f"Starting backtest: {self.start_date} to {self.end_date} (Daily SL: {self.check_daily_sl})")
        logger.info(f"Config: capital={self.config.initial_capital}, "
                   f"max_positions={self.config.max_positions}, "
                   f"exit_threshold={self.config.exit_threshold}")
        
        mondays = self.get_week_mondays()
        
        # Track close-based SL sells pending from Friday → execute on next Monday
        pending_close_sl_sells: set = set()
        
        for week_date in mondays:
            logger.info(f"Processing week: {week_date}")
            
            # 0. Reject any leftover pending actions from previous week
            rejected = self.actions_service.reject_pending_actions()
            if rejected:
                logger.info(f"Rejected {rejected} pending actions from previous week")
            
            # 0a. Execute any pending close-based SL sells from last Friday
            if pending_close_sl_sells:
                self._execute_pending_sl_sells(
                    pending_close_sl_sells, week_date
                )
                pending_close_sl_sells = set()
            
            # 1. Generate actions (SELL/BUY/SWAP decisions from Friday rankings)
            # CRITICAL FIX: Pass check_daily_sl=False even for Daily Backtest.
            # Rationale: ActionsService checks "Last Week's Low" against "This Week's SL".
            # unique to backtesting. If we let it check daily SL, it retroactively sells
            # stocks that dipped last week, even if runner.py successfully navigated that week.
            # We want runner.py to handle ALL daily checks during the week loop.
            actions = self.actions_service.generate_actions(
                week_date, skip_pending_check=True, check_daily_sl=False
            )
            
            # For Weekly SL, correct execution prices to Monday Open (realistic fill)
            # preventing artificial gains from Friday Close fills before Monday gaps
            # NOTE: We now do this for ALL backtests because generate_actions(False)
            # returns close-based fills.
            if actions:
                self._correct_execution_prices(week_date)
            
            if isinstance(actions, str):
                logger.warning(f"generate_actions returned message: {actions}")
                continue
            
            if not actions:
                logger.info(f"No actions for {week_date}")
            
            # 2. Capital-aware approval (sells always, buys if budget allows)
            monday_sold_symbols = set()
            if actions:
                approved_count = self.actions_service.approve_all_actions(week_date)
                logger.info(f"Approved {approved_count} actions for {week_date}")
                
                # 3. Process approved actions (updates holdings, creates summary)
                week_holdings = self.actions_service.process_actions(week_date)
                if week_holdings:
                    logger.info(f"Processed {len(week_holdings)} holdings for {week_date}")
                
                # Collect symbols sold on Monday (by generate_actions)
                monday_actions = self.actions_repo.get_actions(week_date)
                if monday_actions:
                    monday_sold_symbols = {
                        a.symbol for a in monday_actions
                        if a.type == 'sell' and a.status == 'Approved'
                    }
            
            # 4. Daily SL check Mon → Fri (hybrid: close-based + hard intraday)
            if self.check_daily_sl:
                friday = week_date + timedelta(days=4)
                pending_close_sl_sells = self._process_daily_stoploss(
                    week_date, friday, monday_sold_symbols
                )
            
            # 5. Track risk metrics from latest summary
            summary = self.inv_repo.get_summary()
            if summary:
                portfolio_value = float(summary.portfolio_value)
            else:
                portfolio_value = self.config.initial_capital
            
            self.risk_monitor.update(portfolio_value)
            
            # 6. Get current holdings for result snapshot
            current_holdings = self.inv_repo.get_holdings()
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
            
            # 7. Fetch top rankings for the result record
            ranking_friday = week_date - timedelta(days=3)
            rankings = self.data.get_top_rankings(
                self.config.max_positions, ranking_friday
            )
            top_stocks = [r['tradingsymbol'] for r in rankings] if rankings else []
            
            # 8. Record result
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
    
    def _get_business_days(self, start_date: date, end_date: date) -> List[date]:
        """Get business days (Mon-Fri) between start and end dates inclusive."""
        days = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:  # Mon=0 .. Fri=4
                days.append(current)
            current += timedelta(days=1)
        return days
    
    def _process_daily_stoploss(self, monday: date, friday: date,
                                 already_sold: set = None) -> set:
        """
        Process hybrid daily stop-loss checks for all held positions.
        
        Two-tier SL logic:
        1. Hard SL (intraday): If daily low < SL * (1 - hard_sl_percent)
           → immediate disaster exit at the hard SL price.
        2. Close-based SL: If daily close < SL
           → queue for sell at next trading day's open.
        
        Pending close-based sells from the previous day are executed
        at today's open before new checks run.
        
        Parameters:
            monday: Monday of the current week
            friday: Friday of the current week
            already_sold: Symbols already sold by Monday's
                generate_actions (skip these)
        
        Returns:
            Set of symbols with pending close-based SL sells
            from the last day (Friday) that need to be executed
            at next Monday's open.
        """
        business_days = self._get_business_days(monday, friday)
        
        # Track all symbols sold this week to prevent duplicate SL sells
        sold_this_week = set(already_sold) if already_sold else set()
        
        # Symbols pending close-based SL sell (execute at next day's open)
        pending_close_sl: set = set()
        
        # Read hard_sl_percent from config, fallback to 5%
        hard_sl_pct = getattr(
            self.config, 'hard_sl_percent', 0.05
        )
        
        for day in business_days:
            # Get latest holdings
            current_holdings = self.inv_repo.get_holdings()
            if not current_holdings:
                continue
            
            sold_value = 0.0
            sold_today = set()
            
            # --- Phase 1: Execute pending close-based SL sells ---
            # These were triggered by yesterday's close < SL.
            # Sell at today's open price.
            if pending_close_sl:
                for h in current_holdings:
                    if h.symbol not in pending_close_sl:
                        continue
                    if h.symbol in sold_this_week:
                        continue
                    
                    open_price = self.data.get_open_price(
                        h.symbol, day
                    )
                    if open_price is None:
                        # No open price — fallback to previous close
                        open_price = float(h.current_price)
                    
                    logger.info(
                        f"PENDING SL SELL: {h.symbol} "
                        f"sold @ open {open_price:.2f} on {day} "
                        f"(close-based SL triggered previous day)"
                    )
                    
                    sell_action = {
                        'action_date': day,
                        'type': 'sell',
                        'reason': (
                            f'close-based stoploss sell at open on '
                            f'{day}'
                        ),
                        'symbol': h.symbol,
                        'units': h.units,
                        'prev_close': float(h.current_price),
                        'execution_price': open_price,
                        'capital': float(h.units) * open_price,
                        'status': 'Approved',
                        'sell_cost': calculate_round_trip_cost(
                            float(h.units) * open_price
                        ).get('sell_costs', 0),
                        'tax': 0
                    }
                    self.actions_repo.insert_action(sell_action)
                    sold_value += float(h.units) * open_price
                    sold_today.add(h.symbol)
                    sold_this_week.add(h.symbol)
                
                pending_close_sl = set()  # Clear after processing
            
            # --- Phase 2: Check each holding for SL breaches ---
            # Refresh holdings after pending sells
            if sold_today:
                current_holdings = self.inv_repo.get_holdings()
                if not current_holdings:
                    continue
            
            for h in current_holdings:
                if h.symbol in sold_this_week:
                    continue
                
                daily_low = self.data.get_low_price(h.symbol, day)
                if daily_low is None:
                    continue
                
                current_sl = float(h.current_sl)
                hard_sl_price = round(
                    current_sl * (1 - hard_sl_pct), 2
                )
                
                # Tier 1: Hard SL — intraday disaster exit
                if daily_low <= hard_sl_price:
                    logger.info(
                        f"HARD SL: {h.symbol} low "
                        f"{daily_low:.2f} <= hard SL "
                        f"{hard_sl_price:.2f} "
                        f"(SL={current_sl:.2f}, "
                        f"{hard_sl_pct*100:.0f}% buffer) on {day}"
                    )
                    
                    sell_action = {
                        'action_date': day,
                        'type': 'sell',
                        'reason': (
                            f'hard stoploss hit on {day} '
                            f'(low={daily_low:.2f})'
                        ),
                        'symbol': h.symbol,
                        'units': h.units,
                        'prev_close': float(h.current_price),
                        'execution_price': hard_sl_price,
                        'capital': (
                            float(h.units) * hard_sl_price
                        ),
                        'status': 'Approved',
                        'sell_cost': calculate_round_trip_cost(
                            float(h.units) * hard_sl_price
                        ).get('sell_costs', 0),
                        'tax': 0
                    }
                    self.actions_repo.insert_action(sell_action)
                    sold_value += float(h.units) * hard_sl_price
                    sold_today.add(h.symbol)
                    sold_this_week.add(h.symbol)
                    continue  # Skip close check — already sold
                
                # Tier 2: Close-based SL — sell at next day's open
                    daily_close = self.data.get_close_price(
                        h.symbol, day
                    )
                if daily_close is not None and (
                    daily_close < current_sl
                ):
                    logger.info(
                        f"CLOSE-BASED SL: {h.symbol} close "
                        f"{daily_close:.2f} < SL "
                        f"{current_sl:.2f} on {day} "
                        f"→ queued for sell at next open"
                    )
                    pending_close_sl.add(h.symbol)
            
            # --- Phase 3: Fill pending buys with freed capital ---
            if sold_today:
                pending_buys = self.actions_repo.get_pending_actions()
                if pending_buys:
                    summary = self.inv_repo.get_summary()
                    if summary:
                        available = (
                            float(summary.remaining_capital)
                            + sold_value
                        )
                    else:
                        available = sold_value
                    
                    for pending in pending_buys:
                        if pending.type != 'buy':
                            continue
                        
                        close_price = self.data.get_close_price(
                            pending.symbol, day
                        )
                        if close_price is None:
                            continue
                        
                        cost = pending.units * close_price
                        if cost <= available:
                            self.actions_repo.update_action({
                                'action_id': pending.action_id,
                                'status': 'Approved',
                                'execution_price': close_price,
                                'buy_cost': (
                                    calculate_round_trip_cost(
                                        cost
                                    ).get('buy_costs', 0)
                                ),
                                'tax': 0
                            })
                            available -= cost
                            logger.info(
                                f"DAILY FILL: {pending.symbol} "
                                f"{pending.units} units @ "
                                f"{close_price:.2f} on {day}"
                            )
            
            # --- Phase 4: Update holdings with day's close + trailing SL ---
            remaining_holdings = self.inv_repo.get_holdings()
            if not remaining_holdings:
                continue
            
            updated = []
            for h in remaining_holdings:
                if h.symbol in sold_this_week:
                    continue
                
                close_price = self.data.get_close_price(
                    h.symbol, day
                )
                if close_price is None:
                    close_price = float(h.current_price)
                
                atr = self.data.get_indicator(
                    'atrr_14', h.symbol, day
                )
                if atr is None:
                    atr = (
                        float(h.atr) if h.atr
                        else close_price * 0.02
                    )
                
                # MODIFIED: Do NOT update stop-loss daily.
                # Keep the same SL throughout the week (from Monday's update).
                # This aligns with Weekly Backtest logic while keeping Daily CHECKS.
                current_sl = float(h.current_sl) if h.current_sl else float(h.entry_sl)
                
                updated.append({
                    'symbol': h.symbol,
                    'date': day,
                    'entry_date': h.entry_date,
                    'entry_price': float(h.entry_price),
                    'units': h.units,
                    'atr': round(atr, 2),
                    'score': (
                        float(h.score) if h.score else 0
                    ),
                    'entry_sl': float(h.entry_sl),
                    'current_price': close_price,
                    'current_sl': current_sl
                })
            
            # Also add newly bought stocks (from pending fill)
            filled_today = False
            if sold_today:
                pending_filled = self.actions_repo.get_actions(day)
                if pending_filled is None:
                    pending_filled = []
                for pf in pending_filled:
                    if (
                        pf.type == 'buy'
                        and pf.status == 'Approved'
                    ):
                        existing_symbols = {
                            u['symbol'] for u in updated
                        }
                        if (
                            pf.symbol not in existing_symbols
                            and pf.symbol not in sold_this_week
                        ):
                            initial_sl = round(
                                float(pf.execution_price)
                                - float(pf.risk), 2
                            )
                            updated.append({
                                'symbol': pf.symbol,
                                'date': day,
                                'entry_date': day,
                                'entry_price': float(
                                    pf.execution_price
                                ),
                                'units': pf.units,
                                'atr': (
                                    float(pf.atr)
                                    if pf.atr else 0
                                ),
                                'score': 0,
                                'entry_sl': initial_sl,
                                'current_price': float(
                                    pf.execution_price
                                ),
                                'current_sl': initial_sl
                            })
                            filled_today = True
            
            if updated:
                self.inv_repo.delete_holdings(day)
                self.inv_repo.bulk_insert_holdings(updated)
                
                if sold_today or filled_today:
                    existing_summary = self.inv_repo.get_summary(
                        day
                    )
                    
                    start_cap_override = None
                    total_sold = sold_value
                    
                    if existing_summary:
                        start_cap_override = float(
                            existing_summary.starting_capital
                        )
                        total_sold += float(
                            existing_summary.sold
                        )
                    
                    summary_data = (
                        self.actions_service.get_summary(
                            updated,
                            total_sold,
                            override_starting_capital=(
                                start_cap_override
                            )
                        )
                    )
                    summary_data['date'] = day
                    self.inv_repo.insert_summary(summary_data)
        
        # Return any pending close-based SL sells from Friday
        # These will be executed at next Monday's open by run()
        return pending_close_sl
    
    def _execute_pending_sl_sells(
        self, pending_symbols: set, execution_date: date
    ) -> None:
        """
        Execute pending close-based SL sells from previous Friday.
        
        Sells at the opening price of execution_date (Monday).
        
        Parameters:
            pending_symbols: Symbols queued for sell
            execution_date: Date to execute (Monday open)
        """
        current_holdings = self.inv_repo.get_holdings()
        if not current_holdings:
            return
        
        sold_value = 0.0
        sold_symbols = set()
        
        for h in current_holdings:
            if h.symbol not in pending_symbols:
                continue
            
            open_price = self.data.get_open_price(
                h.symbol, execution_date
            )
            if open_price is None:
                open_price = float(h.current_price)
            
            logger.info(
                f"PENDING SL SELL (cross-week): {h.symbol} "
                f"sold @ open {open_price:.2f} on "
                f"{execution_date} "
                f"(close-based SL triggered last Friday)"
            )
            
            sell_action = {
                'action_date': execution_date,
                'type': 'sell',
                'reason': (
                    f'close-based stoploss sell at open on '
                    f'{execution_date} (from Friday)'
                ),
                'symbol': h.symbol,
                'units': h.units,
                'prev_close': float(h.current_price),
                'execution_price': open_price,
                'capital': float(h.units) * open_price,
                'status': 'Approved',
                'sell_cost': calculate_round_trip_cost(
                    float(h.units) * open_price
                ).get('sell_costs', 0),
                'tax': 0
            }
            self.actions_repo.insert_action(sell_action)
            sold_value += float(h.units) * open_price
            sold_symbols.add(h.symbol)
        
        if sold_symbols:
            # Delete previous holdings (e.g. Friday) so
            # process_actions can't fall back to stale data
            previous_date = current_holdings[0].date
            if previous_date != execution_date:
                self.inv_repo.delete_holdings(previous_date)

            # Update holdings: remove sold positions
            remaining = self.inv_repo.get_holdings()
            updated = []
            for h in remaining:
                if h.symbol in sold_symbols:
                    continue
                updated.append({
                    'symbol': h.symbol,
                    'date': execution_date,
                    'entry_date': h.entry_date,
                    'entry_price': float(h.entry_price),
                    'units': h.units,
                    'atr': float(h.atr) if h.atr else 0,
                    'score': (
                        float(h.score) if h.score else 0
                    ),
                    'entry_sl': float(h.entry_sl),
                    'current_price': float(h.current_price),
                    'current_sl': float(h.current_sl)
                })
            
            self.inv_repo.delete_holdings(execution_date)
            if updated:
                self.inv_repo.bulk_insert_holdings(updated)
            
            # Update summary
            existing_summary = self.inv_repo.get_summary(
                execution_date
            )
            start_cap_override = None
            total_sold = sold_value
            if existing_summary:
                start_cap_override = float(
                    existing_summary.starting_capital
                )
                total_sold += float(existing_summary.sold)
            
            summary_data = self.actions_service.get_summary(
                updated,
                total_sold,
                override_starting_capital=start_cap_override
            )
            summary_data['date'] = execution_date
            self.inv_repo.insert_summary(summary_data)
    
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
    #     actions_records = []
    #     for action in actions:
    #         if action.get('action_type') == 'SWAP':
    #             # Swap contains nested sell/buy
    #             sell = action.get('sell_details', {})
    #             buy = action.get('buy_details', {})
    #             actions_records.extend([
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
    #             actions_records.append({
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
    #     if actions_records:
    #         actions_repo = ActionsRepository(session=self.backtest_session)
    #         actions_repo.bulk_insert_actions(actions_records)
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


    def _correct_execution_prices(self, week_date: date) -> None:
        """
        Update pending actions to use Monday Open price instead of Friday Close.
        This provides more realistic backtest results for Weekly SL mode.
        """
        pending_actions = self.actions_repo.get_actions(week_date)
        if not pending_actions:
            return

        for action in pending_actions:
            if action.status != 'Pending':
                continue
            
            # Fetch Monday Open
            open_price = self.data.get_open_price(action.symbol, week_date)
            if open_price is None:
                continue # Keep Friday Close fallback
            
            updates = {
                'action_id': action.action_id,
                'status': action.status,
                'execution_price': open_price,
            }
            
            # Update derived fields
            # Note: For current logic, we update capital/cost but keep RISK constant (ATR based)
            # This means initial_sl will shift to (open - risk), maintaining volatility distance
            
            value = float(action.units) * open_price
            updates['capital'] = value
            
            costs = calculate_round_trip_cost(value)
            if action.type == 'buy':
                updates['buy_cost'] = costs.get('buy_costs', 0)
            elif action.type == 'sell':
                updates['sell_cost'] = costs.get('sell_costs', 0)
                
            self.actions_repo.update_action(updates)
            logger.info(f"Updated {action.symbol} {action.type}: price {action.execution_price} -> {open_price}")


def run_backtest(start_date: date, end_date: date, config_name: str = "momentum_config", check_daily_sl: bool = True):
    """
    Convenience function to run a backtest.
    
    Parameters:
        start_date: Start date for backtest
        end_date: End date for backtest
        config_name: config name for config lookup
        
    Returns:
        Tuple of (results, summary)
    """
    backtester = WeeklyBacktester(start_date, end_date, config_name, check_daily_sl)
    results = backtester.run()
    summary = backtester.get_summary()
    return results, summary

