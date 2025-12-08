from stock_screener.classes.kite_client import KiteClient
from stock_screener.classes.analyzer import StockAnalyzer
from stock_screener.classes.strategy import ScreenerStrategy
from stock_screener.classes.report_generator import ReportGenerator
from stock_screener.classes.ranker import Ranker
from stock_screener.classes.ranker import Ranker
from stock_screener.classes.db import DatabaseManager
from stock_screener.logger import setup_logger
from stock_screener.config import CONFIG

class StockScreener:
    def __init__(self):
        self.logger = setup_logger()
        self.db_manager = DatabaseManager()
        self.market_data_client = KiteClient(CONFIG, self.db_manager, self.logger)
        self.strategy = ScreenerStrategy()
        self.ranker = Ranker()

    def run(self):
        self.logger.info("Starting Stock Screener Application")
        
        # 1. Load tickers
        self.logger.info("Loading Nifty 500 tickers...")
        tickers = self.nse_data_source.get_nifty500_tickers()[:10]

        # 2. Fetch data
        
        working_instruments = self.market_data_client.load_instruments()
        print(working_instruments)
        instrument_tokens = working_instruments['instrument_token'].to_list()[:10]

        self.logger.info(f"Using {len(instrument_tokens)} working instruments from KiteClient for data fetching.")
        market_data = self.market_data_client.fetch_data(instrument_tokens)

        # 3. Analyze stocks
        self.logger.info("Analyzing stocks...")
        analyzer = StockAnalyzer(market_data, self.db_manager)
        all_results = []
        self.logger.info(f"Starting scan for {len(tickers)} stocks...")
        
        for i, ticker in enumerate(tickers):
            if i % 50 == 0:
                self.logger.info(f"Analyzed {i}/{len(tickers)} stocks...")
            analyzed_data = analyzer.analyze_stock(ticker)
            result = self.strategy.apply(analyzed_data)
            all_results.append(result)

        # 4. Generate report
        report_generator = ReportGenerator(all_results)
        report_generator.generate_summary()
        winners = report_generator.get_winners()
        self.logger.info(f"Found {len(winners)} winners.")
        report_generator.display_winners(winners)
        report_generator.display_all_results()
        report_generator.save_to_csv(winners)
        
        # Charts are now generated manually via generate_charts.py

            
        # 6. Rank stocks
        if not winners.empty:
            top_5 = self.ranker.rank_stocks(all_results)
            self.logger.info("\nTop 5 stocks with the highest momentum:")
            print(top_5[['Symbol', 'RSI', 'ROC', 'momentum_score']])
        else:
            self.logger.info("No winners to rank.")
