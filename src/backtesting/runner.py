"""
Backtest Runner

Main entry point for running backtests with API-based data fetching.
No hardcoded values - all configuration from API or config classes.
Writes simulated results to backtest.db (isolated from personal.db).
"""
import os
from datetime import date, timedelta
from typing import Dict, List, Optional
from dataclasses import asdict
from flask import current_app

from config import setup_logger
from config.strategies_config import PositionSizingConfig
from src.backtesting.models import Position, BacktestResult, BacktestRiskMonitor
from src.backtesting.config import BacktestConfigLoader
from src.backtesting.api_client import BacktestAPIClient
from src.utils.stoploss_utils import (
    calculate_initial_stop_loss,
    calculate_effective_stop
)
from src.utils.transaction_costs_utils import calculate_round_trip_cost
from src.utils.tax_utils import calculate_capital_gains_tax
from src.utils.database_manager import DatabaseManager
from src.services.portfolio_controls_service import PortfolioControlsService
from repositories import InvestmentRepository

logger = setup_logger(name="BacktestRunner")


class WeeklyBacktester:
    """
    API-based weekly backtesting engine.
    
    All configuration fetched from API. Uses existing utils for:
    - Stop-loss calculations
    - Transaction costs
    - Tax calculations
    - Drawdown controls
    """
    
    def __init__(self, start_date: date, end_date: date, base_url: Optional[str] = None):
        self.start_date = start_date
        self.end_date = end_date
        
        # Load config from API
        self.config_loader = BacktestConfigLoader(base_url)
        self.config = self.config_loader.fetch()
        
        # API client for data
        self.api = BacktestAPIClient(base_url)
        
        # Portfolio controls for drawdown management
        self.portfolio_controls = PortfolioControlsService()
        
        # Portfolio state
        self.current_capital = self.config.initial_capital
        self.positions: Dict[str, Position] = {}
        self.risk_monitor = BacktestRiskMonitor(self.config.initial_capital)
        self.weekly_results: List[BacktestResult] = []
        
        # Cumulative costs and taxes
        self.total_transaction_costs = 0.0
        self.total_taxes_paid = 0.0
        
        # Drawdown tracking
        self.is_paused = False
        
        # Database session for backtest writes
        self.backtest_session = None
    
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
    
    def calculate_position_size(self, atr: Optional[float], current_price: float) -> Dict:
        """
        Calculate position size based on risk parameters from config.
        
        Parameters:
            atr: Average True Range
            current_price: Current stock price
            
        Returns:
            Dict with shares, position_value, stop_distance
        """
        risk_per_trade = self.config.initial_capital * (self.config.risk_per_trade_percent / 100.0)
        
        if atr is None or atr <= 0:
            stop_distance = current_price * self.config.sl_fallback_percent
        else:
            stop_distance = atr * self.config.stop_multiplier
        
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
    
    def should_trigger_stop_loss(self, current_price: float, effective_stop: float) -> bool:
        """Check if current price has breached the stop-loss level"""
        return current_price <= effective_stop
    
    def should_exit_score_degradation(self, score: float) -> bool:
        """Check if position should exit due to score falling below threshold"""
        return score < self.config.exit_threshold
    
    def should_swap(self, incumbent_score: float, challenger_score: float) -> bool:
        """Determine if challenger should replace incumbent (with buffer)"""
        threshold = incumbent_score * (1 + self.config.buffer_percent)
        return challenger_score > threshold
    
    def calculate_portfolio_value(self, current_prices: Dict[str, float]) -> float:
        """Calculate total portfolio value"""
        positions_value = sum(
            pos.units * current_prices.get(pos.tradingsymbol, pos.entry_price)
            for pos in self.positions.values()
        )
        return self.current_capital + positions_value
    
    def execute_sell(self, symbol: str, current_price: float, week_date: date, 
                     reason: str) -> Dict:
        """
        Execute a sell order with transaction costs and taxes.
        
        Returns:
            Action dict with all details
        """
        pos = self.positions[symbol]
        gross_proceeds = pos.units * current_price
        
        # Calculate transaction costs
        costs = calculate_round_trip_cost(gross_proceeds)
        sell_costs = costs.get('sell_costs', 0)
        self.total_transaction_costs += sell_costs
        
        # Calculate taxes
        tax_info = calculate_capital_gains_tax(
            purchase_price=pos.entry_price,
            current_price=current_price,
            purchase_date=pos.entry_date,
            current_date=week_date,
            quantity=pos.units
        )
        tax = tax_info.get('tax', 0)
        self.total_taxes_paid += tax
        
        # Net proceeds
        net_proceeds = gross_proceeds - sell_costs - tax
        pnl = net_proceeds - (pos.entry_price * pos.units)
        
        # Update capital
        self.current_capital += net_proceeds
        
        action = {
            'action_date': week_date.isoformat(),
            'action_type': 'SELL',
            'tradingsymbol': symbol,
            'units': pos.units,
            'price': current_price,
            'gross_pnl': round((current_price - pos.entry_price) * pos.units, 2),
            'transaction_costs': round(sell_costs, 2),
            'tax': round(tax, 2),
            'net_pnl': round(pnl, 2),
            'reason': reason
        }
        
        # Record and remove
        self.risk_monitor.record_trade({'type': 'SELL', 'symbol': symbol, 'pnl': pnl})
        del self.positions[symbol]
        
        return action
    
    def execute_buy(self, symbol: str, price: float, score: float, atr: float,
                    week_date: date, reason: str) -> Optional[Dict]:
        """
        Execute a buy order with transaction costs.
        
        Returns:
            Action dict or None if insufficient capital
        """
        sizing = self.calculate_position_size(atr, price)
        if sizing['shares'] == 0:
            return None
        
        position_cost = sizing['shares'] * price
        
        # Calculate transaction costs
        costs = calculate_round_trip_cost(position_cost)
        buy_costs = costs.get('buy_costs', 0)
        self.total_transaction_costs += buy_costs
        
        total_cost = position_cost + buy_costs
        
        if total_cost > self.current_capital:
            logger.warning(f"Insufficient capital for {symbol}: need {total_cost}, have {self.current_capital}")
            return None
        
        # Deduct capital
        self.current_capital -= total_cost
        
        # Calculate initial stop-loss
        initial_stop = calculate_initial_stop_loss(
            price, atr, self.config.stop_multiplier,
            PositionSizingConfig()
        )
        
        # Create position
        self.positions[symbol] = Position(
            tradingsymbol=symbol,
            entry_price=price,
            units=sizing['shares'],
            entry_date=week_date,
            composite_score=score,
            atr_at_entry=atr or 0,
            initial_stop_loss=initial_stop,
            current_stop_loss=initial_stop
        )
        
        return {
            'action_date': week_date.isoformat(),
            'action_type': 'BUY',
            'tradingsymbol': symbol,
            'units': sizing['shares'],
            'price': price,
            'transaction_costs': round(buy_costs, 2),
            'initial_stop': round(initial_stop, 2),
            'reason': reason
        }
    
    def rebalance_portfolio(self, week_date: date, top_rankings: List[dict],
                            score_lookup: Dict[str, float],
                            price_lookup: Dict[str, float]) -> List[dict]:
        """
        Rebalance portfolio:
        PHASE 1: SELL (Stop-Loss or Score Degradation)
        PHASE 2: SWAP (Challenger beats Incumbent × buffer)
        PHASE 3: BUY (Fill vacancies)
        """
        actions = []
        vacancies = self.config.max_positions - len(self.positions)
        
        # ========== PHASE 1: SELL ==========
        for symbol, pos in list(self.positions.items()):
            current_price = price_lookup.get(symbol, pos.entry_price)
            current_score = score_lookup.get(symbol, pos.composite_score)
            
            # Fetch current ATR
            current_atr = self.api.get_indicator('atrr_14', symbol, week_date)
            if current_atr is None:
                current_atr = current_price * 0.02  # 2% fallback
            
            # Update trailing stop
            stops = calculate_effective_stop(
                buy_price=pos.entry_price,
                current_price=current_price,
                current_atr=current_atr,
                initial_stop=pos.initial_stop_loss,
                stop_multiplier=self.config.stop_multiplier,
                sl_step_percent=self.config.sl_step_percent,
                previous_stop=pos.current_stop_loss
            )
            pos.current_stop_loss = stops['effective_stop']
            
            # Check STOP-LOSS
            if self.should_trigger_stop_loss(current_price, stops['effective_stop']):
                action = self.execute_sell(
                    symbol, current_price, week_date,
                    f"Stop-loss triggered at {stops['effective_stop']:.2f}"
                )
                actions.append(action)
                vacancies += 1
                continue
            
            # Check SCORE DEGRADATION
            if self.should_exit_score_degradation(current_score):
                action = self.execute_sell(
                    symbol, current_price, week_date,
                    f"Score degraded to {current_score:.1f}"
                )
                actions.append(action)
                vacancies += 1
        
        # ========== PHASE 2: SWAP ==========
        invested_symbols = set(self.positions.keys())
        challengers = [r for r in top_rankings if r['tradingsymbol'] not in invested_symbols]
        
        for symbol, pos in list(self.positions.items()):
            if not challengers:
                break
            
            incumbent_score = score_lookup.get(symbol, 0)
            current_price = price_lookup.get(symbol, pos.entry_price)
            
            top_challenger = challengers[0]
            challenger_symbol = top_challenger['tradingsymbol']
            challenger_score = top_challenger['composite_score']
            challenger_price = price_lookup.get(challenger_symbol, 100.0)
            
            if self.should_swap(incumbent_score, challenger_score):
                # Sell incumbent
                sell_action = self.execute_sell(
                    symbol, current_price, week_date,
                    f"Swapped for {challenger_symbol}"
                )
                
                # Buy challenger
                challenger_atr = self.api.get_indicator('atrr_14', challenger_symbol, week_date)
                buy_action = self.execute_buy(
                    challenger_symbol, challenger_price, challenger_score,
                    challenger_atr or 0, week_date,
                    f"Swap from {symbol}"
                )
                
                if buy_action:
                    actions.append({
                        'action_date': week_date.isoformat(),
                        'action_type': 'SWAP',
                        'swap_from': symbol,
                        'swap_to': challenger_symbol,
                        'sell_details': sell_action,
                        'buy_details': buy_action
                    })
                    challengers.pop(0)
        
        # ========== PHASE 3: BUY ==========
        for challenger in challengers[:vacancies]:
            symbol = challenger['tradingsymbol']
            if symbol in self.positions:
                continue
            
            price = price_lookup.get(symbol, 100.0)
            score = challenger['composite_score']
            atr = self.api.get_indicator('atrr_14', symbol, week_date)
            
            buy_action = self.execute_buy(
                symbol, price, score, atr or 0, week_date,
                "New buy - vacancy fill"
            )
            if buy_action:
                actions.append(buy_action)
                vacancies -= 1
            
            if vacancies <= 0:
                break
        
        return actions
    
    def run(self) -> List[BacktestResult]:
        """
        Execute the backtest.
        
        Returns:
            List of weekly BacktestResult objects
        """
        logger.info(f"Starting backtest: {self.start_date} to {self.end_date}")
        logger.info(f"Config: capital={self.config.initial_capital}, "
                   f"max_positions={self.config.max_positions}, "
                   f"exit_threshold={self.config.exit_threshold}")
        
        # Initialize backtest database
        try:
            app = current_app._get_current_object()
            DatabaseManager.init_backtest_db(app)
            DatabaseManager.clear_backtest_db(app)
            self.backtest_session = DatabaseManager.get_backtest_session()
            logger.info("Backtest database initialized and cleared")
        except RuntimeError as e:
            logger.warning(f"No Flask app context, DB writes disabled: {e}")
            self.backtest_session = None
        
        mondays = self.get_week_mondays()
        
        for week_date in mondays:
            logger.info(f"Processing week: {week_date}")
            
            # Fetch rankings from API
            rankings = self.api.get_top_rankings(self.config.max_positions, week_date)
            if not rankings:
                logger.warning(f"No rankings for {week_date}, skipping")
                continue
            
            # Build lookups
            score_lookup = {r['tradingsymbol']: r['composite_score'] for r in rankings}
            price_lookup = {}
            for r in rankings:
                price = self.api.get_close_price(r['tradingsymbol'], week_date)
                if price:
                    price_lookup[r['tradingsymbol']] = price
            
            # Add current holdings to price lookup
            for symbol in self.positions:
                if symbol not in price_lookup:
                    price = self.api.get_close_price(symbol, week_date)
                    if price:
                        price_lookup[symbol] = price
            
            # Rebalance
            actions = self.rebalance_portfolio(week_date, rankings, score_lookup, price_lookup)
            
            # Calculate metrics
            portfolio_value = self.calculate_portfolio_value(price_lookup)
            self.risk_monitor.update(portfolio_value)
            
            # Check drawdown controls
            drawdown_status = self.portfolio_controls.check_drawdown_status(
                portfolio_value, self.risk_monitor.peak_value
            )
            if drawdown_status['status'] == 'paused':
                self.is_paused = True
                logger.warning(f"New entries paused: {drawdown_status['drawdown']}% drawdown")
            elif drawdown_status['status'] == 'critical':
                self.is_paused = True
                logger.warning(f"Critical drawdown: {drawdown_status['drawdown']}% - reducing exposure")
            else:
                self.is_paused = False
            
            # Record result
            result = BacktestResult(
                week_date=week_date,
                portfolio_value=portfolio_value,
                total_return=self.risk_monitor.get_total_return(),
                max_drawdown=self.risk_monitor.max_drawdown,
                actions=actions,
                top_10_stocks=[r['tradingsymbol'] for r in rankings],
                holdings=[asdict(pos) for pos in self.positions.values()]
            )
            self.weekly_results.append(result)
            
            # Persist to backtest database
            self._persist_weekly_result(week_date, actions, portfolio_value)
        
        logger.info(f"Backtest complete. Final value: {self.weekly_results[-1].portfolio_value if self.weekly_results else 0}")
        logger.info(f"Total transaction costs: {self.total_transaction_costs:.2f}")
        logger.info(f"Total taxes paid: {self.total_taxes_paid:.2f}")
        
        return self.weekly_results
    
    def _persist_weekly_result(self, week_date: date, actions: List[dict], 
                               portfolio_value: float):
        """
        Persist weekly results to backtest database.
        
        Writes actions, holdings, and summary for analysis.
        """
        if self.backtest_session is None:
            return  # DB writes disabled (no Flask context)
        
        # Convert actions to database format
        action_records = []
        for action in actions:
            if action.get('action_type') == 'SWAP':
                # Swap contains nested sell/buy
                sell = action.get('sell_details', {})
                buy = action.get('buy_details', {})
                action_records.extend([
                    {
                        'working_date': week_date,
                        'type': 'sell',
                        'symbol': sell.get('tradingsymbol', ''),
                        'units': sell.get('units', 0),
                        'prev_close': sell.get('price', 0),
                        'execution_price': sell.get('price', 0),
                        'capital': sell.get('gross_pnl', 0),
                        'reason': f"Swap to {buy.get('tradingsymbol', '')}",
                        'status': 'Approved'
                    },
                    {
                        'working_date': week_date,
                        'type': 'buy',
                        'symbol': buy.get('tradingsymbol', ''),
                        'units': buy.get('units', 0),
                        'prev_close': buy.get('price', 0),
                        'execution_price': buy.get('price', 0),
                        'capital': buy.get('units', 0) * buy.get('price', 0),
                        'reason': f"Swap from {sell.get('tradingsymbol', '')}",
                        'status': 'Approved'
                    }
                ])
            else:
                action_records.append({
                    'working_date': week_date,
                    'type': action.get('action_type', '').lower(),
                    'symbol': action.get('tradingsymbol', ''),
                    'units': action.get('units', 0),
                    'prev_close': action.get('price', 0),
                    'execution_price': action.get('price', 0),
                    'capital': action.get('units', 0) * action.get('price', 0),
                    'reason': action.get('reason', ''),
                    'status': 'Approved'
                })
        
        if action_records:
            InvestmentRepository.bulk_insert_actions(
                action_records, 
                session=self.backtest_session
            )
        
        # Convert holdings to database format
        holding_records = []
        for pos in self.positions.values():
            holding_records.append({
                'symbol': pos.tradingsymbol,
                'working_date': week_date,
                'entry_date': pos.entry_date,
                'entry_price': pos.entry_price,
                'units': pos.units,
                'atr': pos.atr_at_entry,
                'score': pos.composite_score,
                'entry_sl': pos.initial_stop_loss,
                'current_price': pos.entry_price,  # Will be updated with actual
                'current_sl': pos.current_stop_loss
            })
        
        if holding_records:
            InvestmentRepository.bulk_insert_holdings(
                holding_records,
                session=self.backtest_session
            )
        
        # Create summary record
        prev_summary = InvestmentRepository.get_summary(session=self.backtest_session)
        starting_capital = prev_summary.remaining_capital if prev_summary else self.config.initial_capital
        
        summary = {
            'working_date': week_date,
            'starting_capital': round(starting_capital, 2),
            'sold': round(self.total_transaction_costs, 2),  # Approx
            'bought': 0,
            'capital_risk': 0,
            'portfolio_value': round(portfolio_value, 2),
            'portfolio_risk': 0,
            'gain': round(portfolio_value - self.config.initial_capital, 2),
            'gain_percentage': round(
                (portfolio_value - self.config.initial_capital) / self.config.initial_capital * 100, 2
            )
        }
        InvestmentRepository.insert_summary(summary, session=self.backtest_session)
    
    def get_summary(self) -> dict:
        """Get comprehensive backtest summary"""
        risk_summary = self.risk_monitor.get_summary()
        risk_summary['total_transaction_costs'] = round(self.total_transaction_costs, 2)
        risk_summary['total_taxes_paid'] = round(self.total_taxes_paid, 2)
        return risk_summary


def run_backtest(start_date: date, end_date: date, base_url: Optional[str] = None):
    """
    Convenience function to run a backtest.
    
    Parameters:
        start_date: Start date for backtest
        end_date: End date for backtest
        base_url: Optional API base URL
        
    Returns:
        Tuple of (results, summary)
    """
    backtester = WeeklyBacktester(start_date, end_date, base_url)
    results = backtester.run()
    summary = backtester.get_summary()
    return results, summary


if __name__ == "__main__":
    # Example usage
    from datetime import date
    from config import setup_logger
    
    logger = setup_logger(name="BacktestRunner")
    
    start = date(2024, 1, 1)
    end = date(2024, 12, 31)
    
    results, summary = run_backtest(start, end)
    logger.info(f"\n{'='*50}")
    logger.info("BACKTEST SUMMARY")
    logger.info(f"{'='*50}")
    for key, value in summary.items():
        logger.info(f"  {key}: {value}")

