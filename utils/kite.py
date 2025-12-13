import pandas as pd
from kiteconnect import KiteConnect
import os
import webbrowser
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
import time

class KiteService:
    def __init__(self, config, logger):
        self.config = config
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
