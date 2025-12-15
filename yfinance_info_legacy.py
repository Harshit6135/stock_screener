"""# Task
Load stock lists from `/content/NSE.csv` and `/content/BSE1.csv`, consolidate their information using ISINs, and then fetch historical stock data for these consolidated stocks using `yfinance`. Prioritize NSE symbols (e.g., 'SYMBOL.NS'), then BSE alphanumeric symbols (e.g., 'ALPHASCRIP.BO'), and finally BSE numeric security codes (e.g., '500000.BO') for `yfinance` queries, implementing fallback and error handling. Save the combined information, including historical data and all original columns, into a new CSV file. Finally, provide a summary of the process, including data retrieval statistics and the location of the output CSV.

## Load NSE Stock List and Prepare Data

### Subtask:
Load the `/content/NSE.csv` file into a pandas DataFrame, identify and store the column names for stock symbols and ISINs, and prepare the DataFrame by cleaning column names and adding a prefix to distinguish them.
"""

import pandas as pd

df_nse = pd.read_csv('/content/NSE.csv')
nse_original_columns = df_nse.columns.tolist()
df_nse = df_nse.rename(columns=lambda x: 'NSE_' + x.strip().replace(" ", "_"))

print("DataFrame 'df_nse' loaded and processed successfully.")
print("First 5 rows of df_nse:")
print(df_nse.head())
print("Original column names:")
print(nse_original_columns)
print("New column names:")
print(df_nse.columns.tolist())

stock_symbol_column_nse = 'NSE_SYMBOL'
isin_column_nse = 'NSE_ISIN_NUMBER'

print(f"Stock symbol column for NSE: {stock_symbol_column_nse}")
print(f"ISIN column for NSE: {isin_column_nse}")

"""## Load BSE Stock List and Prepare Data

### Subtask:
Load the `/content/BSE1.csv` file into a pandas DataFrame, identify and store the column names for stock symbols (BSE security code, and potentially an alphanumeric symbol) and ISINs, and prepare the DataFrame by cleaning column names and adding a prefix to distinguish them.

"""

import pandas as pd

df_bse = pd.read_csv('/content/BSE1.csv')
df_bse.reset_index(inplace=True)
bse_original_columns = df_bse.columns.tolist()

rename_map = {
"level_0":	"bse_Security Code",
"level_1": "BSE_ISSUER_NAME",
"level_2":	"bse_Security Id",
"level_3":	"bse_Security Name",
"level_4":	"bse_Status",
"Security Code": "bse_Group",
"Issuer Name":	"bse_Face Value",
"Security Id":	"bse_ISIN No",
"Security Name":	"bse_Instrument"
}
df_bse = df_bse.rename(columns=rename_map)
df_bse = df_bse[["bse_Face Value", "BSE_ISSUER_NAME",
"bse_ISIN No",
"bse_Instrument",
"bse_Security Code",
"bse_Security Id",
"bse_Security Name",
"bse_Status"]]

# Clean column names: strip whitespace, replace spaces with underscores, prepend 'BSE_'
df_bse = df_bse.rename(columns=lambda x: x.strip().replace(' ', '_').upper())

# Identify column names after renaming based on common patterns and the specific CSV structure.
# Prioritizing the names as suggested by the previous analysis and the subtask instruction.
stock_numeric_symbol_column_bse = "BSE_SECURITY_CODE"
stock_alphanumeric_symbol_column_bse = "BSE_SECURITY_ID"
isin_column_bse = "BSE_ISIN_NO"

print("DataFrame 'df_bse' loaded and processed successfully.")
print("First 5 rows of df_bse:")
print(df_bse.head())
print("Original column names:")
print(bse_original_columns)
print("New column names:")
print(df_bse.columns.tolist())
print(f"Numeric stock symbol column for BSE: {stock_numeric_symbol_column_bse}")
print(f"Alphanumeric stock symbol column for BSE: {stock_alphanumeric_symbol_column_bse}")
print(f"ISIN column for BSE: {isin_column_bse}")

