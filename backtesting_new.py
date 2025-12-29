"""
Weekly Backtesting Script with Top 10 Stock Selection and Risk Monitoring

Aligned with ActionsService logic:
- PHASE 1: SELL (Stop-Loss triggers or Score Degradation)
- PHASE 2: SWAP (Challenger > Incumbent × buffer)
- PHASE 3: BUY (Fill vacancies from top ranked)

Features:
- ATR-based position sizing
- Trailing stop-loss (ATR + hard trailing)
- Exit threshold for score degradation
- Max Drawdown and Total Return tracking
- Weekly CSV exports
"""

from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import requests
import csv
import os

# ============== CONFIGURATION ==============
# API & Date Range
BASE_URL = "http://127.0.0.1:5000"
START_DATE = date(2025, 1, 1)
END_DATE = date(2025, 12, 18)
OUTPUT_DIR = "data"


# Risk Config (matching RiskConfigModel defaults)
INITIAL_CAPITAL = 100000.0
RISK_PER_TRADE_PERCENT = 1.0   # % of capital to risk per trade
STOP_LOSS_MULTIPLIER = 2.0     # ATR multiplier for stop-loss
EXIT_THRESHOLD = 40.0          # Score below this triggers exit
MAX_POSITIONS = 10             # Maximum concurrent positions (soft limit)
SL_STEP_PERCENT = 0.10         # Hard trailing step (10%)
MAX_POSITION_PERCENT = 20.0    # Max % of capital per position (prevents over-concentration)

# ============== KEY PARAMETERS (MODIFY THESE) ==============
TOP_N = MAX_POSITIONS                     # Number of top stocks to select each week
BUFFER_PERCENT = 0.25          # Swap buffer - challenger must beat incumbent by this % (25% = 0.25)

# ============== UTILITY FUNCTIONS (from src/utils) ==============

def calculate_initial_stop_loss(buy_price: float, atr: float, stop_multiplier: float) -> float:
    """Calculate initial ATR-based stop-loss at entry."""
    if atr is None or atr <= 0:
        return buy_price * 0.94  # 6% default stop
    stop_loss = buy_price - (stop_multiplier * atr)
    return max(stop_loss, 0)


def calculate_atr_trailing_stop(current_price: float, current_atr: float, 
                                 stop_multiplier: float, previous_stop: float = 0) -> float:
    """Calculate ATR trailing stop. Only moves up, never down."""
    if current_atr is None or current_atr <= 0:
        return previous_stop
    new_stop = current_price - (stop_multiplier * current_atr)
    return max(new_stop, previous_stop)


