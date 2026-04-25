import sys, os
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd

d = 'data_lake/daily_prices'
fp = os.path.join(d, '510300.SH.parquet')
df = pd.read_parquet(fp)
df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str).str[:8], format='%Y%m%d')
df = df.sort_values('trade_date')

close = df.set_index('trade_date')['close']
ma120 = close.rolling(120).mean()
below = close[close < ma120]

print(f'Total days below MA120: {len(below)}')
if len(below) > 0:
    for y in [2023, 2024, 2025, 2026]:
        sub = below[below.index.year == y]
        if len(sub) > 0:
            print(f'  {y}: {len(sub)} days ({sub.index[0].date()} ~ {sub.index[-1].date()})')

# Also check what 2023 H2 looks like (potential bear/range)
h2_2023 = close['2023-07-01':'2023-12-31']
ma120_h2 = ma120['2023-07-01':'2023-12-31']
pct_below = (h2_2023 < ma120_h2).sum() / len(h2_2023) * 100
print(f'\n2023 H2 below MA120: {pct_below:.0f}% of days')

# Suggest new BEAR period
print('\n--- Suggested BEAR training period ---')
print('Use 2023-07-01 ~ 2024-01-31 (CSI300 -20% drawdown, mostly below MA120)')
print('Valid: 2024-02-01 ~ 2024-04-30 (transition period)')
