import os
import pandas as pd
import logging
import requests
import json
from config.kite_config import KITE_CONFIG
from utils.logger import setup_logger

from utils.kite import KiteService
from services.day0_service import Day0Service


logger = logging.getLogger(__name__)
BASE_URL = "http://127.0.0.1:5000"

logger = setup_logger(name="Orchestrator")

def init_db():
    logger.info("Initializing Instruments List...")

    kite_service = KiteService(KITE_CONFIG, logger)
    day0 = Day0Service(kite_service)
    day0.run_day0_process()

# def get_merged_stock_list():
#     """
#     Reads NSE and BSE csvs, merges them, filters out mutual funds/ETFs,
#     and returns a clean DataFrame for joining.
#     """
#     base_dir = os.path.join("data", "imports")
#     if not os.path.exists(base_dir):
#         logger.error(f"Import directory not found: {base_dir}")
#         return pd.DataFrame()

#     # 1. Read NSE Data (EQUITY_L.csv)
#     try:
#         nse_df = pd.read_csv(os.path.join(base_dir, "EQUITY_L.csv"), sep=',', index_col=False)
#         logger.info(f"Loaded NSE data: {len(nse_df)} rows")
#         # Clean column names first
#         nse_df.columns = nse_df.columns.str.strip()
#         # Rename ISIN column to standard 'ISIN'
#         nse_df.rename(columns={'ISIN NUMBER': 'isin',
#         'NAME OF COMPANY': 'name',
#         'SYMBOL': 'tradingsymbol'}, inplace=True)
#         nse_df['exchange'] = 'NSE'
#     except Exception as e:
#         logger.error(f"Error reading EQUITY_L.csv: {e}")
#         return

#     # 2. Read BSE Data 1 (Equity.csv)
#     try:
#         bse_df = pd.read_csv(os.path.join(base_dir, "Equity.csv"), sep=',', index_col=False)
#         logger.info(f"Loaded BSE data: {len(bse_df)} rows")
#         bse_df.columns = bse_df.columns.str.strip()
#         bse_df.rename(columns={'ISIN No': 'isin',
#         'Security Name': 'name',
#         'Security Id': 'tradingsymbol',
#         'Security Code': 'bsecode',
#         'Issuer Name': 'issuer'}, inplace=True)
#         bse_df['exchange'] = 'BSE'
#         bse_df['tradingsymbol'] = bse_df['tradingsymbol'].str.replace('#', '')
#     except Exception as e:
#         logger.error(f"Error reading Equity.csv: {e}")
#         return

#     combined_df = pd.merge(nse_df, bse_df, on='isin', how='outer', suffixes=('_nse', '_bse'))
#     for col in ['name', 'issuer', 'description', 'tradingsymbol', 'bsecode', 'exchange']:
#         if f'{col}_nse' in combined_df.columns and f'{col}_bse' in combined_df.columns:
#             combined_df[col] = combined_df[f'{col}_nse'].fillna(combined_df[f'{col}_bse'])
#             combined_df.drop(columns=[f'{col}_nse', f'{col}_bse'], inplace=True)

#     # Ensure ISIN is not null
#     combined_df = combined_df.dropna(subset=['isin'])
#     combined_df = combined_df[~combined_df['issuer'].str.contains('Mutual Fund', case=False, na=False)]
#     combined_df = combined_df[~(
#         combined_df['issuer'].str.contains('Asset Management', case=False, na=False) & 
#         combined_df['name'].str.contains('ETF', case=False, na=False)
#     )]

#     # Drop unused columns and reorder
#     columns_to_keep = ['isin', 'tradingsymbol', 'bsecode', 'name', 'exchange']
#     combined_df = combined_df[columns_to_keep]
#     logger.info(f"Loaded and merged {len(combined_df)} valid unique stocks (ISIN deduplicated).")
#     return combined_df

# def load_instruments():
#     """
#     Fetches instruments from Kite and filters/enriches them using the local merged CSV list.
#     """
#     try:
#         logger.info("Loading instruments...")
#         kite_client = KiteService(KITE_CONFIG, logger)
#         kite = kite_client.kite
#         # 1. Get Valid Stock List (The "Master" List)
#         valid_stocks = get_merged_stock_list()
#         if valid_stocks.empty:
#             logger.error("No valid stocks found in CSV imports. Aborting instrument load.")
#             return pd.DataFrame()

#         # 2. Fetch all from Kite
#         instruments = kite.instruments()
#         kite_df = pd.DataFrame(instruments)
        
#         # 4. Merge
#         merged_df = pd.merge(
#             kite_df, 
#             valid_stocks[['tradingsymbol', 'exchange', 'isin']], # Keep ISIN from local
#             on=['tradingsymbol', 'exchange'], 
#             how='inner'
#         )
        
#         # Identify instruments from kite_df that were not merged
#         unmerged_kite_df = kite_df[~kite_df['instrument_token'].isin(merged_df['instrument_token'])]
#         unmerged_kite_df['tradingsymbol'] = unmerged_kite_df['tradingsymbol'].str.split('-').str[0]

#         if not unmerged_kite_df.empty:
#             logger.info(f"Attempting second merge for {len(unmerged_kite_df)} unmerged instruments using normalized symbols.")
#             # Second merge attempt: Using normalized_tradingsymbol and exchange for remaining instruments
#             second_merge_df = pd.merge(
#                 unmerged_kite_df,
#                 valid_stocks[['tradingsymbol', 'exchange', 'isin']],
#                 on=['tradingsymbol', 'exchange'],
#                 how='inner'
#             )
#             # Combine the results of both merges
#             merged_df = pd.concat([merged_df, second_merge_df], ignore_index=True)
#         final_df = merged_df[['isin', 'instrument_token', 'exchange_token', 'exchange', 'tradingsymbol', 'name']]
#         logger.info(f"Enriched and filtered instruments: {len(final_df)} rows.")
#         return final_df

#     except Exception as e:
#         logger.error(f"Could not fetch or process instruments: {e}")
#         return pd.DataFrame()