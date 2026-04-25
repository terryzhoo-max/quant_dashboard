"""Batch 6 Security Verification Script"""
import requests

BASE = "http://127.0.0.1:8000"
API_KEY = "NIT-EUnmt7eLpG5F6cWY8JpvF2EM1OKrlhNaLRbLCDi6DfOLik51E63ZdQ0PqdGz"

tests_passed = 0
tests_total = 0

def check(name, condition, status_code):
    global tests_passed, tests_total
    tests_total += 1
    result = "PASS" if condition else "FAIL"
    if condition:
        tests_passed += 1
    print(f"  [{result}] {name} -> {status_code}")

print("=== Batch 6 Security Verification ===\n")

# 1. GET without key -> should work
r = requests.get(f"{BASE}/health")
check("GET /health (no key)", r.status_code == 200, r.status_code)

# 2. GET dashboard-data without key -> should work
r = requests.get(f"{BASE}/api/v1/dashboard-data")
check("GET /api/v1/dashboard-data (no key)", r.status_code == 200, r.status_code)

# 3. POST without key -> 401
r = requests.post(f"{BASE}/api/v1/aiae/update_fund_position",
                   json={"quarter": "2026Q1", "position": 80.0, "source": "test"})
check("POST /update_fund_position (no key)", r.status_code == 401, r.status_code)

# 4. POST with wrong key -> 403
r = requests.post(f"{BASE}/api/v1/aiae/update_fund_position",
                   json={"quarter": "2026Q1", "position": 80.0, "source": "test"},
                   headers={"X-API-Key": "wrong-key-12345"})
check("POST /update_fund_position (wrong key)", r.status_code == 403, r.status_code)

# 5. POST with correct key -> should pass auth (200 or 422)
r = requests.post(f"{BASE}/api/v1/aiae/update_fund_position",
                   json={"quarter": "2026Q1", "position": 80.0, "source": "test"},
                   headers={"X-API-Key": API_KEY})
check("POST /update_fund_position (valid key)", r.status_code not in (401, 403), r.status_code)

# 6. GET /config.py -> 404 (blocked)
r = requests.get(f"{BASE}/config.py")
check("GET /config.py (should block)", r.status_code == 404, r.status_code)

# 7. GET /.env -> 404 (blocked)
r = requests.get(f"{BASE}/.env")
check("GET /.env (should block)", r.status_code == 404, r.status_code)

print(f"\n{'='*40}")
print(f"Result: {tests_passed}/{tests_total} passed")
if tests_passed == tests_total:
    print("ALL TESTS PASSED!")
else:
    print("SOME TESTS FAILED - review above")