def calculate_trailing_hard_stop(buy_price: float, current_price: float, 
                                  initial_stop: float, sl_step_percent: float) -> float:
    """Calculate trailing hard stop that moves up in increments."""
    if current_price <= buy_price:
        return initial_stop
    gain_percent = (current_price - buy_price) / buy_price
    tiers = int(gain_percent // sl_step_percent)
    adjustment = 1 + (sl_step_percent * tiers)
    hard_stop = initial_stop * adjustment
    return min(hard_stop, buy_price)


def calculate_effective_stop(buy_price: float, current_price: float, current_atr: float, 
                              initial_stop: float, stop_multiplier: float, 
                              sl_step_percent: float, previous_stop: float = 0) -> dict:
    """Calculate effective stop-loss using both ATR and hard trailing methods."""
    atr_stop = calculate_atr_trailing_stop(current_price, current_atr, stop_multiplier, previous_stop)
    hard_stop = calculate_trailing_hard_stop(buy_price, current_price, initial_stop, sl_step_percent)
    
    # Use MAX to be more aggressive in locking in profits as soon as either method moves up
    effective_stop = max(atr_stop, hard_stop)
    
    return {
        "atr_stop": round(atr_stop, 2),
        "hard_stop": round(hard_stop, 2),
        "effective_stop": round(effective_stop, 2)
    }


def calculate_position_size(atr: float, stop_multiplier: float, 
                            risk_per_trade: float, current_price: float) -> dict:
    """Calculate position size based on ATR and risk tolerance."""
    if atr is None or atr <= 0:
        # Fallback: use 5% of price as stop distance
        stop_distance = current_price * 0.05
    else:
        stop_distance = atr * stop_multiplier
    
    if stop_distance <= 0:
        return {"shares": 0, "position_value": 0, "stop_distance": 0}
    
    shares = int(risk_per_trade / stop_distance)
    shares = max(1, shares)
    position_value = shares * current_price
    
    return {
        "shares": shares,
        "position_value": round(position_value, 2),
        "stop_distance": round(stop_distance, 2)
    }


# ============== DATA CLASSES ==============

@dataclass
class Position:
    """Represents a portfolio position with stop-loss tracking"""
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
        return self.entry_price * self.units


@dataclass 
class BacktestResult:
    """Stores backtest results for a single week"""
    week_date: date
    portfolio_value: float
    total_return: float
    max_drawdown: float
    actions: List[dict] = field(default_factory=list)
    top_10_stocks: List[str] = field(default_factory=list)
    holdings: List[dict] = field(default_factory=list)  # Snapshot of all positions
    # New metrics
    invested_amount: float = 0.0          # Total value invested in positions
    total_risk: float = 0.0               # Potential loss if all positions hit stop-loss
    successful_trades: int = 0            # Trades with positive PnL
    total_closed_trades: int = 0          # Total SELL + SWAP trades
    
    @property
    def hit_rate(self) -> float:
        """Percentage of successful trades"""
        if self.total_closed_trades == 0:
            return 0.0
        return (self.successful_trades / self.total_closed_trades) * 100


class BacktestRiskMonitor:
    """Track risk metrics during backtest simulation"""
    
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.portfolio_values: List[float] = [initial_capital]
        self.peak_value = initial_capital
        self.max_drawdown = 0.0
        self.trades: List[dict] = []
    
    def update(self, current_value: float):
        """Update metrics with new portfolio value"""
        self.portfolio_values.append(current_value)
        if current_value > self.peak_value:
            self.peak_value = current_value
        current_drawdown = (self.peak_value - current_value) / self.peak_value * 100
        self.max_drawdown = max(self.max_drawdown, current_drawdown)
    
    def record_trade(self, trade: dict):
        """Record a trade for later analysis"""
        self.trades.append(trade)
    
    def get_total_return(self) -> float:
        """Calculate total return percentage"""
        if not self.portfolio_values:
            return 0.0
        current = self.portfolio_values[-1]
        return ((current - self.initial_capital) / self.initial_capital) * 100
    
    def get_summary(self) -> dict:
        closed_trades = [t for t in self.trades if t['type'] in ('SELL', 'SWAP')]
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


# ============== MAIN BACKTESTER ==============

class WeeklyBacktester:
    """Main backtesting engine aligned with ActionsService logic"""
    
    def __init__(self, start_date: date, end_date: date, initial_capital: float = INITIAL_CAPITAL):
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.positions: Dict[str, Position] = {}
        self.risk_monitor = BacktestRiskMonitor(initial_capital)
        self.weekly_results: List[BacktestResult] = []
    
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
    
    def fetch_rankings_with_prices(self, ranking_date: date) -> List[dict]:
        """Fetch top N rankings with prices for a given date"""
        try:
            response = requests.get(
                f"{BASE_URL}/api/v1/ranking/top/{TOP_N}",
                params={"date": ranking_date.strftime("%Y-%m-%d")},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"  Warning: Could not fetch rankings for {ranking_date}: {e}")
        return []
    
    def fetch_ranking_by_symbol(self, symbol: str, ranking_date: date) -> Optional[dict]:
        """Fetch ranking for a specific symbol on a given date"""
        try:
            response = requests.get(
                f"{BASE_URL}/api/v1/ranking/symbol/{symbol}",
                params={"date": ranking_date.strftime("%Y-%m-%d")},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data and 'tradingsymbol' in data:
                    return data
        except Exception as e:
            pass  # Silently fail, will use stored score
        return None
    
    def fetch_indicator_data(self, symbol: str, as_of_date: date) -> dict:
        """Fetch indicators (ATR) for a symbol from API"""
        try:
            # Query indicators for that specific date
            response = requests.get(
                f"{BASE_URL}/api/v1/indicators/query",
                json={
                    "tradingsymbol": symbol,
                    "start_date": as_of_date.strftime("%Y-%m-%d"),
                    "end_date": as_of_date.strftime("%Y-%m-%d")
                },
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    atr_value = data[0].get('atrr_14')
                    if atr_value:
                        return {"atr": atr_value}
        except Exception as e:
            pass
        
        # Log when ATR is not available
        print(f"    ⚠️ ATR not found for {symbol} on {as_of_date} - using 5% fallback")
        return {"atr": None}
    
    def should_trigger_stop_loss(self, current_price: float, effective_stop: float) -> bool:
        """Check if current price has breached the stop-loss level"""
        return current_price <= effective_stop
    
    def should_exit_score_degradation(self, score: float) -> bool:
        """Check if position should exit due to score falling below threshold"""
        return score < EXIT_THRESHOLD
    
    def should_swap(self, incumbent_score: float, challenger_score: float) -> bool:
        """Determine if challenger should replace incumbent (with buffer)"""
        threshold = incumbent_score * (1 + BUFFER_PERCENT)
        return challenger_score > threshold
    
    def calculate_portfolio_value(self, current_prices: Dict[str, float]) -> float:
        """Calculate total portfolio value"""
        positions_value = sum(
            pos.units * current_prices.get(pos.tradingsymbol, pos.entry_price)
            for pos in self.positions.values()
        )
        return self.current_capital + positions_value
    
    def rebalance_portfolio(self, week_date: date, top_rankings: List[dict], 
                          score_lookup: Dict[str, float], 
                          price_lookup: Dict[str, float]) -> List[dict]:
        """
        Rebalance portfolio using ActionsService logic:
        PHASE 1: SELL (Stop-Loss or Score Degradation)
        PHASE 2: SWAP (Challenger beats Incumbent × buffer)
        PHASE 3: BUY (Fill vacancies)
        """
        actions = []
        top_symbols = set(r['tradingsymbol'] for r in top_rankings)
        
        # Track vacancies
        vacancies = MAX_POSITIONS - len(self.positions)
        sell_symbols = set()
        
        # ========== PHASE 1: SELL (Stop-Loss & Score Degradation) ==========
        for symbol, pos in list(self.positions.items()):
            current_price = price_lookup.get(symbol, pos.entry_price)
            # Use score from rankings if available, otherwise use position's stored score
            current_score = score_lookup.get(symbol, pos.composite_score)
            
            # Fetch current ATR from API
            indicator_data = self.fetch_indicator_data(symbol, week_date)
            current_atr = indicator_data.get('atr') or (current_price * 0.02)
            
            # Re-calculate effective stop-loss with FRESH ATR every week
            stops = calculate_effective_stop(
                buy_price=pos.entry_price,
                current_price=current_price,
                current_atr=current_atr,
                initial_stop=pos.initial_stop_loss,
                stop_multiplier=STOP_LOSS_MULTIPLIER,
                sl_step_percent=SL_STEP_PERCENT,
                previous_stop=pos.current_stop_loss
            )
            
            # Update trailing stop in position
            pos.current_stop_loss = stops['effective_stop']
            
            # Check STOP-LOSS trigger
            if self.should_trigger_stop_loss(current_price, stops['effective_stop']):
                pnl = (current_price - pos.entry_price) * pos.units
                actions.append({
                    'action_date': week_date.strftime('%Y-%m-%d'),
                    'action_type': 'SELL',
                    'tradingsymbol': symbol,
                    'units': pos.units,
                    'price': current_price,
                    'pnl': round(pnl, 2),
                    'reason': f"Stop-loss triggered at {stops['effective_stop']:.2f}"
                })
                self.current_capital += pos.units * current_price
                del self.positions[symbol]
                vacancies += 1
                sell_symbols.add(symbol)
                self.risk_monitor.record_trade({'type': 'SELL', 'symbol': symbol, 'pnl': pnl, 'reason': 'stop_loss'})
                continue
            
            # Check SCORE DEGRADATION exit
            if self.should_exit_score_degradation(current_score):
                pnl = (current_price - pos.entry_price) * pos.units
                actions.append({
                    'action_date': week_date.strftime('%Y-%m-%d'),
                    'action_type': 'SELL',
                    'tradingsymbol': symbol,
                    'units': pos.units,
                    'price': current_price,
                    'pnl': round(pnl, 2),
                    'reason': f"Score degraded to {current_score:.1f} (threshold: {EXIT_THRESHOLD})"
                })
                self.current_capital += pos.units * current_price
                del self.positions[symbol]
                vacancies += 1
                sell_symbols.add(symbol)
                self.risk_monitor.record_trade({'type': 'SELL', 'symbol': symbol, 'pnl': pnl, 'reason': 'score_degradation'})
        
        # ========== PHASE 2: SWAP (Challenger > Incumbent × buffer) ==========
        invested_symbols = set(self.positions.keys())
        challengers = [r for r in top_rankings if r['tradingsymbol'] not in invested_symbols]
        
        for symbol, pos in list(self.positions.items()):
            if not challengers:
                break
            
            incumbent_score = score_lookup.get(symbol, 0)
            current_price = price_lookup.get(symbol, pos.entry_price)
            
            # Get top challenger
            top_challenger = challengers[0]
            challenger_symbol = top_challenger['tradingsymbol']
            challenger_score = top_challenger['composite_score']
            challenger_price = price_lookup.get(challenger_symbol, 100.0)
            
            if self.should_swap(incumbent_score, challenger_score):
                # Sell incumbent
                pnl = (current_price - pos.entry_price) * pos.units
                
                # Calculate new position size with REAL ATR
                risk_amount = INITIAL_CAPITAL * (RISK_PER_TRADE_PERCENT / 100.0)
                challenger_indicator = self.fetch_indicator_data(challenger_symbol, week_date)
                challenger_atr = challenger_indicator.get('atr') or (challenger_price * 0.02)
                
                sizing = calculate_position_size(
                    atr=challenger_atr,
                    stop_multiplier=STOP_LOSS_MULTIPLIER,
                    risk_per_trade=risk_amount,
                    current_price=challenger_price
                )
                
                actions.append({
                    'action_date': week_date.strftime('%Y-%m-%d'),
                    'action_type': 'SWAP',
                    'tradingsymbol': challenger_symbol,
                    'units': sizing['shares'],
                    'price': challenger_price,
                    'swap_from': symbol,
                    'swap_from_units': pos.units,
                    'pnl': round(pnl, 2),
                    'reason': f"Challenger {challenger_score:.1f} > Incumbent {incumbent_score:.1f} × 1.25"
                })
                
                # Execute swap
                self.current_capital += pos.units * current_price  # Sell incumbent
                del self.positions[symbol]
                
                # Buy challenger
                initial_stop = calculate_initial_stop_loss(challenger_price, challenger_atr, STOP_LOSS_MULTIPLIER)
                cost = sizing['shares'] * challenger_price
                self.current_capital -= cost
                
                self.positions[challenger_symbol] = Position(
                    tradingsymbol=challenger_symbol,
                    entry_price=challenger_price,
                    units=sizing['shares'],
                    entry_date=week_date,
                    composite_score=challenger_score,
                    atr_at_entry=challenger_atr,
                    initial_stop_loss=initial_stop,
                    current_stop_loss=initial_stop
                )
                
                challengers.pop(0)  # Remove used challenger
                self.risk_monitor.record_trade({'type': 'SWAP', 'symbol': challenger_symbol, 'pnl': pnl})
        
        # ========== PHASE 3: BUY (Fill Vacancies) ==========
        # Refresh challengers list
        invested_symbols = set(self.positions.keys())
        challengers = [r for r in top_rankings if r['tradingsymbol'] not in invested_symbols]
        
        for challenger in challengers[:vacancies]:
            symbol = challenger['tradingsymbol']
            price = price_lookup.get(symbol, 100.0)
            score = challenger['composite_score']
            
            if price <= 0:
                continue
            
            # Calculate position size with REAL ATR
            risk_amount = INITIAL_CAPITAL * (RISK_PER_TRADE_PERCENT / 100.0)
            indicator_data = self.fetch_indicator_data(symbol, week_date)
            atr = indicator_data.get('atr') or (price * 0.02)
            
            sizing = calculate_position_size(
                atr=atr,
                stop_multiplier=STOP_LOSS_MULTIPLIER,
                risk_per_trade=risk_amount,
                current_price=price
            )
            
            if sizing['shares'] <= 0:
                continue
            
            cost = sizing['shares'] * price
            
            # Enforce max position cap (20% of capital per position)
            max_position_value = self.initial_capital * (MAX_POSITION_PERCENT / 100.0)
            if cost > max_position_value:
                sizing['shares'] = int(max_position_value / price)
                cost = sizing['shares'] * price
            
            if cost > self.current_capital:
                # Try to buy what we can afford
                affordable_shares = int(self.current_capital / price)
                if affordable_shares <= 0:
                    continue
                sizing['shares'] = affordable_shares
                cost = sizing['shares'] * price
            
            initial_stop = calculate_initial_stop_loss(price, atr, STOP_LOSS_MULTIPLIER)
            
            actions.append({
                'action_date': week_date.strftime('%Y-%m-%d'),
                'action_type': 'BUY',
                'tradingsymbol': symbol,
                'units': sizing['shares'],
                'price': price,
                'composite_score': score,
                'reason': f"Filling vacancy - Score {score:.1f}"
            })
            
            self.current_capital -= cost
            self.positions[symbol] = Position(
                tradingsymbol=symbol,
                entry_price=price,
                units=sizing['shares'],
                entry_date=week_date,
                composite_score=score,
                atr_at_entry=atr,
                initial_stop_loss=initial_stop,
                current_stop_loss=initial_stop
            )
            self.risk_monitor.record_trade({'type': 'BUY', 'symbol': symbol})
        
        return actions
    
    def run(self) -> List[BacktestResult]:
        """Execute the weekly backtest"""
        print("=" * 60)
        print("Starting Weekly Backtest (ActionsService Logic)")
        print(f"Period: {self.start_date} to {self.end_date}")
        print(f"Initial Capital: ₹{self.initial_capital:,.2f}")
        print(f"Exit Threshold: {EXIT_THRESHOLD} | Buffer: {BUFFER_PERCENT*100}%")
        print("=" * 60)
        
        mondays = self.get_week_mondays()
        print(f"\nProcessing {len(mondays)} weeks...\n")
        
        for i, monday in enumerate(mondays, 1):
            print(f"Week {i}/{len(mondays)}: {monday.strftime('%Y-%m-%d')}")
            
            # Fetch rankings with prices
            top_rankings = self.fetch_rankings_with_prices(monday)
            
            if not top_rankings:
                print(f"  No rankings available, skipping...")
                continue
            
            top_symbols = [r['tradingsymbol'] for r in top_rankings]
            print(f"  Top {len(top_symbols)}: {', '.join(top_symbols[:5])}...")
            
            # Build lookups for ALL required stocks (Top 10 + currently held)
            score_lookup = {r['tradingsymbol']: r['composite_score'] for r in top_rankings}
            price_lookup = {r['tradingsymbol']: r.get('close_price') or 100.0 for r in top_rankings}
            
            # Fetch for held positions not in top 10
            for sym, pos in list(self.positions.items()):
                if sym not in score_lookup:
                    ranking_data = self.fetch_ranking_by_symbol(sym, monday)
                    # API now returns 0.0 and close_price even if not ranked
                    if ranking_data and 'composite_score' in ranking_data:
                        score_lookup[sym] = ranking_data.get('composite_score', 0.0)
                        price_lookup[sym] = ranking_data.get('close_price') or pos.entry_price
                        pos.composite_score = score_lookup[sym] # Sync position score
                    else:
                        # Fallback only if API failed COMPLETELY
                        score_lookup[sym] = pos.composite_score
                        price_lookup[sym] = pos.entry_price
            
            # Rebalance portfolio (now using the synced lookups)
            actions = self.rebalance_portfolio(monday, top_rankings, score_lookup, price_lookup)
            
            # Calculate current portfolio value
            portfolio_value = self.calculate_portfolio_value(price_lookup)
            self.risk_monitor.update(portfolio_value)
            
            # Calculate new metrics
            invested_amount = sum(
                pos.units * price_lookup.get(sym, pos.entry_price)
                for sym, pos in self.positions.items()
            )
            
            # Total risk = potential loss if all positions hit stop-loss
            total_risk = sum(
                (price_lookup.get(sym, pos.entry_price) - pos.current_stop_loss) * pos.units
                for sym, pos in self.positions.items()
            )
            
            # Count successful trades (positive PnL) from SELL and SWAP actions
            closed_trades = [a for a in actions if a['action_type'] in ('SELL', 'SWAP')]
            successful_trades = len([t for t in closed_trades if t.get('pnl', 0) > 0])
            total_closed_trades = len(closed_trades)
            
            # Capture holdings snapshot for this week
            holdings_snapshot = []
            for sym, pos in self.positions.items():
                current_price = price_lookup.get(sym, pos.entry_price)
                holdings_snapshot.append({
                    'tradingsymbol': sym,
                    'entry_date': pos.entry_date.strftime('%Y-%m-%d'),
                    'entry_price': pos.entry_price,
                    'current_price': current_price,
                    'units': pos.units,
                    'composite_score': pos.composite_score,
                    'initial_stop_loss': pos.initial_stop_loss,
                    'current_stop_loss': pos.current_stop_loss,
                    'unrealized_pnl': round((current_price - pos.entry_price) * pos.units, 2)
                })
            
            # Store result
            result = BacktestResult(
                week_date=monday,
                portfolio_value=portfolio_value,
                total_return=self.risk_monitor.get_total_return(),
                max_drawdown=self.risk_monitor.max_drawdown,
                actions=actions,
                top_10_stocks=top_symbols,
                holdings=holdings_snapshot,
                invested_amount=round(invested_amount, 2),
                total_risk=round(total_risk, 2),
                successful_trades=successful_trades,
                total_closed_trades=total_closed_trades
            )
            self.weekly_results.append(result)
            
            sells = len([a for a in actions if a['action_type'] == 'SELL'])
            swaps = len([a for a in actions if a['action_type'] == 'SWAP'])
            buys = len([a for a in actions if a['action_type'] == 'BUY'])
            print(f"  SELL:{sells} SWAP:{swaps} BUY:{buys} | Portfolio: ₹{portfolio_value:,.2f} | Return: {result.total_return:.2f}%")
        
        print("\n" + "=" * 60)
        print("Backtest Complete!")
        self.print_summary()
        
        return self.weekly_results
    
    def print_summary(self):
        """Print final backtest summary"""
        summary = self.risk_monitor.get_summary()
        print("\n📊 RISK SUMMARY")
        print("-" * 40)
        print(f"Initial Capital:    ₹{summary['initial_capital']:,.2f}")
        print(f"Final Value:        ₹{summary['final_value']:,.2f}")
        print(f"Total Return:       {summary['total_return_percent']:.2f}%")
        print(f"Max Drawdown:       {summary['max_drawdown_percent']:.2f}%")
        print(f"Total Trades:       {summary['total_trades']} (Success: {summary['successful_trades']})")
        print(f"Hit Rate:           {summary['hit_rate_percent']:.2f}%")
        print(f"Open Positions:     {len(self.positions)}")
        print("-" * 40)
    
    def export_to_csv(self, filename_prefix: str = "backtest"):
        """Export results to CSV files"""
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Weekly summary
        summary_file = f"{OUTPUT_DIR}/{filename_prefix}_weekly_summary.csv"
        with open(summary_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Week Date', 'Portfolio Value', 'Total Return %', 'Max Drawdown %', 
                           'Invested Amount', 'Total Risk', 'Successful Trades', 'Total Trades', 
                           'Hit Rate %', 'Sells', 'Swaps', 'Buys', 'Top Stocks'])
            for result in self.weekly_results:
                sells = len([a for a in result.actions if a['action_type'] == 'SELL'])
                swaps = len([a for a in result.actions if a['action_type'] == 'SWAP'])
                buys = len([a for a in result.actions if a['action_type'] == 'BUY'])
                writer.writerow([
                    result.week_date.strftime('%Y-%m-%d'),
                    round(result.portfolio_value, 2),
                    round(result.total_return, 2),
                    round(result.max_drawdown, 2),
                    result.invested_amount,
                    result.total_risk,
                    result.successful_trades,
                    result.total_closed_trades,
                    round(result.hit_rate, 1),
                    sells, swaps, buys,
                    '; '.join(result.top_10_stocks)
                ])
        print(f"\n✅ Weekly summary: {summary_file}")
        
        # Actions log
        actions_file = f"{OUTPUT_DIR}/{filename_prefix}_actions.csv"
        with open(actions_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Date', 'Action', 'Symbol', 'Units', 'Price', 'Swap From', 'PnL', 'Reason'])
            for result in self.weekly_results:
                for action in result.actions:
                    writer.writerow([
                        action.get('action_date', ''),
                        action.get('action_type', ''),
                        action.get('tradingsymbol', ''),
                        action.get('units', ''),
                        round(action.get('price', 0), 2),
                        action.get('swap_from', ''),
                        action.get('pnl', ''),
                        action.get('reason', '')
                    ])
        print(f"✅ Actions log: {actions_file}")
        
        # Risk summary
        risk_file = f"{OUTPUT_DIR}/{filename_prefix}_risk_summary.csv"
        summary = self.risk_monitor.get_summary()
        with open(risk_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Metric', 'Value'])
            for key, value in summary.items():
                writer.writerow([key, value])
        print(f"✅ Risk summary: {risk_file}")
        
        # Holdings log with stop-loss
        holdings_file = f"{OUTPUT_DIR}/{filename_prefix}_holdings.csv"
        with open(holdings_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Week Date', 'Symbol', 'Entry Date', 'Entry Price', 'Current Price',
                           'Units', 'Score', 'Initial SL', 'Current SL', 'Unrealized PnL'])
            for result in self.weekly_results:
                for holding in result.holdings:
                    writer.writerow([
                        result.week_date.strftime('%Y-%m-%d'),
                        holding.get('tradingsymbol', ''),
                        holding.get('entry_date', ''),
                        round(holding.get('entry_price', 0), 2),
                        round(holding.get('current_price', 0), 2),
                        holding.get('units', ''),
                        round(holding.get('composite_score', 0), 2),
                        round(holding.get('initial_stop_loss', 0), 2),
                        round(holding.get('current_stop_loss', 0), 2),
                        holding.get('unrealized_pnl', '')
                    ])
        print(f"✅ Holdings log: {holdings_file}")


def main():
    """Main entry point"""
    backtester = WeeklyBacktester(
        start_date=START_DATE,
        end_date=END_DATE,
        initial_capital=INITIAL_CAPITAL
    )
    
    results = backtester.run()
    backtester.export_to_csv()
    
    return results


if __name__ == "__main__":
    main()