
import json
import requests
import pandas as pd

from datetime import timedelta

from utils.logger import setup_logger
from services.indicators_service import IndicatorsService


logger = setup_logger(name="Orchestrator")
BASE_URL = "http://127.0.0.1:5000"


def calculate_indicators():
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
    
    for instr in instruments:
        tradingsymbol = instr.get("tradingsymbol")
        instr_token = instr.get("instrument_token")
        exchange = instr.get("exchange")
        log_symb = f"{tradingsymbol} ({instr_token})"

        logger.info(f"Processing {log_symb})...")

        last_data_date = None
        try:
            resp = requests.get(f"{BASE_URL}/market_data/latest/{tradingsymbol}")
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    last_data_date = data.get("date")
                    last_data_date = pd.to_datetime(last_data_date)
        except Exception as e:
            logger.error(f"Error fetching latest market data for {log_symb}: {e}")


        last_ind_date = None
        try:
            # GET /indicators/latest/<tradingsymbol>
            resp = requests.get(f"{BASE_URL}/indicators/latest/{tradingsymbol}")
            if resp.status_code == 200:
                ind_data = resp.json()
                if ind_data:
                    last_ind_date = ind_data.get("date")
                    last_ind_date =  pd.to_datetime(last_ind_date)
        except Exception:
            pass # Ignore if not found
            
        if last_ind_date and last_ind_date == last_data_date:
            continue
        elif last_ind_date:
            calc_start_date = pd.to_datetime(last_ind_date) - timedelta(days=365)
            if last_ind_date >= today:
                logger.info(f"Indicators up to date for {log_symb}.")
                continue
        else:
            calc_start_date = pd.to_datetime("2000-01-01")
            
        query_payload = {
            "tradingsymbol": tradingsymbol,
            "start_date": str(calc_start_date.date()),
            "end_date": str(today.date())
        }
        try:
            m_resp = requests.get(f"{BASE_URL}/market_data/query", json=query_payload)
            if m_resp.status_code == 200:
                md_list = m_resp.json()
                if len(md_list)<200:
                    logger.error(f"Less than 200 days data")
                    continue
            else:
                logger.error(f"Failed to query market data: {m_resp.text}")
                continue
        except Exception as e:
             logger.error(f"Error querying market data: {e}")
             continue
        
        if not md_list:
            logger.info(f"No new data to calculate indicators for {log_symb}")
            continue

        df_for_ind = pd.DataFrame(md_list)
        df_for_ind['date'] = pd.to_datetime(df_for_ind['date'])
        df_for_ind.set_index('date', inplace=True)
        df_for_ind.sort_index(inplace=True)
        
        logger.info("Calculating indicators...")

        ind_output = ind_service.calculate_indicators(df_for_ind)
        ind_df = pd.DataFrame(ind_output)

        ind_df.reset_index(inplace=True)
        ind_df['instrument_token'] = instr_token
        ind_df['tradingsymbol'] = tradingsymbol
        ind_df['exchange'] = exchange

        if last_ind_date:
            next_day = last_ind_date + timedelta(days=1)
            ind_df_filtered = ind_df[ind_df['date'] >= next_day]
        else:
            ind_df_filtered = ind_df
        if ind_df_filtered.empty:
            logger.info(f"No new data to calculate indicators for {log_symb}")
            continue
        
        ind_df_filtered['date'] = ind_df_filtered['date'].dt.strftime('%Y-%m-%d')        
        ind_json = json.loads(ind_df_filtered.to_json(orient='records', indent=4))
        try:
            # API expects single object
            resp = requests.post(f"{BASE_URL}/indicators", json=ind_json)
            if resp.status_code != 201:
                logger.error(f"Failed to post indicator: {resp.text}")
        except Exception as e:
            logger.error(f"Error posting indicator: {e}")

    # logger.info("Orchestration Complete.")
