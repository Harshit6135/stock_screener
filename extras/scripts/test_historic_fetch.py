
import sys
import os
import pandas as pd

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.app_config import CONFIG
from database.sqlite_manager import SQLiteManager
from utils.kite import KiteService
from services.market_data_service import MarketDataService
from utils.logger import setup_logger

def test_historic_fetch():
    logger = setup_logger()
    logger.info("TEST: Starting Historic Data Fetch Verification...")
    
    # 1. Use a test DB
    test_db_name = "test_historic_data.db"
    if os.path.exists(os.path.join("data", test_db_name)):
        os.remove(os.path.join("data", test_db_name))
        
    db_manager = SQLiteManager(db_name=test_db_name)
    
    # 2. Init Services
    kite_service = KiteService(CONFIG, db_manager, logger)
    market_data_service = MarketDataService(kite_service, db_manager, logger)
    
    # 3. Test on RELIANCE (Common liquid stock) or just ID 738561 (Reliance)
    # Ideally we need a valid instrument token. 
    # Let's search for Reliance in the instruments list first if we can, or hardcode if known.
    # Reliance EQ token is usually 738561.
    ticker = 738561 
    symbol = "RELIANCE"
    
    logger.info(f"Fetching 10 years for {symbol} ({ticker})...")
    
    # 4. Fetch
    try:
        df = market_data_service.fetch_long_term_history(ticker)
        
        if df is None or df.empty:
            logger.error("TEST FAILED: No data returned.")
            return

        logger.info(f"TEST SUCCESS: Fetched {len(df)} rows.")
        logger.info(f"Date Range: {df.index.min()} to {df.index.max()}")
        
        # 5. Save and Verify DB
        db_manager.save_market_data(ticker, df)
        
        saved_df = db_manager.load_market_data(ticker)
        logger.info(f"DB Verification: Loaded {len(saved_df)} rows from DB.")
        
        if len(saved_df) == len(df):
            logger.info("TEST PASSED: DB row count matches fetched row count.")
        else:
            logger.error(f"TEST FAILED: DB row count mismatch. Fetched: {len(df)}, Saved: {len(saved_df)}")

    except Exception as e:
        logger.error(f"TEST FAILED with exception: {e}")

if __name__ == "__main__":
    test_historic_fetch()
