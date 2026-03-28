import requests, json, sys
sys.stdout.reconfigure(encoding='utf-8')

r = requests.get('http://127.0.0.1:8000/api/v1/dividend_strategy?regime=BEAR', timeout=120)
data = r.json()
sigs = data.get('data', {}).get('signals', [])
print('信号数量:', len(sigs))
for s in sigs:
    score = s.get('signal_score')
    print(f"  [{s['code']}] {s['name']}: signal_score={score} signal={s['signal']} RSI={s['rsi']} TTM={s['ttm_yield']} boll_pos={s['boll_pos']}")
