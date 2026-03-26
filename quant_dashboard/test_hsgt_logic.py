import tushare as ts
import pandas as pd
from datetime import datetime

TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TOKEN)
pro = ts.pro_api()

def test_hsgt():
    today_str = datetime.now().strftime('%Y%m%d')
    print(f"Testing HSGT logic for {today_str}...")
    
    try:
        df_hsgt = pro.moneyflow_hsgt(start_date='20250101', end_date=today_str, limit=30)
        if df_hsgt is not None and not df_hsgt.empty:
            df_hsgt_sorted = df_hsgt.sort_values('trade_date', ascending=True)
            df_hsgt_sorted['cum_5d'] = df_hsgt_sorted['north_money'].rolling(window=5).sum()
            
            latest_5d_val = float(df_hsgt_sorted['cum_5d'].iloc[-1])
            history_5d = df_hsgt_sorted['cum_5d'].dropna().tail(20)
            mean_5d = history_5d.mean()
            std_5d = history_5d.std() if history_5d.std() > 0 else 1.0
            
            hsgt_z = (latest_5d_val - mean_5d) / std_5d
            
            print(f"Latest 5D Cumulative: {latest_5d_val/10000.0:.2f} 亿")
            print(f"Mean 5D: {mean_5d/10000.0:.2f} 亿")
            print(f"Std 5D: {std_5d/10000.0:.2f} 亿")
            print(f"Z-Score: {hsgt_z:.2f}")
            
            liquidity_score = max(0, min(100, 50 + hsgt_z * 25))
            print(f"Liquidity Score: {liquidity_score:.2f}")
        else:
            print("No HSGT data found")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_hsgt()
