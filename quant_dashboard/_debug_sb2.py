"""Debug southbound - deeper analysis."""
import requests
import json

# 1. RPT_MUTUAL_DEAL_HISTORY - 查看所有MUTUAL_TYPE区分南北向
print("=== RPT_MUTUAL_DEAL_HISTORY - All Types ===")
url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
       "reportName=RPT_MUTUAL_DEAL_HISTORY"
       "&columns=MUTUAL_TYPE,TRADE_DATE,FUND_INFLOW,QUOTA_BALANCE,INDEX_CLOSE_PRICE,INDEX_CHANGE_RATE,DEAL_AMT"
       "&pageNumber=1&pageSize=20&sortColumns=TRADE_DATE&sortTypes=-1")
r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
resp = r.json()
result = resp.get("result") or {}
items = result.get("data") or []
print(f"Total: {len(items)} rows")
# Group by MUTUAL_TYPE
types = {}
for item in items:
    mt = item.get("MUTUAL_TYPE", "?")
    if mt not in types:
        types[mt] = []
    types[mt].append(item)

for mt, entries in types.items():
    print(f"\n  MUTUAL_TYPE={mt}:")
    for e in entries[:3]:
        date = str(e.get("TRADE_DATE", ""))[:10]
        inflow = e.get("FUND_INFLOW") or 0
        quota = e.get("QUOTA_BALANCE") or 0
        deal = e.get("DEAL_AMT") or 0
        print(f"    {date}: inflow={inflow}, quota={quota}, deal={deal}")

# 2. 南向过滤 (003=港股通沪, 004=港股通深)
print("\n=== Southbound only (003 + 004) ===")
for mt_code in ["003", "004"]:
    url2 = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
            "reportName=RPT_MUTUAL_DEAL_HISTORY"
            "&columns=MUTUAL_TYPE,TRADE_DATE,FUND_INFLOW,QUOTA_BALANCE,DEAL_AMT"
            f"&filter=(MUTUAL_TYPE=%22{mt_code}%22)"
            "&pageNumber=1&pageSize=10&sortColumns=TRADE_DATE&sortTypes=-1")
    r2 = requests.get(url2, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    resp2 = r2.json()
    result2 = resp2.get("result") or {}
    items2 = result2.get("data") or []
    print(f"\n  Type {mt_code}: {len(items2)} rows")
    for e in items2[:5]:
        date = str(e.get("TRADE_DATE", ""))[:10]
        inflow = e.get("FUND_INFLOW") or 0
        print(f"    {date}: inflow={inflow:.2f}")

# 3. push2 历史 - 确认单位
print("\n=== push2 HSGT history (S2N) ===")
url3 = "https://push2his.eastmoney.com/api/qt/kamt.kline/get?fields1=f1,f3,f5&fields2=f51,f52,f53,f54,f55,f56&klt=101&lmt=20"
r3 = requests.get(url3, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
data3 = r3.json().get("data", {})
s2n = data3.get("s2n", [])
print(f"Total S2N entries: {len(s2n)}")
print("Format: date,net_buy,quota_balance,cumulative")
total_5d = 0
total_10d = 0
count = 0
for entry in s2n[-20:]:
    parts = entry.split(",")
    date = parts[0]
    net_buy = float(parts[1])
    quota = float(parts[2])
    accum = float(parts[3]) if len(parts) > 3 else 0
    # Net buy in 万元
    net_billion = net_buy / 10000  # 万 -> 亿
    print(f"  {date}: net={net_billion:+.2f}亿, quota={quota/10000:.0f}亿, accum={accum/10000:.0f}亿")
    if net_buy != 0:
        count += 1
        total_10d += net_billion
        if count <= 5:
            total_5d += net_billion

print(f"\n  5d total: {total_5d:+.2f}亿")
print(f"  10d total: {total_10d:+.2f}亿")
print(f"  Trading days with activity: {count}")
