import os
import sys

# Add parent directory to path to allow imports from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
from database.sqlite_manager import SQLiteManager
from services.position_sizing_service import PositionSizingService
from utils.kite import KiteService
from config.app_config import CONFIG
from utils.logger import setup_logger

def main():
    logger = setup_logger(name="PositionSizer")
    db_manager = SQLiteManager()
    position_sizer = PositionSizingService(CONFIG)
    
    input_file = "data/position_input.txt"
    if not os.path.exists(input_file):
        logger.error(f"Input file {input_file} not found.")
        return

    with open(input_file, "r") as f:
        tickers = [line.strip() for line in f if line.strip()]

    if not tickers:
        logger.info("No tickers found in input file.")
        return

    logger.info(f"Calculating position sizes for {len(tickers)} tickers...")
    
    # Initialize Kite Client
    kite_client = KiteService(CONFIG, db_manager, logger)
    market_data = kite_client.fetch_data(tickers)
    
    results = []
    
    for ticker, df in market_data.items():
        try:
             plan = position_sizer.calculate_position_size(ticker, df)
             if plan:
                 results.append(plan)
             else:
                 logger.warning(f"Could not calculate position size for {ticker} (insufficient data?)")

        except Exception as e:
            logger.error(f"Error processing {ticker}: {e}")

    if results:
        df_results = pd.DataFrame(results)
        print("\n--- Position Sizing Results ---")
        # Reorder columns for readability
        cols = ['Symbol', 'Entry_Price', 'Stop_Loss', 'Shares', 'Position_Value', 'Risk_Amt', 'Stop_Dist_%']
        print(df_results[cols].to_string(index=False))
        
        # Optional: Save to CSV
        if not os.path.exists('results'):
            os.makedirs('results')
            
        df_results.to_csv('results/position_sizing_results.csv', index=False)
        logger.info("Results saved to results/position_sizing_results.csv")
    else:
        logger.info("No results generated.")

if __name__ == "__main__":
    main()
