
import pandas as pd
import numpy as np
import time
import tushare as ts
from backtest_engine import AlphaBacktester, Indicators

# Re-init Tushare
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

def run_multi_asset_audit():
    print(">>> [ALPHACORE MULTI-ASSET AUDIT] Period: 2021-01-01 to 2025-12-31")
    bt = AlphaBacktester(initial_cash=1000000)
    
    assets = [
        {"code": "588000.SH", "name": "科创50ETF"},
        {"code": "159949.SZ", "name": "创业板50ETF"},
        {"code": "510300.SH", "name": "沪深300ETF"}
    ]
    
    # Global Parameters (Robust Config)
    RSI_P = 7
    RSI_B = 10
    MA_P = 250
    RSI_S = 85

    ranges = [
        ("20210101", "20211231"), 
        ("20220101", "20221231"), 
        ("20230101", "20231231"), 
        ("20240101", "20241231"), 
        ("20250101", "20251231")
    ]

    results = []

    for asset in assets:
        code = asset["code"]
        name = asset["name"]
        print(f"\n[Asset Audit] {name} ({code})...")
        
        # 1. Fetch Data
        data_frames = []
        for start, end in ranges:
            df_part = pro.fund_daily(ts_code=code, start_date=start, end_date=end)
            if df_part is not None: data_frames.append(df_part)
            time.sleep(0.5)
        
        if not data_frames:
            print(f"  !!! ERROR: Fetch failed for {name}")
            continue

        df = pd.concat(data_frames).sort_values("trade_date").reset_index(drop=True)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index('trade_date', inplace=True)
        df = df.rename(columns={'vol': 'volume'})
        target_data = df.loc["2021-01-01":"2025-12-31"]

        # 2. Strategy Logic
        def mr_logic(data):
            close = data['close']
            rsi = Indicators.RSI(close, period=RSI_P)
            ma_trend = close.rolling(MA_P).mean()
            boll = Indicators.BOLL(close, period=20)
            pb = boll['percent_b']
            
            signals = pd.Series(0, index=data.index)
            # Strategy: RSI(21), B=10, S=95, MA=200
            buy_cond = (close >= ma_trend * 0.90) & ((pb < 0) | (rsi < RSI_B))
            sell_cond = (pb > 1.0) | (rsi > RSI_S)
            
            pos = 0
            for i in range(len(data)):
                if buy_cond.iloc[i]: pos = 1
                elif sell_cond.iloc[i]: pos = 0
                signals.iloc[i] = pos
            return signals

        sigs = mr_logic(target_data)
        res = bt.run_vectorized(target_data, sigs, ts_code=code)
        
        m = res['metrics']
        bm = res['bench_metrics']
        
        results.append({
            "name": name,
            "code": code,
            "return": m['total_return'],
            "bench_return": bm['total_return'],
            "mdd": m['max_drawdown'],
            "bench_mdd": bm['max_drawdown'],
            "sharpe": m['sharpe_ratio'],
            "alpha": (m['total_return'] - bm['total_return'])
        })

    # 3. Comparative Report
    print("\n" + "="*95)
    print("      ALPHACORE MULTI-ASSET RIGOROUS AUDIT: 2021 - 2025")
    print("      CONFIG: RSI(21) | B=10 | S=95 | MA=200")
    print("="*95)
    print(f"{'ETF NAME':<15} | {'RETURN':>10} | {'BENCH':>10} | {'ALPHA':>10} | {'MDD':>10} | {'SHARPE':>10}")
    print("-" * 95)
    for r in results:
        print(f"{r['name']:<15} | {r['return']*100:>9.2f}% | {r['bench_return']*100:>9.2f}% | {r['alpha']*100:>9.2f}% | {r['mdd']*100:>9.2f}% | {r['sharpe']:>10.2f}")
    print("="*95)

if __name__ == "__main__":
    run_multi_asset_audit()
