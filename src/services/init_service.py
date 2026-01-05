import os
import json
import time

import pandas as pd

from adaptors import YFinanceAdaptor
from config import setup_logger, MCAP_THRESHOLD, PRICE_THRESHOLD
from repositories import MasterRepository, InstrumentsRepository


yf = YFinanceAdaptor()
master_repo = MasterRepository()
instr_repo = InstrumentsRepository()
logger = setup_logger(name="Orchestrator")


class InitService:
    def __init__(self):
        self.nse_path = "data/imports/NSE.csv"
        self.bse_path = "data/imports/BSE.csv"
        self.dump_path = "data/exports/yfinance_dump.csv"

    def initialize_app(self):
        logger.info("Starting Day 0 Process...")
        
        # 1. Fetch and Merge CSVs
        df, nse_tickers, bse_tickers, merged_tickers = self.fetch_and_merge_csvs()
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
        instruments_df = self.get_instruments()
        response_code, final_count = self.sync_with_kite(df_filtered, instruments_df)
        logger.info("Day 0 Process Completed Successfully.")
        response = {
            "nse_count": nse_tickers,
            "bse_count": bse_tickers,
            "merged_count": merged_tickers,
            "final_count": final_count
        }
        return response_code, response

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

        return df_consolidated, len(df_nse), len(df_bse), len(df_consolidated)

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

    @staticmethod
    def fetch_yfinance_data(df):
        try:
            desired_columns = [
                'industry', 'sector', 'marketCap', 'regularMarketPrice',
                'allTimeHigh', 'allTimeLow', 'floatShares', 'sharesOutstanding',
                'heldPercentInsiders', 'heldPercentInstitutions'
            ]
            for col in desired_columns:
                df[col] = None

            total = len(df)
            logger.info(f"Fetching yfinance data for {total} stocks...")
            
            successful_downloads = 0
            failed_downloads = 0

            for index, row in df.iterrows():
                if index % 100 == 0:
                    time.sleep(2)

                yfinance_info, yfinance_ticker_used, yfinance_status = yf.get_stock_info(df.at[index, 'yfinance_tickers'])
                df.at[index, 'yfinance_info'] = json.dumps(yfinance_info)
                df.at[index, 'yfinance_ticker_used'] = yfinance_ticker_used
                df.at[index, 'yfinance_status'] = yfinance_status
                if yfinance_status != 'Failed':
                    successful_downloads += 1
                    for col in desired_columns:
                        df.at[index, col] = yfinance_info.get(col, None)
                else:
                    failed_downloads += 1
                logger.info(f"Status - Successful - {successful_downloads}, Failed - {failed_downloads}, Total - {total}")
        except Exception as e:
            logger.error(f"Failed to fetch yfinance data: {str(e)}")
        return df

    @staticmethod
    def push_to_master(df):
        try:
            df.fillna('', inplace=True)
            req_cols = [
                'ISIN', 'NSE_SYMBOL', 'BSE_SYMBOL', 'BSE_SECURITY_CODE', 
                'NAME_OF_COMPANY', 'industry', 'sector', 'marketCap', 'regularMarketPrice',
                'allTimeHigh', 'allTimeLow', 'sharesOutstanding', 
                'floatShares', 'heldPercentInsiders', 'heldPercentInstitutions'
            ]
            df = df[req_cols]
            df.columns = df.columns.str.lower()
            master_data = json.loads(df.to_json(orient='records', indent=4))
            master_repo.delete_all()
            master_repo.bulk_insert(master_data)
        except Exception as e:
            logger.error(f"Failed to push to master: {str(e)}")

    @staticmethod
    def filter_stocks(df):
        # Request: Remove mcap < 500cr
        # Mcap is usually in bytes in yfinance? Let's check. Yes, usually full number.
        # "500cr" = 500 * 10,000,000 = 5,000,000,000
        mcap_threshold = MCAP_THRESHOLD * 10000000

        # Ensure numeric
        df['marketCap'] = pd.to_numeric(df['marketCap'], errors='coerce')
        df['regularMarketPrice'] = pd.to_numeric(df['regularMarketPrice'], errors='coerce')
        
        # Filter Mcap
        # Logic: Keep if >= 500cr
        df_filtered = df[df['marketCap'] >= mcap_threshold]
        logger.info(f"Dropped {len(df) - len(df_filtered)} stocks due to Mcap < 500cr")

        # # Filter Price < 75
        # # Logic: Keep  >= 75
        current_len = len(df_filtered)
        df_filtered = df_filtered[df_filtered['regularMarketPrice'] >= PRICE_THRESHOLD]
        logger.info(f"Dropped {current_len - len(df_filtered)} stocks due to Price < {PRICE_THRESHOLD}")

        return df_filtered

    @staticmethod
    def get_instruments():
        url = "https://api.kite.trade/instruments"
        instruments_df = pd.read_csv(url)
        logger.info(f"Fetched {len(instruments_df)} instruments from Kite")
        return instruments_df

    @staticmethod
    def sync_with_kite(df, instruments_df):
        try:
            valid_symbols_nse = set(df.loc[df['NSE_SYMBOL'] != '', 'NSE_SYMBOL'])

            # 1. Exact Match First
            kite_nse_exact = instruments_df[
                (instruments_df['exchange'] == 'NSE') & 
                (instruments_df['tradingsymbol'].isin(valid_symbols_nse))
            ].copy()
            kite_nse_exact['match_type'] = 'exact'
            kite_nse_exact['lookup_symbol'] = kite_nse_exact['tradingsymbol']

            # 2. Find unmatched symbols
            matched_symbols = set(kite_nse_exact['tradingsymbol'])
            remaining_symbols_nse = valid_symbols_nse - matched_symbols
            
            # 3. Match remaining using hyphen-split logic
            instruments_df = instruments_df.copy()
            instruments_df['base_symbol'] = instruments_df['tradingsymbol'].str.split('-').str[0]
            
            kite_nse_hyphen = instruments_df[
                (instruments_df['exchange'] == 'NSE') & 
                (instruments_df['base_symbol'].isin(remaining_symbols_nse))
            ].copy()
            # Keep only one match per base_symbol (prefer non-hyphenated if multiple exist, though exact would have caught it)
            kite_nse_hyphen = kite_nse_hyphen.sort_values('tradingsymbol').drop_duplicates('base_symbol', keep='first')
            kite_nse_hyphen['match_type'] = 'hyphen'
            kite_nse_hyphen['lookup_symbol'] = kite_nse_hyphen['base_symbol']

            # 4. Combine NSE results
            kite_nse = pd.concat([kite_nse_exact, kite_nse_hyphen])

            valid_symbols_bse = set(df.loc[(df['BSE_SYMBOL'] != '') & (df['NSE_SYMBOL'] == ''), 'BSE_SYMBOL'])
            kite_bse = instruments_df[
                (instruments_df['exchange'] == 'BSE') & 
                (instruments_df['tradingsymbol'].isin(valid_symbols_bse))
            ].copy()
            kite_bse['match_type'] = 'exact'
            kite_bse['lookup_symbol'] = kite_bse['tradingsymbol']

            final_instruments = pd.concat([kite_nse, kite_bse])

            req_columns = ['instrument_token', 'exchange_token', 'tradingsymbol', 'name', 'exchange', 'lookup_symbol', 'base_symbol']
            # Ensure columns exist (base_symbol might be NaN for exact matches if not calculated)
            for col in req_columns:
                if col not in final_instruments.columns:
                    final_instruments[col] = None
                    
            final_instruments['exchange_token'] = final_instruments['exchange_token'].astype(str)

            # Merge with df to get mcap, industry, and sector
            # Map NSE using lookup_symbol (which is original NSE_SYMBOL)
            df_nse = df[df['NSE_SYMBOL'] != ''][['NSE_SYMBOL', 'marketCap', 'industry', 'sector']].rename(columns={'NSE_SYMBOL': 'lookup_key'})
            
            # Map BSE using lookup_symbol (which is BSE_SYMBOL)
            df_bse = df[df['BSE_SYMBOL'] != ''][['BSE_SYMBOL', 'marketCap', 'industry', 'sector']].rename(columns={'BSE_SYMBOL': 'lookup_key'})
            
            df_map = pd.concat([df_nse, df_bse]).drop_duplicates('lookup_key')

            final_instruments = final_instruments.merge(
                df_map, left_on='lookup_symbol', right_on='lookup_key', how='left'
            )
            
            output_columns = ['instrument_token', 'exchange_token', 'tradingsymbol', 'name', 'exchange', 'marketCap', 'industry', 'sector']
            final_instruments = final_instruments[output_columns]
            final_instruments.rename(columns={'marketCap': 'marketcap'}, inplace=True)

            instruments_json = json.loads(final_instruments.to_json(orient='records', indent=4))
            logger.info(f"Syncing {len(final_instruments)} instruments to Kite")
            final_instruments.to_json("data/exports/instruments.json", orient='records', indent=4)
            response = instr_repo.delete_all()
            if response == -1:
                return 500, 0
            response = instr_repo.bulk_insert(instruments_json)
            if response is None:
                return 500, 0
            return 200, len(final_instruments)
        except Exception as e:
            logger.error(f"Error syncing with Kite: {e}")
            return 500, 0
