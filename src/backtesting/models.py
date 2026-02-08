"""
Backtest Models

Dataclasses for positions, results, and risk monitoring.
"""
from datetime import date
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Position:
    """
    Represents a portfolio position with stop-loss tracking.
    
    Attributes:
        tradingsymbol: Stock symbol
        entry_price: Price at which position was entered
        units: Number of shares held
        entry_date: Date of position entry
        composite_score: Stock's score at entry
        atr_at_entry: ATR value at entry (for stop calculation)
        initial_stop_loss: Initial stop-loss price
        current_stop_loss: Current trailing stop-loss
    """
    tradingsymbol: str
    entry_price: float
    units: int
    entry_date: date
    composite_score: float
    atr_at_entry: float = 0.0
    initial_stop_loss: float = 0.0
    current_stop_loss: float = 0.0
    
    @property
    def investment_value(self) -> float:
        """Total value invested in this position"""
        return self.entry_price * self.units


@dataclass 
class BacktestResult:
    """
    Stores backtest results for a single week.
    
    Attributes:
        week_date: Monday of the week
        portfolio_value: Total portfolio value
        total_return: Cumulative return percentage
        max_drawdown: Maximum drawdown percentage
        actions: List of actions taken (BUY/SELL/SWAP)
        top_10_stocks: Top ranked stocks for the week
        holdings: Snapshot of all positions
    """
    week_date: date
    portfolio_value: float
    total_return: float
    max_drawdown: float
    actions: List[dict] = field(default_factory=list)
    top_10_stocks: List[str] = field(default_factory=list)
    holdings: List[dict] = field(default_factory=list)
    invested_amount: float = 0.0
    total_risk: float = 0.0
    successful_trades: int = 0
    total_closed_trades: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Percentage of successful trades"""
        if self.total_closed_trades == 0:
            return 0.0
        return (self.successful_trades / self.total_closed_trades) * 100


class BacktestRiskMonitor:
    """
    Track risk metrics during backtest simulation.
    
    Monitors portfolio values, drawdown, and trade outcomes.
    """
    
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.portfolio_values: List[float] = [initial_capital]
        self.peak_value = initial_capital
        self.max_drawdown = 0.0
        self.trades: List[dict] = []
    
    def update(self, current_value: float) -> None:
        """Update metrics with new portfolio value"""
        self.portfolio_values.append(current_value)
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
        """Get comprehensive risk summary"""
        closed_trades = [t for t in self.trades if t.get('type') in ('SELL', 'SWAP')]
        successful_trades = len([t for t in closed_trades if t.get('pnl', 0) > 0])
        total_trades = len(closed_trades)
        hit_rate = (successful_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        return {
            "initial_capital": self.initial_capital,
            "final_value": self.portfolio_values[-1] if self.portfolio_values else self.initial_capital,
            "total_return_percent": round(self.get_total_return(), 2),
            "max_drawdown_percent": round(self.max_drawdown, 2),
            "total_trades": total_trades,
            "successful_trades": successful_trades,
            "hit_rate_percent": round(hit_rate, 2)
        }
