"""Quick retest for the 2 timed-out endpoints with extended timeout"""
import requests, time

BASE = "http://localhost:8000"

for name, url in [
    ("Dashboard Overview", "/api/v1/dashboard-data"),
    ("ERP Timing", "/api/v1/strategy/erp-timing"),
]:
    print(f"Testing {name} ...", flush=True)
    try:
        t0 = time.time()
        r = requests.get(f"{BASE}{url}", timeout=300)
        elapsed = time.time() - t0
        d = r.json()
        status = d.get("status", "?")
        if name == "Dashboard Overview":
            temp = d.get("market_temp", "?")
            vix = d.get("vix", "?")
            erp = d.get("erp", "?")
            pos = str(d.get("pos_advice", ""))[:50]
            print(f"  [OK] {name} ({elapsed:.1f}s) status={status} temp={temp} vix={vix} erp={erp}")
        else:
            snap = d.get("current_snapshot", {})
            erp_val = snap.get("erp_value", "?")
            print(f"  [OK] {name} ({elapsed:.1f}s) status={status} ERP={erp_val}%")
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")

print("\nDone.")
