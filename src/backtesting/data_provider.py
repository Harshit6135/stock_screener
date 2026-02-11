"""
Backtest Data Provider

Direct repository access for backtesting, replacing the HTTP-based BacktestAPIClient.
Provides the same interface for rankings, indicators, market data, and scores
but queries the database directly instead of going through HTTP endpoints.
"""
from datetime import date
from typing import List, Dict, Optional

from config import setup_logger
from repositories import (
    RankingRepository, IndicatorsRepository,
    MarketDataRepository
)
from utils.transaction_costs_utils import calculate_round_trip_cost
from utils.tax_utils import calculate_capital_gains_tax

logger = setup_logger(name="BacktestDataProvider")

# Repository instances
ranking_repo = RankingRepository()
indicators_repo = IndicatorsRepository()
marketdata_repo = MarketDataRepository()


class BacktestDataProvider:
    """
    Data provider for backtesting using direct repository access.
    
    Replaces BacktestAPIClient to avoid HTTP overhead and circular
    dependency issues when running backtests within the same process.
    """
    
    def get_top_rankings(self, n: int, as_of_date: date) -> List[Dict]:
        """
        Get top N ranked stocks for a given date.
        
        Parameters:
            n: Number of top stocks to fetch
            as_of_date: Date for rankings
            
        Returns:
            List of dicts with tradingsymbol and composite_score
        """
        try:
            results = ranking_repo.get_top_n_by_date(n, as_of_date)
            if not results:
                return []
            return [
                {
                    'tradingsymbol': r.tradingsymbol,
                    'composite_score': float(r.composite_score)
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Failed to fetch rankings for {as_of_date}: {e}")
            return []
    
    def get_indicator(self, indicator_name: str, tradingsymbol: str,
                      as_of_date: date) -> Optional[float]:
        """
        Get a specific indicator value for a stock.
        
        Parameters:
            indicator_name: Name of indicator (e.g., 'atrr_14')
            tradingsymbol: Stock symbol
            as_of_date: Date for indicator
            
        Returns:
            Indicator value or None if not found
        """
        try:
            value = indicators_repo.get_indicator_by_tradingsymbol(
                indicator_name, tradingsymbol, as_of_date
            )
            return float(value) if value is not None else None
        except Exception as e:
            logger.warning(f"Failed to fetch {indicator_name} for {tradingsymbol}: {e}")
            return None
    
    def get_close_price(self, tradingsymbol: str, as_of_date: date) -> Optional[float]:
        """Get closing price for a stock on a date"""
        try:
            result = marketdata_repo.get_marketdata_by_trading_symbol(
                tradingsymbol, as_of_date
            )
            if result and hasattr(result, 'close'):
                return float(result.close)
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch close price for {tradingsymbol}: {e}")
            return None
    
    def get_low_price(self, tradingsymbol: str, as_of_date: date) -> Optional[float]:
        """Get low price for a stock on a date"""
        try:
            result = marketdata_repo.get_marketdata_by_trading_symbol(
                tradingsymbol, as_of_date
            )
            if result and hasattr(result, 'low'):
                return float(result.low)
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch low price for {tradingsymbol}: {e}")
            return None
    
    def get_score(self, tradingsymbol: str, as_of_date: date) -> Optional[float]:
        """Get composite score for a stock on a date"""
        try:
            result = ranking_repo.get_by_symbol(tradingsymbol, as_of_date)
            if result and hasattr(result, 'composite_score'):
                return float(result.composite_score)
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch score for {tradingsymbol}: {e}")
            return None
