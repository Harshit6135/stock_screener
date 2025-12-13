import requests
import pandas as pd

from datetime import timedelta

from utils.kite import KiteService
from utils.logger import setup_logger
from config.app_config import CONFIG
from services.market_data_service import MarketDataService

BASE_URL = "http://127.0.0.1:5000"

def get_latest_data():
    logger = setup_logger(name="Orchestrator")
    logger.info("Starting Update Price Data (API Mode)...")

    # Initialize Kite Service
    # We pass None for db_manager as DB operations are via API
    kite_service = KiteService(CONFIG, logger)
    md_service = MarketDataService(kite_service, logger)

    logger.info("Fetching Instruments via Kite API...")
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

    logger.info("Fetching Historical Data for instruments via Kite API...")
    today = pd.Timestamp.now().normalize()
    
    for instr in instruments:
        tradingsymbol = instr.get("tradingsymbol")
        instr_token = instr.get("instrument_token")
        exchange = instr.get("exchange")
        log_symb = f"{tradingsymbol} ({instr_token})"
        logger.info(f"Processing {log_symb})...")
        
        last_date = None
        try:
            resp = requests.get(f"{BASE_URL}/market_data/latest/{tradingsymbol}")
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    last_date = data.get("date")
        except Exception as e:
            logger.error(f"Error fetching latest market data for {log_symb}: {e}")

        start_date = today - timedelta(days=365) # Default 1 year
        if last_date:
            start_date = pd.to_datetime(last_date) + timedelta(days=1)
            
        md_updated = False
        if start_date <= today:
            logger.info(f"Fetching from Kite for {log_symb}) starting {start_date.date()}...")
            # Use Service directly for Kite Call
            new_data_df = md_service.load_data(instr_token, start_date, today)
            
            if new_data_df is not None and not new_data_df.empty:
                logger.info(f"Posting {len(new_data_df)} records to MarketData API...")
                records = []
                for idx, row in new_data_df.iterrows():
                    records.append({
                        "instrument_token": instr_token,
                        "tradingsymbol": tradingsymbol,
                        "exchange": exchange if exchange else "NSE",
                        "date": str(idx.date()), # JSON requires string dates
                        "open": row.get('Open'),
                        "high": row.get('High'),
                        "low": row.get('Low'),
                        "close": row.get('Close'),
                        "volume": row.get('Volume')
                    })
                
                try:
                    p_resp = requests.post(f"{BASE_URL}/market_data", json=records)
                    if p_resp.status_code in [200, 201]:
                        md_updated = True
                    else:
                        logger.error(f"Failed to post market data for {log_symb}: {p_resp.text}")
                except Exception as e:
                    logger.error(f"Error posting market data: {e}")
    logger.info("Price Update Complete.")
