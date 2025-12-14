import requests
import pandas as pd
import logging
from services.ranking_service import StockRankingScorecard

# Configure logging
logger = logging.getLogger(__name__)

BASE_URL = "http://127.0.0.1:5000"

def calculate_score():
    """
    Orchestrates the ranking process:
    1. Fetch instruments
    2. Fetch latest price and indicator data for each instrument
    3. Construct DataFrames
    4. Calculate composite scores
    """
    logger.info("Starting Ranking Calculation...")

    # 1. Get Instruments
    try:
        resp = requests.get(f"{BASE_URL}/instruments")
        if resp.status_code != 200:
            logger.error(f"Failed to fetch instruments: {resp.text}")
            return
        instruments = resp.json()
        logger.info(f"Fetched {len(instruments)} instruments.")
    except Exception as e:
        logger.error(f"Error fetching instruments: {e}")
        return

    price_data_list = []
    indicators_data_list = []

    # 2. Fetch Data for each instrument
    # Optimization: In a real scenario, this should be a bulk API or parallelized.
    # For now, looping as per instructions.
    
    total = len(instruments)
    for i, instr in enumerate(instruments):
        symbol = instr.get("tradingsymbol")
        if not symbol:
            continue
            
        if i % 10 == 0:
            logger.info(f"Processing {i+1}/{total}: {symbol}...")

        # Get Latest Price
        try:
            p_resp = requests.get(f"{BASE_URL}/market_data/latest/{symbol}")
            if p_resp.status_code == 200:
                p_data = p_resp.json()
                if p_data:
                    # Enrich with symbol if missing in response (though it should be there)
                    price_data_list.append(p_data)
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")

        # Get Latest Indicators
        try:
            i_resp = requests.get(f"{BASE_URL}/indicators/latest/{symbol}")
            if i_resp.status_code == 200:
                i_data = i_resp.json()
                if i_data:
                    indicators_data_list.append(i_data)
        except Exception as e:
            logger.error(f"Error fetching indicators for {symbol}: {e}")

    logger.info(f"Collected {len(price_data_list)} price records and {len(indicators_data_list)} indicator records.")

    if not indicators_data_list:
        logger.warning("No indicator data found. Cannot rank.")
        return

    # 3. Create DataFrames
    stocks_df = pd.DataFrame(price_data_list)
    metrics_df = pd.DataFrame(indicators_data_list)

    # Ensure metrics_df has 'symbol' column. 
    # API /indicators/schema might name it 'tradingsymbol' or 'symbol'. 
    # Let's check schemas or assume 'tradingsymbol' from DB model.
    # ranking_service uses 'symbol' in _apply_universe_penalties. 
    # I should rename if necessary.
    
    if 'tradingsymbol' in metrics_df.columns and 'symbol' not in metrics_df.columns:
        metrics_df.rename(columns={'tradingsymbol': 'symbol'}, inplace=True)
    
    if 'tradingsymbol' in stocks_df.columns and 'symbol' not in stocks_df.columns:
        stocks_df.rename(columns={'tradingsymbol': 'symbol'}, inplace=True)

    # 4. Calculate Score
    # We pass empty dict for stock_data as we only have latest 1-row data, 
    # and fetching full history for all stocks for penalty box was not requested/is expensive here.
    # The user specifically asked for "latest price and indicator data".
    ranker = StockRankingScorecard(stocks_df, metrics_df)
    
    ranked_df = ranker.calculate_composite_score()
    
    # 5. Output / Store
    # For now, we'll log the top 10 and maybe return it or save to CSV?
    # User didn't specify where to save. I will print head.
    logger.info("Ranking Complete. Top 10 Stocks:")
    print(ranked_df[['symbol', 'composite_score']].head(10))
    ranked_df.to_csv("data/ranked.csv", index=False)
    return ranked_df