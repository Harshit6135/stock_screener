
import os
from stock_screener.classes.db import DatabaseManager
from stock_screener.classes.report_generator import ChartGenerator
from stock_screener.classes.analyzer import StockAnalyzer
from stock_screener.classes.kite_client import KiteClient
from stock_screener.config import CONFIG
from stock_screener.logger import setup_logger
import pandas as pd

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
    
    # Initialize Kite Client
    kite_client = KiteClient(CONFIG, db_manager, logger)
    market_data = kite_client.fetch_data(tickers)

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
