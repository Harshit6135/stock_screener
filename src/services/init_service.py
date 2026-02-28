import os
import json
import time

import pandas as pd
pd.set_option('future.no_silent_downcasting', True)

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
        self.instr_json = "data/exports/instruments.json"

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
                    time.sleep(4)

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
            req_cols = [
                'ISIN', 'NSE_SYMBOL', 'BSE_SYMBOL', 'BSE_SECURITY_CODE', 
                'NAME_OF_COMPANY', 'industry', 'sector', 'marketCap', 'regularMarketPrice',
                'allTimeHigh', 'allTimeLow', 'sharesOutstanding', 
                'floatShares', 'heldPercentInsiders', 'heldPercentInstitutions'
            ]
            df = df[req_cols]
            df.columns = df.columns.str.lower()
            
            # Replace NaN with None (which becomes NULL in DB)
            df = df.where(pd.notnull(df), None)
            
            master_data = json.loads(df.to_json(orient='records', indent=4))
            master_repo.delete_all()
            master_repo.bulk_insert(master_data)
        except Exception as e:
            logger.error(f"Failed to push to master: {str(e)}")

    @staticmethod
    def filter_stocks(df):
        mcap_threshold = MCAP_THRESHOLD * 10000000
        df['marketCap'] = pd.to_numeric(df['marketCap'], errors='coerce')
        df['regularMarketPrice'] = pd.to_numeric(df['regularMarketPrice'], errors='coerce')
        
        # Filter Mcap
        df_filtered = df[df['marketCap'] >= mcap_threshold]
        logger.info(f"Dropped {len(df) - len(df_filtered)} stocks due to Mcap < {MCAP_THRESHOLD}cr")

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

    def _build_nse_kite_lookup(self, instruments_df):
        """
        Protected helper: build a DataFrame indexed by base_symbol for all NSE
        instruments in instruments_df.  Each row has the best Kite match for that
        base symbol (EQ preferred over BE when both exist) plus an 'inferred_series'
        column ('EQ' or 'BE').
        """
        df = instruments_df.copy()
        df['base_symbol'] = df['tradingsymbol'].apply(
            lambda s: s[:-3] if isinstance(s, str) and s.endswith('-BE') else s
        )
        kite_nse = df[df['exchange'] == 'NSE'].copy()
        # EQ: tradingsymbol has no -BE suffix
        kite_eq = kite_nse[kite_nse['tradingsymbol'] == kite_nse['base_symbol']].copy()
        kite_eq['inferred_series'] = 'EQ'
        # BE: tradingsymbol ends with -BE
        kite_be = kite_nse[kite_nse['tradingsymbol'].str.endswith('-BE', na=False)].copy()
        kite_be['inferred_series'] = 'BE'
        # Merge; 'BE' > 'EQ' alphabetically so ascending sort puts EQ first → keep first = EQ wins
        combined = pd.concat([kite_eq, kite_be]).sort_values('inferred_series', ascending=True)
        return combined.drop_duplicates('base_symbol', keep='first').set_index('base_symbol')

    def _detect_and_cascade_changes(self, existing_map, kite_lookup):
        """
        Protected helper: compare existing_map (from instr_repo.get_token_map()) against
        kite_lookup (from _build_nse_kite_lookup()) and cascade any token/series changes
        into market_data + indicators, then update the instruments row.

        Returns: { checked, changed, errors }
        """
        changes = []
        errors = 0
        for base_symbol, existing in existing_map.items():
            if base_symbol not in kite_lookup.index:
                logger.warning(f"'{base_symbol}' not in Kite instruments — skipped")
                errors += 1
                continue
            kite_row = kite_lookup.loc[base_symbol]
            new_token = int(kite_row['instrument_token'])
            new_exchange_token = str(kite_row['exchange_token'])
            new_series = kite_row['inferred_series']
            new_tradingsymbol = kite_row['tradingsymbol']
            old_token = existing['instrument_token']
            old_series = existing['series']  # may be None before series column existed
            token_changed = new_token != old_token
            series_changed = old_series is not None and new_series != old_series
            if token_changed or series_changed:
                logger.info(
                    f"Change detected '{base_symbol}': "
                    f"{old_series}({old_token}) -> {new_series}({new_token})"
                )
                changes.append({
                    'base_symbol': base_symbol,
                    'old_token': old_token,
                    'new_token': new_token,
                    'new_exchange_token': new_exchange_token,
                    'new_series': new_series,
                    'new_tradingsymbol': new_tradingsymbol,
                })

        for change in changes:
            try:
                instr_repo.cascade_token_update([{
                    'old_token': change['old_token'],
                    'new_token': change['new_token'],
                    'new_exchange_token': change['new_exchange_token'],
                }])
                instr_repo.update_instrument_tokens(
                    old_token=change['old_token'],
                    new_token=change['new_token'],
                    new_exchange_token=change['new_exchange_token'],
                    new_series=change['new_series'],
                    new_tradingsymbol=change['new_tradingsymbol'],
                )
                logger.info(f"Cascaded '{change['base_symbol']}': {change['old_token']} -> {change['new_token']}")
            except Exception as e:
                logger.error(f"Failed to cascade '{change['base_symbol']}': {e}")
                errors += 1

        return {'checked': len(existing_map), 'changed': len(changes), 'errors': errors}

    def sync_with_kite(self, df, instruments_df):
        try:
            valid_symbols_nse = set(df.loc[df['NSE_SYMBOL'] != '', 'NSE_SYMBOL'])

            # Build base_symbol: strip '-BE' suffix only when symbol genuinely ends with it.
            instruments_df = instruments_df.copy()
            instruments_df['base_symbol'] = instruments_df['tradingsymbol'].apply(
                lambda s: s[:-3] if isinstance(s, str) and s.endswith('-BE') else s
            )

            # 1. Exact Match First (EQ series — tradingsymbol == NSE_SYMBOL)
            kite_nse_exact = instruments_df[
                (instruments_df['exchange'] == 'NSE') &
                (instruments_df['tradingsymbol'].isin(valid_symbols_nse))
            ].copy()
            kite_nse_exact['match_type'] = 'exact'
            kite_nse_exact['lookup_symbol'] = kite_nse_exact['tradingsymbol']
            kite_nse_exact['series'] = 'EQ'

            # 2. Find unmatched symbols
            matched_base = set(kite_nse_exact['base_symbol'])
            remaining_symbols_nse = valid_symbols_nse - matched_base

            # 3. BE series match — Kite uses 'SYMBOL-BE' for BE-series stocks
            be_tradingsymbols = {s + '-BE' for s in remaining_symbols_nse}
            kite_nse_be = instruments_df[
                (instruments_df['exchange'] == 'NSE') &
                (instruments_df['tradingsymbol'].isin(be_tradingsymbols))
            ].copy()
            kite_nse_be = kite_nse_be.drop_duplicates('base_symbol', keep='first')
            kite_nse_be['match_type'] = 'be'
            kite_nse_be['lookup_symbol'] = kite_nse_be['base_symbol']
            kite_nse_be['series'] = 'BE'

            # 4. Any still-unmatched symbols: try generic hyphen-split fallback
            matched_base_2 = matched_base | set(kite_nse_be['base_symbol'])
            remaining_symbols_nse_2 = valid_symbols_nse - matched_base_2
            kite_nse_hyphen = instruments_df[
                (instruments_df['exchange'] == 'NSE') &
                (instruments_df['base_symbol'].isin(remaining_symbols_nse_2))
            ].copy()
            kite_nse_hyphen = kite_nse_hyphen.sort_values('tradingsymbol').drop_duplicates('base_symbol', keep='first')
            kite_nse_hyphen['match_type'] = 'hyphen'
            kite_nse_hyphen['lookup_symbol'] = kite_nse_hyphen['base_symbol']
            kite_nse_hyphen['series'] = kite_nse_hyphen['tradingsymbol'].apply(
                lambda s: 'BE' if str(s).endswith('-BE') else 'EQ'
            )

            # 5. Combine NSE results
            kite_nse = pd.concat([kite_nse_exact, kite_nse_be, kite_nse_hyphen])

            valid_symbols_bse = set(df.loc[(df['BSE_SYMBOL'] != '') & (df['NSE_SYMBOL'] == ''), 'BSE_SYMBOL'])
            kite_bse = instruments_df[
                (instruments_df['exchange'] == 'BSE') &
                (instruments_df['tradingsymbol'].isin(valid_symbols_bse))
            ].copy()
            kite_bse['match_type'] = 'exact'
            kite_bse['lookup_symbol'] = kite_bse['tradingsymbol']
            if 'series' not in kite_bse.columns:
                kite_bse['series'] = None

            final_instruments = pd.concat([kite_nse, kite_bse])

            req_columns = ['instrument_token', 'exchange_token', 'tradingsymbol', 'name', 'exchange', 'series', 'lookup_symbol', 'base_symbol']
            for col in req_columns:
                if col not in final_instruments.columns:
                    final_instruments[col] = None

            final_instruments['exchange_token'] = final_instruments['exchange_token'].astype(str)

            df_nse = df[df['NSE_SYMBOL'] != ''][['NSE_SYMBOL', 'marketCap', 'industry', 'sector']].rename(columns={'NSE_SYMBOL': 'lookup_key'})
            df_bse = df[df['BSE_SYMBOL'] != ''][['BSE_SYMBOL', 'marketCap', 'industry', 'sector']].rename(columns={'BSE_SYMBOL': 'lookup_key'})
            df_map = pd.concat([df_nse, df_bse]).drop_duplicates('lookup_key')

            final_instruments = final_instruments.merge(
                df_map, left_on='lookup_symbol', right_on='lookup_key', how='left'
            )

            output_columns = ['instrument_token', 'exchange_token', 'tradingsymbol', 'name', 'exchange', 'series', 'marketCap', 'industry', 'sector']
            final_instruments = final_instruments[output_columns]
            final_instruments.rename(columns={'marketCap': 'marketcap'}, inplace=True)

            instruments_json = json.loads(final_instruments.to_json(orient='records', indent=4))
            logger.info(f"Syncing {len(final_instruments)} instruments to Kite")
            final_instruments.to_json(self.instr_json, orient='records', indent=4)

            # Snapshot existing tokens BEFORE wiping the table so we can cascade changes.
            existing_map = instr_repo.get_token_map()

            response = instr_repo.delete_all()
            if response == -1:
                return 500, 0
            response = instr_repo.bulk_insert(instruments_json)
            if response is None:
                return 500, 0

            # After re-inserting, cascade any token/series changes into market_data + indicators.
            if existing_map:
                kite_lookup = self._build_nse_kite_lookup(instruments_df)
                cascade_result = self._detect_and_cascade_changes(existing_map, kite_lookup)
                logger.info(f"Post-init cascade result: {cascade_result}")

            return 200, len(final_instruments)
        except Exception as e:
            logger.error(f"Error syncing with Kite: {e}")
            return 500, 0

    def sync_instruments(self):
        """
        Lightweight sync: reads existing instruments table, fetches fresh Kite
        instruments CSV, detects series/token changes (EQ <-> BE), cascades new
        instrument_token + exchange_token into market_data and indicators, then
        updates the instruments row itself.

        Does NOT delete/re-insert all rows — only changed symbols are touched.
        Returns a summary dict: {checked, changed, errors}.
        """
        logger.info("Starting instrument sync (series-change detection)...")
        try:
            # 1. Snapshot existing NSE instruments from DB
            existing_map = instr_repo.get_token_map()
            if not existing_map:
                logger.warning("No existing NSE instruments found — run full init first.")
                return {'checked': 0, 'changed': 0, 'errors': 0}

            # 2. Fetch fresh Kite instruments and build lookup
            instruments_df = self.get_instruments()
            kite_lookup = self._build_nse_kite_lookup(instruments_df)

            # 3. Detect changes and cascade
            result = self._detect_and_cascade_changes(existing_map, kite_lookup)
            logger.info(f"Instrument sync complete: {result}")
            return result

        except Exception as e:
            logger.error(f"Instrument sync failed: {e}")
            raise e
