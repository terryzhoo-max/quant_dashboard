"""Batch 8 Frontend Modularization Verification"""
import requests

BASE = "http://127.0.0.1:8000"
passed = 0
total = 0

def check(name, condition, detail=""):
    global passed, total
    total += 1
    ok = "PASS" if condition else "FAIL"
    if condition: passed += 1
    print(f"  [{ok}] {name} {detail}")

print("=== Batch 8 Frontend Verification ===\n")

# 1. HTML pages accessible
html_pages = [
    "/", "/strategy.html", "/backtest.html", "/audit.html",
    "/factor.html", "/industry.html", "/portfolio.html", "/treasury.html",
    "/byd_audit.html", "/eastmoney_audit.html", "/fii_audit.html",
    "/scc_audit.html", "/smic_audit.html", "/wus_audit.html", "/zijin_audit.html"
]
for page in html_pages:
    r = requests.get(f"{BASE}{page}")
    check(f"GET {page}", r.status_code == 200, f"-> {r.status_code}")

# 2. CSS files from new path
css_files = ["styles.css", "strategy.css", "audit.css", "backtest.css", 
             "factor.css", "industry.css", "portfolio.css", "treasury.css"]
for css in css_files:
    r = requests.get(f"{BASE}/static/css/{css}")
    check(f"CSS /static/css/{css}", r.status_code == 200 and len(r.content) > 100, 
          f"-> {r.status_code} ({len(r.content)} bytes)")

# 3. JS files from new path
js_files = ["script.js", "strategy.js", "backtest.js", "alphacore_utils.js",
            "audit.js", "factor.js", "industry.js", "treasury.js"]
for js in js_files:
    r = requests.get(f"{BASE}/static/js/{js}")
    check(f"JS /static/js/{js}", r.status_code == 200 and len(r.content) > 100,
          f"-> {r.status_code} ({len(r.content)} bytes)")

# 4. Vendor (echarts)
r = requests.get(f"{BASE}/static/vendor/echarts.min.js")
check("Vendor echarts.min.js", r.status_code == 200 and len(r.content) > 10000,
      f"-> {r.status_code} ({len(r.content)} bytes)")

# 5. OLD paths should 404 (files moved)
for old in ["styles.css", "script.js", "echarts.min.js"]:
    r = requests.get(f"{BASE}/{old}")
    check(f"OLD /{old} -> 404", r.status_code == 404, f"-> {r.status_code}")

# 6. Security: .py still blocked
r = requests.get(f"{BASE}/config.py")
check("Security: config.py blocked", r.status_code == 404, f"-> {r.status_code}")

# 7. API still works
r = requests.get(f"{BASE}/health")
d = r.json()
check("API /health", r.status_code == 200 and d["status"] in ("ok","starting"), f"-> {d['status']}")

r = requests.get(f"{BASE}/api/v1/dashboard-data")
d = r.json()
check("API /dashboard-data", r.status_code == 200, f"-> {d.get('status')}")

# 8. HTML references contain correct paths
r = requests.get(f"{BASE}/")
html = r.text
check("index.html refs static/css/", "static/css/styles.css" in html)
check("index.html refs static/js/", "static/js/script.js" in html)
check("index.html refs static/vendor/", "static/vendor/echarts.min.js" in html)

print(f"\n{'='*50}")
print(f"Result: {passed}/{total} passed")
print("ALL TESTS PASSED!" if passed == total else "SOME TESTS FAILED")
