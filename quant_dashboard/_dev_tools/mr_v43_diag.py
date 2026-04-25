import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd

d = 'data_lake/daily_prices'
code = '510300.SH'
fp = os.path.join(d, f'{code}.parquet')
df = pd.read_parquet(fp)
df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str).str[:8], format='%Y%m%d')

bear_train = df[(df['trade_date'] >= '2022-01-01') & (df['trade_date'] <= '2022-09-30')]
print(f'510300 BEAR train: {len(bear_train)} days')
print(f'510300 date range: {df.trade_date.min().date()} ~ {df.trade_date.max().date()}')

with open('mr_per_regime_params.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print('\n--- New optimized params ---')
for r, v in data.get('regimes', {}).items():
    p = v.get('params', {})
    t = v.get('train_kpi', {})
    va = v.get('valid_kpi', {})
    sl = p.get('stop_loss', 'N/A')
    tc = t.get('coverage', 'N/A')
    vc = va.get('coverage', 'N/A')
    cs = v.get('combined_score', 'N/A')
    ta = t.get('alpha', 'N/A')
    vaa = va.get('alpha', 'N/A')
    print(f'  {r}: SL={sl}, train_cov={tc}%, valid_cov={vc}%, train_alpha={ta}%, valid_alpha={vaa}%, score={cs}')
