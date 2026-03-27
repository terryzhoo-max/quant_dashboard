
import pandas as pd
import numpy as np
import time
import tushare as ts
import itertools
from backtest_engine import AlphaBacktester, Indicators

TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

def run_extreme_audit():
    print(">>> [ALPHACORE EXTREME ALPHA] Period: 2021-01-01 to 2025-12-31")
    bt = AlphaBacktester(initial_cash=1000000, benchmark_code="000300.SH")
    ts_code = "510300.SH"
    
    # 1. Fetch High-Fidelity Data (Chunked)
    data_frames = []
    ranges = [
        ("20210101", "20211231"), 
        ("20220101", "20221231"), 
        ("20230101", "20231231"), 
        ("20240101", "20241231"), 
        ("20250101", "20251231")
    ]
    for start, end in ranges:
        df_part = pro.fund_daily(ts_code=ts_code, start_date=start, end_date=end)
        if df_part is not None: data_frames.append(df_part)
        time.sleep(0.5)
    
    df = pd.concat(data_frames).sort_values("trade_date").reset_index(drop=True)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df.set_index('trade_date', inplace=True)
    df = df.rename(columns={'vol': 'volume'})
    target_data = df.loc["2021-01-01":"2025-12-31"]

    # 2. Logic & Core Search Loop
    def mr_logic(data, rsi_p, buy_t, ma_p, sell_t=85):
        close = data['close']
        rsi = Indicators.RSI(close, period=rsi_p)
        ma_trend = close.rolling(ma_p).mean()
        boll = Indicators.BOLL(close, period=20)
        pb = boll['percent_b']
        
        signals = pd.Series(0, index=data.index)
        buy_cond = (close >= ma_trend * 0.92) & ((pb < 0) | (rsi < buy_t))
        sell_cond = (pb > 1.0) | (rsi > sell_t)
        
        pos = 0
        for i in range(len(data)):
            if buy_cond.iloc[i]: pos = 1
            elif sell_cond.iloc[i]: pos = 0
            signals.iloc[i] = pos
        return signals

    # Expanded Grid
    rsi_p_list = [2, 3, 7, 14, 21]
    buy_t_list = [10, 15, 20, 25]
    ma_p_list = [120, 200, 250]
    sell_t_list = [75, 85, 95]
    
    results = []
    combos = list(itertools.product(rsi_p_list, buy_t_list, ma_p_list, sell_t_list))
    total = len(combos)
    print(f"[Grid Search] Testing {total} combinations...")

    for i, (rp, rb, mp, st) in enumerate(combos):
        if (i+1) % 50 == 0: print(f"  Progress: {i+1}/{total}...")
        sigs = mr_logic(target_data, rp, rb, mp, st)
        m = bt.run_vectorized(target_data, sigs)['metrics']
        results.append({
            "label": f"RSI({rp}), B={rb}, MA={mp}, S={st}",
            "metrics": m
        })

    # Benchmark metrics
    bench_m = bt.run_vectorized(target_data, pd.Series(1, index=target_data.index))['metrics']
    bench_ret = bench_m['total_return']
    
    # Sort by Alpha
    results.sort(key=lambda x: (x['metrics']['total_return'] - bench_ret), reverse=True)

    # 3. Report
    print("\n" + "="*85)
    print("      ALPHACORE EXTREME ALPHA REPORT: 2021 - 2025")
    print("="*85)
    print(f"BENCHMARK (000300.SH) RETURN: {bench_ret*100:>10.2f}% | MDD: {bench_m['max_drawdown']*100:.2f}%")
    print("-" * 85)
    print(f"{'STRATEGY (TOP PEFORMERS)':<30} | {'RETURN':>10} | {'MDD':>10} | {'SHARPE':>10} | {'ALPHA':>10}")
    print("-" * 85)
    for res in results[:10]:
        m = res['metrics']
        alpha = (m['total_return'] - bench_ret) * 100
        print(f"{res['label']:<30} | {m['total_return']*100:>9.2f}% | {m['max_drawdown']*100:>9.2f}% | {m['sharpe_ratio']:>10.2f} | {alpha:>9.2f}%")
    print("="*85)

if __name__ == "__main__":
    run_extreme_audit()
