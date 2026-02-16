
from unittest.mock import MagicMock, patch
import sys
import os
from datetime import date

# Mock dependencies
sys.modules['pandas_ta'] = MagicMock()
sys.modules['kiteconnect'] = MagicMock()
sys.modules['flask'] = MagicMock()
sys.modules['flask_sqlalchemy'] = MagicMock()
sys.modules['flask_smorest'] = MagicMock()
sys.modules['scipy'] = MagicMock()
sys.modules['scipy.stats'] = MagicMock()

# Add src to path
sys.path.append(os.path.abspath('src'))

# Mock repositories
from services import actions_service
actions_service.ActionsRepository = MagicMock()
actions_service.InvestmentRepository = MagicMock()
actions_service.ConfigRepository = MagicMock()
actions_service.RankingRepository = MagicMock()
actions_service.IndicatorsRepository = MagicMock()
actions_service.MarketDataRepository = MagicMock()

# Mock repositories modules
sys.modules['repositories'] = MagicMock()
sys.modules['repositories.actions_repo'] = MagicMock()
sys.modules['utils.database_manager'] = MagicMock()

# Mock utils.calculate_position_size
actions_service.calculate_position_size = MagicMock(return_value={
    'shares': 100, 
    'position_value': 10000, 
    'stop_distance': 6.0 # 6% of 100
})

from services.actions_service import ActionsService

def test_buy_action_atr_fallback():
    print("Testing buy_action with missing ATR (Fallback)...")
    try:
        # Setup
        service = ActionsService('test_config')
        service.config = MagicMock()
        service.config.sl_multiplier = 2.0
        service.config.sl_fallback_percent = 0.06 # 6% fallback
        
        # Mock indicator return -> None (trigger fallback)
        actions_service.indicators.get_indicator_by_tradingsymbol.return_value = None
        
        # Execution
        # Price = 100. Fallback risk = 6% = 6.0.
        # ATR = Risk / Multiplier = 6.0 / 2.0 = 3.0.
        action = service.buy_action(
            symbol="TEST", 
            action_date=date(2023, 1, 1), 
            prev_close=100.0, 
            reason="Fallback Test"
        )
        
        # Verification
        print("Action:", action)
        print("Calculated ATR:", action['atr'])
        
        expected_atr = 3.0
        assert action['atr'] == expected_atr, f"Expected ATR {expected_atr}, got {action['atr']}"
        
        print("Test Passed: Fallback ATR calculation correct.")
        
    except Exception as e:
        print(f"Test Failed with unexpected error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_buy_action_atr_fallback()