initial_consolidated_count = len(df_bse)

df_bse = df_bse[df_bse['BSE_STATUS'] == 'Active'].copy()

print(f"Initial number of rows in df_consolidated: {initial_consolidated_count}")
print(f"Number of rows after filtering for 'Active' BSE_STATUS: {len(df_bse)}")
print("First 5 rows of df_bse:")
print(df_bse.head())

"""## Consolidate Stock Information by ISIN

### Subtask:
Merge the prepared NSE and BSE DataFrames (`df_nse` and `df_bse`) based on their respective ISIN columns to create a consolidated DataFrame. Prioritize NSE data for common columns (though prefixes should prevent direct conflicts) and retain all non-duplicate columns from both original files.

"""

df_nse['ISIN'] = df_nse[isin_column_nse]
df_bse['ISIN'] = df_bse[isin_column_bse]

df_consolidated = pd.merge(df_nse, df_bse, on='ISIN', how='outer')

print("Consolidated DataFrame 'df_consolidated' created successfully.")
print("First 5 rows of df_consolidated:")
print(df_consolidated.head())
print("Shape of df_consolidated:", df_consolidated.shape)

"""## Filter by ISIN Prefix

### Subtask:
Filter the DataFrame further to remove any stocks where the 'ISIN' does not start with 'IN'. Display the count of remaining stocks after this filter.

"""

initial_isin_filter_count = len(df_consolidated)

df_filtered_isin_prefix = df_consolidated[df_consolidated['ISIN'].astype(str).str.startswith('IN', na=False)].copy()

print(f"Total stocks in df_consolidated before ISIN prefix filter: {initial_isin_filter_count}")
print(f"Stocks remaining after filtering for ISINs starting with 'IN': {len(df_filtered_isin_prefix)}")
print("First 5 rows of df_filtered_isin_prefix:")
print(df_filtered_isin_prefix.head())

"""## Filter by Issuer Name (Mutual Fund)

### Subtask:
Filter the DataFrame further to remove any stocks where the 'BSE_ISSUER_NAME' contains 'Mutual Fund'. Display the count of remaining stocks after this filter.

"""

initial_mutual_fund_filter_count = len(df_filtered_isin_prefix)

df_filtered_mutual_fund = df_filtered_isin_prefix[~
    df_filtered_isin_prefix['BSE_ISSUER_NAME'].astype(str).str.contains('Mutual Fund', case=False, na=False)
].copy()

print(f"Total stocks in df_filtered_isin_prefix before 'Mutual Fund' filter: {initial_mutual_fund_filter_count}")
print(f"Stocks remaining after filtering out 'Mutual Fund' in BSE_ISSUER_NAME: {len(df_filtered_mutual_fund)}")
print("First 5 rows of df_filtered_mutual_fund:")
print(df_filtered_mutual_fund.head())

"""## Filter by Issuer Name (Asset Management & ETF)

### Subtask:
Filter the DataFrame further to remove any stocks where 'BSE_ISSUER_NAME' contains 'asset management' AND 'BSE_SECURITY_NAME' contains 'etf'. Display the count of remaining stocks after this filter.

"""

initial_asset_management_etf_filter_count = len(df_filtered_mutual_fund)

df_filtered_asset_management_etf = df_filtered_mutual_fund[~
    (df_filtered_mutual_fund['BSE_ISSUER_NAME'].astype(str).str.contains('asset management', case=False, na=False) &
     df_filtered_mutual_fund['BSE_SECURITY_NAME'].astype(str).str.contains('etf', case=False, na=False))
].copy()

print(f"Total stocks in df_filtered_mutual_fund before 'Asset Management & ETF' filter: {initial_asset_management_etf_filter_count}")
print(f"Stocks remaining after filtering out 'Asset Management & ETF': {len(df_filtered_asset_management_etf)}")
print("First 5 rows of df_filtered_asset_management_etf:")
print(df_filtered_asset_management_etf.head())

