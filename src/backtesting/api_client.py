"""
Backtest API Client

HTTP client for interacting with the Flask API during backtesting.
"""
import os
import requests
from datetime import date
from typing import List, Dict, Optional

from config import setup_logger

logger = setup_logger(name="BacktestAPIClient")


class BacktestAPIClient:
    """
    API client for backtesting.
    
    Fetches rankings, indicators, and market data via HTTP to simulate
    real-world API usage.
    """
    
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("API_BASE_URL", "http://127.0.0.1:5000")
        self.session = requests.Session()
    
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
            response = self.session.get(
                f"{self.base_url}/api/v1/ranking/top/{n}",
                params={"date": as_of_date.isoformat()},
                timeout=30
            )
            response.raise_for_status()
            return response.json()
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
            response = self.session.get(
                f"{self.base_url}/api/v1/indicators/{indicator_name}",
                params={
                    "tradingsymbol": tradingsymbol,
                    "date": as_of_date.isoformat()
                },
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return data.get(indicator_name)
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch {indicator_name} for {tradingsymbol}: {e}")
            return None
    
    def get_market_data(self, tradingsymbol: str, as_of_date: date) -> Optional[Dict]:
        """
        Get OHLCV market data for a stock.
        
        Parameters:
            tradingsymbol: Stock symbol
            as_of_date: Date for data
            
        Returns:
            Dict with open, high, low, close, volume or None
        """
        try:
            response = self.session.get(
                f"{self.base_url}/api/v1/marketdata/{tradingsymbol}",
                params={"date": as_of_date.isoformat()},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch market data for {tradingsymbol}: {e}")
            return None
    
    def get_close_price(self, tradingsymbol: str, as_of_date: date) -> Optional[float]:
        """Get closing price for a stock on a date"""
        data = self.get_market_data(tradingsymbol, as_of_date)
        return data.get('close') if data else None
    
    def get_low_price(self, tradingsymbol: str, as_of_date: date) -> Optional[float]:
        """Get low price for a stock on a date"""
        data = self.get_market_data(tradingsymbol, as_of_date)
        return data.get('low') if data else None
    
    def get_score(self, tradingsymbol: str, as_of_date: date) -> Optional[float]:
        """Get composite score for a stock on a date"""
        try:
            response = self.session.get(
                f"{self.base_url}/api/v1/score/{tradingsymbol}",
                params={"date": as_of_date.isoformat()},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('composite_score')
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch score for {tradingsymbol}: {e}")
            return None
    
    def calculate_transaction_costs(self, trade_value: float, 
                                     order_pct_adv: float = 0.05) -> Optional[Dict]:
        """
        Get transaction costs for a trade.
        
        Parameters:
            trade_value: Order value in INR
            order_pct_adv: Order as percentage of ADV
            
        Returns:
            Dict with buy_costs, sell_costs, impact_cost, total, percent
        """
        try:
            response = self.session.get(
                f"{self.base_url}/api/v1/costs/roundtrip",
                params={
                    "trade_value": trade_value,
                    "order_pct_adv": order_pct_adv
                },
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            # Fallback to local calculation if endpoint doesn't exist
            return None
        except Exception:
            return None
    
    def estimate_tax(self, purchase_price: float, current_price: float,
                     purchase_date: date, current_date: date,
                     quantity: int) -> Optional[Dict]:
        """
        Estimate tax for a trade.
        
        Returns:
            Dict with gain, tax_type, tax, net_gain
        """
        try:
            response = self.session.get(
                f"{self.base_url}/api/v1/tax/estimate",
                params={
                    "purchase_price": purchase_price,
                    "current_price": current_price,
                    "purchase_date": purchase_date.isoformat(),
                    "current_date": current_date.isoformat(),
                    "quantity": quantity
                },
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            return None
