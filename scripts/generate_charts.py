
import os
import sys

# Add parent directory to path to allow imports from root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.sqlite_manager import SQLiteManager
from services.reporting_service import ReportingService # ChartGenerator is inside? No, ReportingService contains it? 
# Wait, reporting_service.py has ChartGenerator class.
# Let's check ReportingService file again. It had ChartGenerator class and ReportingService class.
# I will import ChartGenerator specifically if needed or use from services.reporting_service import ChartGenerator
from services.reporting_service import ChartGenerator
from services.indicators_service import AnalysisService
from utils.kite import KiteService
from config.app_config import CONFIG
from utils.logger import setup_logger
import pandas as pd

def main():
    logger = setup_logger(name="ChartGen")
    db_manager = SQLiteManager()
    
    input_file = "data/charts_input.txt"
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
    kite_client = KiteService(CONFIG, db_manager, logger)
    market_data = kite_client.fetch_data(tickers)

    if market_data:
        # Calculate indicators needed for charts
        logger.info("Calculating indicators...")
        # Dictionary to store latest results, though chart gen uses the dataframe in market_data
        analyzer = AnalysisService(market_data, db_manager)
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
