"""
Portfolio Management Service

Implements:
- Champion vs Challenger logic (hysteresis buffer)
- Position management with stop-loss
- Action generation (BUY/SELL/SWAP)
"""
from datetime import date
from typing import List, Dict
import pandas as pd

from utils.stop_loss import calculate_initial_stop_loss, calculate_effective_stop, should_trigger_stop_loss
from utils.position_sizing import calculate_position_size


class PortfolioService:
    """Service for portfolio management and action generation"""
    
    def __init__(self, risk_config: dict):
        """
        Initialize with risk configuration.
        
        Args:
            risk_config: Dict with initial_capital, risk_per_trade, max_positions,
                        buffer_percent, exit_threshold, stop_loss_multiplier
        """
        self.config = risk_config
        self.buffer = risk_config.get('buffer_percent', 0.25)
        self.exit_threshold = risk_config.get('exit_threshold', 40.0)
        self.stop_multiplier = risk_config.get('stop_loss_multiplier', 2.0)
        self.risk_per_trade = risk_config.get('risk_per_trade', 1000.0)
        self.max_positions = risk_config.get('max_positions', 15)
        self.current_capital = risk_config.get('current_capital', 100000.0)
    
    def should_swap(self, incumbent_score: float, challenger_score: float) -> bool:
        """
        Determine if a challenger should replace an incumbent.
        
        Implements hysteresis buffer to prevent excessive churn.
        Swap only if: challenger_score > incumbent_score × (1 + buffer)
        
        Args:
            incumbent_score: Score of currently held stock
            challenger_score: Score of potential replacement
            
        Returns:
            True if swap is justified
        """
        threshold = incumbent_score * (1 + self.buffer)
        return challenger_score > threshold
    
    def should_exit(self, score: float) -> bool:
        """
        Determine if a position should be exited due to degradation.
        
        Args:
            score: Current composite score of the stock
            
        Returns:
            True if score below exit threshold
        """
        return score < self.exit_threshold
    
    def calculate_entry_position(
        self, 
        symbol: str, 
        price: float, 
        atr: float
    ) -> dict:
        """
        Calculate position size and stop-loss for a new entry.
        
        Args:
            symbol: Stock symbol
            price: Entry price
            atr: ATR at entry
            
        Returns:
            Dict with shares, stop-losses, and position details
        """
        # Calculate position size
        sizing = calculate_position_size(
            risk_per_trade=self.risk_per_trade,
            atr=atr,
            stop_multiplier=self.stop_multiplier,
            current_price=price,
            max_position_value=self.current_capital
        )
        
        # Calculate initial stop-loss
        initial_stop = calculate_initial_stop_loss(
            buy_price=price,
            atr=atr,
            multiplier=self.stop_multiplier
        )
        
        return {
            'tradingsymbol': symbol,
            'buy_price': price,
            'num_shares': sizing['shares'],
            'atr_at_entry': atr,
            'initial_stop_loss': round(initial_stop, 2),
            'current_stop_loss': round(initial_stop, 2),
            'position_value': sizing['position_value'],
            'risk_amount': sizing['risk_amount']
        }
    
    def generate_actions(
        self,
        ranked_stocks: pd.DataFrame,
        invested_stocks: List[Dict],
        current_prices: Dict[str, float],
        current_atrs: Dict[str, float],
        action_date: date = None
    ) -> List[Dict]:
        """
        Generate trade actions based on rankings and portfolio state.
        
        Process:
        1. Check for SELL (stop-loss hits or score degradation)
        2. Check for SWAP (challenger beats incumbent by buffer)
        3. Check for BUY (vacancies exist, allocate to top stocks)
        
        Args:
            ranked_stocks: DataFrame with 'symbol', 'composite_score'
            invested_stocks: List of currently invested positions
            current_prices: Dict of symbol -> current price
            current_atrs: Dict of symbol -> current ATR
            action_date: Date for actions (default today)
            
        Returns:
            List of action dicts
        """
        if action_date is None:
            action_date = date.today()
        
        actions = []
        invested_symbols = {s['tradingsymbol'] for s in invested_stocks}
        
        # Build score lookup from ranking
        score_lookup = dict(zip(ranked_stocks['symbol'], ranked_stocks['composite_score']))
        
        # ========== PHASE 1: SELL Actions (Stop-Loss & Degradation) ==========
        vacancies = self.max_positions - len(invested_stocks)
        sell_symbols = set()
        
        # Separate strategy vs non-strategy stocks
        strategy_stocks = [s for s in invested_stocks if s.get('include_in_strategy', True)]
        non_strategy_stocks = [s for s in invested_stocks if not s.get('include_in_strategy', True)]
        
        # Non-strategy stocks don't count toward max_positions
        vacancies = self.max_positions - len(strategy_stocks)
        
        for position in invested_stocks:
            symbol = position['tradingsymbol']
            current_price = current_prices.get(symbol, 0)
            current_atr = current_atrs.get(symbol, 0)
            current_score = score_lookup.get(symbol, 0)
            is_strategy = position.get('include_in_strategy', True)
            
            # Update stop-loss levels
            stops = calculate_effective_stop(
                buy_price=position['buy_price'],
                current_price=current_price,
                current_atr=current_atr,
                initial_stop=position['initial_stop_loss'],
                previous_stop=position['current_stop_loss'],
                multiplier=self.stop_multiplier
            )
            
            # Check stop-loss trigger (applies to ALL stocks)
            if should_trigger_stop_loss(current_price, stops['effective_stop']):
                actions.append({
                    'action_date': action_date,
                    'action_type': 'SELL',
                    'tradingsymbol': symbol,
                    'units': position['num_shares'],
                    'expected_price': current_price,
                    'composite_score': current_score,
                    'reason': f"Stop-loss triggered at {stops['effective_stop']}" + (" (manual)" if not is_strategy else "")
                })
                if is_strategy:
                    vacancies += 1
                sell_symbols.add(symbol)
                continue
            
            # Check score degradation (only for strategy stocks)
            if is_strategy and self.should_exit(current_score):
                actions.append({
                    'action_date': action_date,
                    'action_type': 'SELL',
                    'tradingsymbol': symbol,
                    'units': position['num_shares'],
                    'expected_price': current_price,
                    'composite_score': current_score,
                    'reason': f"Score degraded to {current_score:.1f} (threshold: {self.exit_threshold})"
                })
                vacancies += 1
                sell_symbols.add(symbol)
        
        # Update invested symbols after sells
        invested_symbols = invested_symbols - sell_symbols
        strategy_symbols = {s['tradingsymbol'] for s in strategy_stocks} - sell_symbols
        
        # ========== PHASE 2: SWAP Actions (only for strategy stocks) ==========
        # Get top challengers not in portfolio
        challengers = ranked_stocks[~ranked_stocks['symbol'].isin(invested_symbols)].copy()
        
        # Check each STRATEGY incumbent against top challenger
        for position in strategy_stocks:
            symbol = position['tradingsymbol']
            if symbol not in strategy_symbols:  # Already sold
                continue
            
            incumbent_score = score_lookup.get(symbol, 0)
            current_price = current_prices.get(symbol, 0)
            
            # Find best challenger
            if len(challengers) == 0:
                break
            
            top_challenger = challengers.iloc[0]
            challenger_symbol = top_challenger['symbol']
            challenger_score = top_challenger['composite_score']
            challenger_price = current_prices.get(challenger_symbol, 0)
            challenger_atr = current_atrs.get(challenger_symbol, 0)
            
            if self.should_swap(incumbent_score, challenger_score):
                # Calculate new position size
                new_sizing = calculate_position_size(
                    risk_per_trade=self.risk_per_trade,
                    atr=challenger_atr,
                    stop_multiplier=self.stop_multiplier,
                    current_price=challenger_price
                )
                
                actions.append({
                    'action_date': action_date,
                    'action_type': 'SWAP',
                    'tradingsymbol': challenger_symbol,
                    'units': new_sizing['shares'],
                    'expected_price': challenger_price,
                    'composite_score': challenger_score,
                    'swap_from_symbol': symbol,
                    'swap_from_units': position['num_shares'],
                    'swap_from_price': current_price,
                    'reason': f"Challenger {challenger_score:.1f} > Incumbent {incumbent_score:.1f} × 1.25"
                })
                
                invested_symbols.discard(symbol)
                invested_symbols.add(challenger_symbol)
                # Remove this challenger from consideration
                challengers = challengers[challengers['symbol'] != challenger_symbol]
        
        # ========== PHASE 3: BUY Actions (Fill Vacancies) ==========
        if vacancies > 0:
            # Get available stocks not in portfolio
            available = ranked_stocks[~ranked_stocks['symbol'].isin(invested_symbols)]
            
            for _, stock in available.head(vacancies).iterrows():
                symbol = stock['symbol']
                score = stock['composite_score']
                price = current_prices.get(symbol, 0)
                atr = current_atrs.get(symbol, 0)
                
                if price <= 0:
                    continue
                
                sizing = calculate_position_size(
                    risk_per_trade=self.risk_per_trade,
                    atr=atr,
                    stop_multiplier=self.stop_multiplier,
                    current_price=price
                )
                
                actions.append({
                    'action_date': action_date,
                    'action_type': 'BUY',
                    'tradingsymbol': symbol,
                    'units': sizing['shares'],
                    'expected_price': price,
                    'composite_score': score,
                    'reason': f"Filling vacancy - Score {score:.1f}"
                })
                invested_symbols.add(symbol)
        
        return actions
    
    def update_capital_after_trade(
        self,
        action_type: str,
        trade_value: float,
        gain_loss: float = 0
    ) -> float:
        """
        Update capital after executing a trade.
        
        Args:
            action_type: BUY, SELL, or SWAP
            trade_value: Value of the trade
            gain_loss: Profit or loss (for SELL)
            
        Returns:
            New capital value
        """
        if action_type == 'BUY':
            self.current_capital -= trade_value
        elif action_type == 'SELL':
            self.current_capital += trade_value
        
        return self.current_capital