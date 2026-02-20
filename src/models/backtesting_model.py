"""
Backtest Models

Dataclasses for positions, results, and risk monitoring.
"""
from datetime import date
from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd
from utils import calculate_all_metrics


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
