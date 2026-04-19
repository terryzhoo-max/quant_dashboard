# -*- coding: utf-8 -*-
"""Search for the real AH Premium index in tushare"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import tushare as ts
from config import TUSHARE_TOKEN
pro = ts.pro_api(TUSHARE_TOKEN)

# 1. Check what 399330.SZ actually is
print("=== What is 399330.SZ? ===")
for market in ['MSCI', 'CSI', 'CICC', 'SSE', 'SZSE', 'SW', 'OTH']:
    try:
        df = pro.index_basic(market=market)
        match = df[df['ts_code'] == '399330.SZ']
        if not match.empty:
            print(f"  Found in {market}:")
            print(match[['ts_code', 'name', 'publisher', 'category']].to_string())
    except:
        pass

# 2. Search for real AH premium index across all markets
print("\n=== Searching for AH Premium / AH溢价 index ===")
for market in ['MSCI', 'CSI', 'CICC', 'SSE', 'SZSE', 'SW', 'OTH', 'HI']:
    try:
        df = pro.index_basic(market=market)
        for kw in ['溢价', 'AH股', 'A+H', 'HSAHP']:
            matches = df[df['name'].str.contains(kw, na=False, case=False)]
            if not matches.empty:
                print(f"\n  [{market}] keyword='{kw}':")
                print(matches[['ts_code', 'name', 'publisher']].to_string())
        # also check ts_code containing HSAHP
        matches2 = df[df['ts_code'].str.contains('HSAHP', na=False)]
        if not matches2.empty:
            print(f"\n  [{market}] ts_code contains 'HSAHP':")
            print(matches2[['ts_code', 'name']].to_string())
    except Exception as e:
        print(f"  [{market}] error: {e}")

# 3. Try direct API call for known candidates
print("\n=== Direct API test for candidate codes ===")
candidates = [
    'HSAHP.HI',      # original (dead)
    '399330.SZ',      # what we used (need to verify identity)
    'HSCAHP.HI',     # variant
    '000300.SH',      # CSI300 for reference
]
for code in candidates:
    try:
        df = pro.index_daily(ts_code=code, start_date='20260401', end_date='20260415')
        rows = len(df) if df is not None else 0
        last_close = df.sort_values('trade_date').iloc[-1]['close'] if rows > 0 else 'N/A'
        print(f"  {code}: {rows} rows, last_close={last_close}")
    except Exception as e:
        print(f"  {code}: ERROR - {str(e)[:60]}")
