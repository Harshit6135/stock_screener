from time import time, sleep
from datetime import timedelta

import pandas as pd

from adaptors import KiteAdaptor
from config import setup_logger, KITE_CONFIG, HISTORY_LOOKBACK
from repositories import MarketDataRepository, InstrumentsRepository


logger = setup_logger(name='Orchestrator')
instr_repository = InstrumentsRepository()
marketdata_repository = MarketDataRepository()


class MarketDataService:
    def __init__(self):
        self.kite_client = KiteAdaptor(KITE_CONFIG, logger)
        self.logger = logger

    def get_latest_data_by_token(self, token, start_date, end_date=None):
        """
        Fetches data for a ticker from start_date to end_date.
        """
        try:
            start_time = time()
            records = self.kite_client.fetch_ticker_data(token, start_date, end_date)
            
            if not records:
                self.logger.warning(f"No data returned for {token}")
                return None
            return records, start_time

        except Exception as e:
            self.logger.error(f"Failed to fetch/process data for {token}: {e}")
            return None

    def update_latest_data_for_all(self, historical=False, historical_start_date="2010-01-01"):
        """
        Fetches data for a ticker from start_date to end_date.
        """
        logger.info("Fetching Instruments from DB...")
        instruments = instr_repository.get_all_instruments()

        logger.info("Fetching Historical Data for instruments via Kite API...")
        yesterday = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)
        for i, instr in enumerate(instruments):
            tradingsymbol = instr.tradingsymbol
            instr_token = instr.instrument_token
            exchange = instr.exchange
            log_symb = f"{tradingsymbol} ({instr_token})"
            logger.info(f"Processing {i+1}/{len(instruments)} {log_symb})...")
            
            if not historical:
                last_date = None
                last_data_date = marketdata_repository.get_latest_date_by_symbol(tradingsymbol)
                if last_data_date:
                    last_date = last_data_date.date
                    start_date = pd.to_datetime(last_date)
                else:
                    start_date = yesterday - timedelta(days=HISTORY_LOOKBACK) # Default 1 year

                if start_date > yesterday:
                    logger.info(f"No data to fetch for {log_symb} as last data date is {last_date}")
                    continue
                else:
                    logger.info(f"Fetching from Kite for {log_symb}) starting {start_date.date()}...")
                records, start_time = self.get_latest_data_by_token(instr_token, start_date, yesterday)
            else:
                logger.info(f"Fetching Historical data from Kite for {log_symb}) starting {historical_start_date}...")
                records, start_time = self.get_historical_data(instr_token, historical_start_date)

            if records is None:
                logger.warning(f"No data returned for {log_symb}")
                continue

            if not historical and last_data_date and len(records) > 1:
                last_close = records[0]['close']
                next_open = records[1]['open']
                records = records[1:]
                if next_open > (last_close * 1.20) or next_open < (last_close * 0.80):
                    logger.warning(f"Gap detected for {log_symb} (>20%). Triggering full refresh.")
                    marketdata_repository.delete_by_tradingsymbol(tradingsymbol)
                    sleep(max(0, 0.34 - (time() + start_time)))
                    start_date = today - timedelta(days=HISTORY_LOOKBACK)
                    records, start_time = self.get_latest_data_by_token(instr_token, start_date)

            records_df = pd.DataFrame(records)
            records_df.reset_index(inplace=True)
            records_df['instrument_token'] = instr_token
            records_df['tradingsymbol'] = tradingsymbol
            records_df['exchange'] = exchange if exchange else "NSE"
            marketdata_repository.bulk_insert(records_df.to_dict('records'))
            sleep(max(0,0.34-time()+start_time))

    def get_historical_data(self, ticker, start_date=None):
        """
        Fetches long-term history for a ticker, handling the 2000-day API limit.
        OPTIMIZATION: Fetches backwards (Latest -> Oldest) to stop early if stock didn't exist.
        Default start_date is Jan 1, 2010.
        """
        target_start_date = pd.to_datetime(start_date)
        self.logger.info(f"Starting long-term history fetch for {ticker} (Target Start: {target_start_date.date()})...")
        
        all_records = []
        
        # We start from NOW and go backwards
        current_end = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)
        chunk_days = 1900 
        
        try:
            while current_end > target_start_date:
                # Calculate start for this chunk
                current_start = current_end - pd.Timedelta(days=chunk_days)
                
                # Clamp to target start
                if current_start < target_start_date:
                    current_start = target_start_date
                
                self.logger.info(f"Fetching chunk: {current_start.date()} to {current_end.date()}")
                records = self.kite_client.fetch_ticker_data(ticker, current_start, current_end)
                start_time = time()
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

                sleep(max(0, 0.34 - (time() - start_time))) # Rate limiting

            if not all_records:
                self.logger.warning(f"No long-term data found for {ticker}")
                return None, None
            return all_records, start_time

        except Exception as e:
            self.logger.error(f"Failed to fetch long-term history for {ticker}: {e}")
            return None
