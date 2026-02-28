from time import time, sleep
from datetime import timedelta

import pandas as pd
pd.set_option('future.no_silent_downcasting', True)

from adaptors import KiteAdaptor
from config import setup_logger, KITE_CONFIG, HISTORY_LOOKBACK
from repositories import MarketDataRepository, InstrumentsRepository, IndicatorsRepository


logger = setup_logger(name='Orchestrator')
instr_repository = InstrumentsRepository()
marketdata_repository = MarketDataRepository()
indicators_repository = IndicatorsRepository()


class MarketDataService:
    def __init__(self):
        self.kite_client = KiteAdaptor(KITE_CONFIG, logger)
        self.logger = logger

    def _get_fetch_end_date(self):
        now_ist = pd.Timestamp.now(tz='Asia/Kolkata')
        # if now_ist.hour >= 18:
        #     return pd.Timestamp(now_ist.date())
        # else:
        #     return pd.Timestamp(now_ist.date()) - pd.Timedelta(days=1)
        return pd.Timestamp(now_ist.date()) - pd.Timedelta(days=1)

    def get_latest_data_by_token(self, token, start_date, end_date=None):
        """
        Fetches data for a ticker from start_date to end_date.
        """
        try:
            start_time = time()
            records = self.kite_client.fetch_ticker_data(token, start_date, end_date)
            
            if not records:
                self.logger.warning(f"No data returned for {token}")
                return None, None
            return records, start_time

        except Exception as e:
            self.logger.error(f"Failed to fetch/process data for {token}: {e}")
            return None, None

    def update_latest_data_for_all(self, historical=False, historical_start_date="2015-01-01"):
        """
        Fetches data for a ticker from start_date to end_date.
        """
        logger.info("Fetching Instruments from DB...")
        instruments = instr_repository.get_all_instruments()

        logger.info("Fetching Historical Data for instruments via Kite API...")
        fetch_end_date = self._get_fetch_end_date()
        for i, instr in enumerate(instruments):
            tradingsymbol = instr.tradingsymbol
            instr_token = instr.instrument_token
            exchange = instr.exchange
            log_symb = f"{tradingsymbol} ({instr_token})"
            logger.info(f"Processing {i+1}/{len(instruments)} {log_symb})...")
            
            last_date = None
            last_data_date = marketdata_repository.get_latest_date_by_symbol(tradingsymbol)
            if last_data_date:
                last_date = last_data_date.date
                start_date = pd.to_datetime(last_date)
            else:
                if historical:
                    start_date = historical_start_date
                    start_date = pd.Timestamp(start_date)
                else:
                    start_date = fetch_end_date - timedelta(days=HISTORY_LOOKBACK)

            if start_date > fetch_end_date:
                logger.info(f"No data to fetch for {log_symb} as last data date is {last_date}")
                continue
            else:
                logger.info(f"Fetching from Kite for {log_symb}) starting {start_date.date()}...")

            if not historical:
                records, start_time = self.get_latest_data_by_token(instr_token, start_date, fetch_end_date)
            else:
                logger.info(f"Fetching Historical data from Kite for {log_symb}) starting {start_date.date()}...")
                records, start_time = self.get_historical_data(instr_token, start_date)

            if records is None:
                logger.warning(f"No data returned for {log_symb}")
                continue

            if not historical and last_data_date and len(records) >= 1:
                # Corporate action detection: Compare stored close with fetched close for same date
                stored_close = last_data_date.close
                fetched_close = records[0]['close']

                if stored_close != fetched_close:
                    # Corporate action detected (split/bonus) — close values differ for same date.
                    logger.warning(
                        f"Corporate action detected for {log_symb}. "
                        f"Stored close: {stored_close}, Fetched close: {fetched_close}. "
                        f"Triggering full refresh."
                    )

                    # Find the earliest date we have for this stock in the DB
                    # so the refill starts from the same point, not an arbitrary date.
                    earliest_row = marketdata_repository.get_earliest_date_by_symbol(tradingsymbol)
                    if earliest_row:
                        refill_start = pd.Timestamp(earliest_row.date)
                    else:
                        refill_start = pd.Timestamp(historical_start_date)

                    # Decide fetch strategy based on total calendar days to cover.
                    total_calendar_days = (fetch_end_date - refill_start).days
                    logger.info(
                        f"Refill start: {refill_start.date()}, "
                        f"span: {total_calendar_days} calendar days."
                    )

                    # Cascading delete: marketdata → indicators
                    marketdata_repository.delete_by_tradingsymbol(tradingsymbol)
                    indicators_repository.delete_by_tradingsymbol(tradingsymbol)


                    if total_calendar_days > 2000:
                        # Use chunked historical fetch to stay within Kite's 2000-day API limit.
                        logger.info(f"Span > 2000 days — using chunked historical fetch for {log_symb}.")
                        records, start_time = self.get_historical_data(instr_token, refill_start)
                    else:
                        # Single-call fetch is fine within the limit.
                        logger.info(f"Span <= 2000 days — using single fetch for {log_symb}.")
                        records, start_time = self.get_latest_data_by_token(
                            instr_token, refill_start, fetch_end_date
                        )
                else:
                    records = records[1:]

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
        current_end = self._get_fetch_end_date()
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
                    all_records.extend(records)
                else:
                    self.logger.info("No data in this chunk, assuming reached start of history. Stopping fetch.")
                    break
                
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
            return None, None
