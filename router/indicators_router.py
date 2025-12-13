
import pandas as pd
from datetime import timedelta
import time
import requests
import json

# Config and Utils
from config.app_config import CONFIG
from utils.kite import KiteService
from utils.logger import setup_logger
from strategy.strategy_1 import MOMENTUM

# Services
from services.market_data_service import MarketDataService
from services.indicators_service import IndicatorsService

BASE_URL = "http://127.0.0.1:5000"

def calculate_indicators():
    logger = setup_logger(name="Orchestrator")
    logger.info("Starting OUpdate Indicators (API Mode)...")

    ind_service = IndicatorsService()

    logger.info("Step 1: Fetching Instruments via API...")
    try:
        resp = requests.get(f"{BASE_URL}/instruments")
        if resp.status_code == 200:
            instruments = resp.json()
            logger.info(f"Fetched {len(instruments)} instruments.")
        else:
            logger.error(f"Failed to fetch instruments: {resp.text}")
            return
    except Exception as e:
        logger.error(f"API connection failed: {e}")
        return

    logger.info("Calculating Indicators for Instruments...")
    today = pd.Timestamp.now().normalize()
    
    for instr in instruments[:5]:
        tradingsymbol = instr.get("tradingsymbol")
        instr_token = instr.get("instrument_token")
        exchange = instr.get("exchange")
        log_symb = f"{tradingsymbol} ({instr_token})"

        logger.info(f"Processing {log_symb})...")

        last_ind_date = None
        try:
            # GET /indicators/latest/<tradingsymbol>
            resp = requests.get(f"{BASE_URL}/indicators/latest/{tradingsymbol}")
            if resp.status_code == 200:
                ind_data = resp.json()
                if ind_data:
                    last_ind_date = ind_data.get("date")
        except Exception:
            pass # Ignore if not found
            
        if last_ind_date:
            calc_start_date = pd.to_datetime(last_ind_date) - timedelta(days=200)
        else:
            calc_start_date = pd.to_datetime("2000-01-01")
             
        if last_ind_date >= today.date:
            logger.info(f"Indicators up to date for {log_symb}.")
            continue
            
        query_payload = {
            "tradingsymbol": tradingsymbol,
            "start_date": str(calc_start_date.date()),
            "end_date": str(today.date())
        }
        try:
            m_resp = requests.get(f"{BASE_URL}/market_data/query", json=query_payload)
            if m_resp.status_code == 200:
                md_list = m_resp.json()
            else:
                logger.error(f"Failed to query market data: {m_resp.text}")
                continue
        except Exception as e:
             logger.error(f"Error querying market data: {e}")
             continue
        
        if not md_list:
             continue

        df_for_ind = pd.DataFrame(md_list)
        df_for_ind['date'] = pd.to_datetime(df_for_ind['date'])
        df_for_ind.set_index('date', inplace=True)
        df_for_ind.sort_index(inplace=True)
        
        logger.info("Calculating indicators...")

        ind_output = ind_service.update_indicators_to_db(df_for_ind, instr_token, exchange, tradingsymbol, MOMENTUM)
        print(ind_output)
        #
        # ema_50 = ind_service.ema(df_for_ind, 50)
        # ema_200 = ind_service.ema(df_for_ind, 200)
        # rsi_14 = ind_service.rsi(df_for_ind, (14, 3))[""]
        # macd = ind_service.macd(df_for_ind, (12, 26, 9))[""]
        # ind_df = pd.DataFrame({
        #     "ema_50": ema_50,
        #     "ema_200": ema_200,
        #     "rsi_14": rsi_14,
        #     "macd": macd
        # })
        # ind_df.reset_index(inplace=True)
        # ind_df['date'] = ind_df['date'].dt.strftime('%Y-%m-%d')
        #
        # ind_df['instrument_token'] = token
        # ind_df['ticker'] = ticker
        # ind_df['exchange'] = exchange
        # ind_json = json.loads(ind_df.to_json(orient='records', indent=4))
        # ind_df.to_json("data/indicators.json", orient='records', indent=4)
        # try:
        #     # API expects single object
        #     resp = requests.post(f"{BASE_URL}/indicators", json=ind_json)
        #     if resp.status_code != 201:
        #         logger.error(f"Failed to post indicator: {resp.text}")
        # except Exception as e:
        #     logger.error(f"Error posting indicator: {e}")
        #     break
        time.sleep(0.34)

    logger.info("Orchestration Complete.")
