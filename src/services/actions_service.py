import pandas as pd

from datetime import date
from typing import List, Dict


from config import TOP_N_RANKINGS, DEFAULT_INITIAL_SL
from repositories import (ActionsRepository, ConfigRepository, RankingRepository,
                          PortfolioRepository, MarketDataRepository, IndicatorsRepository)
from utils import calculate_initial_stop_loss, calculate_effective_stop, calculate_position_size

actions_repo = ActionsRepository()
config_repo = ConfigRepository()
ranking_repo = RankingRepository()
portfolio_repo = PortfolioRepository()
marketdata_repo = MarketDataRepository()
indicators_repo = IndicatorsRepository()


class ActionsService:
    """Service for portfolio management and action generation"""
    
    def __init__(self):
        config_result = config_repo.get_config()
        if not config_result:
            raise Exception("Risk config not set up. POST to /risk_config first.")
        self.config = {c.name: getattr(config_result, c.name) for c in config_result.__table__.columns}
        self.buffer = self.config.get('buffer_percent', 0.25)
        self.exit_threshold = self.config.get('exit_threshold', 40.0)
        self.stop_multiplier = self.config.get('stop_loss_multiplier', 2.0)
        self.risk_per_trade = self.config.get('risk_per_trade', 1000.0)
        self.max_positions = self.config.get('max_positions', 15)
        self.current_capital = self.config.get('current_capital', 100000.0)
        self.sl_step_percent = self.config.get('sl_step_percent', 0.1)


    @staticmethod
    def query_to_dict(results):
        return [
            {c.name: getattr(row, c.name) for c in row.__table__.columns}
            for row in results
        ]


    @staticmethod
    def should_trigger_stop_loss(current_price: float, effective_stop: float) -> bool:
        """
        Check if current price has breached the stop-loss level.

        Args:
            current_price: Current market price
            effective_stop: Current stop-loss level

        Returns:
            True if stop-loss triggered
        """
        return current_price <= effective_stop

    @staticmethod
    def get_input_to_generate_actions(ranking_date):
        # Get rankings
        rankings = ranking_repo.get_top_n_rankings_by_date(TOP_N_RANKINGS, ranking_date)
        if not rankings:
            raise Exception(f"No rankings found for {ranking_date}")

        invested = portfolio_repo.get_invested()
        invested_list  = []
        for i in invested:
            if i.include_in_strategy:
                ranking = ranking_repo.get_rankings_by_date_and_symbol(ranking_date, i.tradingsymbol)
                rankings.append(ranking)
                invested_list.append(
                    {
                        'tradingsymbol': i.tradingsymbol,
                        'buy_price': i.buy_price,
                        'num_shares': i.num_shares,
                        'initial_stop_loss': i.initial_stop_loss,
                        'current_stop_loss': i.current_stop_loss
                    }
                )
        current_prices = {}
        current_atrs = {}

        symbols = [r.tradingsymbol for r in rankings]
        for symbol in symbols:
            try:
                # Get price
                price = marketdata_repo.get_latest_date_by_symbol(symbol)
                ind_resp = indicators_repo.get_latest_date_by_symbol(symbol)
                current_atrs[symbol] = ind_resp.atrr_14
                current_prices[symbol] = price.close
            except Exception:
                continue
        return rankings, invested_list, current_prices, current_atrs

    def _should_swap(self, incumbent_score: float, challenger_score: float) -> bool:
        """
        Determine if a challenger should replace an incumbent.
        
        Implements hysteresis buffer to prevent excessive churn.
        Swap only if: challenger_score > incumbent_score × (1 + buffer)
        """
        threshold = incumbent_score * (1 + self.buffer)
        return challenger_score > threshold
    
    def _should_exit(self, score: float) -> bool:
        """
        Determine if a position should be exited due to degradation.
        """
        return score < self.exit_threshold

    def _invest_in_stock(self, action):
        trade_value = action.units * action.expected_price
        self.config.current_capital -= trade_value

        atr = indicators_repo.get_indicator_by_tradingsymbol("atrr_14", action.tradingsymbol)
        initial_stop = calculate_initial_stop_loss(action.expected_price,
                                                         atr or (action.expected_price * DEFAULT_INITIAL_SL), self.config.stop_loss_multiplier)

        invested = {
            "tradingsymbol": action.tradingsymbol,
            "buy_price": action.expected_price,
            "num_shares": action.units,
            "buy_date": action.action_date,
            "atr_at_entry": atr,
            "initial_stop_loss": round(initial_stop, 2),
            "current_stop_loss": round(initial_stop, 2),
            "include_in_strategy": True
        }
        response = portfolio_repo.buy_stock(invested)
        if not response:
            raise Exception("Failed to add invested")

    @staticmethod
    def sell_stock(action, swap=False):
        if swap:
            tradingsymbol = action.swap_from_symbol
        else:
            tradingsymbol = action.tradingsymbol
        response = portfolio_repo.sell_stock(tradingsymbol)
        if not response:
            raise Exception("Failed to sell stock")
    
    def generate_actions(self, action_date = None) -> List[Dict]:
        """
        Generate trade actions based on rankings and portfolio state.
        
        Process:
        1. Check for SELL (stop-loss hits or score degradation)
        2. Check for SWAP (challenger beats incumbent by buffer)
        3. Check for BUY (vacancies exist, allocate to top stocks)
        """
        if action_date is None:
            action_date = date.today()

        rankings, invested_list, current_prices, current_atrs = self.get_input_to_generate_actions(action_date)
        rankings = self.query_to_dict(rankings)
        rankings = pd.DataFrame(rankings)

        actions = []
        invested_symbols = {s['tradingsymbol'] for s in invested_list}
        score_lookup = dict(zip(rankings['tradingsymbol'], rankings['composite_score']))
        
        # ========== PHASE 1: SELL Actions (Stop-Loss & Degradation) ==========
        vacancies = self.max_positions - len(invested_list)
        sell_symbols = set()
        
        for position in invested_list:
            symbol = position['tradingsymbol']
            current_price = current_prices.get(symbol, 0)
            current_atr = current_atrs.get(symbol, 0)
            current_score = score_lookup.get(symbol, 0)
            
            # Update stop-loss levels
            stops = calculate_effective_stop(
                buy_price=position['buy_price'],
                current_price=current_price,
                current_atr=current_atr,
                initial_stop=position['initial_stop_loss'],
                previous_stop=position['current_stop_loss'],
                stop_multiplier=self.stop_multiplier,
                sl_step_percent=self.sl_step_percent,
            )
            
            # Check stop-loss trigger (applies to ALL stocks)
            if self.should_trigger_stop_loss(current_price, stops['effective_stop']):
                actions.append({
                    'action_date': action_date,
                    'action_type': 'SELL',
                    'tradingsymbol': symbol,
                    'units': position['num_shares'],
                    'expected_price': current_price,
                    'composite_score': current_score,
                    'amount': round(current_price * position['num_shares'], 2),
                    'reason': f"Stop-loss triggered at {stops['effective_stop']}"
                })
                vacancies += 1
                sell_symbols.add(symbol)
                continue
            
            # Check score degradation (only for strategy stocks)
            if self._should_exit(current_score):
                actions.append({
                    'action_date': action_date,
                    'action_type': 'SELL',
                    'tradingsymbol': symbol,
                    'units': position['num_shares'],
                    'expected_price': current_price,
                    'composite_score': current_score,
                    'amount': round(current_price * position['num_shares'], 2),
                    'reason': f"Score degraded to {current_score:.1f} (threshold: {self.exit_threshold})"
                })
                vacancies += 1
                sell_symbols.add(symbol)
        
        # Update invested symbols after sells
        invested_symbols = invested_symbols - sell_symbols
        
        # ========== PHASE 2: SWAP Actions (only for strategy stocks) ==========
        # Get top challengers not in portfolio
        challengers = rankings[~rankings['tradingsymbol'].isin(invested_symbols)].copy()
        
        # Check each STRATEGY incumbent against top challenger
        for position in invested_list:
            symbol = position['tradingsymbol']
            if symbol not in invested_symbols:  # Already sold
                continue
            
            incumbent_score = score_lookup.get(symbol, 0)
            current_price = current_prices.get(symbol, 0)

            if len(challengers) == 0:
                break
            
            top_challenger = challengers.iloc[0]
            challenger_symbol = top_challenger['symbol']
            challenger_score = top_challenger['composite_score']
            challenger_price = current_prices.get(challenger_symbol, 0)
            challenger_atr = current_atrs.get(challenger_symbol, 0)
            
            if self._should_swap(incumbent_score, challenger_score):
                # Calculate new position size
                new_sizing = calculate_position_size(atr=challenger_atr,
                                                           stop_multiplier=self.stop_multiplier,
                                                           risk_per_trade=self.risk_per_trade,
                                                           current_price=challenger_price
                )
                
                actions.append({
                    'action_date': action_date,
                    'action_type': 'SWAP',
                    'tradingsymbol': challenger_symbol,
                    'units': new_sizing['shares'],
                    'expected_price': challenger_price,
                    'composite_score': challenger_score,
                    'amount': round(challenger_price * new_sizing['shares'], 2),
                    'swap_from_symbol': symbol,
                    'swap_from_units': position['num_shares'],
                    'swap_from_price': current_price,
                    'reason': f"Challenger {challenger_score:.1f} > Incumbent {incumbent_score:.1f} × 1.25"
                })
                
                invested_symbols.discard(symbol)
                invested_symbols.add(challenger_symbol)
                challengers = challengers[challengers['symbol'] != challenger_symbol]
        
        # ========== PHASE 3: BUY Actions (Fill Vacancies) ==========
        if vacancies > 0:
            # Get available stocks not in portfolio
            ranked_stocks = pd.DataFrame(rankings)
            available = ranked_stocks[~ranked_stocks['tradingsymbol'].isin(invested_symbols)]
            
            for _, stock in available.head(vacancies).iterrows():
                symbol = stock['tradingsymbol']
                score = stock['composite_score']
                price = current_prices.get(symbol, 0)
                atr = current_atrs.get(symbol, 0)
                
                if price <= 0:
                    continue
                
                sizing = calculate_position_size(atr=atr,
                                                       stop_multiplier=self.stop_multiplier,
                                                       risk_per_trade=self.risk_per_trade,
                                                       current_price=price)
                actions.append({
                    'action_date': action_date,
                    'action_type': 'BUY',
                    'tradingsymbol': symbol,
                    'units': sizing['shares'],
                    'expected_price': price,
                    'composite_score': score,
                    'reason': f"Filling vacancy - Score {score:.1f}",
                    "amount": round(price * sizing['shares'], 2)
                })
                invested_symbols.add(symbol)
        response = actions_repo.bulk_insert(actions)
        return response

    def execute_action(self, action_id, exec_data):

        action = actions_repo.get_action_by_action_id(action_id)
        if not action:
            raise Exception("Action not found")
        
        if action.executed:
            raise Exception("Action already executed")
        
        # Use actual prices if provided, otherwise fall back to expected
        actual_buy_price = exec_data.get('actual_buy_price') or action.expected_price
        actual_units = exec_data.get('actual_units') or action.units
        actual_sell_price = exec_data.get('actual_sell_price') or action.expected_price
        
        # Update capital based on action type
        if action.action_type == 'BUY':
            action.expected_price = actual_buy_price
            action.units = actual_units
            action.amount = actual_units * actual_buy_price
            self._invest_in_stock(action)
        elif action.action_type == 'SELL':
            action.amount = action.units * actual_sell_price
            self.config.current_capital += action.amount
            action.expected_price = actual_sell_price
            self.sell_stock(action)
        elif action.action_type == 'SWAP':
            sell_value = action.swap_from_units * actual_sell_price
            self.config.current_capital += sell_value
            action.swap_from_price = actual_sell_price
            self.sell_stock(action, swap=True)

            action.amount = actual_units * actual_buy_price
            self.config.current_capital -= action.amount

            action.expected_price = actual_buy_price
            action.units = actual_units
            action.amount = actual_units * actual_buy_price
            self._invest_in_stock(action)

        action.executed = True
        action.status = 'EXECUTED'
        action.executed_at = date.today()
        response = actions_repo.update_action_columns(action.action_id, action)
        return response
