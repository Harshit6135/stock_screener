
import pandas as pd
from datetime import timedelta
import time
import requests
import json

# Config and Utils
from config.app_config import CONFIG
from utils.kite import KiteService
from utils.logger import setup_logger

# Services
from services.market_data_service import MarketDataService
from services.indicators_service import IndicatorsService

BASE_URL = "http://127.0.0.1:5000"

def orchestrator():
    logger = setup_logger(name="Orchestrator")
    logger.info("Starting Orchestrator (API Mode)...")

 # Initialize Kite Service
    # We pass None for db_manager as DB operations are via API
    kite_service = KiteService(CONFIG, logger)
    
    # Initialize Market Data Service (for Kite fetching only)
    md_service = MarketDataService(kite_service, None, logger)
    
    
    ind_service = IndicatorsService()

    # Step 1: Get all instruments via API
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

    # Step 2 & 3: Iterate Tickers
    logger.info("Step 2 & 3: Processing Tickers...")
    today = pd.Timestamp.now().normalize()
    
    for instr in instruments[:5]:
        ticker = instr.get("tradingsymbol")
        token = instr.get("instrument_token")
        exchange = instr.get("exchange")
        
        logger.info(f"Processing {ticker} ({token})...")
        
        # --- MARKET DATA UPDATE ---
        last_date = None
        try:
            # GET /market_data/latest/<ticker>
            resp = requests.get(f"{BASE_URL}/market_data/latest/{ticker}")
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    last_date = data.get("date")
        except Exception as e:
            logger.error(f"Error fetching latest market data for {ticker}: {e}")

        start_date = today - timedelta(days=365) # Default 1 year
        if last_date:
            start_date = pd.to_datetime(last_date) + timedelta(days=1)
            
        md_updated = False
        
        if start_date <= today:
            logger.info(f"Fetching from Kite for {ticker} starting {start_date.date()}...")
            # Use Service directly for Kite Call
            new_data_df = md_service.load_data(token, start_date, today)
            
            if new_data_df is not None and not new_data_df.empty:
                logger.info(f"Posting {len(new_data_df)} records to MarketData API...")
                records = []
                for idx, row in new_data_df.iterrows():
                    records.append({
                        "instrument_id": token,
                        "ticker": ticker,
                        "exchange": exchange if exchange else "NSE",
                        "date": str(idx.date()), # JSON requires string dates
                        "open": row.get('Open'),
                        "high": row.get('High'),
                        "low": row.get('Low'),
                        "close": row.get('Close'),
                        "volume": row.get('Volume')
                    })
                
                # POST /market_data
                try:
                    p_resp = requests.post(f"{BASE_URL}/market_data", json=records)
                    if p_resp.status_code in [200, 201]:
                        md_updated = True
                    else:
                        logger.error(f"Failed to post market data for {ticker}: {p_resp.text}")
                except Exception as e:
                    logger.error(f"Error posting market data: {e}")
        
        # --- INDICATORS UPDATE ---
        last_ind_date = None
        try:
            # GET /indicators/latest/<ticker>
            resp = requests.get(f"{BASE_URL}/indicators/latest/{ticker}")
            if resp.status_code == 200:
                ind_data = resp.json()
                if ind_data:
                    last_ind_date = ind_data.get("date")
        except Exception:
            pass # Ignore if not found
            
        calc_start_date = None
        if last_ind_date:
            calc_start_date = pd.to_datetime(last_ind_date) + timedelta(days=1)
        else:
             calc_start_date = pd.to_datetime("2000-01-01") 
             
        max_date = today
        # If we didn't update MD, max is last MD date
        if last_ind_date and not md_updated and last_date:
             max_date = pd.to_datetime(last_date)
            
        if calc_start_date > max_date:
            logger.info(f"Indicators up to date for {ticker}.")
            continue
            
        context_start = calc_start_date - timedelta(days=200)
        
        # Fetch Context Data via API
        # GET /market_data/query
        query_payload = {
            "ticker": ticker,
            "start_date": str(context_start.date()),
            "end_date": str(max_date.date())
        }
        try:
            # GET with body is non-standard but generic, Flask/requests support it,
            # BUT flask-smorest @blp.arguments(schema, location='json') expects body.
            # requests.get(..., json=...) works.
            m_resp = requests.get(f"{BASE_URL}/market_data/query", json=query_payload)
            md_list = []
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
             
        # Process for Service
        df_list = []
        for m in md_list:
            df_list.append({
                "date": m['date'],
                "Open": m['open'],
                "High": m['high'],
                "Low": m['low'],
                "Close": m['close'],
                "Volume": m['volume']
            })
        
        df_for_ind = pd.DataFrame(df_list)
        df_for_ind['date'] = pd.to_datetime(df_for_ind['date'])
        df_for_ind.set_index('date', inplace=True)
        df_for_ind.sort_index(inplace=True)
        
        ind_conf_map = {}
        if "trend" in CONFIG:
            emas = []
            if "short_ma" in CONFIG["trend"]: emas.append(CONFIG["trend"]["short_ma"])
            if "long_ma" in CONFIG["trend"]: emas.append(CONFIG["trend"]["long_ma"])
            ind_conf_map['ema'] = emas
        
        if "momentum" in CONFIG:
            rsi_period = CONFIG["momentum"].get("rsi_period", 14)
            rsi_smooth = CONFIG["momentum"].get("rsi_smooth", 3)
            ind_conf_map['rsi'] = [(rsi_period, rsi_smooth)]
            if "roc_period" in CONFIG["momentum"]:
                ind_conf_map['roc'] = [CONFIG["momentum"]["roc_period"]]

        if "gps" in CONFIG:
            fast = CONFIG["gps"].get("fast", 12)
            slow = CONFIG["gps"].get("slow", 26)
            signal = CONFIG["gps"].get("signal", 9)
            ind_conf_map['macd'] = [(fast, slow, signal)]

        
        logger.info("Calculating indicators...")
        output_dict = ind_service.update_indicators_to_db(token, exchange, ticker, ind_conf_map)
        
        series_data = {k:v for k,v in output_dict.items() if isinstance(v, pd.Series)}
        if not series_data:
             continue
             
        df_ind = pd.DataFrame(series_data)
        df_ind_filtered = df_ind[df_ind.index >= calc_start_date]
        
        if df_ind_filtered.empty:
            continue
            
        logger.info(f"Posting {len(df_ind_filtered)} indicator records...")
        
        for idx, row in df_ind_filtered.iterrows():
            ema_50 = row.get("ema_50")
            ema_200 = row.get("ema_200")
            
            rsi_p = CONFIG["momentum"].get("rsi_period", 14)
            rsi_s = CONFIG["momentum"].get("rsi_smooth", 3)
            rsi_val = row.get(f"rsi_{rsi_p}_{rsi_s}")
            
            gps_conf = CONFIG.get("gps", {})
            fast = gps_conf.get("fast", 12)
            slow = gps_conf.get("slow", 26)
            sig = gps_conf.get("signal", 9)
            macd_val = row.get(f"macd_{fast}_{slow}_{sig}")
            
            payload = {
                "instrument_token": token, # Schema expects instrument_token
                "ticker": ticker,
                "date": str(idx.date()),
                "exchange": exchange,
                "ema_50": ema_50 if pd.notna(ema_50) else None,
                "ema_200": ema_200 if pd.notna(ema_200) else None,
                "rsi_14": rsi_val if pd.notna(rsi_val) else None,
                "macd": macd_val if pd.notna(macd_val) else None
            }
            
            # POST /indicators
            try:
                # API expects single object
                i_resp = requests.post(f"{BASE_URL}/indicators", json=payload)
                if i_resp.status_code != 201:
                    logger.error(f"Failed to post indicator: {i_resp.text}")
            except Exception as e:
                logger.error(f"Error posting indicator: {e}")
                
        time.sleep(0.34)

    logger.info("Orchestration Complete.")
