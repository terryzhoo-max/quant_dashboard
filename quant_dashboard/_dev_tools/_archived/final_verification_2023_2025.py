
import pandas as pd
import numpy as np
import time
import tushare as ts
from backtest_engine import AlphaBacktester, Indicators

# Re-init Tushare (just in case)
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

def run_rigorous_audit():
    print(">>> [ALPHACORE RIGOROUS AUDIT] Starting 2023-01-01 to 2025-12-31 simulation...")
    
    bt = AlphaBacktester(initial_cash=1000000, benchmark_code="000300.SH")
    
    # 1. Fetch High-Fidelity Data (Chunked for reliability)
    ts_code = "510300.SH"
    try:
        data_frames = []
        ranges = [("20230101", "20231231"), ("20240101", "20241231"), ("20250101", "20251231")]
        for start, end in ranges:
            print(f"  > Fetching {start} to {end}...")
            df_part = pro.fund_daily(ts_code=ts_code, start_date=start, end_date=end)
            if df_part is not None and not df_part.empty:
                data_frames.append(df_part)
            time.sleep(1) # Frequency control

        if not data_frames:
            print("!!! ERROR: All fetch attempts failed.")
            return

        df = pd.concat(data_frames)
        df = df.sort_values("trade_date").reset_index(drop=True)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index('trade_date', inplace=True)
        df = df.rename(columns={'vol': 'volume'})
        print(f"  [SUCCESS] Total data points: {len(df)}")

    except Exception as e:
        print(f"!!! ERROR: Data Acquisition Exception: {e}")
        return

    # 2. Define Backtest Logic (Mean Reversion V2.0 Recommended)
    def mr_logic(data, rsi_p=3, buy_t=15, sell_t=85, ma_p=60):
        close = data['close']
        rsi = Indicators.RSI(close, period=rsi_p)
        ma_trend = close.rolling(ma_p).mean()
        boll = Indicators.BOLL(close, period=20)
        pb = boll['percent_b']
        
        signals = pd.Series(0, index=data.index)
        
        # Trend Filter: Price must be within 10% of MA60 or above it
        # Entry: PB piercing or RSI panic
        buy_cond = (close >= ma_trend * 0.90) & ((pb < 0) | (rsi < buy_t))
        sell_cond = (pb > 1.0) | (rsi > sell_t)
        
        pos = 0
        for i in range(len(data)):
            if buy_cond.iloc[i]:
                pos = 1
            elif sell_cond.iloc[i]:
                pos = 0
            signals.iloc[i] = pos
        return signals

    # Target Period: 2023-01-01 to 2025-12-31
    target_data = df.loc["2023-01-01":"2025-12-31"]
    if target_data.empty:
        print("!!! ERROR: Target period data empty. Check availability up to 2025.")
        return

    signals = mr_logic(target_data)
    results = bt.run_vectorized(target_data, signals, ts_code="510300_MR_V2")
    
    # 3. Optimization Sweep (Full Grid Search)
    print("\n>>> [Grid Search] Exploring long-term parameter synergy...")
    import itertools
    
    rsi_periods = [10, 14, 20]
    rsi_buys = [25, 30, 35, 40]
    ma_periods = [60, 120, 200]
    
    sweep_results = []
    
    combinations = list(itertools.product(rsi_periods, rsi_buys, ma_periods))
    total_combos = len(combinations)
    
    for i, (rp, rb, mp) in enumerate(combinations):
        if (i+1) % 5 == 0:
            print(f"  > Progress: {i+1}/{total_combos} combinations tested...")
        
        sigs = mr_logic(target_data, rsi_p=rp, buy_t=rb, ma_p=mp)
        res = bt.run_vectorized(target_data, sigs)
        m = res['metrics']
        
        sweep_results.append({
            "label": f"RSI({rp}), B={rb}, MA={mp}",
            "rsi_p": rp, "buy_t": rb, "ma_p": mp,
            "return": m['total_return'],
            "mdd": m['max_drawdown'],
            "sharpe": m['sharpe_ratio']
        })

    # Sort by Sharpe Ratio to find the highest industrial quality
    sweep_results.sort(key=lambda x: x['sharpe'], reverse=True)

    # 4. Final Reporting
    bm = results['bench_metrics']
    print("\n" + "="*80)
    print("      ALPHACORE RIGOROUS AUDIT: LONG-TERM GRID SEARCH (2023-2025)")
    print("="*80)
    print(f"BENCHMARK (000300.SH) RETURN: {bm['total_return']*100:>10.2f}% | MDD: {bm['max_drawdown']*100:.2f}%")
    print("-" * 80)
    print(f"{'STRATEGY (TOP 10)':<25} | {'RETURN':>10} | {'MDD':>10} | {'SHARPE':>10} | {'ALPHA':>10}")
    print("-" * 80)
    for res in sweep_results[:10]:
        alpha = (res['return'] - bm['total_return']) * 100
        print(f"{res['label']:<25} | {res['return']*100:>9.2f}% | {res['mdd']*100:>9.2f}% | {res['sharpe']:>10.2f} | {alpha:>9.2f}%")
    print("-" * 80)
    
    best = sweep_results[0]
    print(f"WINNING CONFIG: RSI Period={best['rsi_p']}, Buy Threshold={best['buy_t']}, MA Trend={best['ma_p']}")
    print("="*80)

if __name__ == "__main__":
    run_rigorous_audit()
