"""
Backtest Runner

Simplified backtest engine that reuses ActionsService with DB injection.
All trading logic (generate/approve/process actions) is delegated to ActionsService
for consistency with live trading. Writes results to backtest.db.
"""
import os
import traceback
import pandas as pd

from flask import current_app
from typing import List
from datetime import date, datetime, timedelta

from config import setup_logger, TaxConfig
from models import BacktestResult
from utils import (calculate_transaction_costs, get_business_days,
                    DatabaseManager, calculate_all_metrics,
                   calculate_capital_gains_tax, get_week_starts, get_prev_friday,
                   get_friday_of_week)
from repositories import (InvestmentRepository, ActionsRepository, RankingRepository, IndicatorsRepository,
                          MarketDataRepository, ConfigRepository)
from services import ActionsService, InvestmentService


logger = setup_logger(name="BacktestRunner")


class WeeklyBacktester:
    """
    Weekly backtesting engine using ActionsService with DB injection.
    
    Delegates all trading logic to ActionsService (same code as live trading).
    Only keeps backtest-specific concerns: weekly loop, risk monitoring,
    and result tracking.
    """
    
    def __init__(self, start_date: date, end_date: date, config_name: str, check_daily_sl: bool = True, mid_week_buy: bool = True, enable_pyramiding: bool = False):
        self.start_date = start_date
        self.end_date = end_date
        self.config_name = config_name
        self.check_daily_sl = check_daily_sl
        self.mid_week_buy = mid_week_buy
        self.enable_pyramiding = enable_pyramiding
        
        # Load config from repository
        config_repo = ConfigRepository()
        self.config = config_repo.get_config(self.config_name)

        # Risk monitor and results tracking
        self.risk_monitor = BacktestRiskMonitor(self.config.initial_capital, start_date)
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
        self.ranking_repo = RankingRepository()
        self.inv_service = InvestmentService(session=self.backtest_session)
        self.inv_service.ensure_capital_events_seeded(seed_date=start_date)

    def _process_daily_stoploss(self, monday: date, friday: date) -> None:
        """
        Process daily stop-loss for the backtest week.

        Two phases per day:
          Phase 1 — Hard SL (intraday low breach): sell is dated D, approved and
                    processed immediately so capital is freed on the same day.
                    Symbols with a pending close-based sell from the previous day
                    are SKIPPED (they already have a sell queued for today).
          Phase 2 — Close-based SL (end-of-day breach): sell is dated D+1 by
                    ActionsService.check_daily_stoploss(), so it is picked up by
                    the *next* day's approve/process pass. The check runs on the
                    already-updated holdings (after Phase 1) to avoid acting on
                    positions that were already force-sold intraday.
        """
        business_days = get_business_days(monday, friday)
        hard_sl_pct = getattr(self.config, 'hard_sl_percent', 0.03)

        # Track symbols with pending close-based sells from yesterday's Phase 2.
        # Phase 1 on the next day must skip these to avoid duplicate sells.
        pending_close_sl_symbols: set = set()

        for day in business_days:
            logger.info(f"Processing Daily SL Check for {day}")
            md_prices = self.marketdata_repo.get_prices_for_all_stocks(
                {"start_date": day, "end_date": day}
            )
            if len(md_prices) < 500:
                logger.info(f"{day} is Market closed")
                continue

            # ── Fix 2: Set execution_price on pending close-based sells ─────
            # In live trading, execution_price is already known at order time.
            # In backtest, we set it here to the day's open price BEFORE
            # approve_all_actions runs, so approve doesn't need to look it up.
            if pending_close_sl_symbols:
                pending_actions = self.actions_repo.get_pending_actions()
                for pa in (pending_actions or []):
                    if pa.type == 'sell' and pa.symbol in pending_close_sl_symbols:
                        md_exec = self.marketdata_repo.get_marketdata_by_trading_symbol(pa.symbol, day)
                        if md_exec and md_exec.open:
                            self.actions_repo.update_action({
                                'action_id': pa.action_id,
                                'execution_price': float(md_exec.open)
                            })
                            logger.info(
                                f"Close-SL exec price set: {pa.symbol} → "
                                f"{float(md_exec.open):.2f} (open on {day})"
                            )

            # ── Phase 1: Hard SL (intraday low breach, same-day execution) ──────
            current_holdings = self.inv_repo.get_holdings()
            holding_map = {h.symbol: h for h in current_holdings}
            holding_map_before = set(holding_map)

            for h in current_holdings:
                # Fix 1: skip symbols that already have a pending close-based
                # sell from yesterday — they'll be processed in approve/process
                # below. Creating a hard SL sell too would cause zero-PnL chains.
                if h.symbol in pending_close_sl_symbols:
                    logger.info(
                        f"SKIP HARD SL: {h.symbol} already has pending "
                        f"close-based sell for {day}"
                    )
                    continue

                md = self.marketdata_repo.get_marketdata_by_trading_symbol(h.symbol, day)
                if md is None:
                    continue
                daily_low = md.low
                current_sl = float(h.current_sl)
                hard_sl_price = round(current_sl * (1 - hard_sl_pct), 2)

                if daily_low <= hard_sl_price:
                    # Bug 3: execute at min(daily_low, hard_sl_price) — if price
                    # gapped below hard SL, we fill at the actual low, not the
                    # threshold (conservative: assumes worst-case gap execution).
                    execution_price = round(min(float(daily_low), hard_sl_price), 2)
                    logger.info(
                        f"HARD SL: {h.symbol} low {daily_low:.2f} <= hard SL "
                        f"{hard_sl_price:.2f} (SL={current_sl:.2f}) on {day} "
                        f"→ executing at {execution_price:.2f}"
                    )
                    sell_action = {
                        'action_date': day,
                        'type': 'sell',
                        'reason': f'hard stoploss hit on {day} (low={daily_low:.2f})',
                        'symbol': h.symbol,
                        'units': h.units,
                        'prev_close': float(h.current_price),
                        'execution_price': execution_price,
                        'capital': float(h.units) * execution_price,
                        'status': 'Pending'
                    }
                    self.actions_repo.insert_action(sell_action)
                    del holding_map[h.symbol]

            # Approve and process hard SL sells + any pending close-based sells
            # from yesterday. This updates holdings in the DB before Phase 2.
            self.actions_service.approve_all_actions(day)
            self.actions_service.process_actions(day, midweek=(day != monday))

            # Clear yesterday's exclusions — they've been processed above.
            pending_close_sl_symbols.clear()

            # ── Phase 2: Close-based SL (end-of-day, executed next open) ─────────
            # Runs on the *updated* holdings after Phase 1, so already hard-SL'd
            # symbols are no longer held and won't be double-checked.
            # Skip Friday: generate_actions handles Friday close SL on Monday open.
            if day < friday:
                close_sells = self.actions_service.check_daily_stoploss(
                    day, mid_week_buy=self.mid_week_buy
                )
                if close_sells:
                    # Record symbols so Phase 1 skips them tomorrow
                    pending_close_sl_symbols = {s['symbol'] for s in close_sells}
                    logger.info(
                        f"{len(close_sells)} close-based SL sell(s) dated "
                        f"{close_sells[0]['action_date']} (processed next open)"
                    )


    def run(self) -> List[BacktestResult]:
        try:

            logger.info(f"Starting backtest: {self.start_date} to {self.end_date} (Daily SL: {self.check_daily_sl}, Mid-week Buy: {self.mid_week_buy})")
            logger.info(f"Config: capital={self.config.initial_capital}, "
                    f"max_positions={self.config.max_positions}, "
                    f"exit_threshold={self.config.exit_threshold}")
            
            week_starts = get_week_starts(self.start_date, self.end_date)
            for week_date in week_starts:
                logger.info(f"Processing week: {week_date}")
                
                rejected = self.actions_service.reject_pending_actions()
                if rejected:
                    logger.info(f"Rejected {rejected} pending actions from previous week")

                actions = self.actions_service.generate_actions(
                    week_date, skip_pending_check=True,
                    enable_pyramiding=self.enable_pyramiding
                )
                
                if not actions:
                    logger.info(f"No actions for {week_date}")
                else:
                    # 2. Capital-aware approval (sells always, buys if budget allows)
                    # monday_sold_symbols = set()
                    approved_count = self.actions_service.approve_all_actions(week_date)
                    logger.info(f"Approved {approved_count} actions for {week_date}")
                    
                    # 3. Process approved actions (updates holdings, creates summary)
                    week_holdings = self.actions_service.process_actions(week_date)
                    if week_holdings:
                        logger.info(f"Processed {len(week_holdings)} holdings for {week_date}")

                if self.check_daily_sl:
                    friday = get_friday_of_week(week_date)
                    self._process_daily_stoploss(week_date, friday)
                
                # 5. Track risk metrics from latest summary (after daily SL processing)
                summary = self.inv_repo.get_summary()
                if summary:
                    portfolio_value = float(summary.portfolio_value)
                else:
                    portfolio_value = self.config.initial_capital
                
                self.risk_monitor.update(portfolio_value, week_date)
                
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
                # Bug 21: use get_prev_friday() so holiday-adjusted week starts
                # (e.g. Tuesday) still resolve to the correct data Friday.
                ranking_friday = get_prev_friday(week_date)
                rankings_results = self.ranking_repo.get_top_n_by_date(self.config.max_positions, ranking_friday)
                if not rankings_results:
                    rankings = []
                else:
                    rankings =  [
                        {
                            'tradingsymbol': r.tradingsymbol,
                            'composite_score': float(r.composite_score)
                        }
                        for r in rankings_results
                    ]
                
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
            
            # Close all open positions on the last day of backtest
            self._close_open_positions()


            # Build trade list from DB for trade-level metrics
            self._build_trades_from_db()
            
            if self.weekly_results:
                logger.info(f"Backtest complete. Final value: {self.weekly_results[-1].portfolio_value}")
            else:
                logger.info("Backtest complete. No weekly results generated.")
            
            # Generate report file
            self._generate_report()
            
            return self.weekly_results
        except Exception as e:
            logger.error(f"Backtest failed: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    def _compute_costs_and_taxes(self, sell_trades):
        """
        Compute transaction costs and capital gains tax from completed sell trades.
        
        Shared helper used by both get_summary() and _generate_report() to avoid
        duplicating ~80 lines of identical logic.
        
        Returns:
            dict with cost/tax breakdown
        """
        
        tax_config = TaxConfig()

        total_buy_cost = 0.0
        total_sell_cost = 0.0
        total_stt = 0.0
        total_gst = 0.0
        total_stamp = 0.0
        total_brokerage = 0.0
        total_buy_value = 0.0
        total_sell_value = 0.0
        
        for t in sell_trades:
            buy_value = t.get('price', 0) * t.get('units', 0)
            sell_value = t.get('exit_price', 0) * t.get('units', 0)
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

        # --- Capital Gains Tax (yearly-offset: losses offset gains within same year) ---
        stcg_by_year = {}
        ltcg_by_year = {}
        stcg_gains = 0.0
        ltcg_gains = 0.0
        stcg_count = 0
        ltcg_count = 0
        
        for t in sell_trades:
            tax_info = calculate_capital_gains_tax(
                purchase_price=t.get('price', 0),
                current_price=t.get('exit_price', 0),
                purchase_date=t.get('entry_date'),
                current_date=t['exit_date'],
                quantity=t.get('units', 0)
            )
            pnl = t.get('pnl', 0)
            exit_d = t['exit_date']
            fy = exit_d.year if exit_d.month >= 4 else exit_d.year - 1

            if tax_info['tax_type'] == 'STCG':
                stcg_gains += pnl
                stcg_count += 1
                stcg_by_year[fy] = stcg_by_year.get(fy, 0.0) + pnl
            elif tax_info['tax_type'] == 'LTCG':
                ltcg_gains += pnl
                ltcg_count += 1
                ltcg_by_year[fy] = ltcg_by_year.get(fy, 0.0) + pnl
        
        stcg_total = sum(max(0.0, gain) * tax_config.stcg_rate for gain in stcg_by_year.values())
        ltcg_total = sum(max(0.0, gain - tax_config.ltcg_exemption) * tax_config.ltcg_rate for gain in ltcg_by_year.values())
        total_tax = stcg_total + ltcg_total

        return {
            'total_buy_cost': round(total_buy_cost, 2),
            'total_sell_cost': round(total_sell_cost, 2),
            'total_transaction_costs': round(total_costs, 2),
            'total_brokerage': round(total_brokerage, 2),
            'total_stt': round(total_stt, 2),
            'total_gst': round(total_gst, 2),
            'total_stamp': round(total_stamp, 2),
            'total_buy_value': round(total_buy_value, 2),
            'total_sell_value': round(total_sell_value, 2),
            'total_tax': round(total_tax, 2),
            'stcg_tax': round(stcg_total, 2),
            'ltcg_tax': round(ltcg_total, 2),
            'stcg_gains': round(stcg_gains, 2),
            'ltcg_gains': round(ltcg_gains, 2),
            'stcg_count': stcg_count,
            'ltcg_count': ltcg_count,
        }

    def get_summary(self) -> dict:
        """Get comprehensive backtest summary including costs and tax"""
        summary = self.risk_monitor.get_summary()
        
        sell_trades = [t for t in self.risk_monitor.trades if t.get('type') == 'SELL']
        cost_tax = self._compute_costs_and_taxes(sell_trades)

        final_value = summary.get('final_value', 0)
        initial_capital = summary.get('initial_capital', self.config.initial_capital)
        total_return_abs = final_value - initial_capital
        
        # NOTE: total_return_abs is GROSS return (before costs and tax).
        #       net_post_tax_return below is the NET figure.
        net_post_tax_return = total_return_abs - cost_tax['total_transaction_costs'] - cost_tax['total_tax']

        summary.update(cost_tax)
        summary.update({
            'net_post_tax_return': round(net_post_tax_return, 2),
            'net_post_tax_return_pct': round((net_post_tax_return / initial_capital) * 100, 2)
        })
        
        yoy_list = self._compute_yoy_returns()
        if yoy_list:
            summary['yearly_returns'] = yoy_list
            
        # Add open positions snapshot if available
        if hasattr(self, 'open_positions_snapshot') and self.open_positions_snapshot:
            summary['open_positions'] = self.open_positions_snapshot
        
        return summary

    def _compute_yoy_returns(self) -> list:
        """Compute year-on-year returns from risk_monitor equity curve."""
        if not self.risk_monitor.portfolio_dates:
            return []
        df_equity = pd.DataFrame({
            'date': pd.to_datetime(self.risk_monitor.portfolio_dates),
            'value': self.risk_monitor.portfolio_values
        })
        if df_equity.empty:
            return []
        df_equity['year'] = df_equity['date'].dt.year
        yearly_start = df_equity.groupby('year')['value'].first()
        yearly_end = df_equity.groupby('year')['value'].last()
        yearly_return = (yearly_end - yearly_start) / yearly_start * 100
        yoy_list = []
        for year in yearly_return.index:
            yoy_list.append({
                'year': int(year),
                'return_pct': round(yearly_return[year], 2),
                'pnl': round(yearly_end[year] - yearly_start[year], 2),
                'end_value': round(yearly_end[year], 2)
            })
        return yoy_list

    def _build_trades_from_db(self) -> None:
        """
        Build trade list from backtest DB actions.
        
        Matches each Approved sell to its corresponding buy via proper FIFO
        with remaining-unit tracking, so partial sells don't consume buy lots
        that are still needed by later sells (e.g. backtest_end_close).
        Populates self.risk_monitor.trades for trade-level metrics.
        """
        all_actions = self.actions_repo.get_all_approved_actions(ascending=True)

        self.risk_monitor.total_buys = sum(1 for a in all_actions if a.type == 'buy')
        self.risk_monitor.pyramid_buys = sum(1 for a in all_actions if a.type == 'buy' and a.reason == 'pyramid_add')
        
        # Build FIFO queues: symbol -> list of (action, remaining_units)
        # We keep track of how many units are left in each buy lot so that
        # a partial sell only consumes as many units as it needs — later sells
        # for the same symbol can then match against the remaining balance.
        buy_pool: dict = {}  # symbol -> list of [action, remaining_units]
        for a in all_actions:
            if a.type == 'buy':
                buy_pool.setdefault(a.symbol, []).append([a, int(a.units)])
        
        trades = []
        for a in all_actions:
            if a.type != 'sell':
                continue
            
            buys = buy_pool.get(a.symbol, [])
            units_to_match = int(a.units)
            
            # FIFO: build a list of (buy_action, units_consumed) for this sell
            matched: list = []  # list of (action, units_consumed)
            for slot in buys:
                if units_to_match <= 0:
                    break
                b, remaining = slot
                if b.action_date > a.action_date:
                    break
                consume = min(remaining, units_to_match)
                if consume <= 0:
                    continue
                matched.append((b, consume))
                slot[1] -= consume          # reduce remaining in the pool
                units_to_match -= consume
            
            # Remove fully consumed lots from the front of the queue
            while buys and buys[0][1] <= 0:
                buys.pop(0)
            
            if matched:
                total_cost = sum(float(b.execution_price) * consumed for b, consumed in matched)
                total_units = sum(consumed for _, consumed in matched)
                entry_price = total_cost / total_units if total_units else float(matched[0][0].execution_price)
                entry_date = matched[0][0].action_date
            else:
                # No matching buys found — record at cost=0 so the bad trade
                # is visible but doesn't inflate PnL (price=0 → PnL = exit value,
                # which would be wrong; flag with reason so it can be inspected)
                entry_price = float(a.execution_price) if a.execution_price else 0
                entry_date = a.action_date
                
            exit_price = float(a.execution_price) if a.execution_price else 0
            units = int(a.units)
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
            
            # Record BUY legs for XIRR cash-flow reconstruction
            for b, consumed in matched:
                trades.append({
                    'type': 'BUY',
                    'symbol': a.symbol,
                    'entry_date': b.action_date,
                    'price': float(b.execution_price),
                    'units': consumed,
                })
        
        self.risk_monitor.trades = trades
        logger.info(f"Built {len([t for t in trades if t['type'] == 'SELL'])} completed trades from DB")

    def _close_open_positions(self) -> None:
        """
        Force-close all open positions on the last day of the backtest.
        
        Snapshots the positions before closing them, then generates sell actions
        at the latest close price so all trades are realized for accurate PnL/STCG.
        """
        current_holdings = self.inv_repo.get_holdings()
        if not current_holdings:
            self.open_positions_snapshot = []
            return
        
        # Snapshot open positions before closing
        self.open_positions_snapshot = []
        for h in current_holdings:
            avg_price = float(getattr(h, 'avg_price', None) or h.entry_price)
            current_price = float(h.current_price)
            unrealized_pnl = (current_price - avg_price) * h.units
            self.open_positions_snapshot.append({
                'symbol': h.symbol,
                'entry_date': str(h.entry_date),
                'units': h.units,
                'entry_price': float(h.entry_price),
                'avg_price': avg_price,
                'current_price': current_price,
                'market_value': round(current_price * h.units, 2),
                'unrealized_pnl': round(unrealized_pnl, 2),
            })
        
        logger.info(f"Force-closing {len(current_holdings)} open positions on backtest end date {self.end_date}")
        
        # Generate sell actions for each open position at their last known close price
        close_date = self.end_date
        for h in current_holdings:
            # Use current_price from holding (already set to last Friday close within backtest period)
            close_price = float(h.current_price)
            
            sell_action = {
                'action_date': close_date,
                'type': 'sell',
                'reason': 'backtest_end_close',
                'symbol': h.symbol,
                'units': h.units,
                'prev_close': float(h.current_price),
                'execution_price': close_price,
                'capital': float(h.units) * close_price,
                'status': 'Pending',
            }
            self.actions_repo.insert_action(sell_action)
        
        # Approve and process the force-close sells
        self.actions_service.approve_all_actions(close_date)
        self.actions_service.process_actions(close_date)
        
        # Update risk monitor with final portfolio value (avoid duplicate if already recorded)
        summary = self.inv_repo.get_summary()
        if summary:
            last_recorded = self.risk_monitor.portfolio_dates[-1] if self.risk_monitor.portfolio_dates else None
            if last_recorded != close_date:
                self.risk_monitor.update(float(summary.portfolio_value), close_date)
        
        logger.info(f"Force-closed {len(current_holdings)} positions. All trades now realized.")

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
        lines.append(f'  Min Position (%)  : {self.config.min_position_percent}')
        lines.append(f'  Risk Threshold    : {self.config.risk_threshold}')
        lines.append(f'  Buffer Percent    : {self.config.buffer_percent}')
        lines.append(f'  Exit Threshold    : {self.config.exit_threshold}')
        lines.append(f'  SL Multiplier     : {self.config.sl_multiplier}')
        lines.append(f'  ATR Fallback Pct   : {self.config.atr_fallback_percent}')
        lines.append(f'  Pyramiding        : {"ON" if self.enable_pyramiding else "OFF"}')
        if self.enable_pyramiding:
            from config import PyramidConfig
            pcfg = PyramidConfig()
            lines.append(f'  Pyramid Fraction  : {pcfg.pyramid_fraction}')
        
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
        
        # --- Section 2.5: Year-on-Year Performance ---
        lines.append('')
        lines.append('[ YEAR-ON-YEAR PERFORMANCE ]')
        yoy_list = self._compute_yoy_returns()
        for entry in yoy_list:
            year = entry['year']
            ret = entry['return_pct']
            val_change = entry['pnl']
            end_val = entry['end_value']
            lines.append(f'  {year}              : {ret:>+10.2f}%  (PnL: {val_change:>+12,.2f} | End Val: {end_val:>12,.2f})')
        
        # --- Section 3: Trade Statistics ---
        lines.append('')
        lines.append('[ TRADE STATISTICS ]')
        lines.append(f'  Total Buys        : {getattr(self.risk_monitor, "total_buys", 0)}')
        lines.append(f'  Pyramid Buys      : {getattr(self.risk_monitor, "pyramid_buys", 0)}')
        lines.append(f'  Total Sells       : {len(sell_trades)}')
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
        
        # --- Section 4: Transaction Costs & Section 5: Tax (via shared helper) ---
        cost_tax = self._compute_costs_and_taxes(sell_trades)
        total_costs = cost_tax['total_transaction_costs']
        total_tax = cost_tax['total_tax']
        net_post_tax_return = total_return_abs - total_costs - total_tax
        
        lines.append('')
        lines.append('[ TRANSACTION COSTS ]')
        lines.append(f'  Total Buy Value   : {cost_tax["total_buy_value"]:>15,.2f}')
        lines.append(f'  Total Sell Value  : {cost_tax["total_sell_value"]:>15,.2f}')
        lines.append(f'  Total Turnover    : {(cost_tax["total_buy_value"] + cost_tax["total_sell_value"]):>15,.2f}')
        lines.append(f'  ---')
        lines.append(f'  Buy Side Costs    : {cost_tax["total_buy_cost"]:>15,.2f}')
        lines.append(f'  Sell Side Costs   : {cost_tax["total_sell_cost"]:>15,.2f}')
        lines.append(f'  Total Costs       : {total_costs:>15,.2f}')
        lines.append(f'  ---')
        lines.append(f'  Brokerage         : {cost_tax["total_brokerage"]:>15,.2f}')
        lines.append(f'  STT               : {cost_tax["total_stt"]:>15,.2f}')
        lines.append(f'  GST               : {cost_tax["total_gst"]:>15,.2f}')
        lines.append(f'  Stamp Duty        : {cost_tax["total_stamp"]:>15,.2f}')
        lines.append(f'  Cost as % Return  : {(total_costs / max(abs(total_return_abs), 1) * 100):>10.2f}%')
        
        lines.append('')
        lines.append('[ CAPITAL GAINS TAX ]')
        lines.append(f'  STCG Trades       : {cost_tax["stcg_count"]}')
        lines.append(f'  STCG Gains        : {cost_tax["stcg_gains"]:>15,.2f}')
        lines.append(f'  STCG Tax (20%)    : {cost_tax["stcg_tax"]:>15,.2f}')
        lines.append(f'  ---')
        lines.append(f'  LTCG Trades       : {cost_tax["ltcg_count"]}')
        lines.append(f'  LTCG Gains        : {cost_tax["ltcg_gains"]:>15,.2f}')
        lines.append(f'  LTCG Tax (12.5%)  : {cost_tax["ltcg_tax"]:>15,.2f}')
        lines.append(f'  ---')
        lines.append(f'  Total Tax         : {total_tax:>15,.2f}')
        lines.append(f'  Total Costs+Tax   : {(total_costs + total_tax):>15,.2f}')
        lines.append(f'  Net Post-Tax Ret  : {net_post_tax_return:>+15,.2f}')
        
        # --- Section 5.5: Open Positions at Backtest End ---
        if hasattr(self, 'open_positions_snapshot') and self.open_positions_snapshot:
            lines.append('')
            lines.append('[ OPEN POSITIONS AT BACKTEST END (force-closed) ]')
            lines.append(f'  {"Symbol":<20} {"Entry Date":>12} {"Units":>6} {"Avg Price":>10} {"Close Price":>12} {"Market Val":>12} {"Unrealized PnL":>15}')
            lines.append(f'  {"-"*20} {"-"*12} {"-"*6} {"-"*10} {"-"*12} {"-"*12} {"-"*15}')
            
            total_market_val = 0
            total_unrealized = 0
            for pos in sorted(self.open_positions_snapshot, key=lambda x: x['market_value'], reverse=True):
                lines.append(
                    f'  {pos["symbol"]:<20} '
                    f'{pos["entry_date"]:>12} '
                    f'{pos["units"]:>6} '
                    f'{pos["avg_price"]:>10,.2f} '
                    f'{pos["current_price"]:>12,.2f} '
                    f'{pos["market_value"]:>12,.2f} '
                    f'{pos["unrealized_pnl"]:>+15,.2f}'
                )
                total_market_val += pos['market_value']
                total_unrealized += pos['unrealized_pnl']
            
            lines.append(f'  {"-"*20} {"":>12} {"":>6} {"":>10} {"":>12} {"-"*12} {"-"*15}')
            lines.append(f'  {"TOTAL":<20} {"":>12} {"":>6} {"":>10} {"":>12} {total_market_val:>12,.2f} {total_unrealized:>+15,.2f}')
        
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


class BacktestingService:

    @staticmethod
    def run_backtest(start_date: date, end_date: date, config_name: str = "momentum_config",
                     check_daily_sl: bool = True, mid_week_buy: bool = True, run_label: str = None,
                     enable_pyramiding: bool = False):
        """
        Convenience function to run a backtest.
        
        Parameters:
            start_date: Start date for backtest
            end_date: End date for backtest
            config_name: config name for config lookup
            check_daily_sl: Enable daily stop-loss checks
            mid_week_buy: Enable mid-week vacancy fills
            run_label: Optional label/name for this run
            enable_pyramiding: Enable pyramid adds for winning positions
            
        Returns:
            Tuple of (results, summary, risk_monitor_data, report_path)
        """
        backtester = WeeklyBacktester(start_date, end_date, config_name, check_daily_sl, mid_week_buy, enable_pyramiding)
        results = backtester.run()
        summary = backtester.get_summary()
        
        # Build equity curve with dates
        portfolio_dates = [d.isoformat() if d else None for d in backtester.risk_monitor.portfolio_dates]
        portfolio_values = backtester.risk_monitor.portfolio_values
        equity_curve = [
            {"date": d, "value": v}
            for d, v in zip(portfolio_dates, portfolio_values)
        ]
        
        # Expose risk monitor data for charts/tables
        risk_monitor_data = {
            'trades': backtester.risk_monitor.trades,
            'portfolio_values': portfolio_values,
            'portfolio_dates': portfolio_dates,
            'equity_curve': equity_curve,
        }
        
        # The report path is returned by _generate_report, but that method is internal and called inside run().
        # We need to capture it. Let's make _generate_report store it in self.report_path
        report_path = getattr(backtester, 'report_path', None)
        
        # Read report text
        report_text = ""
        if report_path:
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    report_text = f.read()
            except Exception as e:
                logger.error(f"Failed to read report file {report_path}: {e}")
        
        # Auto-save to history
        try:
            from repositories import BacktestHistoryRepository
            history_repo = BacktestHistoryRepository()
            history_repo.save(
                config_name=config_name,
                start_date=start_date,
                end_date=end_date,
                check_daily_sl=check_daily_sl,
                mid_week_buy=mid_week_buy,
                summary=summary,
                equity_curve=equity_curve,
                trades=backtester.risk_monitor.trades,
                report_text=report_text,
                run_label=run_label,
            )
            logger.info("Backtest run saved to history")
        except Exception as e:
            logger.error(f"Failed to save backtest run to history: {e}")
        
        return results, summary, risk_monitor_data, report_path


class BacktestRiskMonitor:
    """
    Track risk metrics during backtest simulation.
    
    Monitors portfolio values, drawdown, and trade outcomes.
    """
    
    def __init__(self, initial_capital: float, start_date=None):
        self.initial_capital = initial_capital
        self.portfolio_values: List[float] = [initial_capital]
        self.portfolio_dates: List = [start_date]
        self.peak_value = initial_capital
        self.max_drawdown = 0.0
        self.trades: List[dict] = []
    
    def update(self, current_value: float, current_date=None) -> None:
        """Update metrics with new portfolio value"""
        self.portfolio_values.append(current_value)
        self.portfolio_dates.append(current_date)
        if current_value > self.peak_value:
            self.peak_value = current_value
        current_drawdown = (self.peak_value - current_value) / self.peak_value * 100
        self.max_drawdown = max(self.max_drawdown, current_drawdown)
    
    def record_trade(self, trade: dict) -> None:
        """Record a trade for later analysis"""
        self.trades.append(trade)
    
    def get_total_return(self) -> float:
        """Calculate total return percentage"""
        if not self.portfolio_values:
            return 0.0
        current = self.portfolio_values[-1]
        return ((current - self.initial_capital) / self.initial_capital) * 100
    
    def get_summary(self) -> dict:
        """Get comprehensive risk summary using metrics module"""
        # Build equity curve
        equity_curve = pd.Series(self.portfolio_values) if self.portfolio_values else pd.Series(dtype=float)

        # Bug 23: compute actual backtest duration so CAGR/Sharpe are annualised
        # correctly instead of defaulting to 1 year inside calculate_all_metrics.
        dates = [d for d in self.portfolio_dates if d is not None]
        if len(dates) >= 2:
            years = max((dates[-1] - dates[0]).days / 365.25, 0.01)
        else:
            years = 1.0

        # Use master metrics calculator
        metrics = calculate_all_metrics(
            equity_curve=equity_curve,
            trades=self.trades,
            initial_value=self.initial_capital,
            years=years
        )

        # Add fields not covered by metrics module
        metrics['initial_capital'] = self.initial_capital

        return metrics
