# -*- coding: utf-8 -*-
"""Verify the 3 fixes in market_temp.py"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import tushare as ts
from config import TUSHARE_TOKEN
pro = ts.pro_api(TUSHARE_TOKEN)

from dashboard_modules.market_temp import (
    get_margin_risk_ratio, get_real_turnover_score, get_ah_premium_adj
)
from datetime import datetime

date_str = datetime.now().strftime('%Y%m%d')
print(f"Test date: {date_str}")
print("=" * 60)

print("\n[1] Margin (should return tuple, with fallback)")
score, deg = get_margin_risk_ratio(pro, date_str)
print(f"  Result: score={score}, degraded={deg}")

print("\n[2] Turnover (should use daily_basic, with fallback)")
score, deg = get_real_turnover_score(pro, date_str)
print(f"  Result: score={score}, degraded={deg}")

print("\n[3] AH Premium (should use 399330.SZ + percentile)")
adj, deg = get_ah_premium_adj(pro, date_str)
print(f"  Result: adj={adj}, degraded={deg}")

print("\n" + "=" * 60)
print("All 3 sub-modules tested. If degraded=False for all, fix is verified.")
