import requests
import pandas as pd
from datetime import date

from db import db
from models import RankingModel
from services.ranking_service import StockRankingScorecard
from utils.logger import setup_logger


logger = setup_logger(name="Orchestrator")
BASE_URL = "http://127.0.0.1:5000"


def calculate_score():
    """
    Orchestrates the ranking process:
    1. Fetch instruments
    2. Fetch latest price and indicator data for each instrument
    3. Construct DataFrames
    4. Calculate composite scores
    5. Save to ranking table with date
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
                    if p_data['close'] < 75 or p_data['close']*p_data['volume'] < 10000000:
                        continue
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

    if 'tradingsymbol' in metrics_df.columns and 'symbol' not in metrics_df.columns:
        metrics_df.rename(columns={'tradingsymbol': 'symbol'}, inplace=True)
    
    if 'tradingsymbol' in stocks_df.columns and 'symbol' not in stocks_df.columns:
        stocks_df.rename(columns={'tradingsymbol': 'symbol'}, inplace=True)

    # 4. Calculate Score
    ranker = StockRankingScorecard(stocks_df, metrics_df)
    ranked_df = ranker.calculate_composite_score()
    
    # Add ranking date and position
    ranking_date = date.today()
    ranked_df['ranking_date'] = ranking_date
    ranked_df['rank_position'] = range(1, len(ranked_df) + 1)
    
    # Rename symbol back to tradingsymbol for DB
    if 'symbol' in ranked_df.columns:
        ranked_df.rename(columns={'symbol': 'tradingsymbol'}, inplace=True)
    
    # 5. Save to database
    logger.info("Saving rankings to database...")
    
    # Delete existing rankings for today (if re-running)
    from run import app
    with app.app_context():
        RankingModel.query.filter(RankingModel.ranking_date == ranking_date).delete()
        db.session.commit()
        
        # Insert new rankings
        ranking_records = ranked_df.to_dict('records')
        db.session.bulk_insert_mappings(RankingModel, ranking_records)
        db.session.commit()
    
    logger.info(f"Saved {len(ranked_df)} rankings to database for {ranking_date}")
    
    # Also save to CSV for backup
    ranked_df.to_csv("data/ranked.csv", index=False)
    
    logger.info("Ranking Complete. Top 10 Stocks:")
    print(ranked_df[['tradingsymbol', 'composite_score']].head(10))
    
    return ranked_df