"""## Clean and Refine Consolidated DataFrame

### Subtask:
Perform final cleanup on the filtered DataFrame (`df_filtered_asset_management_etf`): remove redundant ISIN columns (keeping the merged 'ISIN' column), convert 'BSE_SECURITY_CODE' to string type without decimals, rename key symbol columns to be user-friendly (e.g., 'NSE_Ticker', 'BSE_Num_Code', 'BSE_Alpha_Symbol', 'BSE_Company_Name'), and remove all specified unwanted columns ('NSE_NAME OF COMPANY', 'NSE_SERIES', 'NSE_DATE OF LISTING', 'NSE_PAID UP VALUE', 'NSE_MARKET LOT', 'NSE_FACE VALUE', 'BSE_FACE_VALUE', 'BSE_ISSUER_NAME', 'BSE_INSTRUMENT', 'BSE_STATUS', 'BSE_GROUP').

"""

df_cleaned = df_filtered_asset_management_etf.copy()

# 2. Drop redundant ISIN columns
df_cleaned = df_cleaned.drop(columns=['NSE_ISIN_NUMBER', 'BSE_ISIN_NO'], errors='ignore')

# 3. Convert 'BSE_SECURITY_CODE' to string type and remove '.0'
df_cleaned['BSE_SECURITY_CODE'] = df_cleaned['BSE_SECURITY_CODE'].fillna(0).astype(int).astype(str)

# 4. Rename key symbol columns for clarity
rename_cols = {
    'BSE_SECURITY_ID': 'BSE_SYMBOL',
    'BSE_SECURITY_NAME': 'NAME_OF_COMPANY'
}
df_cleaned = df_cleaned.rename(columns=rename_cols)
df_cleaned['NAME_OF_COMPANY'] = df_cleaned['NAME_OF_COMPANY'].fillna(df_cleaned['NSE_NAME_OF_COMPANY'])

