"""Quick check ERP Timing response structure"""
import requests, json
r = requests.get("http://localhost:8000/api/v1/strategy/erp-timing", timeout=60)
d = r.json()
print("=== ERP Timing top keys ===")
for k, v in d.items():
    if isinstance(v, dict):
        print(f"  {k}: dict → {list(v.keys())[:10]}")
    elif isinstance(v, list):
        print(f"  {k}: list({len(v)})")
    else:
        print(f"  {k}: {v}")
