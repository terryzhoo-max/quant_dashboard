
import pandas as pd
import numpy as np
import time
import tushare as ts
from backtest_engine import AlphaBacktester, Indicators

# Re-init Tushare
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

def run_5year_audit():
    print(">>> [ALPHACORE 5-YEAR AUDIT] Period: 2021-01-01 to 2025-12-31")
    
    bt = AlphaBacktester(initial_cash=1000000, benchmark_code="000300.SH")
    
    # 1. Fetch High-Fidelity Data (Chunked)
    ts_code = "510300.SH"
    try:
        data_frames = []
        ranges = [
            ("20210101", "20211231"), 
            ("20220101", "20221231"), 
            ("20230101", "20231231"), 
            ("20240101", "20241231"), 
            ("20250101", "20251231")
        ]
        for start, end in ranges:
            print(f"  > Fetching {start} to {end}...")
            df_part = pro.fund_daily(ts_code=ts_code, start_date=start, end_date=end)
            if df_part is not None and not df_part.empty:
                data_frames.append(df_part)
            time.sleep(1)

        if not data_frames:
            print("!!! ERROR: Failed to fetch any data.")
            return

        df = pd.concat(data_frames)
        df = df.sort_values("trade_date").reset_index(drop=True)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index('trade_date', inplace=True)
        df = df.rename(columns={'vol': 'volume'})
        print(f"  [SUCCESS] Total data points: {len(df)}")
    except Exception as e:
        print(f"!!! Error syncing data: {e}")
        return

    # 2. Logic & Grid Search
    def mr_logic(data, rsi_p=20, buy_t=25, ma_p=200):
        close = data['close']
        rsi = Indicators.RSI(close, period=rsi_p)
        ma_trend = close.rolling(ma_p).mean()
        boll = Indicators.BOLL(close, period=20)
        pb = boll['percent_b']
        
        signals = pd.Series(0, index=data.index)
        buy_cond = (close >= ma_trend * 0.90) & ((pb < 0) | (rsi < buy_t))
        sell_cond = (pb > 1.0) | (rsi > 85)
        
        pos = 0
        for i in range(len(data)):
            if buy_cond.iloc[i]: pos = 1
            elif sell_cond.iloc[i]: pos = 0
            signals.iloc[i] = pos
        return signals

    target_data = df.loc["2021-01-01":"2025-12-31"]

    # --- Baseline Test (Winning Config from 2023-2025) ---
    sig_baseline = mr_logic(target_data, rsi_p=20, buy_t=25, ma_p=200)
    res_baseline = bt.run_vectorized(target_data, sig_baseline)
    
    # --- Quick Grid Search for 5-Year Horizon ---
    print("\n>>> [5-Year Optimization] Testing robustness...")
    import itertools
    rsi_p_list = [14, 20]
    buy_t_list = [20, 30]
    ma_p_list = [120, 200]
    
    sweep = []
    for rp, rb, mp in itertools.product(rsi_p_list, buy_t_list, ma_p_list):
        sigs = mr_logic(target_data, rsi_p=rp, buy_t=rb, ma_p=mp)
        m = bt.run_vectorized(target_data, sigs)['metrics']
        sweep.append({"label": f"RSI({rp}), B={rb}, MA={mp}", "metrics": m})
    
    sweep.sort(key=lambda x: x['metrics']['sharpe_ratio'], reverse=True)

    # 3. Report
    bm = res_baseline['bench_metrics']
    print("\n" + "="*80)
    print("      ALPHACORE 5-YEAR RIGOROUS AUDIT: 2021 - 2025")
    print("="*80)
    print(f"BENCHMARK (000300.SH) RETURN: {bm['total_return']*100:>10.2f}% | MDD: {bm['max_drawdown']*100:.2f}%")
    print("-" * 80)
    print(f"{'STRATEGY (TOP PEFORMERS)':<25} | {'RETURN':>10} | {'MDD':>10} | {'SHARPE':>10} | {'ALPHA':>10}")
    print("-" * 80)
    for res in sweep[:5]:
        m = res['metrics']
        alpha = (m['total_return'] - bm['total_return']) * 100
        print(f"{res['label']:<25} | {m['total_return']*100:>9.2f}% | {m['max_drawdown']*100:>9.2f}% | {m['sharpe_ratio']:>10.2f} | {alpha:>9.2f}%")
    print("="*80)

if __name__ == "__main__":
    run_5year_audit()
