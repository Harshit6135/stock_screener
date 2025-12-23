import requests
import pandas as pd
from datetime import date, timedelta
from router.backtesting_ranking_router import backtest_calculate_score

BASE_URL = "http://127.0.0.1:5000"

# p_resp = requests.get(f"{BASE_URL}/market_data/{symbol}/{end_date}")
# p_data = p_resp.json()
# print(p_data)
#
# p_resp = requests.get(f"{BASE_URL}/indicators/{symbol}/{end_date}")
# p_data = p_resp.json()
# print(p_data)

start_date = date(2025, 12, 10)
end_date = date.today()
delta = timedelta(days=1)

while start_date <= end_date:
    date_str = start_date.strftime("%Y-%m-%d")
    print(f"processing for {date_str}")
    backtest_calculate_score(date_str)
    start_date += delta
