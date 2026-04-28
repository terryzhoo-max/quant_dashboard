"""south_money 单位确认"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tushare as ts
import pandas as pd
from datetime import datetime, timedelta

pro = ts.pro_api()
today = datetime.now().strftime('%Y%m%d')
start = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')

df = pro.moneyflow_hsgt(start_date=start, end_date=today, limit=500)
for col in ['south_money', 'north_money', 'hgt', 'sgt', 'ggt_ss', 'ggt_sz']:
    df[col] = pd.to_numeric(df[col], errors='coerce')
df = df.sort_values('trade_date')

print("south_money 最新10日:")
print(df[['trade_date', 'south_money', 'ggt_ss', 'ggt_sz']].tail(10).to_string(index=False))

print(f"\n描述统计:")
print(df['south_money'].describe())

# Tushare 官方文档: south_money 单位 = 百万元(人民币)
# 验证: 南向日均成交 200-600 亿 HKD, 净买入 10-50 亿 RMB 较常见
# 如果是百万: 53718 百万 = 537 亿 → 这是成交额不是净买入
# ggt_ss = 港股通(沪), ggt_sz = 港股通(深), 单位百万
# south_money = ggt_ss + ggt_sz

latest = df.tail(1).iloc[0]
print(f"\n最新日: {latest['trade_date']}")
print(f"  south_money = {latest['south_money']:.2f}")
print(f"  ggt_ss + ggt_sz = {latest['ggt_ss'] + latest['ggt_sz']:.2f}")
print(f"  如果单位=百万RMB: {latest['south_money']/100:.1f} 亿 (成交额)")
print(f"  ggt_ss(沪港通南) = {latest['ggt_ss']:.2f} ({latest['ggt_ss']/100:.1f}亿)")
print(f"  ggt_sz(深港通南) = {latest['ggt_sz']:.2f} ({latest['ggt_sz']/100:.1f}亿)")

# 查 Tushare 文档: 这些是 "当日成交净买额"
# south_money = 南向合计(沪+深), 单位百万, 是 net buy (净买入)
# 但 53718百万 = 537亿, 南向单日净买入537亿? 有点大...
# 可能是 "累计成交额" 而非 "净买入"
# 让我们看变化量
print(f"\n近5日 south_money 变化:")
recent = df.tail(5)
for _, row in recent.iterrows():
    print(f"  {row['trade_date']}: {row['south_money']:.2f} (百万)")

diffs = recent['south_money'].diff()
print(f"\n日变化量:")
for i, (_, row) in enumerate(recent.iterrows()):
    d = diffs.iloc[i]
    if pd.notna(d):
        print(f"  {row['trade_date']}: delta={d:.2f}百万 = {d/100:.2f}亿")
