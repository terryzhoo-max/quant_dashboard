
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

def run_v3_optimization():
    print(">>> [ALPHACORE STRATEGY V3.0 OPTIMIZATION] Period: 2021-01-01 to 2025-12-31")
    bt = AlphaBacktester(initial_cash=1000000)
    
    assets = [
        {"code": "588000.SH", "name": "科创50ETF"},
        {"code": "159949.SZ", "name": "创业板50ETF"},
        {"code": "510300.SH", "name": "沪深300ETF"}
    ]
    
    # V3 Grid Search Parameters
    rsi_periods = [7, 14]
    bias_periods = [10, 20]
    bias_thresholds = [-3, -5, -8]
    vol_multipliers = [1.0, 1.2, 1.5]
    ma_periods = [200, 250]
    
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
        print(f"\n[V3.0 Optimizing] {name} ({code})...")
        
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

        # 2. Grid Search for V3.0 logic
        asset_sweep = []
        combinations = list(itertools.product(rsi_periods, bias_periods, bias_thresholds, vol_multipliers, ma_periods))
        
        # Pre-calc Indicators
        close = target_data['close']
        vol = target_data['volume']
        vol_ma5 = vol.rolling(5).mean()
        
        for rp, bp, bt_val, vm, mp in combinations:
            # Logic V3.0
            rsi = Indicators.RSI(close, period=rp)
            bias = Indicators.BIAS(close, period=bp)
            ma_trend = close.rolling(mp).mean()
            boll = Indicators.BOLL(close, period=20)
            pb = boll['percent_b']
            
            signals = pd.Series(0, index=target_data.index)
            
            # Entry: RSI Oversold + Bias Stretch + Volume Climax + Trend Logic
            buy_cond = (close >= ma_trend * 0.90) & (rsi < 30) & (bias < bt_val) & (vol > vol_ma5 * vm)
            sell_cond = (pb > 1.0) | (rsi > 80)
            
            pos = 0
            for i in range(len(target_data)):
                if buy_cond.iloc[i]: pos = 1
                elif sell_cond.iloc[i]: pos = 0
                signals.iloc[i] = pos
            
            res = bt.run_vectorized(target_data, signals, ts_code=code)
            m = res['metrics']
            asset_sweep.append({
                "params": f"RSI({rp}), BIAS({bp})<{bt_val}, VOL>{vm}x, MA={mp}",
                "rp": rp, "bp": bp, "bt": bt_val, "vm": vm, "mp": mp,
                "return": m['total_return'],
                "mdd": m['max_drawdown'],
                "sharpe": m['sharpe_ratio']
            })

        # Find best V3.0
        asset_sweep.sort(key=lambda x: x['sharpe'], reverse=True)
        best = asset_sweep[0]
        
        # Compare with previous V2 best (simplified)
        bench_m = bt.run_vectorized(target_data, pd.Series(1, index=target_data.index))['metrics']
        
        final_results.append({
            "name": name,
            "best_v3": best,
            "bench_return": bench_m['total_return'],
            "alpha": (best['return'] - bench_m['total_return'])
        })

    # 3. Report
    print("\n" + "="*120)
    print("      ALPHACORE STRATEGY V3.0 PERFORMANCE REPORT: 2021 - 2025")
    print("="*120)
    print(f"{'ETF NAME':<15} | {'V3.0 WINNING CONFIG':<35} | {'RETURN':>10} | {'ALPHA':>10} | {'MDD':>10}")
    print("-" * 120)
    for r in final_results:
        b = r['best_v3']
        print(f"{r['name']:<15} | {b['params']:<35} | {b['return']*100:>9.2f}% | {r['alpha']*100:>9.2f}% | {b['mdd']*100:>9.2f}%")
    print("="*120)

if __name__ == "__main__":
    run_v3_optimization()
