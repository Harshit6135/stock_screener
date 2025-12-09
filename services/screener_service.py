from config.app_config import CONFIG
from utils.logger import setup_logger

from services.kite_service import KiteService
from database.sqlite_manager import SQLiteManager
from services.strategy_service import StrategyService
from services.ranking_service import RankingService
from services.market_data_service import MarketDataService
from services.analysis_service import AnalysisService
import pandas as pd

class ScreenerService:
    def __init__(self):
        self.logger = setup_logger()
        self.db_manager = SQLiteManager()
        self.market_data_client = KiteService(CONFIG, self.db_manager, self.logger)
        self.data_extractor = MarketDataService(self.market_data_client, self.db_manager, self.logger)
        self.strategy = StrategyService()
        self.ranker = RankingService()

    def initialize_instruments(self):
        """
        Fetches all instruments from Kite and saves them to the database.
        This is run when 'day0' flag is True.
        """
        self.logger.info("Day 0: Initializing instruments database...")
        instruments_df = self.data_extractor.load_instruments()
        self.db_manager.save_instruments(instruments_df)
        self.logger.info(f"Saved {len(instruments_df)} instruments to database.")

    def run(self, day0=False):
        self.logger.info("Starting Stock Screener Application")
        
        if day0:
            self.initialize_instruments()
        
        # 1. Load tickers from DB
        self.logger.info("Loading active instruments from database...")
        active_instruments = self.db_manager.get_active_instruments()
        
        if active_instruments.empty:
            self.logger.error("No instruments found in database. Please run with --day0 first.")
            return

        instrument_tokens = active_instruments['instrument_token'].tolist()
        self.logger.info(f"Using {len(instrument_tokens)} working instruments from Database.")

        # 2. Fetch data
        market_data = self.data_extractor.fetch_data(instrument_tokens)

        # 3. Analyze stocks
        self.logger.info("Analyzing stocks...")
        analyzer = AnalysisService(market_data, self.db_manager)
        all_results = []
        self.logger.info(f"Starting scan for {len(instrument_tokens)} stocks...")
        
        for i, row in active_instruments.iterrows():
            token = row['instrument_token']
            symbol = row['tradingsymbol']
            
            if i % 50 == 0:
                self.logger.info(f"Analyzed {i}/{len(active_instruments)} stocks...")
            
            analyzed_data = analyzer.analyze_stock(token)
            
            # Helper to handle cases where data might not be found
            if not analyzed_data.get('Data_Found', False):
                 # Keep symbol in result even if failed, for debugging
                 analyzed_data['Symbol'] = symbol
                 all_results.append(analyzed_data)
                 continue

            # Overwrite Symbol to human readable name
            analyzed_data['Symbol'] = symbol
            
            result = self.strategy.apply(analyzed_data)
            all_results.append(result)

        # 4. Generate report (Simplified)
        df_results = pd.DataFrame(all_results)
        df_results.to_csv("filters.csv")
        winners = pd.DataFrame()
        if not df_results.empty and 'Selected' in df_results.columns:
            winners = df_results[df_results['Selected'] == True]
        
        self.logger.info(f"Found {len(winners)} winners.")
        
        if not winners.empty:
            # Display columns if they exist
            cols = ['Symbol', 'Price', 'RSI', 'ROC', 'Strategy_Match'] 
            display_cols = [c for c in cols if c in winners.columns]
            print(winners[display_cols])
            
            # 6. Rank stocks
            # Ranker expects dataframe or list?
            # rank_stocks(self, results_list) -> returns DataFrame
            # Passing all_results list.
            try:
                top_5 = self.ranker.rank_stocks(all_results)
                self.logger.info("\nTop 5 stocks with the highest momentum:")
                print(top_5[['Symbol', 'RSI', 'ROC', 'momentum_score']])
            except Exception as e:
                self.logger.error(f"Ranking failed: {e}")
                
        else:
            self.logger.info("No winners to rank.")
