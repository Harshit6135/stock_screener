import yfinance as yf
import pandas as pd

class YahooFinanceClient:
    def __init__(self, db_manager, logger):
        self.db_manager = db_manager
        self.logger = logger
        
    def fetch_data(self, tickers):
        self.logger.info("Initializing data fetch process...")
        market_data = {}
        
        # 1. Check DB coverage
        tickers_by_start_date = {}
        today = pd.Timestamp.now().normalize()
        
        for t in tickers:
            last_date = self.db_manager.get_latest_date(t)
            if last_date:
                start_date = last_date + pd.Timedelta(days=1)
                
                # Check for weekend (Saturday=5, Sunday=6)
                while start_date.dayofweek >= 5 and start_date <= today:
                    self.logger.info(f"Skipping weekend date: {start_date.date()} for {t}")
                    start_date += pd.Timedelta(days=1)
                
                if start_date > today:
                    # Up to date
                    start_date_str = "UP_TO_DATE"
                else:
                    start_date_str = start_date.strftime('%Y-%m-%d')
            else:
                start_date_str = "1y" # Default for new stocks
                
            if start_date_str not in tickers_by_start_date:
                tickers_by_start_date[start_date_str] = []
            tickers_by_start_date[start_date_str].append(t)
            
        # 2. Fetch Data by Group
        for start_str, ticker_group in tickers_by_start_date.items():
            if start_str == "UP_TO_DATE":
                self.logger.info(f"skipping {len(ticker_group)} tickers (Data up-to-date).")
                continue
                
            self.logger.info(f"Fetching data for {len(ticker_group)} tickers starting from {start_str}...")
            
            try:
                if start_str == "1y":
                   data = yf.download(ticker_group, period="1y", interval="1d", group_by='ticker', auto_adjust=True, threads=True)
                else:
                   # yfinance download end is exclusive, so we might need today+1 or just omit end (defaults to now)
                   data = yf.download(ticker_group, start=start_str, interval="1d", group_by='ticker', auto_adjust=True, threads=True)
                
                # Handle single ticker case where yfinance doesn't return MultiIndex if list len is 1
                if len(ticker_group) == 1:
                     # Make it look like multi-index for consistent processing or wrap it
                     # Only if data is not empty
                     if not data.empty:
                         # Reconstruct dict
                         data = {ticker_group[0]: data}
                # If multiple tickers, data is a DataFrame with MultiIndex (Ticker, PriceType)
                
                # 3. Process and Save
                for t in ticker_group:
                    if len(ticker_group) > 1:
                        try:
                            df_new = data[t].copy()
                        except KeyError:
                            self.logger.warning(f"No data returned for {t}")
                            continue
                    else:
                        # Logic already handled above to make it a dict if single t
                        if isinstance(data, dict):
                            df_new = data[t].copy()
                        else:
                             # Should not happen with yf struct, but safety
                             df_new = data.copy()

                    # Clean data
                    if isinstance(df_new.columns, pd.MultiIndex):
                        df_new.columns = df_new.columns.get_level_values(0)
                    df_new.dropna(how='all', inplace=True)
                    
                    if df_new.empty:
                        continue
                        
                    # Split/Bonus Check
                    # If this was an incremental update (not "1y"), compare with DB
                    if start_str != "1y":
                        last_close = self.db_manager.get_last_close(t)
                        if last_close:
                            first_new_close = df_new.iloc[0]['Close']
                            # If drop is >= 25%
                            if first_new_close < (last_close * 0.75):
                                self.logger.warning(f"Detected potential split/bonus for {t}. Drop: {last_close} -> {first_new_close}. Resetting data.")
                                self.db_manager.clear_ticker_data(t)
                                # Refetch full history for this specific ticker
                                self._refetch_full_history(t)
                                continue # Skip saving this incremental chunk, as refetch handles it
                    
                    # Save new data
                    self.db_manager.save_market_data(t, df_new)
                    
            except Exception as e:
                self.logger.error(f"Error fetching batch {start_str}: {e}")

        # 4. Load all data from DB for Analysis
        self.logger.info("Loading collected data from database...")
        for t in tickers:
            df = self.db_manager.load_market_data(t)
            if not df.empty:
                market_data[t] = df
            else:
                self.logger.warning(f"No data available in DB for {t}")
                
        self.logger.info(f"Loaded {len(market_data)} tickers for analysis.")
        return market_data

    def _refetch_full_history(self, ticker):
        self.logger.info(f"Refetching 1y history for {ticker}...")
        try:
            df = yf.download(ticker, period="1y", interval="1d", auto_adjust=True, progress=False)
            if not df.empty:
                 if isinstance(df.columns, pd.MultiIndex): # Rare for single download but good validation
                    df.columns = df.columns.get_level_values(0)
                 self.db_manager.save_market_data(ticker, df)
        except Exception as e:
            self.logger.error(f"Failed to refetch history for {ticker}: {e}")
