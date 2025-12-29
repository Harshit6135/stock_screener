from datetime import date, timedelta
import requests

base_url = "http://127.0.0.1:5000"
start_date = date(2023, 1, 1)
end_date = date(2025, 1, 1)
#end_date = date.today()
delta = timedelta(days=1)

while start_date <= end_date:
    if start_date.weekday() < 5:  # 0=Monday, ..., 4=Friday, 5=Saturday, 6=Sunday
        date_str = start_date.strftime("%Y-%m-%d")
        print(f"processing for {date_str}")
        requests.post(f"{base_url}/api/v1/ranking/update/{date_str}")
        print(f"Processing Completed")
    start_date += delta