"""
Backtest Runner

Simplified backtest engine that reuses the split action services with DB injection.
All trading logic (generate/approve/process actions) is delegated to the focused
ActionGenerator / ActionLifecycle / ActionProcessor classes for consistency with
live trading. Writes results to backtest.db.
"""

import os
import traceback
from datetime import date, datetime
from typing import List

import pandas as pd
from flask import current_app

from config import TaxConfig, setup_logger
from models import BacktestResult
from repositories import (
    ActionsRepository,
    ConfigRepository,
    InvestmentRepository,
    MarketDataRepository,
    RankingRepository,
)
from services.action_generator import ActionGenerator
from services.action_lifecycle import ActionLifecycle
from services.action_processor import ActionProcessor
from services.backtest_report_builder import BacktestReportBuilder
from services.investment_service import InvestmentService
from utils import (
    DatabaseManager,
    FIFOTradeTracker,
    calculate_all_metrics,
    calculate_capital_gains_tax,
    calculate_transaction_costs,
    compute_trade_costs_and_taxes,
    get_business_days,
    get_friday_of_week,
    get_prev_friday,
    get_week_starts,
)

logger = setup_logger(name="BacktestRunner")


class WeeklyBacktester:
    """
    Weekly backtesting engine using split action services with DB injection.

    Delegates all trading logic to ActionGenerator / ActionLifecycle /
    ActionProcessor (same code paths as live trading).
    Only keeps backtest-specific concerns: weekly loop, risk monitoring,
    and result tracking.
    """

    def __init__(
        self,
        start_date: date,
        end_date: date,
        config_name: str,
        check_daily_sl: bool = True,
        mid_week_buy: bool = True,
        enable_pyramiding: bool = False,
        strategy_id: str = "strategy1",
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.config_name = config_name
        self.check_daily_sl = check_daily_sl
        self.mid_week_buy = mid_week_buy
        self.enable_pyramiding = enable_pyramiding
        self.strategy_id = strategy_id

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
        self.generator = ActionGenerator(
            config_name=self.config_name,
            session=self.backtest_session,
            config_info=self.config,
            strategy_id=self.strategy_id,
        )
        self.lifecycle = ActionLifecycle(
            config_name=self.config_name, session=self.backtest_session, config_info=self.config
        )
        self.processor = ActionProcessor(
            config_name=self.config_name, session=self.backtest_session, config_info=self.config
        )
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
        hard_sl_pct = getattr(self.config, "hard_sl_percent", 0.03)

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
                for pa in pending_actions or []:
                    if pa.type == "sell" and pa.symbol in pending_close_sl_symbols:
                        md_exec = self.marketdata_repo.get_marketdata_by_trading_symbol(
                            pa.symbol, day
                        )
                        if md_exec and md_exec.open:
                            self.actions_repo.update_action(
                                {"action_id": pa.action_id, "execution_price": float(md_exec.open)}
                            )
                            logger.info(
                                f"Close-SL exec price set: {pa.symbol} → "
                                f"{float(md_exec.open):.2f} (open on {day})"
                            )

            # ── Phase 1: Hard SL (intraday low breach, same-day execution) ──────
            current_holdings = self.inv_repo.get_holdings()
            holding_map = {h.symbol: h for h in current_holdings}

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
                        "action_date": day,
                        "type": "sell",
                        "reason": f"hard stoploss hit on {day} (low={daily_low:.2f})",
                        "symbol": h.symbol,
                        "units": h.units,
                        "prev_close": float(h.current_price),
                        "execution_price": execution_price,
                        "capital": float(h.units) * execution_price,
                        "status": "Pending",
                    }
                    self.actions_repo.insert_action(sell_action)
                    del holding_map[h.symbol]

            # Approve and process hard SL sells + any pending close-based sells
            # from yesterday. This updates holdings in the DB before Phase 2.
            self.lifecycle.approve_all_actions(day)
            self.processor.process_actions(day, midweek=(day != monday))

            # Clear yesterday's exclusions — they've been processed above.
            pending_close_sl_symbols.clear()

            # ── Phase 2: Close-based SL (end-of-day, executed next open) ─────────
            # Runs on the *updated* holdings after Phase 1, so already hard-SL'd
            # symbols are no longer held and won't be double-checked.
            # Skip Friday: generate_actions handles Friday close SL on Monday open.
            if day < friday:
                close_sells = self.generator.check_daily_stoploss(
                    day, mid_week_buy=self.mid_week_buy
                )
                if close_sells:
                    # Record symbols so Phase 1 skips them tomorrow
                    pending_close_sl_symbols = {s["symbol"] for s in close_sells}
                    logger.info(
                        f"{len(close_sells)} close-based SL sell(s) dated "
                        f"{close_sells[0]['action_date']} (processed next open)"
                    )

    def run(self) -> List[BacktestResult]:
        try:

            logger.info(
                f"Starting backtest: {self.start_date} to {self.end_date} (Daily SL: {self.check_daily_sl}, Mid-week Buy: {self.mid_week_buy})"
            )
            logger.info(
                f"Config: capital={self.config.initial_capital}, "
                f"max_positions={self.config.max_positions}, "
                f"exit_threshold={self.config.exit_threshold}"
            )

            week_starts = get_week_starts(self.start_date, self.end_date)
            for week_date in week_starts:
                logger.info(f"Processing week: {week_date}")

                rejected = self.lifecycle.reject_pending_actions()
                if rejected:
                    logger.info(f"Rejected {rejected} pending actions from previous week")

                actions = self.generator.generate_actions(
                    week_date, skip_pending_check=True, enable_pyramiding=self.enable_pyramiding
                )

                if not actions:
                    logger.info(f"No actions for {week_date}")
                else:
                    # 2. Capital-aware approval (sells always, buys if budget allows)
                    # monday_sold_symbols = set()
                    approved_count = self.lifecycle.approve_all_actions(week_date)
                    logger.info(f"Approved {approved_count} actions for {week_date}")

                    # 3. Process approved actions (updates holdings, creates summary)
                    week_holdings = self.processor.process_actions(week_date)
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
                            "symbol": h.symbol,
                            "units": h.units,
                            "entry_price": float(h.entry_price),
                            "current_price": float(h.current_price),
                            "current_sl": float(h.current_sl),
                        }
                        for h in current_holdings
                    ]

                # 7. Fetch top rankings for the result record
                # Bug 21: use get_prev_friday() so holiday-adjusted week starts
                # (e.g. Tuesday) still resolve to the correct data Friday.
                ranking_friday = get_prev_friday(week_date)
                rankings_results = self.ranking_repo.get_top_n_by_date(
                    self.config.max_positions, ranking_friday
                )
                if not rankings_results:
                    rankings = []
                else:
                    rankings = [
                        {
                            "tradingsymbol": r.tradingsymbol,
                            "composite_score": float(r.composite_score),
                        }
                        for r in rankings_results
                    ]

                top_stocks = [r["tradingsymbol"] for r in rankings] if rankings else []

                # 8. Record result
                result = BacktestResult(
                    week_date=week_date,
                    portfolio_value=portfolio_value,
                    total_return=self.risk_monitor.get_total_return(),
                    max_drawdown=self.risk_monitor.max_drawdown,
                    actions=actions if isinstance(actions, list) else [],
                    top_10_stocks=top_stocks,
                    holdings=holdings_snapshot,
                )
                self.weekly_results.append(result)

            # Close all open positions on the last day of backtest
            self._close_open_positions()

            # Build trade list from DB for trade-level metrics
            self._build_trades_from_db()

            if self.weekly_results:
                logger.info(
                    f"Backtest complete. Final value: {self.weekly_results[-1].portfolio_value}"
                )
            else:
                logger.info("Backtest complete. No weekly results generated.")

            # Generate report via dedicated builder (P4)
            builder = BacktestReportBuilder(
                config=self.config,
                config_name=self.config_name,
                start_date=self.start_date,
                end_date=self.end_date,
                check_daily_sl=self.check_daily_sl,
                mid_week_buy=self.mid_week_buy,
                enable_pyramiding=self.enable_pyramiding,
                portfolio_values=self.risk_monitor.portfolio_values,
                portfolio_dates=self.risk_monitor.portfolio_dates,
                trades=self.risk_monitor.trades,
                weekly_results=self.weekly_results,
                open_positions_snapshot=getattr(self, "open_positions_snapshot", []),
                total_buys=getattr(self.risk_monitor, "total_buys", 0),
                pyramid_buys=getattr(self.risk_monitor, "pyramid_buys", 0),
            )
            self._report_builder = builder
            self.report_path = builder.build()

            return self.weekly_results
        except Exception as e:
            logger.error(f"Backtest failed: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    def _compute_costs_and_taxes(self, sell_trades):
        """
        Compute transaction costs and capital gains tax from completed sell trades.

        Delegates to the shared ``compute_trade_costs_and_taxes`` utility in
        tax_utils so that the backtest and any future live summary use identical
        FY-netting logic.  Kept as a method for backward-compatible call sites
        inside this class (get_summary, _generate_report).
        """
        return compute_trade_costs_and_taxes(sell_trades)

    def get_summary(self) -> dict:
        """Get comprehensive backtest summary including costs and tax"""
        summary = self.risk_monitor.get_summary()

        sell_trades = [t for t in self.risk_monitor.trades if t.get("type") == "SELL"]
        cost_tax = self._compute_costs_and_taxes(sell_trades)

        final_value = summary.get("final_value", 0)
        initial_capital = summary.get("initial_capital", self.config.initial_capital)
        total_return_abs = final_value - initial_capital

        # NOTE: total_return_abs is GROSS return (before costs and tax).
        #       net_post_tax_return below is the NET figure.
        net_post_tax_return = (
            total_return_abs - cost_tax["total_transaction_costs"] - cost_tax["total_tax"]
        )

        summary.update(cost_tax)
        summary.update(
            {
                "net_post_tax_return": round(net_post_tax_return, 2),
                "net_post_tax_return_pct": round((net_post_tax_return / initial_capital) * 100, 2),
            }
        )

        yoy_list = self._compute_yoy_returns()
        if yoy_list:
            summary["yearly_returns"] = yoy_list

        # Add open positions snapshot if available
        if hasattr(self, "open_positions_snapshot") and self.open_positions_snapshot:
            summary["open_positions"] = self.open_positions_snapshot

        return summary

    def _compute_yoy_returns(self) -> list:
        """Delegate yoy calculation to BacktestReportBuilder."""
        if not hasattr(self, "_report_builder"):
            # Build a lightweight builder just for yoy (before run() completes)
            self._report_builder = BacktestReportBuilder(
                config=self.config,
                config_name=self.config_name,
                start_date=self.start_date,
                end_date=self.end_date,
                check_daily_sl=self.check_daily_sl,
                mid_week_buy=self.mid_week_buy,
                enable_pyramiding=self.enable_pyramiding,
                portfolio_values=self.risk_monitor.portfolio_values,
                portfolio_dates=self.risk_monitor.portfolio_dates,
                trades=self.risk_monitor.trades,
                weekly_results=self.weekly_results,
            )
        return self._report_builder._compute_yoy_returns()

    def _build_trades_from_db(self) -> None:
        """
        Build trade list from backtest DB actions.

        Uses shared FIFOTradeTracker for consistent FIFO matching across
        backtesting and live trade journal.
        Populates self.risk_monitor.trades for trade-level metrics.
        """
        all_actions = self.actions_repo.get_all_approved_actions(ascending=True)
        matched_trades, stats = FIFOTradeTracker.from_actions(all_actions)

        self.risk_monitor.total_buys = stats["total_buys"]
        self.risk_monitor.pyramid_buys = stats["pyramid_buys"]

        # Convert MatchedTrade objects to the dict format expected by
        # risk_monitor / metrics (SELL entries + BUY legs for XIRR).
        trades = []
        for mt in matched_trades:
            trades.append(
                {
                    "type": "SELL",
                    "symbol": mt.symbol,
                    "entry_date": mt.entry_date,
                    "exit_date": mt.exit_date,
                    "price": mt.entry_price,
                    "exit_price": mt.exit_price,
                    "units": mt.units,
                    "pnl": mt.pnl,
                    "reason": mt.reason,
                }
            )
            # BUY legs for XIRR cash-flow reconstruction
            for leg in mt.buy_legs:
                trades.append(
                    {
                        "type": "BUY",
                        "symbol": mt.symbol,
                        "entry_date": leg.date,
                        "price": leg.price,
                        "units": leg.units,
                    }
                )

        self.risk_monitor.trades = trades
        logger.info(f"Built {stats['total_sells']} completed trades from DB")

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
            avg_price = float(getattr(h, "avg_price", None) or h.entry_price)
            current_price = float(h.current_price)
            unrealized_pnl = (current_price - avg_price) * h.units
            self.open_positions_snapshot.append(
                {
                    "symbol": h.symbol,
                    "entry_date": str(h.entry_date),
                    "units": h.units,
                    "entry_price": float(h.entry_price),
                    "avg_price": avg_price,
                    "current_price": current_price,
                    "market_value": round(current_price * h.units, 2),
                    "unrealized_pnl": round(unrealized_pnl, 2),
                }
            )

        logger.info(
            f"Force-closing {len(current_holdings)} open positions on backtest end date {self.end_date}"
        )

        # Generate sell actions for each open position at their last known close price
        close_date = self.end_date
        for h in current_holdings:
            # Use current_price from holding (already set to last Friday close within backtest period)
            close_price = float(h.current_price)

            sell_action = {
                "action_date": close_date,
                "type": "sell",
                "reason": "backtest_end_close",
                "symbol": h.symbol,
                "units": h.units,
                "prev_close": float(h.current_price),
                "execution_price": close_price,
                "capital": float(h.units) * close_price,
                "status": "Pending",
            }
            self.actions_repo.insert_action(sell_action)

        # Approve and process the force-close sells
        self.lifecycle.approve_all_actions(close_date)
        self.processor.process_actions(close_date)

        # Update risk monitor with final portfolio value (avoid duplicate if already recorded)
        summary = self.inv_repo.get_summary()
        if summary:
            last_recorded = (
                self.risk_monitor.portfolio_dates[-1] if self.risk_monitor.portfolio_dates else None
            )
            if last_recorded != close_date:
                self.risk_monitor.update(float(summary.portfolio_value), close_date)

        logger.info(f"Force-closed {len(current_holdings)} positions. All trades now realized.")


class BacktestingService:

    @staticmethod
    def run_backtest(
        start_date: date,
        end_date: date,
        config_name: str = "momentum_config",
        check_daily_sl: bool = True,
        mid_week_buy: bool = True,
        run_label: str = None,
        enable_pyramiding: bool = False,
        strategy_id: str = "strategy1",
    ):
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
            strategy_id: Which strategy's rankings to use (strategy1 | strategy2)

        Returns:
            Tuple of (results, summary, risk_monitor_data, report_path)
        """
        backtester = WeeklyBacktester(
            start_date, end_date, config_name, check_daily_sl, mid_week_buy,
            enable_pyramiding, strategy_id=strategy_id,
        )
        results = backtester.run()
        summary = backtester.get_summary()

        # Build equity curve with dates
        portfolio_dates = [
            d.isoformat() if d else None for d in backtester.risk_monitor.portfolio_dates
        ]
        portfolio_values = backtester.risk_monitor.portfolio_values
        equity_curve = [{"date": d, "value": v} for d, v in zip(portfolio_dates, portfolio_values)]

        # Expose risk monitor data for charts/tables
        risk_monitor_data = {
            "trades": backtester.risk_monitor.trades,
            "portfolio_values": portfolio_values,
            "portfolio_dates": portfolio_dates,
            "equity_curve": equity_curve,
        }

        # The report path is returned by _generate_report, but that method is internal and called inside run().
        # We need to capture it. Let's make _generate_report store it in self.report_path
        report_path = getattr(backtester, "report_path", None)

        # Read report text
        report_text = ""
        if report_path:
            try:
                with open(report_path, "r", encoding="utf-8") as f:
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
        equity_curve = (
            pd.Series(self.portfolio_values) if self.portfolio_values else pd.Series(dtype=float)
        )

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
            years=years,
        )

        # Add fields not covered by metrics module
        metrics["initial_capital"] = self.initial_capital

        return metrics
