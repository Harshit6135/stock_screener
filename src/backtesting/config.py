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
    
    def __init__(self, config_name):
        self._config = None
        self.config_name = config_name
    
    def fetch(self):
        """
        Fetch configuration from ConfigRepository.
        
        Returns:
            dict with all config parameters
        """
        if self._config is not None:
            return self._config
        
        try:
            data = config_repo.get_config(self.config_name)
            if data is None:
                logger.warning(f"No config found for '{self.config_name}'")
                return None
            if isinstance(data, dict):
                self._config = data
            else:
                # Convert SQLAlchemy model to dict via column introspection
                self._config = {
                    c.name: getattr(data, c.name)
                    for c in data.__table__.columns
                }
            return self._config
        except Exception as e:
            logger.warning(f"Could not fetch config from repository: {e}")
            return None

