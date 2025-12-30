from datetime import date, timedelta
import requests

base_url = "http://127.0.0.1:5000"
start_date = date(2023, 1, 1)
end_date = date(2025, 1, 1)
#end_date = date.today()
delta = timedelta(days=1)

date_str = start_date.strftime("%Y-%m-%d")
print(f"processing for {date_str}")
# requests.post(f"{base_url}/api/v1/marketdata/update_all/historical")
print(f"Processing Completed")
requests.post(f"{base_url}/api/v1/ranking/update_all")
print(f"Processing Completed")