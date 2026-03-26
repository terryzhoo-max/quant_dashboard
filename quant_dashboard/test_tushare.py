import tushare as ts
import pandas as pd

TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TOKEN)
pro = ts.pro_api()

print("Testing moneyflow_hsgt...")
try:
    # 尝试最基础的调用
    df = pro.moneyflow_hsgt(start_date='20240101', end_date='20260321', limit=10)
    print("Result (HSGT):")
    if df is not None:
        print(df.head())
    else:
        print("DF is None")
except Exception as e:
    print(f"Error (HSGT): {e}")

print("\nTesting daily_basic...")
try:
    df = pro.daily_basic(ts_code='', trade_date='20250101', limit=5)
    print("Result (Daily Basic):")
    if df is not None:
        print(df.head())
    else:
        print("DF is None")
except Exception as e:
    print(f"Error (Daily Basic): {e}")
