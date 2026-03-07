import os
import threading
import webbrowser
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict, Any

from kiteconnect import KiteConnect, KiteTicker
from http.server import BaseHTTPRequestHandler, HTTPServer


class KiteAdaptor:
    """
    Kite Connect API adaptor for stock market data.
    
    Handles authentication, session management, and data fetching
    for NSE/BSE market data via Zerodha Kite Connect API.
    """
    
    def __init__(self, config: Dict[str, str], logger: Any) -> None:
        """
        Initialize Kite adaptor with credentials.
        
        Parameters:
            config (Dict[str, str]): API configuration with keys:
                - api_key: Kite Connect API key
                - api_secret: Kite Connect API secret
                - redirect_url: OAuth callback URL
            logger: Logger instance for logging
        """
        self.api_key = config['api_key']
        self.api_secret = config['api_secret']
        self.redirect_url = config['redirect_url']
        self.logger = logger
        self.kite: Optional[KiteConnect] = None
        self.instrument_map: Dict[int, str] = {}
        self.request_token: Optional[str] = None
        
        # --- Live Ticker State ---
        self.kws: Optional[KiteTicker] = None
        self.live_prices: Dict[int, Dict] = {}  # {token: {last_price, prev_close, change, symbol}}
        self._ticker_lock = threading.Lock()
        self._ticker_running = False
        
        self._initialize_kite()

    def _initialize_kite(self):
        try:
            if self.api_key == "YOUR_API_KEY":
                self.logger.warning("Kite API Key not set in config.")
                return

            self.kite = KiteConnect(api_key=self.api_key)
            self._ensure_session()
            self.logger.info("Kite Connect initialized.")            
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
        parsed_url = urllib.parse.urlparse(self.redirect_url)
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
                data = self.kite.generate_session(self.request_token, api_secret=self.api_secret)
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

    def fetch_ticker_data(self, ticker: int, start_date: datetime, 
                          end_date: Optional[datetime] = None) -> Optional[List[Dict]]:
        """
        Fetch historical OHLCV data for a ticker.
        
        Parameters:
            ticker (int): Instrument token from Kite
            start_date (datetime): Start date for data
            end_date (Optional[datetime]): End date, defaults to now
        
        Returns:
            Optional[List[Dict]]: OHLCV records, or None if fetch fails
        
        Raises:
            Exception: If API call fails (logged, returns None)
        
        Example:
            >>> data = adaptor.fetch_ticker_data(738561, datetime(2024, 1, 1))
        """
        try:
            if not end_date:
                end_date = datetime.now()
            records = self.kite.historical_data(ticker, start_date, end_date, interval="day")
            
            if not records:
                self.logger.warning(f"No data returned for {ticker}")
                return None
            
            return records

        except Exception as e:
            self.logger.error(f"Failed to fetch/process data for {ticker}: {e}")
            return None

    def get_instruments(self, exchange: Optional[str] = None) -> Optional[List[Dict]]:
        """
        Get list of tradable instruments from Kite.
        
        Parameters:
            exchange (Optional[str]): Specific exchange (NSE/BSE) or None for all
        
        Returns:
            Optional[List[Dict]]: Instrument data, or None if fetch fails
        
        Example:
            >>> instruments = adaptor.get_instruments("NSE")
        """
        try:
            if exchange:
                instruments = self.kite.instruments(exchange)
            else:
                instruments = self.kite.instruments()
            return instruments
        except Exception as e:
            self.logger.error(f"Failed to fetch instruments: {e}")
            return None

    # ----------------------------------------------------------------
    # Live Ticker (WebSocket) Methods
    # ----------------------------------------------------------------

    def get_access_token(self) -> Optional[str]:
        """Read the persisted access token."""
        token_file = "access_token.txt"
        if os.path.exists(token_file):
            with open(token_file, "r") as f:
                return f.read().strip()
        return None

    def fetch_ohlc(self, exchange_symbols: List[str]) -> Dict[str, Dict]:
        """
        Fetch OHLC + LTP for a list of instruments via Kite REST API.
        
        Parameters:
            exchange_symbols: List like ["NSE:RELIANCE", "NSE:TCS"]
        
        Returns:
            Dict keyed by exchange:symbol with {last_price, ohlc: {open, high, low, close}, instrument_token}
        """
        if not self.kite:
            self.logger.warning("Kite client not initialised, cannot fetch OHLC")
            return {}
        try:
            data = self.kite.ohlc(exchange_symbols)
            return data
        except Exception as e:
            self.logger.error(f"Failed to fetch OHLC: {e}")
            return {}

    def start_ticker(self, token_symbol_map: Dict[int, str]) -> bool:
        """
        Start KiteTicker WebSocket for live price streaming.
        
        Parameters:
            token_symbol_map: {instrument_token: symbol} for current holdings
        
        Returns:
            True if started successfully
        """
        if self._ticker_running:
            self.logger.info("Ticker already running, updating subscriptions")
            self._update_subscriptions(token_symbol_map)
            return True

        access_token = self.get_access_token()
        if not access_token or not self.api_key:
            self.logger.error("Cannot start ticker: missing api_key or access_token")
            return False

        try:
            self.kws = KiteTicker(self.api_key, access_token)
            self.instrument_map = token_symbol_map

            # Initialize prev_close slots (will be populated by fetch_ohlc before starting)
            with self._ticker_lock:
                for token, symbol in token_symbol_map.items():
                    if token not in self.live_prices:
                        self.live_prices[token] = {
                            'symbol': symbol,
                            'last_price': 0,
                            'prev_close': 0,
                            'change': 0
                        }

            tokens = list(token_symbol_map.keys())

            def on_ticks(ws, ticks):
                with self._ticker_lock:
                    for tick in ticks:
                        t = tick['instrument_token']
                        ltp = tick.get('last_price', 0)
                        if t in self.live_prices:
                            prev = self.live_prices[t].get('prev_close', 0)
                            self.live_prices[t]['last_price'] = ltp
                            self.live_prices[t]['change'] = (
                                ((ltp - prev) / prev * 100) if prev else 0
                            )

            def on_connect(ws, response):
                self.logger.info(f"KiteTicker connected. Subscribing to {len(tokens)} tokens.")
                ws.subscribe(tokens)
                ws.set_mode(ws.MODE_LTP, tokens)

            def on_close(ws, code, reason):
                self.logger.warning(f"KiteTicker closed: {code} - {reason}")

            def on_error(ws, code, reason):
                self.logger.error(f"KiteTicker error: {code} - {reason}")

            def on_reconnect(ws, attempts):
                self.logger.info(f"KiteTicker reconnecting, attempt {attempts}")

            self.kws.on_ticks = on_ticks
            self.kws.on_connect = on_connect
            self.kws.on_close = on_close
            self.kws.on_error = on_error
            self.kws.on_reconnect = on_reconnect

            # Run in background daemon thread
            self.kws.connect(threaded=True)
            self._ticker_running = True
            self.logger.info("KiteTicker started in background thread.")
            return True

        except Exception as e:
            self.logger.error(f"Failed to start KiteTicker: {e}")
            return False

    def _update_subscriptions(self, token_symbol_map: Dict[int, str]):
        """Update subscriptions on an already-running ticker."""
        if not self.kws or not self._ticker_running:
            return
        
        old_tokens = set(self.instrument_map.keys())
        new_tokens = set(token_symbol_map.keys())
        
        to_unsub = old_tokens - new_tokens
        to_sub = new_tokens - old_tokens
        
        if to_unsub:
            self.kws.unsubscribe(list(to_unsub))
        if to_sub:
            self.kws.subscribe(list(to_sub))
            self.kws.set_mode(self.kws.MODE_LTP, list(to_sub))
        
        self.instrument_map = token_symbol_map
        with self._ticker_lock:
            # Remove old, add new
            for t in to_unsub:
                self.live_prices.pop(t, None)
            for t in to_sub:
                self.live_prices[t] = {
                    'symbol': token_symbol_map[t],
                    'last_price': 0,
                    'prev_close': 0,
                    'change': 0
                }

    def stop_ticker(self):
        """Stop the KiteTicker WebSocket."""
        if self.kws and self._ticker_running:
            try:
                self.kws.close()
            except Exception as e:
                self.logger.warning(f"Error closing ticker: {e}")
            self._ticker_running = False
            self.logger.info("KiteTicker stopped.")

    def get_live_prices(self) -> Dict[str, Dict]:
        """
        Return current live prices snapshot keyed by symbol.
        
        Returns:
            {"RELIANCE": {"last_price": 2400, "prev_close": 2380, "change": 0.84}, ...}
        """
        with self._ticker_lock:
            result = {}
            for token, data in self.live_prices.items():
                symbol = data.get('symbol', str(token))
                result[symbol] = {
                    'last_price': data.get('last_price', 0),
                    'prev_close': data.get('prev_close', 0),
                    'change': round(data.get('change', 0), 2),
                    'instrument_token': token
                }
            return result

    def is_ticker_running(self) -> bool:
        """Check if ticker is currently active."""
        return self._ticker_running