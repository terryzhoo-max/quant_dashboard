import tushare as ts
import pandas as pd

ts.set_token("5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6")
pro = ts.pro_api()

ts_code = "510300.SH"
start_date = "20230101"
end_date = "20240101"

print(f"Fetching fund_daily for {ts_code} from {start_date} to {end_date}...")
df = pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
if df is not None and not df.empty:
    print(f"SUCCESS: Result count: {len(df)}")
    print(df.head())
else:
    print("DataFrame is empty.")
