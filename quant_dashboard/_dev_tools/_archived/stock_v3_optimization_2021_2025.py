
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

def run_stock_optimization():
    print(">>> [ALPHACORE STOCK V3.0 OPTIMIZATION] Period: 2021-01-01 to 2025-12-31")
    bt = AlphaBacktester(initial_cash=1000000)
    
    # Mix of stocks and ETF
    assets = [
        {"code": "688981.SH", "name": "中芯国际", "type": "stock"},
        {"code": "300059.SZ", "name": "东方财富", "type": "stock"},
        {"code": "688041.SH", "name": "海光信息", "type": "stock"},
        {"code": "002851.SZ", "name": "麦格米特", "type": "stock"},
        {"code": "512480.SH", "name": "芯片ETF", "type": "fund"}
    ]
    
    # V3 Search Parameters (Aggressive for Stocks)
    rsi_p_list = [7, 14]
    bp_list = [10, 20]
    bt_list = [-5, -8, -12] 
    vm_list = [1.2, 1.5, 2.0]
    mp_list = [120, 200]

    final_results = []

    for asset in assets:
        code = asset["code"]
        name = asset["name"]
        a_type = asset["type"]
        print(f"\n[Audit] {name} ({code})...")
        
        # 1. Fetch Data using pro_bar (Robust for QFQ)
        try:
            # pro_bar for stocks, fund_daily with manual adj for funds if needed
            # but usually pro_bar(asset_type='E') or 'FD' works
            asset_type = 'E' if a_type == 'stock' else 'FD'
            df = ts.pro_bar(ts_code=code, adj='qfq', asset=asset_type, start_date="20200601", end_date="20251231")
            
            if df is None or df.empty:
                print(f"  !!! ERROR: Fetch failed for {name}")
                continue

            df = df.sort_values("trade_date").reset_index(drop=True)
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df.set_index('trade_date', inplace=True)
            df = df.rename(columns={'vol': 'volume'})
            target_data = df.loc["2021-01-01":"2025-12-31"]
            if target_data.empty: print(f"  > Warning: Empty data in target range."); continue
            
            print(f"  > Data Points: {len(target_data)} (Starts {target_data.index[0].date()})")

            # 2. Optimization Loop
            close = target_data['close']
            vol = target_data['volume']
            vol_ma5 = vol.rolling(5).mean()
            
            combinations = list(itertools.product(rsi_p_list, bp_list, bt_list, vm_list, mp_list))
            asset_sweep = []
            
            for rp, bp, btv, vm, mp in combinations:
                rsi = Indicators.RSI(close, period=rp)
                bias = Indicators.BIAS(close, period=bp)
                ma_trend = close.rolling(mp).mean()
                boll = Indicators.BOLL(close, period=20)
                pb = boll['percent_b']
                
                signals = pd.Series(0, index=target_data.index)
                
                # V3.0 Rule: Multi-Factor Climax
                # Increased buffer to 0.95 for stocks (faster trend adoption)
                buy_cond = (close >= ma_trend * 0.95) & (rsi < 30) & (bias < btv) & (vol > vol_ma5 * vm)
                sell_cond = (pb > 1.0) | (rsi > 80)
                
                pos = 0
                for i in range(len(target_data)):
                    if buy_cond.iloc[i]: pos = 1
                    elif sell_cond.iloc[i]: pos = 0
                    signals.iloc[i] = pos
                
                res = bt.run_vectorized(target_data, signals, ts_code=code)
                m = res['metrics']
                asset_sweep.append({
                    "params": f"RSI({rp}), BIAS({bp})<{btv}, VOL>{vm}x, MA={mp}",
                    "sharpe": m['sharpe_ratio'],
                    "return": m['total_return'],
                    "mdd": m['max_drawdown']
                })
            
            asset_sweep.sort(key=lambda x: x['sharpe'], reverse=True)
            best = asset_sweep[0]
            
            bench_m = bt.run_vectorized(target_data, pd.Series(1, index=target_data.index))['metrics']
            
            final_results.append({
                "name": name,
                "code": code,
                "best": best,
                "bench_ret": bench_m['total_return'],
                "alpha": (best['return'] - bench_m['total_return'])
            })
            time.sleep(1) # API Cooling

        except Exception as e:
            print(f"  !!! CRITICAL ERROR for {name}: {e}")

    # 3. Report
    print("\n" + "="*125)
    print("      ALPHACORE STOCK-LEVEL V3.0 RIGOROUS AUDIT: 2021 - 2025")
    print("="*125)
    print(f"{'STOCK/ETF NAME':<18} | {'WINNING CONFIG (V3.0)':<40} | {'RETURN':>10} | {'ALPHA':>10} | {'MDD':>10}")
    print("-" * 125)
    for r in final_results:
        b = r['best']
        print(f"{r['name']:<18} | {b['params']:<40} | {b['return']*100:>9.2f}% | {r['alpha']*100:>9.2f}% | {b['mdd']*100:>9.2f}%")
    print("="*125)

if __name__ == "__main__":
    run_stock_optimization()
