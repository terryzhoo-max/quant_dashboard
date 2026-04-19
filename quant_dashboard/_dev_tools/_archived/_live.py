import json
from mean_reversion_engine import run_strategy as mr_run
from dividend_trend_engine import run_dividend_strategy as div_run
from momentum_rotation_engine import run_momentum_strategy as mom_run

def main():
    print("Fetching Mean Reversion...")
    mr_results = mr_run()
    
    print("Fetching Dividend Trend...")
    div_results = div_run()
    
    print("Fetching Momentum Rotation...")
    mom_results = mom_run()
    
    # Extract buys
    mr_buys = [r for r in mr_results if r.get('signal') == 'buy']
    div_buys = [r for r in div_results.get('data', {}).get('signals', []) if r.get('signal') == 'buy']
    mom_buys = mom_results.get('buy_signals', [])
    
    print("\n\n" + "="*50)
    print("🔥 LIVE STRATEGY SIGNALS 🔥")
    print("="*50)
    
    print("\n[1] 均值回归 (Mean Reversion) - BUY SIGNALS:")
    for b in mr_buys[:5]:
        print(f"  - {b['name']} ({b['ts_code']}): Score={b['signal_score']}, RSI={b['rsi']}, BIAS={b['bias']}%")
        
    print("\n[2] 红利防线 (Dividend Trend) - BUY SIGNALS:")
    for b in div_buys[:5]:
        print(f"  - {b['name']} ({b['code']}): Yield={b['ttm_yield']}%, Score={b['signal_score']}, Pos={b['suggested_position']}%")
        
    print("\n[3] 动量轮动 (Momentum Rotation) - BUY SIGNALS:")
    for b in mom_buys[:5]:
        print(f"  - {b['name']} ({b['ts_code']}): MOM_S={b['momentum_pct']}%, Score={b['momentum_score']}, Pos={b['suggested_position']}%")
        
    print("="*50)

if __name__ == '__main__':
    main()
