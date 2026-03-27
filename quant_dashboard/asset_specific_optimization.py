
import pandas as pd
import numpy as np
import time
import tushare as ts
import itertools
from backtest_engine import AlphaBacktester, Indicators

# Re-init Tushare
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

def run_specific_optimization():
    print(">>> [ALPHACORE ASSET-SPECIFIC OPTIMIZATION] Period: 2021-01-01 to 2025-12-31")
    bt = AlphaBacktester(initial_cash=1000000)
    
    assets = [
        {"code": "588000.SH", "name": "科创50ETF"},
        {"code": "159949.SZ", "name": "创业板50ETF"},
        {"code": "510300.SH", "name": "沪深300ETF"}
    ]
    
    rsi_periods = [7, 14, 21]
    buy_thresholds = [10, 15, 20, 25]
    ma_periods = [120, 200, 250]
    sell_thresholds = [80, 90]
    
    ranges = [
        ("20210101", "20211231"), 
        ("20220101", "20221231"), 
        ("20230101", "20231231"), 
        ("20240101", "20241231"), 
        ("20250101", "20251231")
    ]

    final_results = []

    for asset in assets:
        code = asset["code"]
        name = asset["name"]
        print(f"\n[Optimizing] {name} ({code})...")
        
        # 1. Fetch Data
        data_frames = []
        for start, end in ranges:
            df_part = pro.fund_daily(ts_code=code, start_date=start, end_date=end)
            if df_part is not None: data_frames.append(df_part)
            time.sleep(0.5)
        
        df = pd.concat(data_frames).sort_values("trade_date").reset_index(drop=True)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index('trade_date', inplace=True)
        df = df.rename(columns={'vol': 'volume'})
        target_data = df.loc["2021-01-01":"2025-12-31"]

        # 2. Grid Search for this Asset
        asset_sweep = []
        combinations = list(itertools.product(rsi_periods, buy_thresholds, ma_periods, sell_thresholds))
        
        for rp, rb, mp, st in combinations:
            # Logic
            close = target_data['close']
            rsi = Indicators.RSI(close, period=rp)
            ma_trend = close.rolling(mp).mean()
            boll = Indicators.BOLL(close, period=20)
            pb = boll['percent_b']
            
            signals = pd.Series(0, index=target_data.index)
            buy_cond = (close >= ma_trend * 0.90) & ((pb < 0) | (rsi < rb))
            sell_cond = (pb > 1.0) | (rsi > st)
            
            pos = 0
            for i in range(len(target_data)):
                if buy_cond.iloc[i]: pos = 1
                elif sell_cond.iloc[i]: pos = 0
                signals.iloc[i] = pos
            
            res = bt.run_vectorized(target_data, signals, ts_code=code)
            m = res['metrics']
            asset_sweep.append({
                "rsi_p": rp, "buy_t": rb, "ma_p": mp, "sell_t": st,
                "return": m['total_return'],
                "mdd": m['max_drawdown'],
                "sharpe": m['sharpe_ratio']
            })

        # Find best for this asset (Prioritize Sharpe, then Return)
        asset_sweep.sort(key=lambda x: x['sharpe'], reverse=True)
        best = asset_sweep[0]
        
        # Benchmark for comparison
        bench_m = bt.run_vectorized(target_data, pd.Series(1, index=target_data.index))['metrics']
        
        final_results.append({
            "name": name,
            "code": code,
            "best_params": f"RSI({best['rsi_p']}), B={best['buy_t']}, MA={best['ma_p']}, S={best['sell_t']}",
            "return": best['return'],
            "bench_return": bench_m['total_return'],
            "mdd": best['mdd'],
            "bench_mdd": bench_m['max_drawdown'],
            "sharpe": best['sharpe'],
            "alpha": (best['return'] - bench_m['total_return'])
        })

    # 3. Final Report
    print("\n" + "="*110)
    print("      ALPHACORE ASSET-SPECIFIC OPTIMIZATION: 2021 - 2025 MASTER KEY")
    print("="*110)
    print(f"{'ETF NAME':<15} | {'WINNING CONFIG':<30} | {'RETURN':>10} | {'ALPHA':>10} | {'MDD':>10} | {'SHARPE':>10}")
    print("-" * 110)
    for r in final_results:
        print(f"{r['name']:<15} | {r['best_params']:<30} | {r['return']*100:>9.2f}% | {r['alpha']*100:>9.2f}% | {r['mdd']*100:>9.2f}% | {r['sharpe']:>10.2f}")
    print("="*110)

if __name__ == "__main__":
    run_specific_optimization()
