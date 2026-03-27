import sys, traceback
sys.stdout.reconfigure(encoding='utf-8')

from dividend_trend_engine import (
    REGIME_PARAMS, DIVIDEND_POOL, fetch_etf_data_by_code, 
    calculate_indicators, score_etf, generate_signal
)

regime = "BEAR"
p = REGIME_PARAMS[regime]

print(f"BEAR params: ma_trend={p['ma_trend']}, min data required={max(p['ma_trend'], 100)}")

etf_data = fetch_etf_data_by_code(days=150)

for item in DIVIDEND_POOL:
    code = item['code']
    df = etf_data.get(code)
    if df is None:
        print(f"  [{code}] NO DATA")
        continue
    required = max(p['ma_trend'], 100)
    print(f"  [{code}] rows={len(df)}, required={required}, PASS={len(df) >= required}", end="")
    if len(df) >= required:
        try:
            ind = calculate_indicators(df, code, p)
            score = score_etf(ind, regime, p)
            sig, pos = generate_signal(ind, item['weight'], p, regime)
            print(f" | score={score} signal={sig} RSI={ind['rsi']} BIAS={ind['bias']:.2f}")
        except Exception as e:
            print(f" | ERROR: {e}")
            traceback.print_exc()
    else:
        print(" | SKIPPED - insufficient data")
