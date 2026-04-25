"""Batch 7 Architecture Decoupling Verification"""
import requests

BASE = "http://127.0.0.1:8000"
API_KEY = "NIT-EUnmt7eLpG5F6cWY8JpvF2EM1OKrlhNaLRbLCDi6DfOLik51E63ZdQ0PqdGz"

tests_passed = 0
tests_total = 0

def check(name, condition, detail=""):
    global tests_passed, tests_total
    tests_total += 1
    result = "PASS" if condition else "FAIL"
    if condition:
        tests_passed += 1
    print(f"  [{result}] {name} {detail}")

print("=== Batch 7 Architecture Verification ===\n")

# 1. Health check
r = requests.get(f"{BASE}/health")
d = r.json()
check("GET /health", r.status_code == 200 and d["status"] in ("ok","starting"), f"-> {d['status']}")

# 2. Dashboard data
r = requests.get(f"{BASE}/api/v1/dashboard-data")
d = r.json()
check("GET /dashboard-data", r.status_code == 200 and d.get("status") == "success", f"-> keys={len(d.get('data',{}))} ")

# 3. Strategy (MR) - from new routers/strategy.py
r = requests.get(f"{BASE}/api/v1/strategy")
check("GET /strategy (MR)", r.status_code == 200, f"-> {r.status_code}")

# 4. Dividend strategy
r = requests.get(f"{BASE}/api/v1/dividend_strategy")
check("GET /dividend_strategy", r.status_code == 200, f"-> {r.status_code}")

# 5. Momentum strategy
r = requests.get(f"{BASE}/api/v1/momentum_strategy")
check("GET /momentum_strategy", r.status_code == 200, f"-> {r.status_code}")

# 6. ERP strategy
r = requests.get(f"{BASE}/api/v1/erp_strategy")
d = r.json()
check("GET /erp_strategy", r.status_code == 200 and d.get("status") in ("success","error"), f"-> {d.get('status')}")

# 7. AIAE strategy
r = requests.get(f"{BASE}/api/v1/aiae_strategy")
d = r.json()
check("GET /aiae_strategy", r.status_code == 200, f"-> {d.get('status')}")

# 8. AIAE report (from routers/aiae.py - now using cache_manager)
r = requests.get(f"{BASE}/api/v1/aiae/report")
check("GET /aiae/report", r.status_code == 200, f"-> {r.status_code}")

# 9. AIAE global report (cache unified)
r = requests.get(f"{BASE}/api/v1/aiae_global/report")
d = r.json()
check("GET /aiae_global/report", r.status_code == 200 and d.get("status") in ("success","error"), f"-> {d.get('status')}")

# 10. Auth still works (Batch 6 regression)
r = requests.post(f"{BASE}/api/v1/aiae/update_fund_position", json={"quarter": "Q1", "position": 80})
check("POST without key -> 401", r.status_code == 401, f"-> {r.status_code}")

# 11. Static file security
r = requests.get(f"{BASE}/config.py")
check("GET /config.py blocked", r.status_code == 404, f"-> {r.status_code}")

# 12. HTML pages
r = requests.get(f"{BASE}/")
check("GET / (index.html)", r.status_code == 200, f"-> {r.status_code}")

r = requests.get(f"{BASE}/strategy.html")
check("GET /strategy.html", r.status_code == 200, f"-> {r.status_code}")

print(f"\n{'='*50}")
print(f"Result: {tests_passed}/{tests_total} passed")
if tests_passed == tests_total:
    print("ALL TESTS PASSED!")
else:
    print("SOME TESTS FAILED")
