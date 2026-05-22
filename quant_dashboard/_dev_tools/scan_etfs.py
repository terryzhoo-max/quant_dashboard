"""扫描data_lake中所有ETF，找出8年以上数据的行业ETF"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from pathlib import Path
from datetime import datetime

data_dir = Path("data_lake/daily_prices")
etf_prefixes = ["51", "15", "58", "56"]  # ETF code prefixes

results = []
for f in sorted(data_dir.glob("*.parquet")):
    code = f.stem
    if code.startswith("gem_"):
        continue
    # Only ETF-like codes
    is_etf = any(code.startswith(p) for p in etf_prefixes)
    if not is_etf:
        continue
    try:
        df = pd.read_parquet(f)
        if "trade_date" not in df.columns or "close" not in df.columns:
            continue
        dates = pd.to_datetime(df["trade_date"])
        first = dates.min()
        last = dates.max()
        years = (last - first).days / 365.25
        n_rows = len(df)
        results.append({
            "code": code,
            "first": str(first.date()),
            "last": str(last.date()),
            "years": round(years, 1),
            "rows": n_rows,
        })
    except Exception as e:
        pass

results.sort(key=lambda x: x["years"], reverse=True)

print("=" * 80)
print("  ALL ETFs IN DATA LAKE (sorted by data length)")
print("=" * 80)
print("%-14s %-12s %-12s %6s %6s" % ("Code", "First", "Last", "Years", "Rows"))
print("-" * 60)

qualified = []
for r in results:
    marker = " *** 8Y+" if r["years"] >= 8 else ""
    print("%-14s %-12s %-12s %6.1f %6d%s" % (
        r["code"], r["first"], r["last"], r["years"], r["rows"], marker))
    if r["years"] >= 8:
        qualified.append(r["code"])

print()
print("=" * 60)
print("  8Y+ ETFs: %d" % len(qualified))
print("=" * 60)
for code in qualified:
    print("  %s" % code)
