"""Debug southbound API responses."""
import requests
import json

# 1. 检查实时南向原始数据
print("=== RT S2N Raw ===")
url = "https://push2.eastmoney.com/api/qt/kamt.rtmin/get?fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
data = r.json().get("data", {})
s2n = data.get("s2n", [])
print(f"Total entries: {len(s2n)}")
# Show last 5 entries
for entry in s2n[-5:]:
    print(f"  {entry}")
# Show first valid entry from end
for entry in reversed(s2n):
    parts = entry.split(",")
    if len(parts) >= 4 and parts[3] not in ("-", "", None):
        print(f"Last valid: {entry}")
        print(f"  Parts: {parts}")
        break

print()
# 2. 试探东财datacenter API - 不带filter
print("=== Trying DataCenter API (no filter) ===")
url2 = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
        "reportName=RPT_MUTUAL_MARKET_STA"
        "&columns=ALL"
        "&pageNumber=1&pageSize=5&sortColumns=TRADE_DATE&sortTypes=-1")
r2 = requests.get(url2, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
resp2 = r2.json()
code = resp2.get("code")
msg = resp2.get("message", "")[:100]
print(f"Code: {code}")
print(f"Message: {msg}")
result = resp2.get("result") or {}
items = result.get("data") or []
if items:
    print(f"Got {len(items)} items")
    for item in items[:3]:
        print(f"  Keys: {list(item.keys())}")
        print(f"  Sample: {json.dumps(item, default=str, ensure_ascii=False)[:300]}")
else:
    print("No data returned")

print()
# 3. 试不同的报表名
print("=== Trying different report names ===")
reports = [
    "RPT_HMUTUAL_DEAL_HISTORY",
    "RPT_MUTUAL_DEAL_HISTORY", 
    "RPT_MUTUAL_QUOTA",
    "RPT_HMUTUAL_DEAL_SUMSTA",
]
for rpt in reports:
    url3 = (f"https://datacenter-web.eastmoney.com/api/data/v1/get?"
            f"reportName={rpt}"
            "&columns=ALL"
            "&pageNumber=1&pageSize=3&sortColumns=TRADE_DATE&sortTypes=-1")
    try:
        r3 = requests.get(url3, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp3 = r3.json()
        c = resp3.get("code")
        result3 = resp3.get("result") or {}
        items3 = result3.get("data") or []
        if items3:
            print(f"[OK] {rpt}: code={c}, {len(items3)} items")
            for item in items3[:1]:
                print(f"  Keys: {list(item.keys())}")
                print(f"  Data: {json.dumps(item, default=str, ensure_ascii=False)[:400]}")
        else:
            m3 = resp3.get("message", "")[:80]
            print(f"[--] {rpt}: code={c}, msg={m3}")
    except Exception as e:
        print(f"[!!] {rpt}: {e}")

print()
# 4. 尝试另一组 push2 API - 沪深港通历史数据
print("=== Trying push2 HSGT history ===")
url4 = "https://push2his.eastmoney.com/api/qt/kamt.kline/get?fields1=f1,f3,f5&fields2=f51,f52,f53,f54,f55,f56&klt=101&lmt=10"
try:
    r4 = requests.get(url4, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    resp4 = r4.json()
    data4 = resp4.get("data", {})
    if data4:
        print(f"Keys: {list(data4.keys())}")
        # s2n = southbound daily history
        s2n_hist = data4.get("s2n", [])
        n2s_hist = data4.get("n2s", [])
        print(f"S2N history entries: {len(s2n_hist)}")
        print(f"N2S history entries: {len(n2s_hist)}")
        for entry in s2n_hist[-5:]:
            print(f"  S2N: {entry}")
    else:
        print(f"No data. Response keys: {list(resp4.keys())}")
except Exception as e:
    print(f"Error: {e}")
