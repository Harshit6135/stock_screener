import pandas as pd
import requests
import io

class NSEDataSource:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def get_nifty500_tickers(self):
        print("Setting up the stealth connection...")
        try:
            print("Visiting NSE Homepage to get cookies...")
            self.session.get("https://www.nseindia.com")

            print("Downloading Nifty 500 list...")
            nifty500_url = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
            response = self.session.get(nifty500_url)

            if response.status_code == 200:
                df_nifty = pd.read_csv(io.StringIO(response.text))
                tickers = [symbol for symbol in df_nifty['Symbol']]
                print(f"Success! Downloaded {len(tickers)} stocks.")
                print(f"Sample: {tickers[:5]}")
                return tickers
            else:
                print(f"Failed with status code: {response.status_code}")
                raise Exception("NSE blocked the request.")
        except Exception as e:
            print(f"Error: {e}")
            print("Falling back to Mini-List.")
            return [
                "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
                "TCS.NS", "ITC.NS", "LT.NS", "SBIN.NS",
                "BHARTIARTL.NS", "TATAMOTORS.NS"
            ]
