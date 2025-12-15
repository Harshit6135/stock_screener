import os
import time

import pandas as pd


class MarketDataService:
    def __init__(self, kite_client, logger):
        self.kite = kite_client.kite
        self.kite_client = kite_client
        self.logger = logger

    def fetch_history(self, ticker):
        """
        Fetches full available history for a ticker (e.g. 1 year default or configured max).
        """
        self.logger.info(f"Full refresh triggered for {ticker}")
        end_date = pd.Timestamp.now().normalize()
        start_date = end_date - pd.Timedelta(days=900) # Default to 1 year for full history
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
                start_date = today - pd.Timedelta(days=900)
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
                         existing_df = self.db_manager.load_market_data(token)
                         if existing_df is not None and not existing_df.empty:
                             last_close = existing_df.iloc[-1]['Close']
                             next_open = df_new.iloc[0]['Open']
                             
                             if next_open > (last_close * 1.20) or next_open < (last_close * 0.80):
                                 self.logger.warning(f"Gap detected for {token} (>20%). Triggering full refresh.")
                                 full_refresh_needed = True

                    if full_refresh_needed:
                        df_new = self.fetch_history(token)
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
