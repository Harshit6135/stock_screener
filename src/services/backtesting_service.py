"""
Backtest Runner

Simplified backtest engine that reuses ActionsService with DB injection.
All trading logic (generate/approve/process actions) is delegated to ActionsService
for consistency with live trading. Writes results to backtest.db.
"""
import os
import pandas as pd

from flask import current_app
from typing import List, Dict, Optional
from datetime import date, datetime, timedelta

from config import setup_logger
from models import BacktestResult, BacktestRiskMonitor
from utils import (calculate_round_trip_cost, calculate_transaction_costs, get_business_days,
                   calculate_position_size, DatabaseManager, calculate_all_metrics,
                   calculate_capital_gains_tax, get_week_mondays)
from repositories import (InvestmentRepository, ActionsRepository, RankingRepository, IndicatorsRepository,
                          MarketDataRepository, ConfigRepository)
from services import ActionsService, MarketDataService

logger = setup_logger(name="BacktestRunner")
ranking_repo = RankingRepository()
indicators_repo = IndicatorsRepository()
marketdata_repo = MarketDataRepository()
config_repo = ConfigRepository()


class BacktestDataProvider:
    """
    Data provider for backtesting using direct repository access.

    Replaces BacktestAPIClient to avoid HTTP overhead and circular
    dependency issues when running backtests within the same process.
    """

    def get_top_rankings(self, n: int, as_of_date: date) -> List[Dict]:
        """
        Get top N ranked stocks for a given date.

        Parameters:
            n: Number of top stocks to fetch
            as_of_date: Date for rankings

        Returns:
            List of dicts with tradingsymbol and composite_score
        """
        try:
            results = ranking_repo.get_top_n_by_date(n, as_of_date)
            if not results:
                return []
            return [
                {
                    'tradingsymbol': r.tradingsymbol,
                    'composite_score': float(r.composite_score)
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Failed to fetch rankings for {as_of_date}: {e}")
            return []

    def get_indicator(self, indicator_name: str, tradingsymbol: str,
                      as_of_date: date) -> Optional[float]:
        """
        Get a specific indicator value for a stock.

        Parameters:
            indicator_name: Name of indicator (e.g., 'atrr_14')
            tradingsymbol: Stock symbol
            as_of_date: Date for indicator

        Returns:
            Indicator value or None if not found
        """
        try:
            value = indicators_repo.get_indicator_by_tradingsymbol(
                indicator_name, tradingsymbol, as_of_date
            )
            return float(value) if value is not None else None
        except Exception as e:
            logger.warning(f"Failed to fetch {indicator_name} for {tradingsymbol}: {e}")
            return None

    def get_close_price(self, tradingsymbol: str, as_of_date: date) -> Optional[float]:
        """Get closing price for a stock on a date"""
        try:
            result = marketdata_repo.get_marketdata_by_trading_symbol(
                tradingsymbol, as_of_date
            )
            if result and hasattr(result, 'close'):
                return float(result.close)
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch close price for {tradingsymbol}: {e}")
            return None

    def get_open_price(self, tradingsymbol: str, as_of_date: date) -> Optional[float]:
        """Get opening price for a stock on a date.

        Parameters:
            tradingsymbol: Stock symbol
            as_of_date: Date for price lookup

        Returns:
            Opening price or None if not found
        """
        try:
            result = marketdata_repo.get_marketdata_by_trading_symbol(
                tradingsymbol, as_of_date
            )
            if result and hasattr(result, 'open'):
                return float(result.open)
            return None
        except Exception as e:
            logger.warning(
                f"Failed to fetch open price for {tradingsymbol}: {e}"
            )
            return None

    def get_daily_lows_in_range(self, tradingsymbol: str, start_date: date,
                                end_date: date) -> List[tuple]:
        """Get daily low prices for a stock across a date range.

        Returns a list of (date, low) tuples sorted ascending by date.
        Used for intra-week stop-loss checking.

        Parameters:
            tradingsymbol: Stock symbol
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)

        Returns:
            List of (date, low) tuples, sorted by date
        """
        try:
            results = marketdata_repo.query({
                'tradingsymbol': tradingsymbol,
                'start_date': start_date,
                'end_date': end_date,
            })
            if not results:
                return []
            daily_lows = [
                (r.date, float(r.low))
                for r in results
                if hasattr(r, 'low') and r.low is not None
            ]
            daily_lows.sort(key=lambda x: x[0])
            return daily_lows
        except Exception as e:
            logger.warning(
                f"Failed to fetch daily lows for {tradingsymbol} "
                f"({start_date} to {end_date}): {e}"
            )
            return []

    def get_low_price(self, tradingsymbol: str, as_of_date: date) -> Optional[float]:
        """Get low price for a stock on a date"""
        try:
            result = marketdata_repo.get_marketdata_by_trading_symbol(
                tradingsymbol, as_of_date
            )
            if result and hasattr(result, 'low'):
                return float(result.low)
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch low price for {tradingsymbol}: {e}")
            return None

    def get_trading_days(self, start_date: date, end_date: date) -> List[date]:
        """Get actual trading days from market data between start and end dates.

        Queries distinct dates from the market data table to get only days
        when the market was actually open (excludes weekends and holidays).
        Uses NIFTY 50 as reference since it trades every session.

        Parameters:
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)

        Returns:
            List of dates sorted ascending
        """
        try:
            from models import MarketDataModel
            from db import db
            results = db.session.query(
                MarketDataModel.date
            ).filter(
                MarketDataModel.tradingsymbol == 'NIFTY 50',
                MarketDataModel.date >= start_date,
                MarketDataModel.date <= end_date
            ).distinct().order_by(MarketDataModel.date.asc()).all()
            return [r[0] for r in results]
        except Exception as e:
            logger.warning(f"Failed to fetch trading days: {e}, falling back to business days")
            # Fallback: return Mon-Fri calendar days
            days = []
            current = start_date
            while current <= end_date:
                if current.weekday() < 5:
                    days.append(current)
                current += timedelta(days=1)
            return days

    def get_score(self, tradingsymbol: str, as_of_date: date) -> Optional[float]:
        """Get composite score for a stock on a date"""
        try:
            result = ranking_repo.get_by_symbol(tradingsymbol, as_of_date)
            if result and hasattr(result, 'composite_score'):
                return float(result.composite_score)
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch score for {tradingsymbol}: {e}")
            return None


class WeeklyBacktester:
    """
    Weekly backtesting engine using ActionsService with DB injection.
    
    Delegates all trading logic to ActionsService (same code as live trading).
    Only keeps backtest-specific concerns: weekly loop, risk monitoring,
    and result tracking.
    """
    
    def __init__(self, start_date: date, end_date: date, config_name: str, check_daily_sl: bool = True, mid_week_buy: bool = True):
        self.start_date = start_date
        self.end_date = end_date
        self.config_name = config_name
        self.check_daily_sl = check_daily_sl
        self.mid_week_buy = mid_week_buy
        
        # Load config from repository
        self.config = config_repo.get_config(self.config_name)


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
        self.marketdata_repo = MarketDataRepository()
        self.total_capital = self.inv_repo.get_total_capital(include_realized=True)

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
                continue  # Keep Friday Close fallback

            updates = {
                'action_id': action.action_id,
                'status': action.status,
                'execution_price': open_price,
            }

            value = float(action.units) * open_price
            updates['capital'] = value

            costs = calculate_round_trip_cost(value)
            if action.type == 'buy':
                updates['buy_cost'] = costs.get('buy_costs', 0)
            elif action.type == 'sell':
                updates['sell_cost'] = costs.get('sell_costs', 0)

            self.actions_repo.update_action(updates)
            logger.info(f"Updated {action.symbol} {action.type}: price {action.execution_price} -> {open_price}")

    def _process_daily_stoploss(self, monday: date, friday: date,
                                already_sold: set = None) -> None:

        business_days = get_business_days(monday, friday)
        sold_this_week = set(already_sold) if already_sold else set()

        hard_sl_pct = getattr(
            self.config, 'hard_sl_percent', 0.03
        )
        #TODO Parameterize this

        pending_close_sl: set = set()
        for day in business_days:
            md_prices = self.marketdata_repo.get_prices_for_all_stocks(
                {"start_date": day,
                 "end_date": day
            })
            if len(md_prices) < 500:
                logger.info(f"{day} is Market closed")
                continue

            current_holdings = self.inv_repo.get_holdings()
            if not current_holdings:
                continue

            sold_value = 0.0
            sold_today = set()

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
                pending_close_sl = set()

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
                        f"{hard_sl_pct * 100:.0f}% buffer) on {day}"
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
                # Skip on Friday — generate_actions handles Friday close SL
                is_friday = (day.weekday() == 4)
                if not is_friday:
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

            # --- Phase 3: Fill pending buys if vacancy exists ---
            # Only when mid_week_buy is enabled.
            # Check every day, not just on sell days — vacancy may exist
            # from a previous day's sell that wasn't filled yet.
            if self.mid_week_buy:
                current_holding_count = len([
                    h for h in (self.inv_repo.get_holdings() or [])
                    if h.symbol not in sold_this_week
                ])
                has_vacancy = current_holding_count < self.config.max_positions

                if has_vacancy:
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

                            # 3% stale buy guard: skip if price rallied
                            # too far above the signal price (prev_close
                            # from when the action was generated)
                            signal_price = float(pending.prev_close)
                            if signal_price > 0 and close_price > signal_price * 1.03:
                                logger.info(
                                    f"STALE BUY SKIP: {pending.symbol} "
                                    f"close {close_price:.2f} > "
                                    f"signal {signal_price:.2f} * 1.03 "
                                    f"= {signal_price * 1.03:.2f} on {day}"
                                )
                                continue

                            # Re-size if capital-constrained (units=0)
                            if pending.units == 0:
                                sizing = calculate_position_size(
                                    atr=float(pending.atr),
                                    current_price=float(close_price),
                                    total_capital=self.total_capital,
                                    remaining_capital=available,
                                    config=self.config
                                )
                                fill_units = sizing['shares']
                                if fill_units <= 0:
                                    continue
                                cost = fill_units * close_price
                            else:
                                fill_units = pending.units
                                cost = fill_units * close_price

                            if cost <= available:
                                self.actions_repo.update_action({
                                    'action_id': pending.action_id,
                                    'status': 'Approved',
                                    'execution_price': close_price,
                                    'units': fill_units,
                                    'buy_cost': (
                                        calculate_round_trip_cost(
                                            cost
                                        ).get('buy_costs', 0)
                                    ),
                                    'tax': 0
                                })
                                available -= cost
                                current_holding_count += 1
                                logger.info(
                                    f"DAILY FILL: {pending.symbol} "
                                    f"{fill_units} units @ "
                                    f"{close_price:.2f} on {day}"
                                )
                                # Stop filling if no more vacancies
                                if current_holding_count >= self.config.max_positions:
                                    break

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
            if self.mid_week_buy:
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

    def run(self) -> List[BacktestResult]:

        logger.info(f"Starting backtest: {self.start_date} to {self.end_date} (Daily SL: {self.check_daily_sl}, Mid-week Buy: {self.mid_week_buy})")
        logger.info(f"Config: capital={self.config.initial_capital}, "
                   f"max_positions={self.config.max_positions}, "
                   f"exit_threshold={self.config.exit_threshold}")
        
        mondays = get_week_mondays(self.start_date, self.end_date)
        for week_date in mondays:
            logger.info(f"Processing week: {week_date}")
            
            rejected = self.actions_service.reject_pending_actions()
            if rejected:
                logger.info(f"Rejected {rejected} pending actions from previous week")

            actions = self.actions_service.generate_actions(
                week_date, skip_pending_check=True
            )

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
            
            if self.check_daily_sl:
                friday = week_date + timedelta(days=4)
                self._process_daily_stoploss(
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
        
        # Build trade list from DB for trade-level metrics
        self._build_trades_from_db()
        
        if self.weekly_results:
            logger.info(f"Backtest complete. Final value: {self.weekly_results[-1].portfolio_value}")
        else:
            logger.info("Backtest complete. No weekly results generated.")
        
        # Generate report file
        self._generate_report()
        
        return self.weekly_results
    


    
    def get_summary(self) -> dict:
        """Get comprehensive backtest summary including costs and tax"""
        summary = self.risk_monitor.get_summary()
        
        # --- Transaction Costs ---
        sell_trades = [t for t in self.risk_monitor.trades if t.get('type') == 'SELL']
        total_buy_cost = 0.0
        total_sell_cost = 0.0
        total_stt = 0.0
        total_gst = 0.0
        total_stamp = 0.0
        total_brokerage = 0.0
        
        for t in sell_trades:
            buy_value = t.get('price', 0) * t.get('units', 0)
            sell_value = t.get('exit_price', 0) * t.get('units', 0)
            
            bc = calculate_transaction_costs(buy_value, 'buy')
            sc = calculate_transaction_costs(sell_value, 'sell')
            total_buy_cost += bc['total']
            total_sell_cost += sc['total']
            total_stt += bc['stt'] + sc['stt']
            total_gst += bc['gst'] + sc['gst']
            total_stamp += bc['stamp'] + sc['stamp']
            total_brokerage += bc['brokerage'] + sc['brokerage']
        
        total_costs = total_buy_cost + total_sell_cost

        # --- Capital Gains Tax ---
        stcg_total = 0.0
        ltcg_total = 0.0
        
        for t in sell_trades:
            if t.get('pnl', 0) <= 0:
                continue
            tax_info = calculate_capital_gains_tax(
                purchase_price=t.get('price', 0),
                current_price=t.get('exit_price', 0),
                purchase_date=t.get('entry_date'),
                current_date=t['exit_date'],
                quantity=t.get('units', 0)
            )
            if tax_info['tax_type'] == 'STCG':
                stcg_total += tax_info['tax']
            elif tax_info['tax_type'] == 'LTCG':
                ltcg_total += tax_info['tax']
        
        total_tax = stcg_total + ltcg_total
        final_value = summary.get('final_value', 0)
        initial_capital = summary.get('initial_capital', self.config.initial_capital)
        total_return_abs = final_value - initial_capital
        
        net_post_tax_return = total_return_abs - total_costs - total_tax

        summary.update({
            'total_buy_cost': round(total_buy_cost, 2),
            'total_sell_cost': round(total_sell_cost, 2),
            'total_transaction_costs': round(total_costs, 2),
            'total_brokerage': round(total_brokerage, 2),
            'total_stt': round(total_stt, 2),
            'total_gst': round(total_gst, 2),
            'total_stamp': round(total_stamp, 2),
            'total_tax': round(total_tax, 2),
            'stcg_tax': round(stcg_total, 2),
            'ltcg_tax': round(ltcg_total, 2),
            'net_post_tax_return': round(net_post_tax_return, 2),
            'net_post_tax_return_pct': round((net_post_tax_return / initial_capital) * 100, 2)
        })
        
        return summary

    def _build_trades_from_db(self) -> None:
        """
        Build trade list from backtest DB actions.
        
        Matches each Approved sell to its corresponding buy (same symbol,
        nearest earlier date). Populates self.risk_monitor.trades for
        trade-level metrics (win rate, profit factor, XIRR, etc.).
        """
        from models import ActionsModel
        all_actions = (
            self.backtest_session.query(ActionsModel)
            .filter(ActionsModel.status == 'Approved')
            .order_by(ActionsModel.action_date)
            .all()
        )
        
        # Index buys by symbol (most recent first for matching)
        buy_pool = {}  # symbol -> list of buy actions
        for a in all_actions:
            if a.type == 'buy':
                buy_pool.setdefault(a.symbol, []).append(a)
        
        trades = []
        for a in all_actions:
            if a.type != 'sell':
                continue
            
            # Find matching buy (earliest unmatched buy for same symbol)
            buys = buy_pool.get(a.symbol, [])
            matched_buy = None
            for i, b in enumerate(buys):
                if b.action_date <= a.action_date:
                    matched_buy = buys.pop(i)
                    break
            
            entry_price = float(matched_buy.execution_price) if matched_buy else 0
            exit_price = float(a.execution_price) if a.execution_price else 0
            units = int(a.units)
            entry_date = matched_buy.action_date if matched_buy else a.action_date
            exit_date = a.action_date
            pnl = (exit_price - entry_price) * units
            
            trades.append({
                'type': 'SELL',
                'symbol': a.symbol,
                'entry_date': entry_date,
                'exit_date': exit_date,
                'price': entry_price,
                'exit_price': exit_price,
                'units': units,
                'pnl': round(pnl, 2),
                'reason': a.reason or '',
            })
            
            # Also record the BUY leg for XIRR cash flow
            if matched_buy:
                trades.append({
                    'type': 'BUY',
                    'symbol': a.symbol,
                    'entry_date': entry_date,
                    'price': entry_price,
                    'units': units,
                })
        
        self.risk_monitor.trades = trades
        logger.info(f"Built {len([t for t in trades if t['type'] == 'SELL'])} completed trades from DB")

    def _generate_report(self) -> None:
        """
        Generate comprehensive backtest report and save to backtesting_results/.
        
        Includes: config, all metrics, transaction costs, trade log.
        """
        # Create output directory
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        report_dir = os.path.join(project_root, 'backtesting_results')
        os.makedirs(report_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        sl_tag = 'daily_sl' if self.check_daily_sl else 'weekly_sl'
        mwb_tag = 'mwb_on' if self.mid_week_buy else 'mwb_off'
        filename = f"{self.config_name}_{self.start_date}_{self.end_date}_{sl_tag}_{mwb_tag}_{timestamp}.txt"
        filepath = os.path.join(report_dir, filename)
        
        lines = []
        sep = '=' * 70
        lines.append(sep)
        lines.append('  BACKTEST RESULTS REPORT')
        lines.append(f'  Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        lines.append(sep)
        
        # --- Section 1: Configuration ---
        lines.append('')
        lines.append('[ CONFIGURATION ]')
        lines.append(f'  Config Name       : {self.config_name}')
        lines.append(f'  Start Date        : {self.start_date}')
        lines.append(f'  End Date          : {self.end_date}')
        lines.append(f'  Daily SL          : {self.check_daily_sl}')
        lines.append(f'  Mid-Week Buy      : {self.mid_week_buy}')
        lines.append(f'  Initial Capital   : {self.config.initial_capital:>15,.2f}')
        lines.append(f'  Max Positions     : {self.config.max_positions}')
        lines.append(f'  Risk Threshold    : {self.config.risk_threshold}')
        lines.append(f'  Buffer Percent    : {self.config.buffer_percent}')
        lines.append(f'  Exit Threshold    : {self.config.exit_threshold}')
        lines.append(f'  SL Multiplier     : {self.config.sl_multiplier}')
        lines.append(f'  SL Step Percent   : {self.config.sl_step_percent}')
        lines.append(f'  SL Fallback Pct   : {self.config.sl_fallback_percent}')
        
        # --- Section 2: Performance Metrics ---
        equity_curve = pd.Series(self.risk_monitor.portfolio_values)
        sell_trades = [t for t in self.risk_monitor.trades if t.get('type') == 'SELL']
        
        # Calculate duration in years
        total_days = (self.end_date - self.start_date).days
        years = max(total_days / 365.25, 0.01)
        
        metrics = calculate_all_metrics(
            equity_curve=equity_curve,
            trades=self.risk_monitor.trades,
            initial_value=self.config.initial_capital,
            years=years
        )
        
        final_value = self.risk_monitor.portfolio_values[-1] if self.risk_monitor.portfolio_values else self.config.initial_capital
        total_return_abs = final_value - self.config.initial_capital
        
        lines.append('')
        lines.append('[ PERFORMANCE METRICS ]')
        lines.append(f'  Final Portfolio   : {final_value:>15,.2f}')
        lines.append(f'  Total Return      : {total_return_abs:>+15,.2f}  ({metrics.get("total_return", 0):+.2f}%)')
        lines.append(f'  CAGR              : {metrics.get("cagr", 0):>+10.2f}%')
        lines.append(f'  XIRR              : {metrics.get("xirr", 0):>+10.2f}%')
        lines.append(f'  Max Drawdown      : {metrics.get("max_drawdown", 0):>10.2f}%')
        lines.append(f'  Sharpe Ratio      : {metrics.get("sharpe_ratio", 0):>10.2f}')
        lines.append(f'  Sortino Ratio     : {metrics.get("sortino_ratio", 0):>10.2f}')
        lines.append(f'  Calmar Ratio      : {metrics.get("calmar_ratio", 0):>10.2f}')
        
        # --- Section 3: Trade Statistics ---
        lines.append('')
        lines.append('[ TRADE STATISTICS ]')
        lines.append(f'  Total Trades      : {len(sell_trades)}')
        lines.append(f'  Win Rate          : {metrics.get("win_rate", 0):>10.2f}%')
        lines.append(f'  Profit Factor     : {metrics.get("profit_factor", 0):>10.2f}')
        lines.append(f'  Expectancy/Trade  : {metrics.get("expectancy", 0):>+10.2f}')
        lines.append(f'  Avg Holding Days  : {metrics.get("avg_holding_period_days", 0):>10.1f}')
        
        if sell_trades:
            winning = [t for t in sell_trades if t['pnl'] > 0]
            losing = [t for t in sell_trades if t['pnl'] <= 0]
            avg_win = sum(t['pnl'] for t in winning) / len(winning) if winning else 0
            avg_loss = sum(t['pnl'] for t in losing) / len(losing) if losing else 0
            best_trade = max(sell_trades, key=lambda t: t['pnl'])
            worst_trade = min(sell_trades, key=lambda t: t['pnl'])
            
            lines.append(f'  Winners           : {len(winning)}')
            lines.append(f'  Losers            : {len(losing)}')
            lines.append(f'  Avg Win           : {avg_win:>+15,.2f}')
            lines.append(f'  Avg Loss          : {avg_loss:>+15,.2f}')
            lines.append(f'  Best Trade        : {best_trade["symbol"]} {best_trade["pnl"]:>+,.2f}')
            lines.append(f'  Worst Trade       : {worst_trade["symbol"]} {worst_trade["pnl"]:>+,.2f}')
        
        # --- Section 4: Transaction Costs (calculated from trades) ---
        total_buy_cost = 0.0
        total_sell_cost = 0.0
        total_buy_value = 0.0
        total_sell_value = 0.0
        total_stt = 0.0
        total_gst = 0.0
        total_stamp = 0.0
        total_brokerage = 0.0
        
        for t in sell_trades:
            buy_value = t['price'] * t['units']
            sell_value = t['exit_price'] * t['units']
            total_buy_value += buy_value
            total_sell_value += sell_value
            
            bc = calculate_transaction_costs(buy_value, 'buy')
            sc = calculate_transaction_costs(sell_value, 'sell')
            total_buy_cost += bc['total']
            total_sell_cost += sc['total']
            total_stt += bc['stt'] + sc['stt']
            total_gst += bc['gst'] + sc['gst']
            total_stamp += bc['stamp'] + sc['stamp']
            total_brokerage += bc['brokerage'] + sc['brokerage']
        
        total_costs = total_buy_cost + total_sell_cost
        
        lines.append('')
        lines.append('[ TRANSACTION COSTS ]')
        lines.append(f'  Total Buy Value   : {total_buy_value:>15,.2f}')
        lines.append(f'  Total Sell Value  : {total_sell_value:>15,.2f}')
        lines.append(f'  Total Turnover    : {(total_buy_value + total_sell_value):>15,.2f}')
        lines.append(f'  ---')
        lines.append(f'  Buy Side Costs    : {total_buy_cost:>15,.2f}')
        lines.append(f'  Sell Side Costs   : {total_sell_cost:>15,.2f}')
        lines.append(f'  Total Costs       : {total_costs:>15,.2f}')
        lines.append(f'  ---')
        lines.append(f'  Brokerage         : {total_brokerage:>15,.2f}')
        lines.append(f'  STT               : {total_stt:>15,.2f}')
        lines.append(f'  GST               : {total_gst:>15,.2f}')
        lines.append(f'  Stamp Duty        : {total_stamp:>15,.2f}')
        lines.append(f'  Cost as % Return  : {(total_costs / max(abs(total_return_abs), 1) * 100):>10.2f}%')
        
        # --- Section 5: Capital Gains Tax ---
        stcg_total = 0.0
        ltcg_total = 0.0
        stcg_gains = 0.0
        ltcg_gains = 0.0
        stcg_count = 0
        ltcg_count = 0
        
        for t in sell_trades:
            if t['pnl'] <= 0:
                continue
            tax_info = calculate_capital_gains_tax(
                purchase_price=t['price'],
                current_price=t['exit_price'],
                purchase_date=t['entry_date'],
                current_date=t['exit_date'],
                quantity=t['units']
            )
            if tax_info['tax_type'] == 'STCG':
                stcg_total += tax_info['tax']
                stcg_gains += tax_info['gain']
                stcg_count += 1
            elif tax_info['tax_type'] == 'LTCG':
                ltcg_total += tax_info['tax']
                ltcg_gains += tax_info['gain']
                ltcg_count += 1
        
        total_tax = stcg_total + ltcg_total
        net_post_tax_return = total_return_abs - total_costs - total_tax
        
        lines.append('')
        lines.append('[ CAPITAL GAINS TAX ]')
        lines.append(f'  STCG Trades       : {stcg_count}')
        lines.append(f'  STCG Gains        : {stcg_gains:>15,.2f}')
        lines.append(f'  STCG Tax (20%)    : {stcg_total:>15,.2f}')
        lines.append(f'  ---')
        lines.append(f'  LTCG Trades       : {ltcg_count}')
        lines.append(f'  LTCG Gains        : {ltcg_gains:>15,.2f}')
        lines.append(f'  LTCG Tax (12.5%)  : {ltcg_total:>15,.2f}')
        lines.append(f'  ---')
        lines.append(f'  Total Tax         : {total_tax:>15,.2f}')
        lines.append(f'  Total Costs+Tax   : {(total_costs + total_tax):>15,.2f}')
        lines.append(f'  Net Post-Tax Ret  : {net_post_tax_return:>+15,.2f}')
        
        # --- Section 6: Trade Log ---
        lines.append('')
        lines.append('[ TRADE LOG ]')
        lines.append(f'  {"Symbol":<20} {"Entry":>12} {"Exit":>12} {"Entry ₹":>10} {"Exit ₹":>10} {"Units":>6} {"PnL":>12} {"Reason"}')
        lines.append(f'  {"-"*20} {"-"*12} {"-"*12} {"-"*10} {"-"*10} {"-"*6} {"-"*12} {"-"*20}')
        
        for t in sorted(sell_trades, key=lambda x: x['exit_date']):
            lines.append(
                f'  {t["symbol"]:<20} '
                f'{str(t["entry_date"]):>12} '
                f'{str(t["exit_date"]):>12} '
                f'{t["price"]:>10,.2f} '
                f'{t["exit_price"]:>10,.2f} '
                f'{t["units"]:>6} '
                f'{t["pnl"]:>+12,.2f} '
                f'{t.get("reason", "")}'
            )
        
        lines.append('')
        lines.append(sep)
        lines.append(f'  Weeks Simulated: {len(self.weekly_results)} | '
                     f'Duration: {total_days} days ({years:.2f} years)')
        lines.append(sep)
        
        # Write file
        report_content = '\n'.join(lines)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        logger.info(f"Report saved: {filepath}")
        self.report_path = filepath
        return filepath
    
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





def run_backtest(start_date: date, end_date: date, config_name: str = "momentum_config", check_daily_sl: bool = True, mid_week_buy: bool = True):
    """
    Convenience function to run a backtest.
    
    Parameters:
        start_date: Start date for backtest
        end_date: End date for backtest
        config_name: config name for config lookup
        check_daily_sl: Enable daily stop-loss checks
        mid_week_buy: Enable mid-week vacancy fills
        
    Returns:
        Tuple of (results, summary, risk_monitor_data, report_path)
    """
    backtester = WeeklyBacktester(start_date, end_date, config_name, check_daily_sl, mid_week_buy)
    results = backtester.run()
    summary = backtester.get_summary()
    
    # Expose risk monitor data for charts/tables
    risk_monitor_data = {
        'trades': backtester.risk_monitor.trades,
        'portfolio_values': backtester.risk_monitor.portfolio_values
    }
    
    # The report path is returned by _generate_report, but that method is internal and called inside run().
    # We need to capture it. Let's make _generate_report store it in self.report_path
    report_path = getattr(backtester, 'report_path', None)
    
    return results, summary, risk_monitor_data, report_path

