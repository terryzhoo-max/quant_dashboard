import pandas as pd
import tushare as ts
from backtest_engine import AlphaBacktester
import os

# Set token
ts.set_token('8766a56e0f214f440536735166240032c10b1a03e1e916ea05634509')
pro = ts.pro_api()

def debug():
    print("--- Debugging Tushare Data Fetch for 510300.SH ---")
    bt = AlphaBacktester()
    
    # Try fetching data directly
    try:
        df = bt.fetch_tushare_data('510300.SH', '20230101', '20231231', adj='qfq')
        print(f"Fetch success. Rows: {len(df)}")
        if len(df) > 0:
            print(df.head())
        else:
            print("!!! Dataframe is empty")
            
        # Check fund_basic to see if 510300.SH exists
        basic = pro.fund_basic(ts_code='510300.SH')
        print(f"Fund Basic for 510300.SH:\n{basic}")
        
        # Check if daily data exists
        daily = pro.fund_daily(ts_code='510300.SH', start_date='20230101', end_date='20230110')
        print(f"Daily Sample (10 days):\n{daily}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug()
