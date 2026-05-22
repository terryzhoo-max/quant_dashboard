"""检查现有标的池中每只ETF的数据起始日期"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.momentum_backtest_engine import MOMENTUM_POOL_V2, BENCHMARK_CODE, FactorDataManager

dm = FactorDataManager()

print("%-14s %-20s %-10s %-12s %-12s %s" % ("Code", "Name", "Group", "First Date", "Last Date", "Years"))
print("-" * 90)

all_codes = [etf["code"] for etf in MOMENTUM_POOL_V2] + [BENCHMARK_CODE, "000300.SH"]
name_map = {etf["code"]: etf["name"] for etf in MOMENTUM_POOL_V2}
name_map[BENCHMARK_CODE] = "沪深300ETF"
name_map["000300.SH"] = "沪深300指数"
group_map = {etf["code"]: etf["group"] for etf in MOMENTUM_POOL_V2}

qualified = []

for code in all_codes:
    try:
        df = dm.get_price_payload(code)
        if df.empty:
            print("%-14s %-20s NO DATA" % (code, name_map.get(code, "?")))
            continue
        dates = df["trade_date"]
        first = str(dates.min())[:10]
        last = str(dates.max())[:10]
        from datetime import datetime
        d1 = datetime.strptime(first, "%Y-%m-%d")
        d2 = datetime.strptime(last, "%Y-%m-%d")
        years = (d2 - d1).days / 365.25
        marker = " *** 8Y+" if years >= 8 else ""
        print("%-14s %-20s %-10s %-12s %-12s %.1f%s" % (
            code, name_map.get(code, "?"), group_map.get(code, "-"), first, last, years, marker))
        if years >= 8 and code not in [BENCHMARK_CODE, "000300.SH"]:
            qualified.append(code)
    except Exception as e:
        print("%-14s ERROR: %s" % (code, e))

print()
print("=" * 60)
print("  QUALIFIED (8Y+ data): %d ETFs" % len(qualified))
print("=" * 60)
for code in qualified:
    print("  %s  %s  [%s]" % (code, name_map.get(code), group_map.get(code)))
