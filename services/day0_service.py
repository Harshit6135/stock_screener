import os
import json
import time
import requests

import pandas as pd
import yfinance as yf

from db import db

from models import MasterModel
from utils.logger import setup_logger


logger = setup_logger(name="Orchestrator")
BASE_URL = "http://127.0.0.1:5000"

class Day0Service:
    def __init__(self):
        self.nse_path = "data/imports/EQUITY_L.csv"
        self.bse_path = "data/imports/Equity.csv"
        self.dump_path = "data/exports/yfinance_dump.csv"

    def run_day0_process(self):
        logger.info("Starting Day 0 Process...")
        
        # 1. Fetch and Merge CSVs
        df = self.fetch_and_merge_csvs()
        logger.info(f"Merged DataFrame shape: {df.shape}")

        # 2. Fetch yfinance data
        df['yfinance_tickers'] = df.apply(self.generate_yfinance_tickers, axis=1)
        df = self.fetch_yfinance_data(df)
        
        # 3. Save raw output to CSV
        df.to_csv(self.dump_path, index=False)
        logger.info(f"Saved yfinance data to {self.dump_path}")

        # 4. Push to Master Table
        self.push_to_master(df)

        # 5. Filter stocks (Mcap < 500cr, Price < 75)
        df_filtered = self.filter_stocks(df)
        logger.info(f"Filtered DataFrame shape: {df_filtered.shape}")

        # 6. Sync with Kite Instruments
        self.sync_with_kite(df_filtered)
        
        logger.info("Day 0 Process Completed Successfully.")

    def fetch_and_merge_csvs(self):
        # Load NSE
        if not os.path.exists(self.nse_path):
             raise FileNotFoundError(f"NSE file not found at {self.nse_path}")
        
        df_nse = pd.read_csv(self.nse_path)
        df_nse = df_nse.rename(columns=lambda x: 'NSE_' + x.strip().replace(" ", "_"))
        
        # Load BSE
        if not os.path.exists(self.bse_path):
             raise FileNotFoundError(f"BSE file not found at {self.bse_path}")

        df_bse = pd.read_csv(self.bse_path)
        df_bse.reset_index(inplace=True)
        rename_map = {
            "level_0":	"bse_Security Code",
            "level_1": "bse_Issuer Name",
            "level_2":	"bse_Symbol",
            "level_3":	"bse_Security Name",
            "level_4":	"bse_Status",
            "Security Code": "bse_Group",
            "Issuer Name":	"bse_Face Value",
            "Security Id":	"bse_ISIN No",
            "Security Name":	"bse_Instrument"
        }
        df_bse = df_bse.rename(columns=rename_map)
        df_bse = df_bse[[
            "bse_Face Value",
            "bse_Issuer Name",
            "bse_ISIN No",
            "bse_Instrument",
            "bse_Security Code",
            "bse_Symbol",
            "bse_Security Name",
            "bse_Status"
        ]]
        df_bse = df_bse.rename(columns=lambda x: x.strip().replace(" ", "_").upper())
        df_bse = df_bse[df_bse['BSE_STATUS'] == 'Active']

        # Merge
        df_nse['ISIN'] = df_nse['NSE_ISIN_NUMBER']
        df_bse['ISIN'] = df_bse['BSE_ISIN_NO']
        df_consolidated = pd.merge(df_nse, df_bse, on='ISIN', how='outer')
        
        # Filter Logic (Mutual Funds, ISIN prefix)
        # 1. ISIN starts with IN
        df_consolidated = df_consolidated[df_consolidated['ISIN'].astype(str).str.startswith('IN', na=False)]
        
        # 2. Remove Mutual Funds
        # Check BSE_ISSUER_NAME (originally 'Issuer Name')
        if 'BSE_ISSUER_NAME' in df_consolidated.columns:
             df_consolidated = df_consolidated[~df_consolidated['BSE_ISSUER_NAME'].astype(str).str.contains('Mutual Fund', case=False, na=False)]

        # 3. Remove Asset Management & ETF
        if 'BSE_ISSUER_NAME' in df_consolidated.columns and 'BSE_SECURITY_NAME' in df_consolidated.columns:
            df_consolidated = df_consolidated[~
                (df_consolidated['BSE_ISSUER_NAME'].astype(str).str.contains('asset management', case=False, na=False) &
                 df_consolidated['BSE_SECURITY_NAME'].astype(str).str.contains('etf', case=False, na=False))
            ]

        # Cleanup columns
        # NSE_SYMBOL, BSE_SECURITY_CODE (as string), BSE_SECURITY_ID (as alphanumeric)
        # Prioritize NSE Symbol
        df_consolidated['NSE_SYMBOL'] = df_consolidated['NSE_SYMBOL'].fillna('')
        df_consolidated['BSE_SYMBOL'] = df_consolidated['BSE_SYMBOL'].fillna('')
        df_consolidated['BSE_SECURITY_CODE'] = df_consolidated['BSE_SECURITY_CODE'].fillna(0).astype(int).astype(str)
        df_consolidated['NAME_OF_COMPANY'] = df_consolidated['NSE_NAME_OF_COMPANY'].fillna(df_consolidated['BSE_ISSUER_NAME'])
        unwanted_cols = [
            'NSE_ISIN_NUMBER',
            'BSE_ISIN_NO',
            'NSE_NAME_OF_COMPANY',
            'NSE_SERIES',
            'NSE_DATE_OF_LISTING',
            'NSE_PAID_UP_VALUE',
            'NSE_MARKET_LOT',
            'NSE_FACE_VALUE',
            'BSE_FACE_VALUE',
            'BSE_ISSUER_NAME',
            'BSE_INSTRUMENT',
            'BSE_STATUS'
        ]
        df_consolidated = df_consolidated.drop(columns=unwanted_cols, errors='ignore')
        df_consolidated = df_consolidated[['ISIN', 'NSE_SYMBOL', 'BSE_SYMBOL', 'BSE_SECURITY_CODE', 'NAME_OF_COMPANY']]

        return df_consolidated

    @staticmethod
    def generate_yfinance_tickers(row):
        tickers = []
        # Priority 1: NSE symbol
        if pd.notna(row['NSE_SYMBOL']) and row['NSE_SYMBOL'] != '':
            tickers.append(f"{row['NSE_SYMBOL']}.NS")
        # Priority 2: BSE alphanumeric symbol
        if pd.notna(row['BSE_SYMBOL']) and row['BSE_SYMBOL'] != '':
            tickers.append(f"{row['BSE_SYMBOL']}.BO")
        # Priority 3: BSE numeric security code
        if pd.notna(row['BSE_SECURITY_CODE']) and row['BSE_SECURITY_CODE'] != '0': # '0' after conversion from NaN
            tickers.append(f"{row['BSE_SECURITY_CODE']}.BO")
        return tickers

    def fetch_yfinance_data(self, df):
        
        desired_columns = [
            'industry', 'sector', 'marketCap', 'previousClose',
            'allTimeHigh', 'allTimeLow', 'floatShares', 'sharesOutstanding',
            'heldPercentInsiders', 'heldPercentInstitutions'
        ]
        
        for col in desired_columns:
            df[col] = None
        

        df['yfinance_info'] = None # for dump
        df['yfinance_ticker_used'] = None
        df['yfinance_status'] = 'Failed'
        
        total = len(df)
        logger.info(f"Fetching yfinance data for {total} stocks...")
        
        successful_downloads = 0
        failed_downloads = 0
        
        for index, row in df.iterrows():
            if index % 50 == 0:
                time.sleep(5)# Basic rate limiting

            success = False
            for ticker in row['yfinance_tickers']:
                logger.info(f"\rAttempting to download data for ({index}/{total}) with ticker: {ticker}")
                try:
                    info = yf.Ticker(ticker).info
                    if info and 'regularMarketPrice' in info: # Basic validation
                        df.at[index, 'yfinance_info'] = json.dumps(info)
                        df.at[index, 'yfinance_ticker_used'] = ticker
                        df.at[index, 'yfinance_status'] = 'Success'
                        for col in desired_columns:
                            df.at[index, col] = info.get(col)
                        success = True
                        successful_downloads += 1
                        break
                except Exception as e:
                    # logger.warning(f"Failed to fetch {ticker}: {e}")
                    pass
            
            if not success:
                # Keep blank values as requested
                failed_downloads += 1
            logger.info(f"\nStatus - Successful - {successful_downloads}, Failed - {failed_downloads}\n")
        return df

    def filter_stocks(self, df):
        # Request: Remove mcap < 500cr
        # Mcap is usually in bytes in yfinance? Let's check. Yes, usually full number.
        # "500cr" = 500 * 10,000,000 = 5,000,000,000
        mcap_threshold = 500 * 10000000

        # Ensure numeric
        df['marketCap'] = pd.to_numeric(df['marketCap'], errors='coerce')
        df['previousClose'] = pd.to_numeric(df['previousClose'], errors='coerce')
        
        # Filter Mcap
        # Logic: Keep if NaN OR >= 500cr
        df_filtered = df[
            (df['marketCap'].isna()) | 
            (df['marketCap'] >= mcap_threshold)
        ]
        logger.info(f"Dropped {len(df) - len(df_filtered)} stocks due to Mcap < 500cr")
        
        # Filter Price < 75
        # Logic: Keep if NaN OR >= 75
        current_len = len(df_filtered)
        df_filtered = df_filtered[
             (df_filtered['previousClose'].isna()) |
             (df_filtered['previousClose'] >= 75)
        ]
        logger.info(f"Dropped {current_len - len(df_filtered)} stocks due to Price < 75")
        
        return df_filtered

    def push_to_master(self, df):
        # Map DataFrame columns to MasterModel
        # MasterModel fields: isin, nse_symbol, bse_symbol, bse_security_code, name_of_company, ...
        
        objs = []
        for _, row in df.iterrows():
            # Convert NaN to None for DB
            row = row.where(pd.notnull(row), None)
            
            obj = MasterModel(
                isin=row['ISIN'],
                nse_symbol=row['NSE_SYMBOL'],
                bse_symbol=row['BSE_SYMBOL'],
                bse_security_code=row['BSE_SECURITY_CODE'] if row['BSE_SECURITY_CODE'] != '0' else None,
                name_of_company=row['NAME_OF_COMPANY'],
                industry=row['industry'],
                sector=row['sector'],
                market_cap=row['marketCap'],
                all_time_high=row['allTimeHigh'],
                all_time_low=row['allTimeLow'],
                shares_outstanding=row['sharesOutstanding'],
                float_shares=row['floatShares'],
                held_percent_insiders=row['heldPercentInsiders'],
                held_percent_institutions=row['heldPercentInstitutions'],
                status='Active'
            )
            objs.append(obj)
            
        try:
            db.session.query(MasterModel).delete() # Full refresh for Day 0
            db.session.bulk_save_objects(objs)
            db.session.commit()
            logger.info(f"Pushed {len(objs)} records to MasterModel")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to push to MasterModel: {e}")
            raise

    def sync_with_kite(self, df):
        logger.info("Fetching Kite instruments...")
        try:
            # Common public URL for instruments if we don't have active session
            url = "https://api.kite.trade/instruments"
            instruments_df = pd.read_csv(url)
            logger.info(f"Fetched {len(instruments_df)} instruments from Kite")
            
            instruments_df['tradingsymbol1'] = instruments_df['tradingsymbol'].str.rsplit('-', n=1).str[0]

            valid_symbols_nse = set(df[df['NSE_SYMBOL'] != '']['NSE_SYMBOL'])

            kite_nse = instruments_df[
                (instruments_df['exchange'] == 'NSE') & 
                ((instruments_df['tradingsymbol'].isin(valid_symbols_nse) | instruments_df['tradingsymbol1'].isin(valid_symbols_nse)))
            ]

            valid_symbols_bse = set(df[(df['BSE_SYMBOL'] != '') & (df['NSE_SYMBOL'] == '')]['BSE_SYMBOL'])

            kite_bse = instruments_df[
                (instruments_df['exchange'] == 'BSE') & 
                ((instruments_df['tradingsymbol'].isin(valid_symbols_bse)  | instruments_df['tradingsymbol1'].isin(valid_symbols_bse)))
            ]

            final_instruments = pd.concat([kite_nse, kite_bse])

            req_columns = ['instrument_token', 'exchange_token', 'tradingsymbol', 'name', 'exchange']
            final_instruments = final_instruments[req_columns]
            final_instruments['exchange_token'] = final_instruments['exchange_token'].astype(str)

            instruments_json = json.loads(final_instruments.to_json(orient='records', indent=4))
            logger.info(f"Syncing {len(final_instruments)} instruments to Kite")
            final_instruments.to_json("data/exports/instruments.json", orient='records', indent=4)
            resp = requests.delete(f"{BASE_URL}/instruments")
            resp = requests.post(f"{BASE_URL}/instruments", json=instruments_json)
            if resp.status_code != 201:
                logger.error(f"Failed to initialize instruments: {resp.text}")
            return resp        
        except Exception as e:
            logger.error(f"Error syncing with Kite: {e}")
            raise
