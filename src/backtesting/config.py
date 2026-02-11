"""
Backtest Configuration

All backtest parameters loaded from ConfigRepository - no HTTP calls.
"""
from typing import Optional
from dataclasses import dataclass

from config import setup_logger
from config.strategies_config import (
    PositionSizingConfig,
    ChallengerConfig,
    BacktestConfig as BaseBacktestConfig
)
from repositories import ConfigRepository

logger = setup_logger(name="BacktestConfig")

config_repo = ConfigRepository()

@dataclass
class FetchedConfig:
    """Configuration loaded from database at runtime"""
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
    Load backtest configuration from ConfigRepository.
    
    Falls back to local config classes if DB config unavailable.
    """
    
    def __init__(self):
        self._config: Optional[FetchedConfig] = None
    
    def fetch(self, strategy_name: str = "momentum_strategy_one") -> FetchedConfig:
        """
        Fetch configuration from ConfigRepository.
        
        Parameters:
            strategy_name: Strategy identifier
            
        Returns:
            FetchedConfig with all parameters
        """
        if self._config is not None:
            return self._config
        
        try:
            data = config_repo.get_config(strategy_name)
            if data:
                self._config = FetchedConfig(
                    initial_capital=getattr(data, 'initial_capital', 100000.0),
                    risk_per_trade_percent=getattr(data, 'risk_threshold', 1.0),
                    stop_multiplier=getattr(data, 'sl_multiplier', 2.0),
                    exit_threshold=getattr(data, 'exit_threshold', 40.0),
                    max_positions=getattr(data, 'max_positions', 10),
                    buffer_percent=getattr(data, 'buffer_percent', 0.25),
                    sl_fallback_percent=PositionSizingConfig().sl_fallback_percent,
                    sl_step_percent=PositionSizingConfig().sl_step_percent
                )
                return self._config
        except Exception as e:
            logger.warning(f"Could not fetch config from repository: {e}")
        
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
