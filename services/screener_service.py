from services.kite_service import KiteService
from services.market_data_service import MarketDataService
from services.analysis_service import AnalysisService
from services.strategy_service import StrategyService
from services.reporting_service import ReportingService
from services.ranking_service import RankingService
from database.sqlite_manager import SQLiteManager
from utils.logger import setup_logger
from config.app_config import CONFIG

class ScreenerService:
    def __init__(self):
        self.logger = setup_logger()
        self.db_manager = SQLiteManager()
        self.market_data_client = KiteService(CONFIG, self.db_manager, self.logger)
        self.data_extractor = MarketDataService(self.market_data_client, self.db_manager, self.logger)
        self.strategy = StrategyService()
        self.ranker = RankingService()

    def run(self):
        self.logger.info("Starting Stock Screener Application")
        
        # 1. Load tickers
        self.logger.info("Loading Nifty 500 tickers...")
        tickers = self.nse_data_source.get_nifty500_tickers()[:10]

        # 2. Fetch data
        
        working_instruments = self.data_extractor.load_instruments()
        print(working_instruments)
        instrument_tokens = working_instruments['instrument_token'].to_list()[:10]

        self.logger.info(f"Using {len(instrument_tokens)} working instruments from KiteClient for data fetching.")
        market_data = self.data_extractor.fetch_data(instrument_tokens)

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
