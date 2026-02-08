"""
Portfolio Controls Service

Portfolio-level risk controls for drawdown management and sector concentration.
"""
import pandas as pd
from config import setup_logger
from config.strategies_config import PortfolioControlConfig

logger = setup_logger(name="PortfolioControls")


class PortfolioControlsService:
    """Portfolio-level risk controls"""
    
    def __init__(self, config: PortfolioControlConfig = None):
        self.config = config or PortfolioControlConfig()
    
    def check_drawdown_status(self, current_value: float, 
                               peak_value: float) -> dict:
        """
        Check drawdown circuit breakers.
        
        Parameters:
            current_value (float): Current portfolio value
            peak_value (float): Peak portfolio value
        
        Returns:
            dict with drawdown %, status, action, and exposure_factor
        """
        if peak_value <= 0:
            return {"drawdown": 0, "status": "normal", "action": "none"}
        
        drawdown = (peak_value - current_value) / peak_value
        
        if drawdown >= self.config.drawdown_reduce_threshold:
            return {
                "drawdown": round(drawdown * 100, 2),
                "status": "critical",
                "action": f"reduce_exposure_to_{self.config.reduce_exposure_factor*100}%",
                "exposure_factor": self.config.reduce_exposure_factor
            }
        elif drawdown >= self.config.drawdown_pause_threshold:
            return {
                "drawdown": round(drawdown * 100, 2),
                "status": "paused",
                "action": "pause_new_entries",
                "exposure_factor": 1.0
            }
        else:
            return {
                "drawdown": round(drawdown * 100, 2),
                "status": "normal",
                "action": "none",
                "exposure_factor": 1.0
            }
    
    def check_sector_concentration(self, holdings: pd.DataFrame,
                                    sector_column: str = 'sector') -> dict:
        """
        Check sector concentration limits.
        
        Parameters:
            holdings: DataFrame with columns [symbol, sector, position_value]
            sector_column: Column name for sector data
            
        Returns:
            dict with limits status and sector weights
        """
        if holdings.empty or sector_column not in holdings.columns:
            return {"within_limits": True, "sectors": {}}
        
        total_value = holdings['position_value'].sum()
        sector_weights = holdings.groupby(sector_column)['position_value'].sum() / total_value
        
        breached = sector_weights[sector_weights > self.config.max_sector_weight]
        
        return {
            "within_limits": len(breached) == 0,
            "breached_sectors": breached.to_dict() if len(breached) > 0 else {},
            "sector_weights": sector_weights.to_dict(),
            "limit": self.config.max_sector_weight
        }
    
    def apply_all_controls(self, portfolio_value: float, peak_value: float,
                            holdings: pd.DataFrame = None) -> dict:
        """
        Apply all portfolio controls and return combined status.
        
        Parameters:
            portfolio_value: Current portfolio value
            peak_value: Peak portfolio value
            holdings: DataFrame of current holdings (optional)
            
        Returns:
            dict with overall status, exposure factor, and detailed breakdowns
        """
        drawdown = self.check_drawdown_status(portfolio_value, peak_value)
        
        # Check sector concentration if holdings provided
        if holdings is not None and not holdings.empty:
            sector = self.check_sector_concentration(holdings)
        else:
            sector = {"within_limits": True, "sectors": {}}
        
        # Use drawdown factor
        combined_factor = drawdown.get('exposure_factor', 1.0)
        
        # Determine overall status
        if drawdown['status'] == 'critical':
            overall_status = 'critical'
        elif drawdown['status'] == 'paused':
            overall_status = 'paused'
        elif not sector['within_limits']:
            overall_status = 'sector_breach'
        else:
            overall_status = 'normal'
        
        return {
            "overall_status": overall_status,
            "combined_exposure_factor": round(combined_factor, 2),
            "drawdown": drawdown,
            "sector": sector
        }
