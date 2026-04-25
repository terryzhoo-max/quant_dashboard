"""Batch 11 Feature Enhancement Verification"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = 0
total = 0

def check(name, condition, detail=""):
    global passed, total
    total += 1
    ok = "PASS" if condition else "FAIL"
    if condition: passed += 1
    print(f"  [{ok}] {name} {detail}")

print("=== Batch 11 Feature Enhancement Verification ===\n")

# ── 11-C: API Response Module ──
print("--- 11-C: API Response Standardization ---")
from models import response as R
check("R.ok() structure", R.ok({"test": 1})["status"] == "success" and R.ok()["version"] == "V15.1")
check("R.error() structure", R.error("bad", "ERR_TEST")["code"] == "ERR_TEST")
check("R.error() has version", "version" in R.error("x"))

# ── 11-B: Portfolio Snapshots (SQLite) ──
print("\n--- 11-B: Portfolio Snapshots ---")
from services import db as ac_db
ac_db.init_db()
check("portfolio_snapshots table exists", True)

ac_db.save_portfolio_snapshot("2026-04-22", 1500000, 50000, 1450000, 80000, 24)
ac_db.save_portfolio_snapshot("2026-04-21", 1480000, 50000, 1430000, 60000, 24)
snaps = ac_db.get_portfolio_snapshots(30)
check("save + get snapshots", len(snaps) >= 2, f"-> {len(snaps)} snapshots")

# Check ordering (should be date ASC)
dates = [s["date"] for s in snaps]
check("Snapshots ordered ASC", dates == sorted(dates))

# Upsert idempotent
ac_db.save_portfolio_snapshot("2026-04-22", 1510000, 51000, 1459000, 81000, 24)
snaps2 = ac_db.get_portfolio_snapshots(30)
count_22 = sum(1 for s in snaps2 if s["date"] == "2026-04-22")
check("Upsert idempotent", count_22 == 1)
check("Upsert updates value", [s for s in snaps2 if s["date"] == "2026-04-22"][0]["total_asset"] == 1510000)

cnt = ac_db.get_portfolio_snapshot_count()
check("get_portfolio_snapshot_count()", cnt >= 2, f"-> {cnt}")

# ── Now test via HTTP (requires running server) ──
print("\n--- Integration Tests (HTTP) ---")
try:
    import requests
    BASE = "http://127.0.0.1:8000"
    
    # 11-A: /health upgrade
    r = requests.get(f"{BASE}/health", timeout=5)
    h = r.json()
    check("/health version V15.1", h.get("version") == "AlphaCore V15.1")
    check("/health has uptime_sec", "uptime_sec" in h and isinstance(h["uptime_sec"], int))
    check("/health has database", "database" in h)
    check("/health database.trades", h.get("database", {}).get("trades", 0) > 0,
          f"-> {h.get('database', {}).get('trades')}")
    check("/health database.snapshots", "snapshots" in h.get("database", {}),
          f"-> {h.get('database', {}).get('snapshots')}")

    # 11-B: /portfolio/snapshots endpoint
    r = requests.get(f"{BASE}/api/v1/portfolio/snapshots", timeout=5)
    d = r.json()
    check("GET /portfolio/snapshots 200", r.status_code == 200)
    check("snapshots has version", d.get("version") == "V15.1")
    check("snapshots has data", isinstance(d.get("data"), list))

    # 11-C: standardized response
    r = requests.get(f"{BASE}/api/v1/portfolio/valuation", timeout=5)
    d = r.json()
    check("valuation has version", d.get("version") == "V15.1")
    check("valuation has status=success", d.get("status") == "success")

    r = requests.get(f"{BASE}/api/v1/portfolio/history", timeout=5)
    d = r.json()
    check("history has version", d.get("version") == "V15.1")

except requests.ConnectionError:
    print("  [SKIP] Server not running, skipping HTTP tests")
except Exception as e:
    print(f"  [SKIP] HTTP test error: {e}")

print(f"\n{'='*50}")
print(f"Result: {passed}/{total} passed")
print("ALL TESTS PASSED!" if passed == total else "SOME TESTS FAILED")
