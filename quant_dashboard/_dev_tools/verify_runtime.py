import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import json, urllib.request

urls = [
    ("erp-timing",     "http://127.0.0.1:8000/api/v1/strategy/erp-timing"),
    ("aiae/report",    "http://127.0.0.1:8000/api/v1/aiae/report"),
    ("audit",          "http://127.0.0.1:8000/api/v1/audit"),
    ("decision/hub",   "http://127.0.0.1:8000/api/v1/decision/hub"),
    ("strategy(MR)",   "http://127.0.0.1:8000/api/v1/strategy"),
    ("portfolio",      "http://127.0.0.1:8000/api/v1/portfolio/overview"),
    ("stock/name",     "http://127.0.0.1:8000/api/v1/stock/name?ts_code=510300.SH"),
    ("strategy/rates", "http://127.0.0.1:8000/api/v1/strategy/rates"),
    ("market/regime",  "http://127.0.0.1:8000/api/v1/market/regime"),
]

print("=" * 50)
print("AlphaCore API Runtime Verification")
print("=" * 50)

ok_count = 0
fail_count = 0

for name, url in urls:
    try:
        resp = urllib.request.urlopen(url, timeout=15)
        data = json.loads(resp.read())
        status = data.get("status", "??")
        ok_count += 1
        print(f"  ✅ {name:20s} -> {status}")
    except Exception as e:
        fail_count += 1
        print(f"  ❌ {name:20s} -> ERROR: {e}")

print("=" * 50)
print(f"Results: {ok_count} passed / {fail_count} failed")
