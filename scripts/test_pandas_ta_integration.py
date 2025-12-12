
import sys
import os
import pandas as pd
import pandas_ta as ta
import numpy as np

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.analysis_service import AnalysisService
from config.app_config import CONFIG

# Mock DB Manager
class MockDBManager:
    def save_indicators(self, ticker, result):
        print(f"Saving indicators for {ticker}")

# Create dummy market data
def create_dummy_data():
    dates = pd.date_range(start="2024-01-01", periods=200)
    data = {
        'Open': np.random.uniform(100, 200, size=200),
        'High': np.random.uniform(100, 200, size=200),
        'Low': np.random.uniform(100, 200, size=200),
        'Close': np.random.uniform(100, 200, size=200),
        'Volume': np.random.randint(1000, 10000, size=200)
    }
    df = pd.DataFrame(data, index=dates)
    # Ensure High is highest and Low is lowest
    df['High'] = df[['Open', 'Close', 'High']].max(axis=1) + 1
    df['Low'] = df[['Open', 'Close', 'Low']].min(axis=1) - 1
    return df

def test_analysis_service():
    print("Testing AnalysisService with pandas_ta...")
    
    ticker = "TEST_STOCK"
    df = create_dummy_data()
    market_data = {ticker: df}
    db_manager = MockDBManager()
    
    service = AnalysisService(market_data, db_manager)
    
    try:
        result = service.analyze_stock(ticker)
        print("\nAnalysis Result:")
        for k, v in result.items():
            print(f"{k}: {v}")
            
        if result['Data_Found']:
            print("\nSUCCESS: Analysis returned data.")
        else:
            print(f"\nFAILURE: {result.get('Issue', 'Unknown issue')}")

    except Exception as e:
        print(f"\nEXCEPTION: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_analysis_service()
