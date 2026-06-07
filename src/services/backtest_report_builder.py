"""
Backtest Report Builder (P4)

Generates the human-readable text report from completed backtest results.
Zero dependency on WeeklyBacktester internals — accepts all data via constructor,
making it independently testable.
"""

import os
from datetime import datetime
from typing import List, Optional

import pandas as pd

from config import setup_logger
from utils import calculate_all_metrics, compute_trade_costs_and_taxes

logger = setup_logger(name="BacktestReportBuilder")


class BacktestReportBuilder:
    """
    Build and write the backtest result report to disk.

    All inputs are injected at construction time so this class has no
    access to WeeklyBacktester internals and can be unit-tested in isolation.
    """

    def __init__(
        self,
        config,
        config_name: str,
        start_date,
        end_date,
        check_daily_sl: bool,
        mid_week_buy: bool,
        enable_pyramiding: bool,
        portfolio_values: List[float],
        portfolio_dates: List,
        trades: List[dict],
        weekly_results: list,
        open_positions_snapshot: Optional[List[dict]] = None,
        total_buys: int = 0,
        pyramid_buys: int = 0,
    ):
        self.config = config
        self.config_name = config_name
        self.start_date = start_date
        self.end_date = end_date
        self.check_daily_sl = check_daily_sl
        self.mid_week_buy = mid_week_buy
        self.enable_pyramiding = enable_pyramiding
        self.portfolio_values = portfolio_values
        self.portfolio_dates = portfolio_dates
        self.trades = trades
        self.weekly_results = weekly_results
        self.open_positions_snapshot = open_positions_snapshot or []
        self.total_buys = total_buys
        self.pyramid_buys = pyramid_buys

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _compute_yoy_returns(self) -> list:
        """Compute year-on-year returns from the equity curve."""
        if not self.portfolio_dates:
            return []
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(self.portfolio_dates),
                "value": self.portfolio_values,
            }
        )
        if df.empty:
            return []
        df["year"] = df["date"].dt.year
        yearly_start = df.groupby("year")["value"].first()
        yearly_end = df.groupby("year")["value"].last()
        yearly_return = (yearly_end - yearly_start) / yearly_start * 100
        return [
            {
                "year": int(year),
                "return_pct": round(yearly_return[year], 2),
                "pnl": round(yearly_end[year] - yearly_start[year], 2),
                "end_value": round(yearly_end[year], 2),
            }
            for year in yearly_return.index
        ]

    # ------------------------------------------------------------------ #
    #  Report builder                                                      #
    # ------------------------------------------------------------------ #

    def build(self) -> str:
        """
        Build and write the report file.

        Returns:
            str: Absolute path to the written report file.
        """
        project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        report_dir = os.path.join(project_root, "backtesting_results")
        os.makedirs(report_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sl_tag = "daily_sl" if self.check_daily_sl else "weekly_sl"
        mwb_tag = "mwb_on" if self.mid_week_buy else "mwb_off"
        filename = (
            f"{self.config_name}_{self.start_date}_{self.end_date}"
            f"_{sl_tag}_{mwb_tag}_{timestamp}.txt"
        )
        filepath = os.path.join(report_dir, filename)

        lines = self._build_lines()
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info(f"Report saved: {filepath}")
        return filepath

    def _build_lines(self) -> list:
        """Return the report as a list of text lines."""
        sell_trades = [t for t in self.trades if t.get("type") == "SELL"]
        total_days = (self.end_date - self.start_date).days
        years = max(total_days / 365.25, 0.01)

        equity_curve = pd.Series(self.portfolio_values)
        metrics = calculate_all_metrics(
            equity_curve=equity_curve,
            trades=self.trades,
            initial_value=self.config.initial_capital,
            years=years,
        )
        final_value = (
            self.portfolio_values[-1] if self.portfolio_values else self.config.initial_capital
        )
        total_return_abs = final_value - self.config.initial_capital
        cost_tax = compute_trade_costs_and_taxes(sell_trades)
        total_costs = cost_tax["total_transaction_costs"]
        total_tax = cost_tax["total_tax"]
        net_post_tax_return = total_return_abs - total_costs - total_tax

        sep = "=" * 70
        lines = []

        # Header
        lines += [
            sep,
            "  BACKTEST RESULTS REPORT",
            f'  Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
            sep,
        ]

        # Section 1: Configuration
        lines += [
            "",
            "[ CONFIGURATION ]",
            f"  Config Name       : {self.config_name}",
            f"  Start Date        : {self.start_date}",
            f"  End Date          : {self.end_date}",
            f"  Daily SL          : {self.check_daily_sl}",
            f"  Mid-Week Buy      : {self.mid_week_buy}",
            f"  Initial Capital   : {self.config.initial_capital:>15,.2f}",
            f"  Max Positions     : {self.config.max_positions}",
            f"  Min Position (%)  : {self.config.min_position_percent}",
            f"  Risk Threshold    : {self.config.risk_threshold}",
            f"  Buffer Percent    : {self.config.buffer_percent}",
            f"  Exit Threshold    : {self.config.exit_threshold}",
            f"  SL Multiplier     : {self.config.sl_multiplier}",
            f"  ATR Fallback Pct   : {self.config.atr_fallback_percent}",
            f'  Pyramiding        : {"ON" if self.enable_pyramiding else "OFF"}',
        ]
        if self.enable_pyramiding:
            from config import PyramidConfig
            pcfg = PyramidConfig()
            lines.append(f"  Pyramid Fraction  : {pcfg.pyramid_fraction}")

        # Section 2: Performance Metrics
        lines += [
            "",
            "[ PERFORMANCE METRICS ]",
            f"  Final Portfolio   : {final_value:>15,.2f}",
            f'  Total Return      : {total_return_abs:>+15,.2f}  ({metrics.get("total_return", 0):+.2f}%)',
            f'  CAGR              : {metrics.get("cagr", 0):>+10.2f}%',
            f'  XIRR              : {metrics.get("xirr", 0):>+10.2f}%',
            f'  Max Drawdown      : {metrics.get("max_drawdown", 0):>10.2f}%',
            f'  Sharpe Ratio      : {metrics.get("sharpe_ratio", 0):>10.2f}',
            f'  Sortino Ratio     : {metrics.get("sortino_ratio", 0):>10.2f}',
            f'  Calmar Ratio      : {metrics.get("calmar_ratio", 0):>10.2f}',
        ]

        # Section 2.5: Year-on-Year
        lines += ["", "[ YEAR-ON-YEAR PERFORMANCE ]"]
        for entry in self._compute_yoy_returns():
            lines.append(
                f'  {entry["year"]}              : {entry["return_pct"]:>+10.2f}%'
                f'  (PnL: {entry["pnl"]:>+12,.2f} | End Val: {entry["end_value"]:>12,.2f})'
            )

        # Section 3: Trade Statistics
        winning = [t for t in sell_trades if t["pnl"] > 0]
        losing = [t for t in sell_trades if t["pnl"] <= 0]
        lines += [
            "",
            "[ TRADE STATISTICS ]",
            f"  Total Buys        : {self.total_buys}",
            f"  Pyramid Buys      : {self.pyramid_buys}",
            f"  Total Sells       : {len(sell_trades)}",
            f'  Win Rate          : {metrics.get("win_rate", 0):>10.2f}%',
            f'  Profit Factor     : {metrics.get("profit_factor", 0):>10.2f}',
            f'  Expectancy/Trade  : {metrics.get("expectancy", 0):>+10.2f}',
            f'  Avg Holding Days  : {metrics.get("avg_holding_period_days", 0):>10.1f}',
        ]
        if sell_trades:
            avg_win = sum(t["pnl"] for t in winning) / len(winning) if winning else 0
            avg_loss = sum(t["pnl"] for t in losing) / len(losing) if losing else 0
            best = max(sell_trades, key=lambda t: t["pnl"])
            worst = min(sell_trades, key=lambda t: t["pnl"])
            lines += [
                f"  Winners           : {len(winning)}",
                f"  Losers            : {len(losing)}",
                f"  Avg Win           : {avg_win:>+15,.2f}",
                f"  Avg Loss          : {avg_loss:>+15,.2f}",
                f'  Best Trade        : {best["symbol"]} {best["pnl"]:>+,.2f}',
                f'  Worst Trade       : {worst["symbol"]} {worst["pnl"]:>+,.2f}',
            ]

        # Section 4: Transaction Costs
        lines += [
            "",
            "[ TRANSACTION COSTS ]",
            f'  Total Buy Value   : {cost_tax["total_buy_value"]:>15,.2f}',
            f'  Total Sell Value  : {cost_tax["total_sell_value"]:>15,.2f}',
            f'  Total Turnover    : {(cost_tax["total_buy_value"] + cost_tax["total_sell_value"]):>15,.2f}',
            "  ---",
            f'  Buy Side Costs    : {cost_tax["total_buy_cost"]:>15,.2f}',
            f'  Sell Side Costs   : {cost_tax["total_sell_cost"]:>15,.2f}',
            f"  Total Costs       : {total_costs:>15,.2f}",
            "  ---",
            f'  Brokerage         : {cost_tax["total_brokerage"]:>15,.2f}',
            f'  STT               : {cost_tax["total_stt"]:>15,.2f}',
            f'  GST               : {cost_tax["total_gst"]:>15,.2f}',
            f'  Stamp Duty        : {cost_tax["total_stamp"]:>15,.2f}',
            f"  Cost as % Return  : {(total_costs / max(abs(total_return_abs), 1) * 100):>10.2f}%",
        ]

        # Section 5: Capital Gains Tax
        lines += [
            "",
            "[ CAPITAL GAINS TAX ]",
            f'  STCG Trades       : {cost_tax["stcg_count"]}',
            f'  STCG Gains        : {cost_tax["stcg_gains"]:>15,.2f}',
            f'  STCG Tax (20%)    : {cost_tax["stcg_tax"]:>15,.2f}',
            "  ---",
            f'  LTCG Trades       : {cost_tax["ltcg_count"]}',
            f'  LTCG Gains        : {cost_tax["ltcg_gains"]:>15,.2f}',
            f'  LTCG Tax (12.5%)  : {cost_tax["ltcg_tax"]:>15,.2f}',
            "  ---",
            f"  Total Tax         : {total_tax:>15,.2f}",
            f"  Total Costs+Tax   : {(total_costs + total_tax):>15,.2f}",
            f"  Net Post-Tax Ret  : {net_post_tax_return:>+15,.2f}",
        ]

        # Section 5.5: Open Positions at Backtest End
        if self.open_positions_snapshot:
            lines += [
                "",
                "[ OPEN POSITIONS AT BACKTEST END (force-closed) ]",
                f'  {"Symbol":<20} {"Entry Date":>12} {"Units":>6} {"Avg Price":>10}'
                f' {"Close Price":>12} {"Market Val":>12} {"Unrealized PnL":>15}',
                f'  {"-"*20} {"-"*12} {"-"*6} {"-"*10} {"-"*12} {"-"*12} {"-"*15}',
            ]
            total_mval = total_upnl = 0
            for pos in sorted(self.open_positions_snapshot, key=lambda x: x["market_value"], reverse=True):
                lines.append(
                    f'  {pos["symbol"]:<20} {pos["entry_date"]:>12} {pos["units"]:>6}'
                    f' {pos["avg_price"]:>10,.2f} {pos["current_price"]:>12,.2f}'
                    f' {pos["market_value"]:>12,.2f} {pos["unrealized_pnl"]:>+15,.2f}'
                )
                total_mval += pos["market_value"]
                total_upnl += pos["unrealized_pnl"]
            lines += [
                f'  {"-"*20} {"":>12} {"":>6} {"":>10} {"":>12} {"-"*12} {"-"*15}',
                f'  {"TOTAL":<20} {"":>12} {"":>6} {"":>10} {"":>12}'
                f' {total_mval:>12,.2f} {total_upnl:>+15,.2f}',
            ]

        # Section 6: Trade Log
        lines += [
            "",
            "[ TRADE LOG ]",
            f'  {"Symbol":<20} {"Entry":>12} {"Exit":>12} {"Entry ₹":>10}'
            f' {"Exit ₹":>10} {"Units":>6} {"PnL":>12} {"Reason"}',
            f'  {"-"*20} {"-"*12} {"-"*12} {"-"*10} {"-"*10} {"-"*6} {"-"*12} {"-"*20}',
        ]
        for t in sorted(sell_trades, key=lambda x: x["exit_date"]):
            lines.append(
                f'  {t["symbol"]:<20} {str(t["entry_date"]):>12} {str(t["exit_date"]):>12}'
                f' {t["price"]:>10,.2f} {t["exit_price"]:>10,.2f} {t["units"]:>6}'
                f' {t["pnl"]:>+12,.2f} {t.get("reason", "")}'
            )

        # Footer
        lines += [
            "",
            sep,
            f"  Weeks Simulated: {len(self.weekly_results)} | "
            f"Duration: {total_days} days ({years:.2f} years)",
            sep,
        ]
        return lines
