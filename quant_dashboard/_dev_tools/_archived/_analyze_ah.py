# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import numpy as np
import tushare as ts
from config import TUSHARE_TOKEN

pro = ts.pro_api(TUSHARE_TOKEN)
df = pro.index_daily(ts_code='H50066.CSI', start_date='20240101', end_date='20260415')
df = df.sort_values('trade_date')
vals = df['close'].values

print("H50066.CSI (中证沪港AH溢价) Statistics:")
print(f"  Period: {df.iloc[0]['trade_date']} to {df.iloc[-1]['trade_date']}")
print(f"  Rows: {len(df)}")
print(f"  Min: {min(vals):.2f}")
print(f"  Max: {max(vals):.2f}")
print(f"  Mean: {np.mean(vals):.2f}")
print(f"  Median: {np.median(vals):.2f}")
print(f"  P25: {np.percentile(vals,25):.2f}")
print(f"  P75: {np.percentile(vals,75):.2f}")
print(f"  Latest: {vals[-1]:.2f}")
print()

# Real HSAHP from xueqiu: 119.51 today
# H50066.CSI: 129.37 today
# Difference: ~10 points
# HSAHP base=100 (Dec 2006), H50066 base=100 (different base date?)
# They measure AH premium differently

print("Key comparison:")
print(f"  HSAHP (real, from xueqiu): 119.51")
print(f"  H50066.CSI (tushare):      {vals[-1]:.2f}")
print(f"  Difference:                {vals[-1] - 119.51:.2f}")
print()
print("Conclusion: H50066.CSI is NOT the same as HSAHP.")
print("H50066 has a higher baseline but tracks similar trends.")
print("Need to calibrate thresholds for H50066 specifically.")
print()
print("For HSAHP (real): neutral=125-145, today=119.51 -> H-share attractive")
print("For H50066.CSI: need proportional thresholds")

# Calculate proportional thresholds
# HSAHP 119.51 -> below 125 -> adj=0.85
# H50066 129.37 -> what should the equivalent threshold be?
ratio = vals[-1] / 119.51
print(f"\nRatio H50066/HSAHP = {ratio:.4f}")
print(f"Proportional thresholds for H50066:")
print(f"  Low: 125 * {ratio:.4f} = {125 * ratio:.1f}")
print(f"  High: 145 * {ratio:.4f} = {145 * ratio:.1f}")
