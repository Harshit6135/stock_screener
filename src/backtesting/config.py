"""
Backtest Configuration

All backtest parameters loaded from ConfigRepository - no HTTP calls.
"""
from config import setup_logger
from repositories import ConfigRepository


logger = setup_logger(name="BacktestConfig")
config_repo = ConfigRepository()


class BacktestConfigLoader:
    """
    Load backtest configuration from ConfigRepository.
    
    Falls back to local config classes if DB config unavailable.
    """
    
    def __init__(self, strategy_name):
        self._config = None
        self.strategy_name = strategy_name
    
    def fetch(self):
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
            data = config_repo.get_config(self.strategy_name)
            if data and not isinstance(data, dict):
                data = dict(data)
                return data
        except Exception as e:
            logger.warning(f"Could not fetch config from repository: {e}")
