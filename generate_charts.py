
import os
from stock_screener.classes.db import DatabaseManager
from stock_screener.classes.report_generator import ChartGenerator
from stock_screener.classes.analyzer import StockAnalyzer
from stock_screener.logger import setup_logger
import pandas as pd
import yfinance as yf

def main():
    logger = setup_logger(name="ChartGen")
    db_manager = DatabaseManager()
    
    input_file = "charts_input.txt"
    if not os.path.exists(input_file):
        logger.error(f"Input file {input_file} not found.")
        return

    with open(input_file, "r") as f:
        tickers = [line.strip() for line in f if line.strip()]

    if not tickers:
        logger.info("No tickers found in input file.")
        return

    logger.info(f"Generating charts for {len(tickers)} tickers...")
    
    market_data = {}
    
    # Try to load from DB first, if missing fetch from yfinance
    for ticker in tickers:
        try:
            df = db_manager.load_market_data(ticker)
            if not df.empty:
                market_data[ticker] = df
            else:
                logger.info(f"Data for {ticker} not found in DB. Fetching from yfinance...")
                df = yf.download(ticker, period="1y", interval="1d", auto_adjust=True, progress=False, threads=False)
                if not df.empty:
                     if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                     market_data[ticker] = df
                else:
                    logger.warning(f"Could not fetch data for {ticker}")
        except Exception as e:
            logger.error(f"Error processing {ticker}: {e}")

    if market_data:
        # Calculate indicators needed for charts
        logger.info("Calculating indicators...")
        # Dictionary to store latest results, though chart gen uses the dataframe in market_data
        analyzer = StockAnalyzer(market_data, db_manager)
        for ticker in market_data:
            analyzer.analyze_stock(ticker)

        chart_generator = ChartGenerator(market_data)
        for ticker in market_data:
            logger.info(f"Generating chart for {ticker}...")
            chart_generator.generate_chart(ticker)
        logger.info("Chart generation complete.")
    else:
        logger.warning("No data available to generate charts.")

if __name__ == "__main__":
    main()
