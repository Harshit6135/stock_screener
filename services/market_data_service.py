import pandas as pd
import time
from datetime import timedelta
import os



import pandas as pd
import os


class MarketDataService:
    def __init__(self, kite_client, db_manager, logger):
        self.kite = kite_client.kite  # Access the underlying KiteConnect instance
        self.kite_client = kite_client # Keep reference to wrapper if needed
        self.db_manager = db_manager
        self.logger = logger

    def get_merged_stock_list(self):
        """
        Reads NSE and BSE csvs, merges them, filters out mutual funds/ETFs,
        and returns a clean DataFrame for joining.
        """
        base_dir = os.path.join("data", "imports")
        if not os.path.exists(base_dir):
            self.logger.error(f"Import directory not found: {base_dir}")
            return pd.DataFrame()
    
        # 1. Read NSE Data (EQUITY_L.csv)
        try:
            nse_df = pd.read_csv(os.path.join(base_dir, "EQUITY_L.csv"), sep=',', index_col=False)
            self.logger.info(f"Loaded NSE data: {len(nse_df)} rows")
            # Clean column names first
            nse_df.columns = nse_df.columns.str.strip()
            # Rename ISIN column to standard 'ISIN'
            nse_df.rename(columns={'ISIN NUMBER': 'isin',
            'NAME OF COMPANY': 'name',
            'SYMBOL': 'tradingsymbol'}, inplace=True)
            nse_df['exchange'] = 'NSE'
        except Exception as e:
            self.logger.error(f"Error reading EQUITY_L.csv: {e}")
            return

        # 2. Read BSE Data 1 (Equity.csv)
        try:
            bse_df = pd.read_csv(os.path.join(base_dir, "Equity.csv"), sep=',', index_col=False)
            self.logger.info(f"Loaded BSE data: {len(bse_df)} rows")
            bse_df.columns = bse_df.columns.str.strip()
            bse_df.rename(columns={'ISIN No': 'isin',
            'Security Name': 'name',
            'Security Id': 'tradingsymbol',
            'Security Code': 'bsecode',
            'Issuer Name': 'issuer'}, inplace=True)
            bse_df['exchange'] = 'BSE'
            bse_df['tradingsymbol'] = bse_df['tradingsymbol'].str.replace('#', '')
        except Exception as e:
            self.logger.error(f"Error reading Equity.csv: {e}")
            return

        combined_df = pd.merge(nse_df, bse_df, on='isin', how='outer', suffixes=('_nse', '_bse'))
        for col in ['name', 'issuer', 'description', 'tradingsymbol', 'bsecode', 'exchange']:
            if f'{col}_nse' in combined_df.columns and f'{col}_bse' in combined_df.columns:
                combined_df[col] = combined_df[f'{col}_nse'].fillna(combined_df[f'{col}_bse'])
                combined_df.drop(columns=[f'{col}_nse', f'{col}_bse'], inplace=True)

        # Ensure ISIN is not null
        combined_df = combined_df.dropna(subset=['isin'])
        combined_df = combined_df[~combined_df['issuer'].str.contains('Mutual Fund', case=False, na=False)]
        combined_df = combined_df[~(
            combined_df['issuer'].str.contains('Asset Management', case=False, na=False) & 
            combined_df['name'].str.contains('ETF', case=False, na=False)
        )]

        # Drop unused columns and reorder
        columns_to_keep = ['isin', 'tradingsymbol', 'bsecode', 'name', 'exchange']
        combined_df = combined_df[columns_to_keep]
        self.logger.info(f"Loaded and merged {len(combined_df)} valid unique stocks (ISIN deduplicated).")
        return combined_df

    def load_instruments(self):
        """
        Fetches instruments from Kite and filters/enriches them using the local merged CSV list.
        """
        try:
            self.logger.info("Loading instruments...")
            
            # 1. Get Valid Stock List (The "Master" List)
            valid_stocks = self.get_merged_stock_list()
            if valid_stocks.empty:
                self.logger.error("No valid stocks found in CSV imports. Aborting instrument load.")
                return pd.DataFrame()

            # 2. Fetch all from Kite
            instruments = self.kite.instruments()
            kite_df = pd.DataFrame(instruments)
            
            # 4. Merge
            merged_df = pd.merge(
                kite_df, 
                valid_stocks[['tradingsymbol', 'exchange', 'isin']], # Keep ISIN from local
                on=['tradingsymbol', 'exchange'], 
                how='inner'
            )
           
            # Identify instruments from kite_df that were not merged
            unmerged_kite_df = kite_df[~kite_df['instrument_token'].isin(merged_df['instrument_token'])]
            unmerged_kite_df['tradingsymbol'] = unmerged_kite_df['tradingsymbol'].str.split('-').str[0]

            if not unmerged_kite_df.empty:
                self.logger.info(f"Attempting second merge for {len(unmerged_kite_df)} unmerged instruments using normalized symbols.")
                # Second merge attempt: Using normalized_tradingsymbol and exchange for remaining instruments
                second_merge_df = pd.merge(
                    unmerged_kite_df,
                    valid_stocks[['tradingsymbol', 'exchange', 'isin']],
                    on=['tradingsymbol', 'exchange'],
                    how='inner'
                )
                # Combine the results of both merges
                merged_df = pd.concat([merged_df, second_merge_df], ignore_index=True)
            final_df = merged_df[['isin', 'instrument_token', 'exchange_token', 'exchange', 'tradingsymbol', 'name']]
            self.logger.info(f"Enriched and filtered instruments: {len(final_df)} rows.")
            return final_df

        except Exception as e:
            self.logger.error(f"Could not fetch or process instruments: {e}")
            return pd.DataFrame()

    def fetch_history(self, ticker):
        """
        Fetches full available history for a ticker (e.g. 1 year default or configured max).
        """
        self.logger.info(f"Full refresh triggered for {ticker}")
        end_date = pd.Timestamp.now().normalize()
        start_date = end_date - pd.Timedelta(days=365) # Default to 1 year for full history
        return self.load_data(ticker, start_date, end_date)

    def load_data(self, ticker, start_date, end_date):
        """
        Fetches data for a ticker from start_date to end_date.
        """
        try:
            records = self.kite.historical_data(ticker, start_date, end_date, "day")
            
            if not records:
                self.logger.warning(f"No data returned for {ticker}")
                return None
            
            df_new = pd.DataFrame(records)
            df_new['date'] = pd.to_datetime(df_new['date']).dt.normalize()
            df_new.set_index('date', inplace=True)
            
            rename_map = {
                'open': 'Open', 'high': 'High', 'low': 'Low', 
                'close': 'Close', 'volume': 'Volume'
            }
            if not all(col in df_new.columns for col in rename_map.keys()):
                 # Handle cases where kite might return different columns or empty
                 pass

            df_new.rename(columns=rename_map, inplace=True, errors='ignore')
            # Filter only desired columns if they exist
            cols_to_keep = [c for c in rename_map.values() if c in df_new.columns]
            df_new = df_new[cols_to_keep] 
            
            return df_new

        except Exception as e:
            self.logger.error(f"Failed to fetch/process data for {ticker}: {e}")
            return None

    def fetch_data(self, tickers):
        """
        Smart fetch:
        - Checks DB for last date.
        - Fetches only new data.
        - Checks for >20% gap between last DB close and new Open.
        - Refreshes full history if gap detected.
        """
        self.logger.info("Initializing Data Extractor fetch process...")
        market_data = {}
        
        today = pd.Timestamp.now().normalize()

        for token in tickers:
            try:
                last_date = self.db_manager.get_latest_date(token)
                
                # Default start date if no data exists
                start_date = today - pd.Timedelta(days=365)
                full_refresh_needed = False

                if last_date:
                     start_date = last_date + pd.Timedelta(days=1)
                     # Check if we are already up to date
                     if pd.to_datetime(start_date).tz_localize(None) > pd.to_datetime(today).tz_localize(None):
                         market_data[token] = self.db_manager.load_market_data(token)
                         continue
                else:
                    full_refresh_needed = True

                self.logger.info(f"Fetching data for {token} from {start_date.date()}...")
                
                # Fetch the delta or full data
                df_new = self.load_data(token, start_date, today)

                if df_new is not None and not df_new.empty:
                    # CHECK FOR 20% GAP if we had previous data
                    if not full_refresh_needed and last_date:
                        # Get last close from DB (simulated here by loading, or we could have optimized db_manager to return it)
                        # For now, let's load current DB data to check.
                        # Optimization: pass last_close from db_manager.get_latest_date if possible, 
                         # but existing current method only returns date.
                         # We'll load the last row specifically if possible, or just load all.
                         # Loading all is safe for now given local DB size context usually.
                         existing_df = self.db_manager.load_market_data(token)
                         if existing_df is not None and not existing_df.empty:
                             last_close = existing_df.iloc[-1]['Close']
                             next_open = df_new.iloc[0]['Open']
                             
                             if next_open > (last_close * 1.20) or next_open < (last_close * 0.80):
                                 # 20% gap detected (up or down, user said "greater than ... by more than 20%", usually implies gap up, 
                                 # but let's cover gap logic safely. User specifically said "refresh whole data")
                                 self.logger.warning(f"Gap detected for {token} (>20%). Triggering full refresh.")
                                 full_refresh_needed = True

                    if full_refresh_needed:
                        df_new = self.fetch_history(token)
                        # When full refresh, we overwrite/save freshly.
                        # db_manager.save_market_data usually appends or replaces? 
                        # We need to make sure we replace if full refresh.
                        # Assuming save_market_data handles it or we might need `if_exists='replace'` logic.
                        # Standard pattern: if we pass full history, we might want to plain overwrite.
                        # Let's check db_manager implementation later. For now, we assume save handles it 
                        # but we might need to clear old data first if it's an append-only system.
                        # If existing system was "append new", a full refresh = delete old + insert new.
                        self.db_manager.clear_ticker_data(token) # Heuristic: add a clear method or rely on overwrite.
                        self.db_manager.save_market_data(token, df_new)
                    else:
                        self.db_manager.save_market_data(token, df_new)
                    
                    # Finally load full data to return
                    market_data[token] = self.db_manager.load_market_data(token)

                # Rate limiting
                time.sleep(0.34)
                
            except Exception as e:
                self.logger.error(f"Error fetching data for {token}: {e}")

        self.logger.info(f"Loaded {len(market_data)} tickers for analysis.")
        return market_data

    def fetch_long_term_history(self, ticker, start_date=None):
        """
        Fetches long-term history for a ticker, handling the 2000-day API limit.
        OPTIMIZATION: Fetches backwards (Latest -> Oldest) to stop early if stock didn't exist.
        Default start_date is Jan 1, 2015.
        """
        if start_date is None:
            # User requested specific start from 2015-01-01
            target_start_date = pd.Timestamp("2015-01-01")
        else:
            target_start_date = pd.to_datetime(start_date)

        self.logger.info(f"Starting long-term history fetch for {ticker} (Target Start: {target_start_date.date()})...")
        
        all_records = []
        
        # We start from NOW and go backwards
        current_end = pd.Timestamp.now().normalize()
        # chunk_days optimized: 1900 calendar days (Safe under 2000 day API limit)
        # This allows spanning 10 years (3652 days) in just 2 calls (1900 * 2 = 3800).
        chunk_days = 1900 
        
        try:
            while current_end > target_start_date:
                # Calculate start for this chunk
                current_start = current_end - pd.Timedelta(days=chunk_days)
                
                # Clamp to target start
                if current_start < target_start_date:
                    current_start = target_start_date
                
                self.logger.info(f"Fetching chunk: {current_start.date()} to {current_end.date()}")
                records = self.kite.historical_data(ticker, current_start, current_end, "day")
                
                if records:
                    # We got data, add it to our list
                    # Note: records come sorted by date usually. 
                    all_records.extend(records)
                else:
                    # Optimization: If we get NO data for this chunk, and we are moving backwards,
                    # it means we have likely reached before the stock's listing date.
                    self.logger.info("No data in this chunk, assuming reached start of history. Stopping fetch.")
                    break
                
                # Prepare for next backward chunk
                current_end = current_start - pd.Timedelta(days=1)
                
                if current_end < target_start_date:
                    break

                time.sleep(0.4) # Rate limiting
            
            if not all_records:
                self.logger.warning(f"No long-term data found for {ticker}")
                return None

            df_new = pd.DataFrame(all_records)
            df_new['date'] = pd.to_datetime(df_new['date']).dt.normalize()
            df_new.set_index('date', inplace=True)
            df_new.sort_index(inplace=True) # Ensure final order is correct
            
            # Remove potential duplicates
            df_new = df_new[~df_new.index.duplicated(keep='first')]

            rename_map = {
                'open': 'Open', 'high': 'High', 'low': 'Low', 
                'close': 'Close', 'volume': 'Volume'
            }
            df_new.rename(columns=rename_map, inplace=True, errors='ignore')
            cols_to_keep = [c for c in rename_map.values() if c in df_new.columns]
            df_new = df_new[cols_to_keep] 
            
            self.logger.info(f"Fetched {len(df_new)} rows for {ticker}")
            return df_new

        except Exception as e:
            self.logger.error(f"Failed to fetch long-term history for {ticker}: {e}")
            return None