# 5. Drop specified unwanted columns
unwanted_cols = [
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
# BSE_GROUP was not present in the dataframe columns after the previous processing steps,
# but it was in the requested list to be dropped. Using errors='ignore' to prevent key errors.
df_cleaned = df_cleaned.drop(columns=unwanted_cols, errors='ignore')

df_cleaned = df_cleaned[['ISIN', 'NSE_SYMBOL', 'BSE_SYMBOL', 'BSE_SECURITY_CODE', 'NAME_OF_COMPANY']]

print("DataFrame 'df_cleaned' processed successfully.")
print("First 5 rows of df_cleaned:")
print(df_cleaned.head())
print("Shape of df_cleaned:", df_cleaned.shape)
print("Columns of df_cleaned:", df_cleaned.columns.tolist())

"""## Prepare Tickers for yfinance with Prioritization

### Subtask:
From the cleaned and consolidated DataFrame (`df_cleaned`), create a list of prioritized `yfinance` tickers for each unique ISIN. The order of priority should be: 1. NSE symbol (e.g., 'SYMBOL.NS'), 2. BSE alphanumeric symbol (e.g., 'ALPHASCRIP.BO'), 3. BSE numeric security code (e.g., '500000.BO'). Handle cases where a symbol might be missing or invalid for a specific exchange and append the correct exchange suffix (.NS or .BO).

"""

df_cleaned['yfinance_tickers'] = [[] for _ in range(len(df_cleaned))]

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

df_cleaned['yfinance_tickers'] = df_cleaned.apply(generate_yfinance_tickers, axis=1)

print("DataFrame 'df_cleaned' updated with 'yfinance_tickers' successfully.")
print("First 5 rows of df_cleaned with yfinance_tickers:")
print(df_cleaned.head())
print("Shape of df_cleaned:", df_cleaned.shape)
print("Columns of df_cleaned:", df_cleaned.columns.tolist())

"""## Fetch Ticker Information from yfinance with Prioritized Fallback and Error Handling

### Subtask:
Iterate through the `df_cleaned` DataFrame. For each stock, attempt to retrieve `yfinance.Ticker().info` using the prioritized tickers from the 'yfinance_tickers' column. Implement robust error handling (e.g., `try-except` blocks for `yfinance` errors, network issues) and introduce `time.sleep()` between requests to respect API rate limits. Store the retrieved `.info` (as a JSON string to handle varying data structures), noting which ticker was successfully used and the status of the retrieval.

**Reasoning**:
The subtask requires fetching data from yfinance for each stock in `df_cleaned`, with prioritized tickers, error handling, and rate limiting. This step imports the necessary libraries (`yfinance`, `json`, `time`), initializes new columns to store the results, and sets up a loop to attempt data retrieval for each stock, applying the specified logic.
"""

import yfinance as yf
import json
import time
import numpy as np # Import numpy for np.nan

# Initialize new columns
df_cleaned['yfinance_info'] = None
df_cleaned['yfinance_ticker_used'] = None
df_cleaned['yfinance_status'] = 'Pending'
desired_columns = [
    'industry', 'industryKey', 'industryDisp',
    'sector', 'sectorKey', 'sectorDisp',
    'fullTimeEmployees', 'marketCap',
    'allTimeHigh', 'allTimeLow',
    'floatShares', 'sharesOutstanding',
    'heldPercentInsiders', 'heldPercentInstitutions',
    'impliedSharesOutstanding', 'quoteType', 'exchange'
]

# Add all desired columns to DataFrame at once (do this BEFORE your loop)
missing_cols = [col for col in desired_columns if col not in df_cleaned.columns]
if missing_cols:
    df_cleaned = pd.concat([
        df_cleaned,
        pd.DataFrame({col: pd.NA for col in missing_cols}, index=df_cleaned.index)
    ], axis=1)

successful_downloads = 0
failed_downloads = 0

print("Starting yfinance data retrieval...")

# Iterate through each row of the DataFrame
for index, row in df_cleaned.iterrows():
    isin = row['ISIN']
    tickers_to_try = row['yfinance_tickers']

    # Default status for the current row if all attempts fail
    df_cleaned.at[index, 'yfinance_info'] = None
    df_cleaned.at[index, 'yfinance_ticker_used'] = None
    df_cleaned.at[index, 'yfinance_status'] = 'Failed'

    downloaded = False
    for ticker in tickers_to_try:
        print(f"\rAttempting to download data for ({index}/{len(df_cleaned)}) ISIN: {isin} with ticker: {ticker}", end="")
        try:
            stock_info = yf.Ticker(ticker).info

            # yfinance returns an empty dictionary if the ticker is not found
            if stock_info and 'regularMarketPrice' in stock_info: # Check for a key that typically indicates valid stock data
                df_cleaned.at[index, 'yfinance_info'] = json.dumps(stock_info)
                df_cleaned.at[index, 'yfinance_ticker_used'] = ticker
                df_cleaned.at[index, 'yfinance_status'] = 'Success'
                filtered_data = {k: stock_info[k] for k in desired_columns if k in stock_info}
                if filtered_data:
                    df_cleaned.loc[index, filtered_data.keys()] = list(filtered_data.values())
                successful_downloads += 1
                downloaded = True
                break # Move to the next stock if data is successfully downloaded
            else:
                print(f" - No valid info found for {ticker}")
        except Exception as e:
            print(f" - Error downloading {ticker}: {e}")
    if index % 20 == 0:
      time.sleep(5) # Sleep to respect API rate limits
    if not downloaded:
        failed_downloads += 1
    print(f"\nStatus - Susccessful - {successful_downloads}, Failed - {failed_downloads}\n")
print("\n\nFinished yfinance data retrieval.")
print("First 5 rows of df_cleaned with yfinance data:")
print(df_cleaned.head())
print(f"Total stocks processed: {len(df_cleaned)}")
print(f"Successful downloads: {successful_downloads}")
print(f"Failed downloads: {failed_downloads}")

file_path = '/content/drive/MyDrive/stocks_list.csv'