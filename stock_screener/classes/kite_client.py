import pandas as pd
from kiteconnect import KiteConnect
import os
import webbrowser
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
import time

class KiteClient:
    def __init__(self, config, db_manager, logger):
        self.config = config
        self.db_manager = db_manager
        self.logger = logger
        self.kite = None
        self.instrument_map = {}
        self.request_token = None
        
        self._initialize_kite()

    def _initialize_kite(self):
        try:
            api_key = self.config['kite']['api_key']
            
            if api_key == "YOUR_API_KEY":
                self.logger.warning("Kite API Key not set in config.")
                return

            self.kite = KiteConnect(api_key=api_key)
            self._ensure_session()
            
            self.logger.info("Kite Connect initialized.")
            
            # Fetch instruments to build a map (Symbol -> Token)
            self._load_instruments()
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Kite Client: {e}")

    def _ensure_session(self):
        token_file = "access_token.txt"
        access_token = None
        
        if os.path.exists(token_file):
            with open(token_file, "r") as f:
                access_token = f.read().strip()
                
        if access_token:
            self.kite.set_access_token(access_token)
            try:
                self.kite.profile()
                self.logger.info("Existing Access Token is valid.")
                return
            except Exception:
                self.logger.warning("Existing Access Token invalid.")
        
        # Start Automated Login Flow
        self._start_login_flow()

    def _start_login_flow(self):
        self.logger.info("Starting automated login flow...")
        
        # 1. Parse Redirect URL to find port
        redirect_url = self.config['kite'].get('redirect_url', 'http://127.0.0.1')
        parsed_url = urllib.parse.urlparse(redirect_url)
        port = parsed_url.port if parsed_url.port else 80
        host = parsed_url.hostname
        
        # 2. Define Callback Handler
        class CallbackHandler(BaseHTTPRequestHandler):
            client_instance = self
            
            def do_GET(self):
                # Extract query parameters
                parsed_path = urllib.parse.urlparse(self.path)
                query_params = urllib.parse.parse_qs(parsed_path.query)
                
                if 'request_token' in query_params:
                    # Capture token
                    self.client_instance.request_token = query_params['request_token'][0]
                    
                    # Send response to browser
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(b"<h1>Login Successful!</h1><p>You can close this window now.</p>")
                else:
                    self.send_response(400)
                    self.end_headers()
            
            def log_message(self, format, *args):
                pass # Suppress logging

        # 3. Start Local Server
        server = HTTPServer((host, port), CallbackHandler)
        server_thread = threading.Thread(target=server.handle_request)
        server_thread.start()
        
        # 4. Open Browser
        login_url = self.kite.login_url()
        self.logger.info(f"Opening Login URL: {login_url}")
        self.logger.info(f"Listening for callback on {host}:{port}...")
        webbrowser.open(login_url)
        
        # 5. Wait for token
        server_thread.join(timeout=120) # Wait max 2 minutes
        
        if self.request_token:
            self.logger.info("Request Token received via callback.")
            try:
                api_secret = self.config['kite']['api_secret']
                data = self.kite.generate_session(self.request_token, api_secret=api_secret)
                access_token = data["access_token"]
                self.kite.set_access_token(access_token)
                
                with open("access_token.txt", "w") as f:
                    f.write(access_token)
                self.logger.info("New Access Token generated and saved.")
            except Exception as e:
                self.logger.error(f"Login failed during session generation: {e}")
                raise e
        else:
            self.logger.error("Login timed out or failed to receive token.")
            raise TimeoutError("Login timed out")

    def _load_instruments(self):
        inst_file = "instruments.csv"
        # if os.path.exists(inst_file):
        #     self.logger.info("Loading instruments from local cache...")
        #     df = pd.read_csv(inst_file)
        # else:
        #     self.logger.info("Fetching instruments from Kite API...")
        try:
            instruments = self.kite.instruments()
            df = pd.DataFrame(instruments)
            df.to_csv(inst_file, index=False)

            # Filters for working instruments
            df = df[(df['segment'].isin(['NSE', 'BSE'])) & (df['lot_size'] == 1)]
            df = df[df['name'].notna()]
            
            # Exclude names containing certain keywords
            exclude_keywords = ['LOAN', 'ETF', 'BONDS', 'MUTUAL', '%']
            keyword_pattern = '|'.join(exclude_keywords)
            df = df[~df['name'].str.contains(keyword_pattern, case=False, na=False)]

            # Exclude names with month-year pattern like JAN24 for derivatives
            month_pattern = r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}'
            df = df[~df['name'].str.contains(month_pattern, case=True, na=False)]

            # Exclude Treasury Bill patterns like 364TB...
            tb_pattern = r'\d+TB\d+'
            df = df[~df['name'].str.contains(tb_pattern, case=True, na=False)]

            working_file = "working_instruments.csv"
            df.to_csv(working_file, index=False)
            self.logger.info(f"Filtered instruments saved to {working_file}")

        except Exception as e:
            self.logger.error(f"Could not fetch or process instruments: {e}")
            return

        self.instrument_map = dict(zip(df['tradingsymbol'], df['instrument_token']))
        self.logger.info(f"Loaded {len(self.instrument_map)} instruments.")

    def get_token(self, symbol):
        clean_symbol = symbol.replace('.NS', '').replace('.BO', '')
        return self.instrument_map.get(clean_symbol)

    def fetch_data(self, tickers):
        self.logger.info("Initializing Kite data fetch process...")
        market_data = {}
        
        if not self.kite:
            self.logger.error("Kite Client not initialized. Cannot fetch data.")
            return {}

        today = pd.Timestamp.now().normalize()

        for ticker in tickers:
            try:
                last_date = self.db_manager.get_latest_date(ticker)
                
                if last_date:
                     start_date = last_date + pd.Timedelta(days=1)
                     # Standardize timezone to avoid comparison errors
                     if pd.to_datetime(start_date).tz_localize(None) > pd.to_datetime(today).tz_localize(None):
                         market_data[ticker] = self.db_manager.load_market_data(ticker)
                         continue
                else:
                    start_date = today - pd.Timedelta(days=365)

                token = self.get_token(ticker)
                if not token:
                    self.logger.warning(f"Could not find token for {ticker}")
                    continue

                self.logger.info(f"Fetching data for {ticker} (Token: {token}) from {start_date.date()}...")
                
                records = self.kite.historical_data(token, start_date, today, "day")
                with open(f"{ticker}.txt", 'w') as f:
                    f.write(str(records))
                if not records:
                    self.logger.warning(f"No data returned for {ticker}")
                    continue
                    
                df_new = pd.DataFrame(records)
                df_new.set_index('date', inplace=True)
                df_new.index = pd.to_datetime(df_new.index).tz_localize(None) 
                
                rename_map = {
                    'open': 'Open', 'high': 'High', 'low': 'Low', 
                    'close': 'Close', 'volume': 'Volume'
                }
                df_new.rename(columns=rename_map, inplace=True)
                df_new = df_new[rename_map.values()] 
                
                self.db_manager.save_market_data(ticker, df_new)
                full_df = self.db_manager.load_market_data(ticker)
                market_data[ticker] = full_df
                
            except Exception as e:
                self.logger.error(f"Error fetching data for {ticker}: {e}")

        self.logger.info(f"Loaded {len(market_data)} tickers for analysis.")
        return market_data
