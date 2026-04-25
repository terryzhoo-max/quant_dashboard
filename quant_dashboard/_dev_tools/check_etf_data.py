import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core_etf_config import CORE_ETF_CODES

# DATA_DIR in data_manager.py is "data_lake"
DAILY_PRICE_DIR = "data_lake/daily_prices"
etf_list = CORE_ETF_CODES

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
