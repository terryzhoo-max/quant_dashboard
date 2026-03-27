import pandas as pd
import os

# DATA_DIR in data_manager.py is "data_lake"
DAILY_PRICE_DIR = "data_lake/daily_prices"
etf_list = ["512760.SH", "512720.SH", "515030.SH", "512010.SH", "512690.SH", 
            "512880.SH", "512800.SH", "512660.SH", "512100.SH", "512400.SH", 
            "510180.SH", "159915.SZ"]

print(f"Checking directory: {DAILY_PRICE_DIR}")
if not os.path.exists(DAILY_PRICE_DIR):
    print(f"DIRECTORY NOT FOUND: {DAILY_PRICE_DIR}")
else:
    for code in etf_list:
        path = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
        if os.path.exists(path):
            try:
                df = pd.read_parquet(path)
                print(f"{code}: {len(df)} rows, last date: {df['trade_date'].max()}")
            except Exception as e:
                print(f"{code}: ERROR READING: {e}")
        else:
            print(f"{code}: NOT FOUND")
