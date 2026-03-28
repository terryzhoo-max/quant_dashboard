import tushare as ts
import pandas as pd
from datetime import datetime, timedelta

ts.set_token("5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6")
pro = ts.pro_api()
today_str = datetime.now().strftime('%Y%m%d')
start_str = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d')

print("--- Margin (Financing) ---")
# margin_detail for SSE/SZSE
try:
    df_margin = pro.margin_detail(trade_date=today_str)
    print(df_margin.head())
except:
    print("No margin data for today yet.")

print("\n--- AH Premium ---")
try:
    df_ah = pro.index_daily(ts_code='HSAHP.HI', start_date=start_str, end_date=today_str)
    print(df_ah.head())
except:
    print("No AH Premium data.")

print("\n--- HK Daily (Short Sell) ---")
try:
    # Check if hk_daily has short sell info
    df_hk = pro.hk_daily(ts_code='0700.HK', start_date=start_str, end_date=today_str)
    print(df_hk.columns)
except:
    print("No HK Daily columns found.")
