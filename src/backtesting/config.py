"""
Backtest Configuration

All backtest parameters fetched from API - no hardcoding.
"""
import os
import requests
from typing import Optional
from dataclasses import dataclass

from config import setup_logger
from config.strategies_config import (
    PositionSizingConfig,
    ChallengerConfig,
    BacktestConfig as BaseBacktestConfig
)

logger = setup_logger(name="BacktestConfig")

@dataclass
class FetchedConfig:
    """Configuration fetched from API at runtime"""
    initial_capital: float
    risk_per_trade_percent: float
    stop_multiplier: float
    exit_threshold: float
    max_positions: int
    buffer_percent: float
    sl_fallback_percent: float
    sl_step_percent: float


class BacktestConfigLoader:
    """
    Load backtest configuration from API.
    
    Falls back to local config if API unavailable.
    """
    
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("API_BASE_URL", "http://127.0.0.1:5000")
        self._config: Optional[FetchedConfig] = None
    
    def fetch(self, strategy_name: str = "momentum_strategy_one") -> FetchedConfig:
        """
        Fetch configuration from API.
        
        Parameters:
            strategy_name: Strategy identifier
            
        Returns:
            FetchedConfig with all parameters
        """
        if self._config is not None:
            return self._config
        
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/config/{strategy_name}",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                self._config = FetchedConfig(
                    initial_capital=data.get('initial_capital', 100000.0),
                    risk_per_trade_percent=data.get('risk_threshold', 1.0),
                    stop_multiplier=data.get('sl_multiplier', 2.0),
                    exit_threshold=data.get('exit_threshold', 40.0),
                    max_positions=data.get('max_positions', 10),
                    buffer_percent=data.get('buffer_percent', 0.25),
                    sl_fallback_percent=PositionSizingConfig().sl_fallback_percent,
                    sl_step_percent=PositionSizingConfig().sl_step_percent
                )
                return self._config
        except Exception as e:
            logger.warning(f"Could not fetch config from API: {e}")
        
        # Fallback to local config classes
        sizing = PositionSizingConfig()
        challenger = ChallengerConfig()
        backtest = BaseBacktestConfig()
        
        self._config = FetchedConfig(
            initial_capital=backtest.initial_capital,
            risk_per_trade_percent=sizing.risk_per_trade_percent * 100,
            stop_multiplier=sizing.stop_multiplier,
            exit_threshold=challenger.absolute_exit_threshold,
            max_positions=backtest.max_positions,
            buffer_percent=challenger.base_buffer_percent,
            sl_fallback_percent=sizing.sl_fallback_percent,
            sl_step_percent=sizing.sl_step_percent
        )
        return self._config
    
    @property
    def config(self) -> FetchedConfig:
        """Get cached or fetched config"""
        if self._config is None:
            return self.fetch()
        return self._config
