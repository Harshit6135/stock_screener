# PYRAMIDING MODULE SPECIFICATION
## Production-Ready Implementation for Indian Momentum Framework

**Module:** `pyramiding.py`  
**Dependencies:** `indicators.py`, `scoring.py`, `portfolio.py`, `costs.py`  
**Author:** Momentum Strategy Team  
**Date:** February 8, 2026  
**Version:** 1.0.0

---

## Table of Contents

1. [Module Overview](#module-overview)
2. [Data Structures](#data-structures)
3. [Core Functions](#core-functions)
4. [Integration Points](#integration-points)
5. [Configuration](#configuration)
6. [Testing Requirements](#testing-requirements)
7. [Performance Benchmarks](#performance-benchmarks)

---

## Module Overview

### Purpose

This module implements **pyramiding logic** (scaling into winning positions) for momentum-based equity strategies in the Indian market. It extends the base ranking and portfolio management framework with:

1. **Multi-gate entry filters** (5 mandatory checks + 5 trigger conditions)
2. **ATR-based position sizing** for each pyramid layer
3. **Cost-benefit analysis** accounting for Indian market frictions (STT, impact cost)
4. **Unified exit management** (one stop for all layers)
5. **Tax lot tracking** (separate STCG/LTCG for each layer)

### Key Design Principles

- **Treat each add as a new trade** - runs through full ATR position sizing formula
- **One logical position** - all layers share one score, one exit rule
- **Conservative by default** - strict entry criteria (score >80, 50 EMA > entry price, stop > cost)
- **Cost-aware** - requires expected gain > 3× transaction costs
- **Capital allocation priority** - only pyramid if no better new ideas exist

---

## Data Structures

### 1. PyramidLayer (Individual Tax Lot)

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class PyramidLayer:
    """
    Represents a single entry layer (initial position or add)
    Each layer is a separate tax lot with its own holding period
    """
    layer_number: int           # 0 = initial, 1 = first add, 2 = second add
    entry_date: datetime        # Date of this entry
    entry_price: float          # Execution price for this layer
    shares: int                 # Number of shares in this layer
    size_inr: float             # Position value at entry (shares × entry_price)
    
    # ATR at entry (for tracking risk evolution)
    atr_at_entry: float
    stop_distance_at_entry: float  # 2 × ATR at entry
    
    # Score tracking
    score_at_entry: float       # Composite score when this layer was added
    
    # Computed properties
    @property
    def holding_days(self, current_date: datetime) -> int:
        return (current_date - self.entry_date).days
    
    @property
    def is_ltcg(self, current_date: datetime) -> bool:
        return self.holding_days(current_date) >= 365
    
    def unrealized_pnl(self, current_price: float) -> float:
        return (current_price - self.entry_price) * self.shares
    
    def unrealized_pnl_pct(self, current_price: float) -> float:
        return ((current_price - self.entry_price) / self.entry_price) * 100
```

### 2. PyramidedPosition (Complete Multi-Layer Holding)

```python
@dataclass
class PyramidedPosition:
    """
    A single stock position that may have multiple entry layers
    """
    symbol: str
    sector: str
    market_cap: float           # In ₹Cr
    
    # All layers (chronological order: 0 = initial, 1 = add1, 2 = add2)
    layers: list[PyramidLayer]
    
    # Current market data
    current_price: float
    current_date: datetime
    
    # Computed aggregates
    @property
    def total_shares(self) -> int:
        return sum(layer.shares for layer in self.layers)
    
    @property
    def average_cost(self) -> float:
        total_cost = sum(layer.entry_price * layer.shares for layer in self.layers)
        return total_cost / self.total_shares if self.total_shares > 0 else 0
    
    @property
    def current_value(self) -> float:
        return self.total_shares * self.current_price
    
    @property
    def total_unrealized_pnl(self) -> float:
        return sum(layer.unrealized_pnl(self.current_price) for layer in self.layers)
    
    @property
    def total_unrealized_pnl_pct(self) -> float:
        return ((self.current_price - self.average_cost) / self.average_cost) * 100
    
    @property
    def pyramid_count(self) -> int:
        """Number of adds (excludes initial position)"""
        return len(self.layers) - 1
    
    @property
    def initial_entry_date(self) -> datetime:
        return self.layers[0].entry_date
    
    @property
    def last_add_price(self) -> float:
        """Price of most recent layer (for trigger calculation)"""
        return self.layers[-1].entry_price
    
    @property
    def last_layer_size(self) -> float:
        """Size of most recent layer in INR (for 50% rule)"""
        return self.layers[-1].size_inr
    
    def get_tax_liability(self, current_date: datetime) -> float:
        """Calculate total tax if entire position sold today"""
        total_tax = 0
        
        for layer in self.layers:
            gain = layer.unrealized_pnl(self.current_price)
            if gain <= 0:
                continue  # No tax on losses
            
            if layer.is_ltcg(current_date):
                # LTCG: 12.5% on gains (no exemption for simplicity)
                tax = gain * 0.125
            else:
                # STCG: 20% on gains
                tax = gain * 0.20
            
            total_tax += tax
        
        return total_tax
```

### 3. PyramidConfig (Configuration Object)

```python
@dataclass
class PyramidConfig:
    """
    Configuration for pyramiding rules
    Adjust based on portfolio size and market regime
    """
    # Entry thresholds
    min_score_threshold: float = 80.0      # Minimum composite score to pyramid
    min_score_improvement: float = -5.0    # Allow small score decay (negative = decay tolerance)
    
    # Price/trend confirmations
    min_price_gain_pct: float = 5.0        # % gain since last entry
    require_ema50_above_entry: bool = True # 50 EMA must be above initial entry price
    require_stop_above_cost: bool = True   # Trailing stop must be above avg cost (risk-free)
    
    # Position sizing
    pyramid_size_pct: float = 0.50         # Each add = 50% of previous layer
    max_pyramid_layers: int = 2            # 0 = initial, 1 = add1, 2 = add2 (total 3 entries)
    
    # Risk constraints
    max_position_pct: float = 0.12         # 12% portfolio max per stock (all layers combined)
    max_add_liquidity_pct: float = 0.03    # Max 3% of daily turnover per add
    min_add_size_pct: float = 0.015        # Min 1.5% of portfolio (else skip)
    
    # Cost-benefit
    cost_benefit_multiplier: float = 3.0   # Expected gain must be 3× transaction cost
    
    # Capital allocation priority
    max_score_gap_to_challengers: float = 15.0  # Don't pyramid if Challenger is 15+ points better
    
    # Market cap adjustments (min gain thresholds)
    large_cap_threshold_cr: float = 10000  # ₹10,000 Cr
    mid_cap_threshold_cr: float = 5000     # ₹5,000 Cr
    large_cap_min_gain: float = 5.0        # %
    mid_cap_min_gain: float = 6.5          # %
    small_cap_min_gain: float = 8.0        # %
    
    # Portfolio-level circuit breakers
    max_portfolio_drawdown: float = 0.15   # Disable pyramiding if DD > 15%
    max_vix: float = 30                    # Disable if India VIX > 30
    min_market_efficiency: float = 0.30    # Disable if market choppy (efficiency < 30%)
    max_single_position_pct: float = 0.10  # Disable if any position > 10%

    @classmethod
    def for_regime(cls, regime: str, vix: float) -> 'PyramidConfig':
        """
        Factory method: create config adapted to market regime
        
        Regimes: 'MONTHLY' (strong trend), 'BIWEEKLY' (standard), 'WEEKLY' (choppy)
        """
        if regime == 'MONTHLY' and vix < 15:
            # Aggressive pyramiding (strong uptrend + low vol)
            return cls(
                min_score_threshold=75.0,
                min_price_gain_pct=4.0,
                max_pyramid_layers=2,
                cost_benefit_multiplier=3.0
            )
        elif regime == 'BIWEEKLY':
            # Standard (default values)
            return cls()
        else:
            # Conservative (volatile/choppy)
            return cls(
                min_score_threshold=85.0,
                min_price_gain_pct=8.0,
                max_pyramid_layers=1,
                cost_benefit_multiplier=4.0
            )
```

---

## Core Functions

### Function 1: `can_pyramid()` - Mandatory Gate Check

```python
def can_pyramid(
    position: PyramidedPosition,
    current_score: float,
    prior_score: float,
    indicators: dict,
    config: PyramidConfig,
    date: datetime
) -> tuple[bool, str]:
    """
    Gate check: Can we even consider pyramiding this position?
    
    Args:
        position: Current pyramided position
        current_score: Composite score at this rebalance
        prior_score: Composite score at last rebalance
        indicators: Dict with 'price', 'ema_50', 'ema_200', 'atr_14', 'atr_20d_avg'
        config: PyramidConfig object
        date: Current date
    
    Returns:
        (can_pyramid: bool, reason: str)
    
    Logic:
        ALL conditions must be True. If any fails, return False immediately.
    """
    # Check 1: Still passes penalty box (score > 0)
    if current_score == 0:
        return False, "PENALTY_BOX_TRIGGERED"
    
    # Check 2: Above 200 EMA (primary trend intact)
    if indicators['price'] < indicators['ema_200']:
        return False, "BELOW_200_EMA"
    
    # Check 3: No ATR spike (no recent earnings/news shock)
    atr_ratio = indicators['atr_14'] / indicators['atr_20d_avg']
    if atr_ratio > 2.0:
        return False, "ATR_SPIKE_DETECTED"
    
    # Check 4: Liquidity still adequate
    avg_turnover = get_avg_daily_turnover(position.symbol, date, days=20)
    if avg_turnover < 5_00_00_000:  # ₹5 Cr minimum
        return False, "LIQUIDITY_DEGRADED"
    
    # Check 5: Score quality threshold
    if current_score < config.min_score_threshold:
        return False, f"SCORE_TOO_LOW_{current_score:.1f}"
    
    # Check 6: Score not deteriorating beyond tolerance
    score_change = current_score - prior_score
    if score_change < config.min_score_improvement:
        return False, f"SCORE_DETERIORATING_{score_change:.1f}"
    
    # Check 7: 50 EMA above initial entry price (NEW - sustained trend structure)
    if config.require_ema50_above_entry:
        initial_entry_price = position.layers[0].entry_price
        if indicators['ema_50'] < initial_entry_price:
            return False, "EMA50_BELOW_INITIAL_ENTRY"
    
    # Check 8: Trailing stop above average cost (NEW - risk-free position)
    if config.require_stop_above_cost:
        # Calculate trailing stop
        highest_high = get_highest_high_since(
            position.symbol, 
            position.initial_entry_date, 
            date
        )
        trailing_stop = highest_high - (2 * indicators['atr_14'])
        
        if trailing_stop < position.average_cost:
            return False, "STOP_BELOW_AVG_COST"
    
    # All checks passed
    return True, "ELIGIBLE"
```

### Function 2: `should_pyramid_now()` - Trigger Decision

```python
def should_pyramid_now(
    position: PyramidedPosition,
    current_score: float,
    indicators: dict,
    portfolio: 'Portfolio',  # Forward reference
    config: PyramidConfig,
    date: datetime
) -> tuple[bool, str]:
    """
    Decide if THIS rebalance is the right moment to add
    
    Args:
        position: Current pyramided position
        current_score: Composite score now
        indicators: Technical indicators dict
        portfolio: Full portfolio object (for Challenger comparison)
        config: PyramidConfig
        date: Current date
    
    Returns:
        (should_add: bool, reason: str)
    
    Logic:
        Event-driven triggers (not calendar-based)
        Requires meaningful price move + strong score + no better alternatives
    """
    # Trigger 1: Sufficient price appreciation since last add
    last_entry_price = position.last_add_price
    current_price = indicators['price']
    price_gain_pct = ((current_price - last_entry_price) / last_entry_price) * 100
    
    # Market cap-adjusted threshold
    if position.market_cap > config.large_cap_threshold_cr:
        min_gain = config.large_cap_min_gain
    elif position.market_cap > config.mid_cap_threshold_cr:
        min_gain = config.mid_cap_min_gain
    else:
        min_gain = config.small_cap_min_gain
    
    if price_gain_pct < min_gain:
        return False, f"INSUFFICIENT_PRICE_MOVE_{price_gain_pct:.2f}%"
    
    # Trigger 2: Score in top tier
    if current_score < config.min_score_threshold:
        return False, f"SCORE_NOT_TOP_TIER_{current_score:.1f}"
    
    # Trigger 3: Capital allocation priority (Challenger comparison)
    # Only pyramid if no unowned stock has significantly higher score
    top_challengers = portfolio.get_top_unowned_stocks(top_n=3, date=date)
    
    for challenger in top_challengers:
        score_gap = challenger['composite_score'] - current_score
        if score_gap > config.max_score_gap_to_challengers:
            return False, f"BETTER_CHALLENGER_{challenger['symbol']}_+{score_gap:.1f}"
    
    # Trigger 4: Not at max layers
    if position.pyramid_count >= config.max_pyramid_layers:
        return False, f"MAX_LAYERS_{position.pyramid_count}"
    
    # Trigger 5: Risk-adjusted momentum still strong
    roc_20 = indicators['roc_20']  # 20-day return
    atr_pct = (indicators['atr_14'] / indicators['price']) * 100
    efficiency = roc_20 / atr_pct if atr_pct > 0 else 0
    
    if efficiency < 1.0:
        return False, f"EFFICIENCY_WEAK_{efficiency:.2f}"
    
    # All triggers satisfied
    return True, "PYRAMID_APPROVED"
```

### Function 3: `calculate_pyramid_add_size()` - Position Sizing

```python
def calculate_pyramid_add_size(
    position: PyramidedPosition,
    portfolio_capital: float,
    indicators: dict,
    config: PyramidConfig,
    date: datetime
) -> tuple[float, int, str]:
    """
    Calculate size for pyramid add using ATR-based risk parity
    
    Args:
        position: Current position
        portfolio_capital: Total portfolio equity
        indicators: Technical indicators
        config: Pyramid config
        date: Current date
    
    Returns:
        (add_size_inr: float, shares: int, reason: str)
        Returns (0, 0, reason) if any constraint violated
    
    Logic:
        1. Start with 50% of last layer (pyramid rule)
        2. Recalculate under ATR constraint (new trade)
        3. Take minimum of both
        4. Apply concentration, liquidity, market cap constraints
        5. Verify minimum viable size
    """
    # Step 1: Pyramid rule (50% of previous layer)
    last_layer_size = position.last_layer_size
    proposed_add = last_layer_size * config.pyramid_size_pct
    
    # Step 2: ATR-based sizing (treat as fresh trade)
    atr = indicators['atr_14']
    price = indicators['price']
    stop_loss_distance = 2 * atr  # 2× ATR stop
    
    risk_per_trade_pct = 0.01  # 1% portfolio risk per trade
    risk_per_trade_inr = portfolio_capital * risk_per_trade_pct
    
    shares_atr = risk_per_trade_inr / stop_loss_distance
    position_size_atr = shares_atr * price
    
    # Step 3: Take minimum (more conservative of two)
    add_size = min(proposed_add, position_size_atr)
    
    # Step 4: Apply constraints
    
    # Constraint 1: Total position concentration
    current_position_value = position.current_value
    max_total_position = config.max_position_pct * portfolio_capital
    
    if current_position_value + add_size > max_total_position:
        add_size = max(0, max_total_position - current_position_value)
        
        # Check if remaining room is too small
        if add_size < config.min_add_size_pct * portfolio_capital:
            return 0, 0, "CONCENTRATION_LIMIT"
    
    # Constraint 2: Liquidity (daily turnover limit)
    avg_daily_turnover = get_avg_daily_turnover(position.symbol, date, days=20)
    max_add_liquidity = config.max_add_liquidity_pct * avg_daily_turnover
    
    if add_size > max_add_liquidity:
        add_size = max_add_liquidity
        
        # Check if liquidity-constrained size is too small
        if add_size < config.min_add_size_pct * portfolio_capital:
            return 0, 0, "LIQUIDITY_CONSTRAINED"
    
    # Constraint 3: Market cap penalty (reduce for small/mid caps)
    if position.market_cap < config.mid_cap_threshold_cr:  # Small cap
        add_size *= 0.50
    elif position.market_cap < config.large_cap_threshold_cr:  # Mid cap
        add_size *= 0.75
    
    # Constraint 4: Minimum viable add
    min_add_size = config.min_add_size_pct * portfolio_capital
    if add_size < min_add_size:
        return 0, 0, f"ADD_TOO_SMALL_{add_size:.0f}"
    
    # Step 5: Convert to shares (round down)
    shares = int(add_size / price)
    actual_add_size = shares * price
    
    return actual_add_size, shares, "APPROVED"
```

### Function 4: `cost_benefit_check()` - Indian Cost Analysis

```python
def cost_benefit_check(
    position: PyramidedPosition,
    proposed_add_size: float,
    config: PyramidConfig,
    date: datetime
) -> tuple[bool, dict]:
    """
    Check if expected benefit exceeds Indian market transaction costs
    
    Args:
        position: Current position
        proposed_add_size: Proposed add in INR
        config: Pyramid config
        date: Current date
    
    Returns:
        (is_worth_it: bool, analysis: dict)
    
    Logic:
        - Calculate full round-trip cost (entry + eventual exit)
        - Estimate expected gain from momentum continuation
        - Require expected gain > cost × multiplier (default 3×)
    """
    symbol = position.symbol
    
    # Calculate Indian market costs
    # Entry costs
    entry_brokerage = min(proposed_add_size * 0.0003, 20)  # ₹20 or 0.03%, whichever lower
    stamp_duty = proposed_add_size * 0.00015  # 0.015% on buy
    entry_impact = estimate_impact_cost(symbol, proposed_add_size, date)
    
    # Exit costs (will be incurred later)
    exit_brokerage = min(proposed_add_size * 0.0003, 20)
    stt = proposed_add_size * 0.001  # 0.1% on delivery sell
    exit_impact = estimate_impact_cost(symbol, proposed_add_size, date)
    
    # GST on brokerage (18%)
    gst = (entry_brokerage + exit_brokerage) * 0.18
    
    # Exchange + SEBI charges (small, ~0.00035%)
    misc_charges = proposed_add_size * 0.0000035 * 2  # Both sides
    
    total_cost = (entry_brokerage + stamp_duty + entry_impact + 
                  exit_brokerage + stt + exit_impact + gst + misc_charges)
    
    cost_pct = (total_cost / proposed_add_size) * 100
    
    # Estimate expected gain (conservative)
    # Look at recent momentum (gain since last add)
    recent_gain_pct = ((indicators['price'] - position.last_add_price) / 
                       position.last_add_price) * 100
    
    # Adjust by score momentum
    score_change = current_score - position.layers[-1].score_at_entry
    
    if score_change > 5:
        momentum_multiplier = 1.5  # Score accelerating
    elif score_change > 0:
        momentum_multiplier = 1.0  # Score stable
    else:
        momentum_multiplier = 0.7  # Score slightly declining
    
    # Expected gain = (recent gain × multiplier) × 50% haircut (conservative)
    expected_gain_pct = recent_gain_pct * momentum_multiplier * 0.50
    
    # Require expected gain > cost × multiplier
    min_required_gain = cost_pct * config.cost_benefit_multiplier
    
    is_worth_it = expected_gain_pct > min_required_gain
    
    analysis = {
        'total_cost_inr': total_cost,
        'cost_pct': cost_pct,
        'expected_gain_pct': expected_gain_pct,
        'min_required_gain_pct': min_required_gain,
        'score_change': score_change,
        'recent_gain_pct': recent_gain_pct,
        'is_worth_it': is_worth_it,
        'cost_breakdown': {
            'entry_brokerage': entry_brokerage,
            'stamp_duty': stamp_duty,
            'entry_impact': entry_impact,
            'exit_brokerage': exit_brokerage,
            'stt': stt,
            'exit_impact': exit_impact,
            'gst': gst,
            'misc': misc_charges
        }
    }
    
    reason = f"ExpGain={expected_gain_pct:.2f}%_vs_Cost={cost_pct:.2f}%"
    
    return is_worth_it, analysis
```

### Function 5: `execute_pyramid_add()` - Add Execution

```python
def execute_pyramid_add(
    position: PyramidedPosition,
    add_size_inr: float,
    shares: int,
    current_score: float,
    indicators: dict,
    date: datetime,
    portfolio: 'Portfolio'
) -> PyramidLayer:
    """
    Execute the pyramid add and update position state
    
    Args:
        position: Position to add to
        add_size_inr: Add size in INR
        shares: Number of shares to add
        current_score: Composite score at entry
        indicators: Technical indicators
        date: Entry date
        portfolio: Portfolio object (to deduct cash)
    
    Returns:
        new_layer: PyramidLayer object
    
    Side Effects:
        - Deducts cash from portfolio
        - Appends new layer to position.layers
        - Updates position metadata
    """
    # Calculate actual execution price (conservative: open + 0.1%)
    entry_price = get_next_day_open(position.symbol, date) * 1.001
    
    # Create new layer
    new_layer = PyramidLayer(
        layer_number=len(position.layers),  # 0-indexed
        entry_date=date,
        entry_price=entry_price,
        shares=shares,
        size_inr=shares * entry_price,
        atr_at_entry=indicators['atr_14'],
        stop_distance_at_entry=2 * indicators['atr_14'],
        score_at_entry=current_score
    )
    
    # Update position
    position.layers.append(new_layer)
    
    # Deduct cash from portfolio
    total_cost = new_layer.size_inr
    transaction_costs = calculate_transaction_costs(
        total_cost, position.symbol, side='buy'
    )
    
    portfolio.cash -= (total_cost + transaction_costs)
    
    # Log the trade
    log_trade(
        action='PYRAMID_ADD',
        symbol=position.symbol,
        date=date,
        price=entry_price,
        shares=shares,
        size=total_cost,
        layer=new_layer.layer_number,
        score=current_score
    )
    
    return new_layer
```

### Function 6: `calculate_unified_exit()` - Exit Signal

```python
def calculate_unified_exit(
    position: PyramidedPosition,
    current_score: float,
    indicators: dict,
    date: datetime
) -> tuple[bool, str, Optional[float]]:
    """
    Unified exit logic for entire pyramided position
    
    Args:
        position: Pyramided position
        current_score: Current composite score
        indicators: Technical indicators
        date: Current date
    
    Returns:
        (should_exit: bool, reason: str, scale_out_pct: Optional[float])
        
        scale_out_pct:
            None = exit entire position
            0.33 = sell 33% (partial exit)
            0.50 = sell 50% (partial exit)
    
    Exit Rules:
        Hard Exits (entire position):
        1. Score < 50 (degradation threshold)
        2. Price < 50 EMA (trend broken)
        3. ATR trailing stop hit
        4. ATR spike > 2.0 (volatility shock)
        
        Soft Exits (partial scale-out):
        5. Score dropped from 80+ to 50-65 range (fading)
        6. Price > 50% above 200 EMA (parabolic extension)
    """
    # Hard Exit 1: Score degradation
    if current_score < 50:
        return True, 'SCORE_DEGRADED', None
    
    # Hard Exit 2: Trend break
    if indicators['price'] < indicators['ema_50']:
        return True, 'TREND_BREAK_50_EMA', None
    
    # Hard Exit 3: Trailing ATR stop hit
    highest_high = get_highest_high_since(
        position.symbol,
        position.initial_entry_date,
        date
    )
    
    trailing_stop = highest_high - (2 * indicators['atr_14'])
    
    if indicators['price'] < trailing_stop:
        return True, 'ATR_TRAILING_STOP', None
    
    # Hard Exit 4: Fresh volatility shock
    atr_spike = indicators['atr_14'] / indicators['atr_20d_avg']
    if atr_spike > 2.0:
        return True, 'ATR_SPIKE', None
    
    # Soft Exit 5: Momentum fading (partial exit)
    # Only for positions >8% of portfolio
    position_pct = position.current_value / portfolio.total_equity
    
    if position_pct > 0.08:
        # Score dropped from peak but not broken
        peak_score = max(layer.score_at_entry for layer in position.layers)
        
        if peak_score > 80 and 50 < current_score < 65:
            # Trim 1/3 of position (sell most recent layer)
            return True, 'MOMENTUM_FADING', 0.33
    
    # Soft Exit 6: Overextension risk (partial exit)
    dist_200_pct = ((indicators['price'] - indicators['ema_200']) / 
                    indicators['ema_200']) * 100
    
    if dist_200_pct > 50:
        # Price > 50% above 200 EMA = parabolic, take half off
        return True, 'OVEREXTENSION', 0.50
    
    # No exit signal
    return False, 'HOLD', None
```

### Function 7: `should_disable_pyramiding_global()` - Circuit Breaker

```python
def should_disable_pyramiding_global(
    portfolio: 'Portfolio',
    config: PyramidConfig,
    date: datetime
) -> tuple[bool, str]:
    """
    Portfolio-level circuit breaker
    
    Disables ALL pyramiding if adverse conditions detected
    
    Args:
        portfolio: Full portfolio object
        config: Pyramid config
        date: Current date
    
    Returns:
        (disable: bool, reason: str)
    
    Conditions that disable pyramiding:
        1. Portfolio drawdown > 15%
        2. India VIX > 30
        3. Market regime = choppy (efficiency < 0.30)
        4. Any single position > 10% (over-concentration)
    """
    # Check 1: Portfolio drawdown
    equity_curve = portfolio.get_equity_curve()
    peak_equity = equity_curve.max()
    current_equity = equity_curve.iloc[-1]
    drawdown = (peak_equity - current_equity) / peak_equity
    
    if drawdown > config.max_portfolio_drawdown:
        return True, f"PORTFOLIO_DD_{drawdown*100:.1f}%"
    
    # Check 2: VIX spike
    india_vix = get_india_vix(date)
    if india_vix > config.max_vix:
        return True, f"VIX_HIGH_{india_vix:.1f}"
    
    # Check 3: Market regime (choppy/sideways)
    regime = determine_rebalancing_frequency(date)
    efficiency = calculate_market_efficiency(date, lookback=60)
    
    if regime == 'WEEKLY' and efficiency < config.min_market_efficiency:
        return True, f"CHOPPY_MARKET_EFF_{efficiency:.2f}"
    
    # Check 4: Over-concentration
    position_weights = [
        holding.current_value / portfolio.total_equity 
        for holding in portfolio.holdings
    ]
    max_position_weight = max(position_weights) if position_weights else 0
    
    if max_position_weight > config.max_single_position_pct:
        return True, f"CONCENTRATION_{max_position_weight*100:.1f}%"
    
    # Pyramiding enabled
    return False, "ENABLED"
```

### Function 8: `get_pyramid_suitability()` - Stock Quality Score

```python
def get_pyramid_suitability(
    symbol: str,
    date: datetime
) -> tuple[str, float]:
    """
    Rate how suitable a stock is for pyramiding (0-10 scale)
    
    Args:
        symbol: Stock symbol
        date: Current date
    
    Returns:
        (rating: str, score: float)
        Ratings: 'EXCELLENT' (8-10), 'GOOD' (6-8), 'ACCEPTABLE' (4-6), 'AVOID' (<4)
    
    Factors:
        - Market cap (larger = better liquidity)
        - Sector (IT/Pharma/FMCG = smoother trends)
        - Beta (0.8-1.2 = ideal, >1.5 = too volatile)
        - Liquidity (turnover)
    """
    market_cap = get_market_cap(symbol, date)
    sector = get_sector(symbol)
    beta = get_beta(symbol, date, period=60)
    avg_turnover = get_avg_daily_turnover(symbol, date, days=20)
    
    score = 5.0  # Base score
    
    # Factor 1: Market cap
    if market_cap > 100000:  # > ₹1L Cr (mega cap)
        score += 3
    elif market_cap > 50000:  # ₹50k-1L Cr (large cap)
        score += 2
    elif market_cap > 10000:  # ₹10k-50k Cr (mid cap)
        score += 1
    else:  # < ₹10k Cr (small cap)
        score -= 2
    
    # Factor 2: Sector characteristics
    smooth_sectors = ['IT', 'Pharma', 'FMCG', 'Healthcare']
    choppy_sectors = ['Metals', 'Real Estate', 'PSU Banks', 'Commodities']
    
    if sector in smooth_sectors:
        score += 2
    elif sector in choppy_sectors:
        score -= 1
    
    # Factor 3: Beta (volatility profile)
    if 0.8 <= beta <= 1.2:
        score += 1  # Moderate volatility
    elif beta > 1.5:
        score -= 1  # High beta
    
    # Factor 4: Liquidity
    if avg_turnover < 10_00_00_000:  # < ₹10 Cr
        score -= 2
    elif avg_turnover > 50_00_00_000:  # > ₹50 Cr
        score += 1
    
    # Classify
    if score >= 8:
        rating = 'EXCELLENT'
    elif score >= 6:
        rating = 'GOOD'
    elif score >= 4:
        rating = 'ACCEPTABLE'
    else:
        rating = 'AVOID'
    
    return rating, score
```

---

## Integration Points

### Integration 1: Main Rebalancing Loop

**Location:** `portfolio_manager.py::rebalance_portfolio()`

**Modification:** Add pyramiding step between exits and Challenger comparison.

```python
def rebalance_portfolio(portfolio, universe, date, enable_pyramiding=True):
    """
    Main rebalancing function with pyramiding support
    
    Execution order:
    1. Check exits (absolute degradation)
    2. **[NEW] Check pyramid adds to winners**
    3. Check Challenger vs Incumbent swaps
    4. Fill vacancies with new stocks
    """
    actions = []
    
    # Step 1: Exits (existing code, unchanged)
    for holding in portfolio.holdings:
        current_score = universe.get_score(holding.symbol, date)
        
        if current_score < 40:  # Absolute exit
            actions.append(create_sell_action(holding, 'ABSOLUTE_EXIT'))
            continue
    
    # === NEW: Step 2 - Pyramiding ===
    if enable_pyramiding:
        # Global circuit breaker check
        disable_pyramiding, reason = should_disable_pyramiding_global(
            portfolio, pyramid_config, date
        )
        
        if not disable_pyramiding:
            cash_available = portfolio.cash
            
            for holding in portfolio.holdings:
                # Skip if already exiting
                if holding.symbol in [a.symbol for a in actions if a.action == 'SELL']:
                    continue
                
                current_score = universe.get_score(holding.symbol, date)
                prior_score = holding.get_score_at_last_rebalance()
                indicators = get_indicators(holding.symbol, date)
                
                # Gate check
                can_add, reason = can_pyramid(
                    holding, current_score, prior_score, 
                    indicators, pyramid_config, date
                )
                
                if not can_add:
                    continue
                
                # Trigger check
                should_add, reason = should_pyramid_now(
                    holding, current_score, indicators, 
                    portfolio, pyramid_config, date
                )
                
                if not should_add:
                    continue
                
                # Position sizing
                add_size, shares, size_reason = calculate_pyramid_add_size(
                    holding, portfolio.total_equity, 
                    indicators, pyramid_config, date
                )
                
                if add_size == 0:
                    continue
                
                # Check cash availability
                if add_size > cash_available:
                    continue
                
                # Cost-benefit check
                is_worth_it, analysis = cost_benefit_check(
                    holding, add_size, pyramid_config, date
                )
                
                if not is_worth_it:
                    continue
                
                # All checks passed - execute add
                new_layer = execute_pyramid_add(
                    holding, add_size, shares, current_score,
                    indicators, date, portfolio
                )
                
                actions.append(create_pyramid_add_action(
                    holding, new_layer, analysis
                ))
                
                cash_available -= add_size
    
    # Step 3: Challenger vs Incumbent (existing code)
    # ... existing swap logic ...
    
    # Step 4: Fill vacancies (existing code)
    # ... existing new entry logic ...
    
    return actions
```

### Integration 2: Position Object

**Location:** `portfolio.py::Position` class

**Modification:** Extend to support multiple layers.

```python
# Before: Simple position
class Position:
    def __init__(self, symbol, entry_date, entry_price, shares):
        self.symbol = symbol
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares

# After: Pyramided position (use PyramidedPosition from data structures)
# Replace Position class with PyramidedPosition throughout codebase
```

### Integration 3: Exit Logic

**Location:** `portfolio_manager.py::check_exits()`

**Modification:** Use unified pyramid exit logic.

```python
def check_exits(portfolio, universe, date):
    """
    Check exit signals for all holdings (including pyramided)
    """
    exit_actions = []
    
    for holding in portfolio.holdings:
        current_score = universe.get_score(holding.symbol, date)
        indicators = get_indicators(holding.symbol, date)
        
        # Use pyramid-aware exit logic
        should_exit, reason, scale_out_pct = calculate_unified_exit(
            holding, current_score, indicators, date
        )
        
        if should_exit:
            if scale_out_pct is None:
                # Full exit
                exit_actions.append(create_sell_action(
                    holding, reason, size_pct=1.0
                ))
            else:
                # Partial exit
                exit_actions.append(create_sell_action(
                    holding, reason, size_pct=scale_out_pct
                ))
    
    return exit_actions
```

---

## Configuration

### Default Configuration (Standard Market)

```python
# config/pyramid_config.yaml

pyramiding:
  enabled: true
  
  # Entry criteria
  entry:
    min_score: 80.0
    min_score_change: -5.0  # Tolerance for small decay
    require_ema50_above_entry: true
    require_stop_above_cost: true
  
  # Price triggers (market cap dependent)
  price_thresholds:
    large_cap_min_gain_pct: 5.0   # Market cap > ₹10k Cr
    mid_cap_min_gain_pct: 6.5     # ₹5k-10k Cr
    small_cap_min_gain_pct: 8.0   # < ₹5k Cr
  
  # Position sizing
  sizing:
    pyramid_size_fraction: 0.50   # Each add = 50% of previous
    max_layers: 2                 # 0=initial, 1=add1, 2=add2
    risk_per_trade_pct: 0.01      # 1% portfolio risk per layer
    stop_multiplier: 2.0          # 2× ATR stop
  
  # Constraints
  constraints:
    max_position_pct: 0.12        # 12% portfolio per stock
    max_add_liquidity_pct: 0.03   # 3% of daily turnover
    min_add_size_pct: 0.015       # 1.5% of portfolio minimum
  
  # Cost-benefit
  costs:
    benefit_multiplier: 3.0       # Expected gain > 3× cost
  
  # Capital allocation
  allocation:
    max_score_gap_to_challengers: 15.0  # Don't pyramid if Challenger 15+ pts better
  
  # Circuit breakers
  circuit_breakers:
    max_portfolio_drawdown: 0.15  # 15%
    max_vix: 30
    min_market_efficiency: 0.30
    max_single_position_pct: 0.10
  
  # Market cap thresholds (₹Cr)
  market_cap:
    large_cap: 10000
    mid_cap: 5000
```

### Regime-Specific Overrides

```python
# config/pyramid_config.yaml (continued)

regime_overrides:
  
  # Strong uptrend + low volatility
  aggressive:
    conditions:
      regime: MONTHLY
      max_vix: 15
    overrides:
      entry.min_score: 75.0
      price_thresholds.large_cap_min_gain_pct: 4.0
      sizing.max_layers: 2
      costs.benefit_multiplier: 3.0
  
  # Choppy/volatile market
  conservative:
    conditions:
      regime: WEEKLY
      min_vix: 25
    overrides:
      entry.min_score: 85.0
      price_thresholds.large_cap_min_gain_pct: 8.0
      sizing.max_layers: 1
      costs.benefit_multiplier: 4.0
```

---

## Testing Requirements

### Unit Tests

```python
# tests/test_pyramiding.py

import pytest
from datetime import datetime, timedelta
from pyramiding import *

class TestPyramiding:
    
    def test_can_pyramid_all_checks_pass(self):
        """Test that can_pyramid returns True when all conditions met"""
        position = create_mock_position(
            symbol='TCS',
            score=85,
            price=3800,
            ema_200=3500,
            atr_ratio=1.2
        )
        
        can_add, reason = can_pyramid(position, 85, 80, indicators, config, date)
        
        assert can_add == True
        assert reason == "ELIGIBLE"
    
    def test_can_pyramid_fails_on_score_degradation(self):
        """Test that score degradation blocks pyramiding"""
        position = create_mock_position(score=65)
        
        can_add, reason = can_pyramid(position, 65, 82, indicators, config, date)
        
        assert can_add == False
        assert "SCORE_DETERIORATING" in reason
    
    def test_can_pyramid_fails_on_ema50_below_entry(self):
        """Test new constraint: 50 EMA must be above initial entry"""
        position = create_mock_position(
            initial_entry_price=3500,
            ema_50=3450  # Below entry
        )
        
        config = PyramidConfig(require_ema50_above_entry=True)
        
        can_add, reason = can_pyramid(position, 85, 80, indicators, config, date)
        
        assert can_add == False
        assert reason == "EMA50_BELOW_INITIAL_ENTRY"
    
    def test_can_pyramid_fails_on_stop_below_cost(self):
        """Test new constraint: stop must be above average cost (risk-free)"""
        position = create_mock_position(
            average_cost=3600,
            highest_high=3850,
            atr=50
        )
        
        # Trailing stop = 3850 - (2 × 50) = 3750
        # Average cost = 3600
        # Stop is above cost, should pass
        
        config = PyramidConfig(require_stop_above_cost=True)
        
        can_add, reason = can_pyramid(position, 85, 80, indicators, config, date)
        
        assert can_add == True  # Stop > cost
        
        # Now test failure case
        position2 = create_mock_position(
            average_cost=3800,  # Higher cost
            highest_high=3850,
            atr=50
        )
        
        # Trailing stop = 3750
        # Average cost = 3800
        # Stop is BELOW cost, should fail
        
        can_add2, reason2 = can_pyramid(position2, 85, 80, indicators, config, date)
        
        assert can_add2 == False
        assert reason2 == "STOP_BELOW_AVG_COST"
    
    def test_pyramid_sizing_respects_atr(self):
        """Test that add size is recalculated with current ATR"""
        position = create_mock_position(
            last_layer_size=100000,
            current_atr=100,
            current_price=4000
        )
        
        config = PyramidConfig(
            pyramid_size_pct=0.50,
            risk_per_trade_pct=0.01
        )
        
        portfolio_capital = 10_00_000  # ₹10L
        
        # 50% of last layer = ₹50,000 (pyramid rule)
        # ATR sizing:
        # Risk = 1% × 10L = ₹10,000
        # Stop distance = 2 × 100 = 200
        # Shares = 10000 / 200 = 50
        # ATR size = 50 × 4000 = ₹2,00,000
        
        # Should take min(50000, 200000) = 50,000
        
        add_size, shares, reason = calculate_pyramid_add_size(
            position, portfolio_capital, indicators, config, date
        )
        
        assert add_size == 50000  # Pyramid rule is more conservative
        assert reason == "APPROVED"
    
    def test_cost_benefit_blocks_low_expected_gain(self):
        """Test that adds with low expected gain are blocked"""
        position = create_mock_position(
            recent_gain_pct=2.0,  # Only 2% since last add
            score_momentum=0      # Score flat
        )
        
        proposed_add_size = 50000
        
        # Expected gain = 2% × 1.0 × 0.5 = 1.0%
        # Cost = ~0.35% round-trip
        # Min required = 0.35% × 3 = 1.05%
        # 1.0% < 1.05% → FAIL
        
        is_worth_it, analysis = cost_benefit_check(
            position, proposed_add_size, config, date
        )
        
        assert is_worth_it == False
        assert analysis['expected_gain_pct'] < analysis['min_required_gain_pct']
```

### Integration Tests

```python
def test_full_pyramid_lifecycle(self):
    """
    End-to-end test: Initial entry → Add #1 → Add #2 → Exit
    """
    portfolio = initialize_portfolio(capital=10_00_000)
    
    # T+0: Initial entry (TCS @ ₹3500, Score 75)
    initial_position = enter_position(
        portfolio, 'TCS', date=datetime(2025, 1, 15),
        price=3500, score=75
    )
    
    assert initial_position.pyramid_count == 0
    assert len(initial_position.layers) == 1
    
    # T+20: Price rises to ₹3780 (+8%), Score rises to 85
    # Should trigger pyramid add #1
    universe.update_scores(date=datetime(2025, 2, 5))
    actions = rebalance_portfolio(portfolio, universe, datetime(2025, 2, 5))
    
    pyramid_actions = [a for a in actions if a.action == 'PYRAMID_ADD']
    assert len(pyramid_actions) == 1
    assert pyramid_actions[0].symbol == 'TCS'
    assert pyramid_actions[0].layer == 1
    
    # Update position
    position_after_add1 = portfolio.get_position('TCS')
    assert position_after_add1.pyramid_count == 1
    assert len(position_after_add1.layers) == 2
    
    # T+40: Price rises to ₹4000 (+5.8% from add #1), Score stable at 83
    # Should trigger pyramid add #2
    universe.update_scores(date=datetime(2025, 2, 25))
    actions2 = rebalance_portfolio(portfolio, universe, datetime(2025, 2, 25))
    
    pyramid_actions2 = [a for a in actions2 if a.action == 'PYRAMID_ADD']
    assert len(pyramid_actions2) == 1
    assert pyramid_actions2[0].layer == 2
    
    position_after_add2 = portfolio.get_position('TCS')
    assert position_after_add2.pyramid_count == 2
    assert len(position_after_add2.layers) == 3
    
    # T+60: Score drops to 48 (below 50 threshold)
    # Should trigger full exit
    universe.update_scores(date=datetime(2025, 3, 15))
    actions3 = rebalance_portfolio(portfolio, universe, datetime(2025, 3, 15))
    
    exit_actions = [a for a in actions3 if a.action == 'SELL' and a.symbol == 'TCS']
    assert len(exit_actions) == 1
    assert exit_actions[0].reason == 'SCORE_DEGRADED'
    assert exit_actions[0].size_pct == 1.0  # Full exit
```

---

## Performance Benchmarks

### Backtest Comparison Requirements

When implementing, you MUST compare:

1. **Base strategy (no pyramiding)**
   - Expected CAGR: 22-28%
   - Expected Sharpe: 1.6-2.0
   - Expected Max DD: 18-24%

2. **With pyramiding**
   - Expected CAGR: 26-34%
   - Expected Sharpe: 1.7-2.1
   - Expected Max DD: 20-26%

### Success Criteria

Pyramiding implementation is **correct** if:

- [ ] CAGR improvement: +3% to +8% (median: +5%)
- [ ] Sharpe improvement: +0.1 to +0.3 (median: +0.15)
- [ ] Max DD increase: ≤ 3% (acceptable for return improvement)
- [ ] Win rate change: -3% to +1% (neutral to slight decrease)
- [ ] Average win size: +5% to +10% (key benefit)
- [ ] Transaction cost increase: +40% to +60% (more trades)
- [ ] Pyramiding occurs in 15-25% of holdings (not too rare, not too common)

### Red Flags (Implementation Bugs)

If you see these, something is wrong:

- ❌ CAGR improvement >10% (likely over-fitted or cost model wrong)
- ❌ Sharpe improvement >0.5 (unrealistic)
- ❌ Max DD improves (pyramiding should increase DD slightly)
- ❌ Win rate improves (pyramiding should not improve win rate)
- ❌ Pyramiding occurs >50% of time (too aggressive, ignoring filters)
- ❌ Average position size >15% (violating concentration limits)

---

## Implementation Checklist

### Phase 1: Data Structures (Week 1)

- [ ] Define `PyramidLayer` dataclass
- [ ] Define `PyramidedPosition` dataclass
- [ ] Define `PyramidConfig` dataclass
- [ ] Add `layers` field to existing Position class
- [ ] Implement `@property` methods for aggregates (total_shares, average_cost, etc.)
- [ ] Write unit tests for data structures

### Phase 2: Core Logic (Week 2)

- [ ] Implement `can_pyramid()` with 8 gate checks
- [ ] Implement `should_pyramid_now()` with 5 trigger conditions
- [ ] Implement `calculate_pyramid_add_size()` with ATR sizing
- [ ] Implement `cost_benefit_check()` with Indian cost model
- [ ] Implement `calculate_unified_exit()` with partial exit support
- [ ] Implement `should_disable_pyramiding_global()` circuit breaker
- [ ] Write unit tests for each function

### Phase 3: Integration (Week 3)

- [ ] Modify `rebalance_portfolio()` to include pyramiding step
- [ ] Update Position class → PyramidedPosition throughout codebase
- [ ] Modify exit logic to use unified pyramid exit
- [ ] Add pyramiding actions to trade log
- [ ] Update portfolio state tracking for pyramid metadata
- [ ] Write integration tests

### Phase 4: Backtesting (Week 4)

- [ ] Run backtest with pyramiding OFF (baseline)
- [ ] Run backtest with pyramiding ON (test)
- [ ] Compare metrics (CAGR, Sharpe, DD, win rate, avg win)
- [ ] Validate against success criteria
- [ ] Check for red flags
- [ ] Stress test: vary config parameters (cost multiplier, min score, etc.)

### Phase 5: Validation (Week 5)

- [ ] Walk-forward analysis (train 2015-2020, test 2021-2025)
- [ ] Regime analysis (pyramiding performance in uptrend vs choppy)
- [ ] Sector analysis (which sectors benefit most from pyramiding?)
- [ ] Position size analysis (pyramided positions vs non-pyramided)
- [ ] Tax impact analysis (STCG drag from pyramid layers)
- [ ] Generate validation report

---

## Code Examples

### Example 1: Complete Pyramid Workflow

```python
# At rebalance date: Feb 5, 2025
# Existing holding: TCS, entered Jan 15 @ ₹3500, Score was 75
# Current: Price ₹3800, Score 85

position = portfolio.get_position('TCS')
current_score = universe.get_score('TCS', date)
prior_score = 75
indicators = get_indicators('TCS', date)
config = PyramidConfig.for_regime('BIWEEKLY', vix=18)

# Step 1: Gate check
can_add, reason = can_pyramid(
    position, current_score, prior_score, indicators, config, date
)

if not can_add:
    print(f"Cannot pyramid: {reason}")
    # Output: (nothing, passes all gates)

# Step 2: Trigger check
should_add, reason = should_pyramid_now(
    position, current_score, indicators, portfolio, config, date
)

if not should_add:
    print(f"Should not add now: {reason}")
    # Output: (nothing, triggers satisfied)

# Step 3: Position sizing
add_size, shares, size_reason = calculate_pyramid_add_size(
    position, portfolio.total_equity, indicators, config, date
)

print(f"Proposed add: ₹{add_size:,.0f} ({shares} shares)")
# Output: Proposed add: ₹50,000 (13 shares)

# Step 4: Cost-benefit
is_worth_it, analysis = cost_benefit_check(
    position, add_size, config, date
)

if not is_worth_it:
    print(f"Cost-benefit fail: Expected {analysis['expected_gain_pct']:.2f}% "
          f"vs Required {analysis['min_required_gain_pct']:.2f}%")
else:
    print(f"Cost-benefit pass: Expected {analysis['expected_gain_pct']:.2f}% "
          f"> Required {analysis['min_required_gain_pct']:.2f}%")
    
    # Step 5: Execute
    new_layer = execute_pyramid_add(
        position, add_size, shares, current_score, indicators, date, portfolio
    )
    
    print(f"Pyramid add executed: Layer {new_layer.layer_number} @ ₹{new_layer.entry_price:.2f}")
    # Output: Pyramid add executed: Layer 1 @ ₹3804.00
```

### Example 2: Exit with Tax Optimization

```python
# Later: TCS score drops to 60 (still above 50 but fading)
# Position is large (11% of portfolio)
# Consider partial exit

position = portfolio.get_position('TCS')
current_score = 60
indicators = get_indicators('TCS', date)

should_exit, reason, scale_out_pct = calculate_unified_exit(
    position, current_score, indicators, date
)

if should_exit:
    if scale_out_pct is None:
        # Full exit
        print(f"Exit entire position: {reason}")
    else:
        # Partial exit - choose tax-efficient layers
        print(f"Scale out {scale_out_pct*100:.0f}%: {reason}")
        
        # Determine which layers to sell
        tax_lots = track_pyramid_tax_lots(position)
        
        # Sort by tax efficiency (sell STCG first if possible)
        tax_lots_sorted = sorted(tax_lots, key=lambda x: x['is_ltcg'])
        
        shares_to_sell = int(position.total_shares * scale_out_pct)
        
        layers_to_exit = []
        shares_sold = 0
        
        for lot in tax_lots_sorted:
            if shares_sold >= shares_to_sell:
                break
            
            shares_from_lot = min(lot['shares'], shares_to_sell - shares_sold)
            layers_to_exit.append({
                'layer': lot['layer_number'],
                'shares': shares_from_lot,
                'is_ltcg': lot['is_ltcg'],
                'entry_price': lot['avg_price']
            })
            shares_sold += shares_from_lot
        
        print(f"Exiting layers: {layers_to_exit}")
```

### Example 3: Regime-Based Config Loading

```python
from datetime import datetime

def get_pyramid_config_for_date(date: datetime) -> PyramidConfig:
    """
    Load appropriate pyramid config based on current market regime
    """
    # Determine market regime
    regime = determine_rebalancing_frequency(date)  # Returns MONTHLY/BIWEEKLY/WEEKLY
    india_vix = get_india_vix(date)
    
    # Load regime-specific config
    config = PyramidConfig.for_regime(regime, india_vix)
    
    # Log config in use
    print(f"[{date}] Regime: {regime}, VIX: {india_vix:.1f}")
    print(f"Pyramid config: Score≥{config.min_score_threshold}, "
          f"Gain≥{config.min_price_gain_pct}%, "
          f"MaxLayers={config.max_pyramid_layers}")
    
    return config

# Usage in main rebalancing loop
config = get_pyramid_config_for_date(current_date)
actions = rebalance_portfolio_with_pyramiding(portfolio, universe, date, config)
```

---

## Helper Functions

### Utility 1: `estimate_impact_cost()`

```python
def estimate_impact_cost(symbol: str, order_value: float, date: datetime) -> float:
    """
    Estimate impact cost based on order size vs daily liquidity
    
    Impact cost = slippage due to market depth
    
    Indian market rules of thumb:
    - Order < 5% of daily turnover: 15 bps impact
    - Order 5-10%: 35 bps
    - Order 10-15%: 60 bps
    - Order >15%: 150 bps (severe, avoid)
    """
    avg_daily_turnover = get_avg_daily_turnover(symbol, date, days=20)
    order_as_pct_adv = order_value / avg_daily_turnover
    
    if order_as_pct_adv < 0.05:
        impact_bps = 15
    elif order_as_pct_adv < 0.10:
        impact_bps = 35
    elif order_as_pct_adv < 0.15:
        impact_bps = 60
    else:
        impact_bps = 150
    
    impact_cost = order_value * (impact_bps / 10000)
    
    return impact_cost
```

### Utility 2: `calculate_market_efficiency()`

```python
def calculate_market_efficiency(date: datetime, lookback: int = 60) -> float:
    """
    Calculate trend efficiency of Nifty 50 index
    
    Efficiency = |Total Return| / Sum of |Daily Returns|
    
    - High efficiency (>0.50): Strong trend (good for pyramiding)
    - Low efficiency (<0.30): Choppy market (avoid pyramiding)
    
    Returns:
        float in range [0, 1]
    """
    nifty_prices = get_price_series('^NSEI', date, lookback=lookback)
    daily_returns = nifty_prices.pct_change().dropna()
    
    total_return = (nifty_prices.iloc[-1] / nifty_prices.iloc[0]) - 1
    path_length = daily_returns.abs().sum()
    
    efficiency = abs(total_return) / path_length if path_length > 0 else 0
    
    return efficiency
```

### Utility 3: `get_highest_high_since()`

```python
def get_highest_high_since(symbol: str, since_date: datetime, current_date: datetime) -> float:
    """
    Get highest high price since entry date
    
    Used for trailing stop calculation
    """
    price_data = get_price_series(
        symbol, 
        start_date=since_date, 
        end_date=current_date
    )
    
    highest_high = price_data['high'].max()
    
    return highest_high
```

---

## Logging & Monitoring

### Log Structure

```python
# Every pyramid action should be logged with full context

log_entry = {
    'timestamp': datetime.now(),
    'action': 'PYRAMID_ADD',
    'symbol': 'TCS',
    'layer': 1,
    'price': 3804.0,
    'shares': 13,
    'size_inr': 49452,
    'score': 85.0,
    'score_prev': 75.0,
    'price_gain_pct': 8.2,
    'ema_50': 3650,
    'initial_entry_price': 3500,
    'ema50_vs_entry': 150,  # ₹150 above
    'trailing_stop': 3700,
    'avg_cost': 3500,
    'stop_vs_cost': 200,  # ₹200 above (risk-free)
    'expected_gain_pct': 4.1,
    'cost_pct': 0.37,
    'cost_benefit_ratio': 11.1,  # 4.1 / 0.37
    'total_position_value': 249452,
    'total_position_pct': 2.49,
    'regime': 'BIWEEKLY',
    'vix': 18.2,
    'decision_path': [
        'GATE_CHECK_PASSED',
        'TRIGGER_CHECK_PASSED',
        'SIZE_CALCULATED',
        'COST_BENEFIT_PASSED',
        'EXECUTED'
    ]
}
```

### Monitoring Dashboard Metrics

Track these metrics separately for pyramided vs non-pyramided positions:

```python
pyramid_metrics = {
    # Incidence
    'pct_positions_pyramided': 0.22,  # 22% of holdings were pyramided
    'avg_pyramid_layers': 1.3,        # Average 1.3 adds per pyramided position
    
    # Performance
    'avg_return_pyramided': 0.28,     # 28% avg return on pyramided positions
    'avg_return_non_pyramided': 0.19, # 19% on non-pyramided
    'lift_from_pyramiding': 0.09,     # 9% lift
    
    # Costs
    'total_pyramid_cost_inr': 45000,  # Total STT/impact on adds
    'cost_as_pct_gains': 0.02,        # 2% of gains consumed by pyramid costs
    
    # Risk
    'max_pyramided_position_pct': 0.11,  # Largest pyramided position
    'avg_pyramided_position_pct': 0.09,  # Average
    'pyramided_positions_in_loss': 0.18  # 18% of pyramid adds ended in loss
}
```

---

## Advanced Features (Optional)

### Feature 1: Dynamic Layer Sizing

Instead of fixed 50%, adjust layer size by momentum strength:

```python
def calculate_dynamic_pyramid_size(position, current_score, prior_score):
    """
    Vary pyramid size based on momentum acceleration
    
    - Score rising >10 points: 60% of previous layer (aggressive)
    - Score rising 5-10 points: 50% (standard)
    - Score rising 0-5 points: 40% (conservative)
    """
    score_change = current_score - prior_score
    
    if score_change > 10:
        size_fraction = 0.60
    elif score_change > 5:
        size_fraction = 0.50
    else:
        size_fraction = 0.40
    
    return size_fraction
```

### Feature 2: Sector-Specific Pyramid Rules

```python
def get_sector_pyramid_config(symbol: str, date: datetime) -> dict:
    """
    Adjust pyramid rules by sector characteristics
    
    IT/Pharma: More aggressive (smoother trends)
    Metals/RE: More conservative (cyclical, choppy)
    """
    sector = get_sector(symbol)
    
    sector_rules = {
        'IT': {
            'min_score': 75,
            'max_layers': 2,
            'min_gain_pct': 4.0
        },
        'Pharma': {
            'min_score': 75,
            'max_layers': 2,
            'min_gain_pct': 4.5
        },
        'FMCG': {
            'min_score': 78,
            'max_layers': 2,
            'min_gain_pct': 5.0
        },
        'Metals': {
            'min_score': 85,
            'max_layers': 1,
            'min_gain_pct': 8.0
        },
        'Real Estate': {
            'min_score': 85,
            'max_layers': 1,
            'min_gain_pct': 10.0
        },
        'PSU Banks': {
            'min_score': 85,
            'max_layers': 1,
            'min_gain_pct': 8.0
        }
    }
    
    return sector_rules.get(sector, {
        'min_score': 80,
        'max_layers': 2,
        'min_gain_pct': 5.0
    })
```

### Feature 3: Adaptive Cost Multiplier

```python
def calculate_adaptive_cost_multiplier(
    position: PyramidedPosition,
    portfolio: 'Portfolio',
    date: datetime
) -> float:
    """
    Adjust cost multiplier based on:
    - How many winners in portfolio (if few, be more aggressive)
    - Recent strategy performance (if struggling, be more conservative)
    
    Returns:
        float: cost multiplier (2.0 - 5.0)
    """
    # Factor 1: Scarcity of winners
    high_score_count = len([
        h for h in portfolio.holdings 
        if universe.get_score(h.symbol, date) > 80
    ])
    
    if high_score_count <= 3:
        scarcity_adjustment = -0.5  # More aggressive (lower multiplier)
    elif high_score_count >= 8:
        scarcity_adjustment = +0.5  # More conservative
    else:
        scarcity_adjustment = 0
    
    # Factor 2: Recent strategy performance
    portfolio_returns_60d = portfolio.get_returns(date, lookback=60)
    rolling_sharpe = calculate_rolling_sharpe(portfolio_returns_60d, window=60)
    
    if rolling_sharpe > 2.0:
        performance_adjustment = -0.5  # Strategy hot, be more aggressive
    elif rolling_sharpe < 1.0:
        performance_adjustment = +1.0  # Strategy struggling, be conservative
    else:
        performance_adjustment = 0
    
    # Base multiplier = 3.0
    adjusted_multiplier = 3.0 + scarcity_adjustment + performance_adjustment
    
    # Clamp to reasonable range
    adjusted_multiplier = max(2.0, min(5.0, adjusted_multiplier))
    
    return adjusted_multiplier
```

---

## FAQ for Implementation

### Q1: What if a pyramid add gets filled at a gap up price?

**A:** Use conservative execution assumptions:
- Entry price = Next day open × 1.001 (0.1% slippage)
- If actual fill is better, great (but don't rely on it in backtest)
- If actual fill is worse, your backtest was still realistic

### Q2: How to handle partial fills on pyramid adds?

**A:** For backtesting:
- Assume full fill if order ≤ 5% of daily volume
- Assume 80% fill if order 5-10% of daily volume
- Skip order if >10% of daily volume

For live trading:
- Use limit orders (accept partial fills)
- If <80% filled, cancel and skip this add (don't chase)

### Q3: What if the stock gaps down through stop before I can exit?

**A:** Slippage modeling:
- On stop hits, assume exit at stop price − 0.5% (conservative)
- On earnings gaps, assume exit at open − 1.0% (more severe)
- This is why we have the ATR spike check (blocks pyramiding before earnings)

### Q4: Should I pyramid into positions already showing a loss?

**A:** No, never:
- The gate check `require_stop_above_cost` prevents this
- Only pyramid when trailing stop > average cost (effective risk = 0)
- Otherwise you're averaging down, not pyramiding up

### Q5: How to choose between pyramiding stock A vs B (both eligible)?

**A:** Priority order:
1. Higher composite score
2. Stronger score momentum (rising vs stable)
3. Better risk-adjusted return (ROC/ATR)
4. Better liquidity (if one is mid-cap, other is large-cap, prefer large-cap)

---

## Final Implementation Notes

### Critical Path

The minimal implementation requires:

1. **PyramidedPosition data structure** (must track multiple layers)
2. **can_pyramid() + should_pyramid_now()** (entry logic)
3. **calculate_pyramid_add_size()** (ATR-based sizing)
4. **calculate_unified_exit()** (single exit for all layers)
5. **Integration into rebalance loop** (add Step 2 between exits and swaps)

### Optional Enhancements (Implement Later)

- Partial exits (scale-out logic)
- Dynamic layer sizing (vary 50% by score momentum)
- Sector-specific rules
- Adaptive cost multipliers
- Tax-lot optimization

### Expected Implementation Time

- **Minimal version:** 3-4 weeks (data structures + core functions + integration + basic tests)
- **Full version:** 6-8 weeks (add advanced features + comprehensive backtests + validation)

### Success Validation

After implementation, you MUST see:

1. **In backtest output:**
   - Clear improvement in CAGR (+3-8%)
   - Slight increase in max DD (+1-3%)
   - Pyramiding occurring 15-25% of time
   - Average win size larger for pyramided positions

2. **In trade logs:**
   - Pyramid adds only on scores >80
   - Pyramid adds only after 5-8% price moves
   - No pyramiding during VIX >30 periods
   - Position sizes respecting 12% cap

3. **In cost analysis:**
   - Total transaction costs 40-60% higher (due to more trades)
   - But net returns still higher (costs << additional gains)

---

**This spec is complete and ready for implementation. Hand this to your IDE coding assistant with the instruction: "Implement the pyramiding module as specified, maintaining 100% compatibility with existing portfolio.py and scoring.py interfaces."**
