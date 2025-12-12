import argparse
from services.screener_service import ScreenerService
from config.app_config import CONFIG
from database.sqlite_manager import SQLiteManager
from utils.kite import KiteService
from services.market_data_service import MarketDataService
from utils.logger import setup_logger

def run_historic_data_collection():
    logger = setup_logger()
    logger.info("Starting Historic Data Collection (10 Years)...")
    
    # 1. Init DB for Historic Data
    # specific db_name used to keep it separate as requested
    historic_db = SQLiteManager(db_name="historic_data.db")
    
    # 2. Init Services
    kite_service = KiteService(CONFIG, historic_db, logger)
    market_data_service = MarketDataService(kite_service, historic_db, logger)
    
    # 3. Get Instruments
    # We fetch fresh instruments to ensure we have "all stocks"
    logger.info("Fetching valid instruments list...")
    instruments = market_data_service.load_instruments()
    
    if instruments.empty:
        logger.error("No instruments found. Aborting.")
        return

    logger.info(f"Found {len(instruments)} instruments to fetch history for.")
    
    # 4. Iterate and Fetch
    count = 0
    total = len(instruments)
    
    for _, row in instruments.iterrows():
        count += 1
        ticker = row['instrument_token']
        symbol = row['tradingsymbol']
        
        logger.info(f"[{count}/{total}] Processing {symbol} ({ticker})...")
        
        # Check if we already have data to skip (optional, but good for resuming)
        # However, user asked for "fetch in 1 go", implying a fresh run usually.
        # But if it crashes, resuming is nice.
        if historic_db.get_latest_date(ticker):
             logger.info(f"Data already exists for {symbol}, skipping...")
             continue

        # Fetch from 2015-01-01 (default in method now)
        df = market_data_service.fetch_long_term_history(ticker)
        
        if df is not None and not df.empty:
            historic_db.save_market_data(ticker, df)
            logger.info(f"Saved history for {symbol}")
        
    logger.info("Historic Data Collection Completed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock Screener V3")
    parser.add_argument("--day0", action="store_true", help="Initialize instruments database from Kite")
    parser.add_argument("--historic", action="store_true", help="Fetch 10 years of historic data for all stocks to a separate DB")
    args = parser.parse_args()

    if args.historic:
        run_historic_data_collection()
    else:
        screener = ScreenerService()
        screener.logger.info(f"Starting Stock Screener (Day0 mode: {args.day0})")
        screener.run(day0=args.day0)
