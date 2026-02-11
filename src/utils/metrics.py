"""
Performance Metrics Module

Provides comprehensive performance analytics for backtesting and live trading.
Functions: CAGR, Sharpe, Sortino, Calmar, max drawdown, win rate,
profit factor, expectancy, average holding period, and a master calculator.
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Union
from datetime import date

from utils import calculate_xirr



def calculate_cagr(
    initial_value: float,
    final_value: float,
    years: float
) -> float:
    """
    Compound Annual Growth Rate.
    
    CAGR = (final / initial)^(1/years) - 1
    
    Parameters:
        initial_value: Starting portfolio value
        final_value: Ending portfolio value
        years: Number of years (can be fractional)
    
    Returns:
        CAGR as a decimal (e.g., 0.12 = 12%)
    """
    if initial_value <= 0 or years <= 0:
        return 0.0
    return (final_value / initial_value) ** (1 / years) - 1


def calculate_sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.06,
    periods_per_year: int = 52
) -> float:
    """
    Annualized Sharpe Ratio.
    
    Sharpe = (mean_excess_return / std_dev) * sqrt(periods_per_year)
    
    Parameters:
        returns: Series of periodic returns
        risk_free_rate: Annual risk-free rate (default 6% for India)
        periods_per_year: Number of periods per year (52 for weekly)
    
    Returns:
        Annualized Sharpe ratio
    """
    if returns.empty or returns.std() == 0:
        return 0.0
    
    period_rf = risk_free_rate / periods_per_year
    excess_returns = returns - period_rf
    return float(
        (excess_returns.mean() / excess_returns.std()) * np.sqrt(periods_per_year)
    )


def calculate_sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.06,
    periods_per_year: int = 52
) -> float:
    """
    Annualized Sortino Ratio (uses downside deviation only).
    
    Parameters:
        returns: Series of periodic returns
        risk_free_rate: Annual risk-free rate
        periods_per_year: Number of periods per year
    
    Returns:
        Annualized Sortino ratio
    """
    if returns.empty:
        return 0.0
    
    period_rf = risk_free_rate / periods_per_year
    excess_returns = returns - period_rf
    downside = excess_returns[excess_returns < 0]
    
    if downside.empty or downside.std() == 0:
        return float('inf') if excess_returns.mean() > 0 else 0.0
    
    return float(
        (excess_returns.mean() / downside.std()) * np.sqrt(periods_per_year)
    )


def calculate_max_drawdown(equity_curve: pd.Series) -> float:
    """
    Maximum drawdown from peak.
    
    Parameters:
        equity_curve: Series of portfolio values over time
    
    Returns:
        Maximum drawdown as a positive decimal (e.g., 0.15 = 15%)
    """
    if equity_curve.empty:
        return 0.0
    
    running_max = equity_curve.cummax()
    drawdowns = (equity_curve - running_max) / running_max
    return float(abs(drawdowns.min()))


def calculate_calmar_ratio(
    cagr: float,
    max_drawdown: float
) -> float:
    """
    Calmar Ratio = CAGR / Max Drawdown.
    
    Parameters:
        cagr: Compound annual growth rate
        max_drawdown: Maximum drawdown (positive decimal)
    
    Returns:
        Calmar ratio
    """
    if max_drawdown == 0:
        return float('inf') if cagr > 0 else 0.0
    return cagr / max_drawdown


def calculate_win_rate(trades: List[Dict]) -> float:
    """
    Percentage of winning trades.
    
    Parameters:
        trades: List of trade dicts with 'pnl' key
    
    Returns:
        Win rate as decimal (e.g., 0.60 = 60%)
    """
    if not trades:
        return 0.0
    
    sell_trades = [t for t in trades if t.get('type') == 'SELL']
    if not sell_trades:
        return 0.0
    
    winners = sum(1 for t in sell_trades if t.get('pnl', 0) > 0)
    return winners / len(sell_trades)


def calculate_profit_factor(trades: List[Dict]) -> float:
    """
    Profit Factor = Gross Profit / Gross Loss.
    
    Parameters:
        trades: List of trade dicts with 'pnl' key
    
    Returns:
        Profit factor (> 1 means profitable)
    """
    sell_trades = [t for t in trades if t.get('type') == 'SELL']
    
    gross_profit = sum(t['pnl'] for t in sell_trades if t.get('pnl', 0) > 0)
    gross_loss = abs(sum(t['pnl'] for t in sell_trades if t.get('pnl', 0) < 0))
    
    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0
    
    return gross_profit / gross_loss


def calculate_expectancy(trades: List[Dict]) -> float:
    """
    Average expected PnL per trade.
    
    E = (win_rate × avg_win) - (loss_rate × avg_loss)
    
    Parameters:
        trades: List of trade dicts with 'pnl' key
    
    Returns:
        Expected PnL per trade
    """
    sell_trades = [t for t in trades if t.get('type') == 'SELL']
    if not sell_trades:
        return 0.0
    
    winners = [t['pnl'] for t in sell_trades if t.get('pnl', 0) > 0]
    losers = [t['pnl'] for t in sell_trades if t.get('pnl', 0) < 0]
    
    win_rate = len(winners) / len(sell_trades) if sell_trades else 0
    avg_win = np.mean(winners) if winners else 0
    avg_loss = abs(np.mean(losers)) if losers else 0
    
    return float(win_rate * avg_win - (1 - win_rate) * avg_loss)


def calculate_avg_holding_period(trades: List[Dict]) -> float:
    """
    Average holding period in days.
    
    Parameters:
        trades: List of trade dicts with 'entry_date' and 'exit_date'
    
    Returns:
        Average holding period in days
    """
    holding_periods = []
    for t in trades:
        entry = t.get('entry_date')
        exit_d = t.get('exit_date')
        if entry and exit_d:
            if isinstance(entry, str):
                entry = date.fromisoformat(entry)
            if isinstance(exit_d, str):
                exit_d = date.fromisoformat(exit_d)
            holding_periods.append((exit_d - entry).days)
    
    return float(np.mean(holding_periods)) if holding_periods else 0.0


def calculate_all_metrics(
    equity_curve: Optional[pd.Series] = None,
    trades: Optional[List[Dict]] = None,
    initial_value: float = 1_000_000,
    years: Optional[float] = None
) -> Dict[str, float]:
    """
    Master function: calculate all performance metrics.
    
    Parameters:
        equity_curve: Series of portfolio values indexed by date
        trades: List of trade dictionaries
        initial_value: Starting portfolio value
        years: Duration in years (computed from equity_curve if None)
    
    Returns:
        Dictionary of all computed metrics
    """
    metrics = {}
    
    if equity_curve is not None and not equity_curve.empty:
        final_value = float(equity_curve.iloc[-1])
        
        if years is None:
            if hasattr(equity_curve.index, 'to_pydatetime'):
                days = (equity_curve.index[-1] - equity_curve.index[0]).days
            else:
                days = len(equity_curve) * 7  # Assume weekly
            years = max(days / 365.25, 0.01)
        
        # Returns
        returns = equity_curve.pct_change().dropna()
        
        metrics['cagr'] = round(calculate_cagr(initial_value, final_value, years) * 100, 2)
        metrics['sharpe_ratio'] = round(calculate_sharpe_ratio(returns), 2)
        metrics['sortino_ratio'] = round(calculate_sortino_ratio(returns), 2)
        metrics['max_drawdown'] = round(calculate_max_drawdown(equity_curve) * 100, 2)
        metrics['calmar_ratio'] = round(
            calculate_calmar_ratio(
                metrics['cagr'] / 100,
                metrics['max_drawdown'] / 100
            ), 2
        )
        metrics['total_return'] = round(
            (final_value - initial_value) / initial_value * 100, 2
        )
        metrics['final_value'] = round(final_value, 2)
    
    if trades:
        metrics['win_rate'] = round(calculate_win_rate(trades) * 100, 2)
        metrics['profit_factor'] = round(calculate_profit_factor(trades), 2)
        metrics['expectancy'] = round(calculate_expectancy(trades), 2)
        metrics['avg_holding_period_days'] = round(
            calculate_avg_holding_period(trades), 1
        )
        metrics['total_trades'] = len([t for t in trades if t.get('type') == 'SELL'])

        # XIRR from trade cash flows
        try:
            cash_flows = []
            for t in trades:
                trade_date = t.get('entry_date') or t.get('exit_date')
                if trade_date and isinstance(trade_date, str):
                    trade_date = date.fromisoformat(trade_date)
                if not trade_date:
                    continue

                if t.get('type') == 'BUY':
                    # Capital outflow (negative)
                    amount = -(t.get('price', 0) * t.get('units', 0))
                    cash_flows.append((amount, trade_date))
                elif t.get('type') == 'SELL':
                    # Capital inflow (positive) — use net PnL + cost basis
                    entry_cost = t.get('price', 0) * t.get('units', 0)
                    net_pnl = t.get('pnl', 0)
                    amount = entry_cost + net_pnl
                    exit_date = t.get('exit_date')
                    if exit_date and isinstance(exit_date, str):
                        exit_date = date.fromisoformat(exit_date)
                    cash_flows.append((amount, exit_date or trade_date))

            if cash_flows:
                xirr_val = calculate_xirr(cash_flows)
                metrics['xirr'] = round(xirr_val * 100, 2)
            else:
                metrics['xirr'] = 0.0
        except Exception:
            metrics['xirr'] = 0.0

    return metrics
