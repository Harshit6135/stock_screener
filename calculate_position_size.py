import os
import pandas as pd
import yfinance as yf
from stock_screener.classes.db import DatabaseManager
from stock_screener.classes.position_sizer import PositionSizer
from stock_screener.config import CONFIG
from stock_screener.logger import setup_logger

def main():
    logger = setup_logger(name="PositionSizer")
    db_manager = DatabaseManager()
    position_sizer = PositionSizer(CONFIG)
    
    input_file = "position_input.txt"
    if not os.path.exists(input_file):
        logger.error(f"Input file {input_file} not found.")
        return

    with open(input_file, "r") as f:
        tickers = [line.strip() for line in f if line.strip()]

    if not tickers:
        logger.info("No tickers found in input file.")
        return

    logger.info(f"Calculating position sizes for {len(tickers)} tickers...")
    
    results = []
    
    for ticker in tickers:
        try:
            # Try to load from DB first
            df = db_manager.load_market_data(ticker)
            
            # If missing or stale (logic for stale could be improved), fetch from yfinance
            if df.empty:
                logger.info(f"Data for {ticker} not found in DB. Fetching from yfinance...")
                df = yf.download(ticker, period="1y", interval="1d", auto_adjust=True, progress=False, threads=False)
                if isinstance(df.columns, pd.MultiIndex):
                     df.columns = df.columns.get_level_values(0)
            
            if not df.empty:
                 plan = position_sizer.calculate_position_size(ticker, df)
                 if plan:
                     results.append(plan)
                 else:
                     logger.warning(f"Could not calculate position size for {ticker} (insufficient data?)")
            else:
                 logger.warning(f"Could not fetch data for {ticker}")

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
