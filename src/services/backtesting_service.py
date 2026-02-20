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

from config import setup_logger
from models import BacktestResult
from utils import (calculate_transaction_costs, get_business_days,
                    DatabaseManager, calculate_all_metrics,
                   calculate_capital_gains_tax, get_week_mondays)
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
    
    def __init__(self, start_date: date, end_date: date, config_name: str, check_daily_sl: bool = True, mid_week_buy: bool = True):
        self.start_date = start_date
        self.end_date = end_date
        self.config_name = config_name
        self.check_daily_sl = check_daily_sl
        self.mid_week_buy = mid_week_buy
        
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

        business_days = get_business_days(monday, friday)
        hard_sl_pct = getattr(self.config, 'hard_sl_percent', 0.03)
        #TODO Parameterize this

        pending_close_sl: set = set()
        for day in business_days:
            logger.info(f"Processing Daily SL Check for {day}")
            day_sold_count = 0
            md_prices = self.marketdata_repo.get_prices_for_all_stocks(
                {"start_date": day,
                 "end_date": day
            })
            if len(md_prices) < 500:
                logger.info(f"{day} is Market closed")
                continue

            current_holdings = self.inv_repo.get_holdings() #TODO What is 100% Cash
            holding_map = {h.symbol: h for h in current_holdings}

            for symbol in pending_close_sl:
                h = holding_map[symbol]
                open_price = self.marketdata_repo.get_marketdata_by_trading_symbol(h.symbol, day).open
                if open_price is None:
                    open_price = float(h.current_price)

                logger.info(
                    f"PENDING SL SOLD: {h.symbol} "
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
                    'status': 'Pending',
                }
                self.actions_repo.insert_action(sell_action)
                del holding_map[h.symbol]
                day_sold_count += 1
            pending_close_sl = set()

            for h in current_holdings:
                if h.symbol not in holding_map:
                    continue
                daily_low = self.marketdata_repo.get_marketdata_by_trading_symbol(
                    h.symbol, day
                ).low

                current_sl = float(h.current_sl)
                hard_sl_price = round(current_sl * (1 - hard_sl_pct), 2)

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
                        'status': 'Pending'
                    }
                    self.actions_repo.insert_action(sell_action)
                    day_sold_count += 1
                    continue  # Skip close check — already sold

                # Tier 2: Close-based SL — sell at next day's open
                # Skip on Friday — generate_actions handles Friday close SL
                if day < friday:
                    daily_close = self.marketdata_repo.get_marketdata_by_trading_symbol(h.symbol, day).close
                    if daily_close is not None and (daily_close < current_sl):
                        logger.info(
                            f"CLOSE-BASED SL: {h.symbol} close "
                            f"{daily_close:.2f} < SL "
                            f"{current_sl:.2f} on {day} "
                            f"→ queued for sell at next open"
                        )
                        pending_close_sl.add(h.symbol)
                        del holding_map[h.symbol]

            if self.mid_week_buy and day_sold_count:
                current_holding_count = len(holding_map)
                has_vacancy = current_holding_count < self.config.max_positions

                if has_vacancy:
                    pending_buys = self.actions_repo.get_pending_buy_actions()
                    if pending_buys:
                        for pending in pending_buys:
                            close_price = self.marketdata_repo.get_marketdata_by_trading_symbol(pending.symbol, day).close
                            signal_price = float(pending.prev_close)
                            if signal_price > 0 and close_price > signal_price * 1.03:
                                logger.info(
                                    f"STALE BUY SKIP: {pending.symbol} "
                                    f"close {close_price:.2f} > "
                                    f"signal {signal_price:.2f} * 1.03 "
                                    f"= {signal_price * 1.03:.2f} on {day}"
                                )
                                continue
                            self.actions_repo.update_action({
                                'action_id': pending.action_id,
                                'action_date': day
                            })

            self.actions_service.approve_all_actions(day)
            if day == monday:
                midweek = False
            else:
                midweek = True
            self.actions_service.process_actions(day, midweek=midweek)

    def run(self) -> List[BacktestResult]:
        try:

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
                    friday = week_date + timedelta(days=4)
                    self._process_daily_stoploss(week_date, friday)
                
                # 5. Track risk metrics from latest summary
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
                ranking_friday = week_date - timedelta(days=3)
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
        lines.append(f'  ATR Fallback Pct   : {self.config.atr_fallback_percent}')
        
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


class BacktestingService:

    @staticmethod
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
            'portfolio_values': backtester.risk_monitor.portfolio_values,
            'portfolio_dates': [d.isoformat() if d else None for d in backtester.risk_monitor.portfolio_dates]
        }
        
        # The report path is returned by _generate_report, but that method is internal and called inside run().
        # We need to capture it. Let's make _generate_report store it in self.report_path
        report_path = getattr(backtester, 'report_path', None)
        
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
        
        # Use master metrics calculator
        metrics = calculate_all_metrics(
            equity_curve=equity_curve,
            trades=self.trades,
            initial_value=self.initial_capital
        )
        
        # Add fields not covered by metrics module
        metrics['initial_capital'] = self.initial_capital
        
        return metrics
