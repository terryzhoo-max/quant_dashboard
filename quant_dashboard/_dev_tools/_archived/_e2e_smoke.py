"""
AlphaCore E2E Smoke Test V2 — 全链路烟雾测试
基于 OpenAPI 真实路由表测试所有核心 API endpoint
"""
import requests
import json
import time
import sys

BASE = "http://localhost:8000"
TIMEOUT = 120  # Dashboard 首次可能需要较长时间
PASS = 0
FAIL = 0
RESULTS = []

def test(name, url, check_fn=None, method="GET", timeout=TIMEOUT):
    global PASS, FAIL
    try:
        t0 = time.time()
        if method == "GET":
            r = requests.get(f"{BASE}{url}", timeout=timeout)
        else:
            r = requests.post(f"{BASE}{url}", timeout=timeout)
        elapsed = time.time() - t0
        
        if r.status_code != 200:
            FAIL += 1
            RESULTS.append(f"  FAIL  {name}  HTTP {r.status_code}  ({elapsed:.1f}s)")
            return None
        
        data = r.json()
        
        if check_fn:
            ok, detail = check_fn(data)
            if ok:
                PASS += 1
                RESULTS.append(f"  PASS  {name}  ({elapsed:.1f}s) {detail}")
            else:
                FAIL += 1
                RESULTS.append(f"  FAIL  {name}  ({elapsed:.1f}s) {detail}")
        else:
            PASS += 1
            RESULTS.append(f"  PASS  {name}  ({elapsed:.1f}s)")
        return data
    except Exception as e:
        FAIL += 1
        RESULTS.append(f"  FAIL  {name}  Exception: {e}")
        return None

print("Starting AlphaCore E2E Smoke Test...")
print(f"Target: {BASE}")
print()

# ═════════════════════════════════════════════════════
# 1. Dashboard Overview (核心总览) — 最重的接口, 先测
# ═════════════════════════════════════════════════════
def check_dashboard(d):
    if d.get("status") != "success":
        return False, f"status={d.get('status')}"
    mc = d.get("data", {}).get("macro_cards", {})
    required = ["market_temp", "vix", "erp", "regime_banner", "aiae_thermometer", "signal"]
    missing = [k for k in required if k not in mc]
    if missing:
        return False, f"Missing macro_cards keys: {missing}"
    temp = mc.get("market_temp", {}).get("value", "?")
    vix = mc.get("vix", {}).get("value", "?")
    erp = mc.get("erp", {}).get("value", "?")
    aiae = mc.get("aiae_thermometer", {}).get("aiae_v1", "?")
    return True, f"temp={temp} vix={vix} erp={erp} aiae={aiae}"

test("Dashboard Overview", "/api/v1/dashboard-data", check_dashboard, timeout=300)

# ═════════════════════════════════════════════════════
# 2. ERP Timing Engine
# ═════════════════════════════════════════════════════
def check_erp(d):
    if d.get("status") not in ("success", "fallback"):
        return False, f"status={d.get('status')}"
    inner = d.get("data", d)  # unwrap envelope
    snap = inner.get("current_snapshot", {})
    erp = snap.get("erp_value", "?")
    return True, f"ERP={erp}%"

test("ERP Timing", "/api/v1/strategy/erp-timing", check_erp, timeout=300)

# ═════════════════════════════════════════════════════
# 3. ERP Global (Multi-Market)
# ═════════════════════════════════════════════════════
def check_erp_global(d):
    if d.get("status") not in ("success", "fallback"):
        return False, f"status={d.get('status')}"
    inner = d.get("data", d)
    markets = inner.get("markets", d.get("markets", []))
    return True, f"{len(markets)} markets"

test("ERP Global", "/api/v1/strategy/erp-global", check_erp_global)

# ═════════════════════════════════════════════════════
# 4. HK ERP (HSI / HSTECH)
# ═════════════════════════════════════════════════════
def check_hk_erp(d):
    if d.get("status") not in ("success", "fallback"):
        return False, f"status={d.get('status')}"
    inner = d.get("data", d)
    sig = inner.get("signal", d.get("signal", {}))
    score = sig.get("score", "?")
    return True, f"Score={score}"

test("HK ERP (HSI)", "/api/v1/strategy/erp-hk?market=HSI", check_hk_erp)
test("HK ERP (HSTECH)", "/api/v1/strategy/erp-hk?market=HSTECH", check_hk_erp)

# ═════════════════════════════════════════════════════
# 5. AIAE Report (A股)
# ═════════════════════════════════════════════════════
def check_aiae(d):
    if d.get("status") not in ("success", "fallback"):
        return False, f"status={d.get('status')}"
    inner = d.get("data", d)
    cur = inner.get("current", d.get("current", {}))
    v1 = cur.get("aiae_v1", "?")
    regime = cur.get("regime", "?")
    return True, f"AIAE={v1}% Regime={regime}"

test("AIAE Report (CN)", "/api/v1/aiae/report", check_aiae)

# ═════════════════════════════════════════════════════
# 6. AIAE Global (US/JP/HK/CN 四地对比)
# ═════════════════════════════════════════════════════
def check_aiae_global(d):
    if d.get("status") not in ("success", "fallback"):
        return False, f"status={d.get('status')}"
    inner = d.get("data", d)
    gc = inner.get("global_comparison", d.get("global_comparison", {}))
    markets = ["cn_aiae", "us_aiae", "jp_aiae", "hk_aiae"]
    vals = {m: gc.get(m, "?") for m in markets}
    return True, f"CN={vals['cn_aiae']} US={vals['us_aiae']} JP={vals['jp_aiae']} HK={vals['hk_aiae']}"

test("AIAE Global", "/api/v1/aiae_global/report", check_aiae_global)

# ═════════════════════════════════════════════════════
# 7. HK AIAE Report
# ═════════════════════════════════════════════════════
test("HK AIAE Report", "/api/v1/aiae_hk/report", check_aiae)

# ═════════════════════════════════════════════════════
# 8. Rates Strategy
# ═════════════════════════════════════════════════════
def check_rates(d):
    if d.get("status") not in ("success", "fallback"):
        return False, f"status={d.get('status')}"
    return True, f"keys={list(d.keys())[:5]}"

test("Rates Strategy", "/api/v1/strategy/rates", check_rates)

# ═════════════════════════════════════════════════════
# 9. Industry Tracking
# ═════════════════════════════════════════════════════
def check_industry(d):
    if d.get("status") not in ("success", "fallback"):
        return False, f"status={d.get('status')}"
    data = d.get("data", {})
    sectors = data.get("sector_heatmap", [])
    return True, f"{len(sectors)} sectors"

test("Industry Tracking", "/api/v1/industry-tracking", check_industry)

# ═════════════════════════════════════════════════════
# 10. Run All Strategies (5策略共振)
# ═════════════════════════════════════════════════════
def check_run_all(d):
    if d.get("status") not in ("success", "partial", "fallback"):
        return False, f"status={d.get('status')}"
    sigs = d.get("top_signals", [])
    return True, f"{len(sigs)} signals"

test("Run All Strategies", "/api/v1/strategy/run-all", check_run_all)

# ═════════════════════════════════════════════════════
# 11. Individual Strategies
# ═════════════════════════════════════════════════════
def check_strategy(d):
    return True, f"keys={list(d.keys())[:5]}"

test("Strategy (MR)", "/api/v1/strategy", check_strategy)
test("AIAE Strategy", "/api/v1/aiae_strategy", check_strategy)
test("ERP Strategy", "/api/v1/erp_strategy", check_strategy)
test("Dividend Strategy", "/api/v1/dividend_strategy", check_strategy)
test("Momentum Strategy", "/api/v1/momentum_strategy", check_strategy)

# ═════════════════════════════════════════════════════
# 12. Portfolio Module
# ═════════════════════════════════════════════════════
def check_portfolio(d):
    return True, f"keys={list(d.keys())[:5]}"

test("Portfolio Valuation", "/api/v1/portfolio/valuation", check_portfolio)
test("Portfolio Risk", "/api/v1/portfolio/risk", check_portfolio)
test("Portfolio History", "/api/v1/portfolio/history", check_portfolio)
test("Portfolio NAV", "/api/v1/portfolio/nav", check_portfolio)

# ═════════════════════════════════════════════════════
# 13. Audit Module
# ═════════════════════════════════════════════════════
def check_audit(d):
    return True, f"keys={list(d.keys())[:5]}"

test("Audit", "/api/v1/audit", check_audit)
test("Audit Enforcer Status", "/api/v1/audit/enforcer/status", check_audit)

# ═════════════════════════════════════════════════════
# 14. Static Files (Frontend Pages)
# ═════════════════════════════════════════════════════
for page in ["index.html", "strategy.html", "industry.html", "portfolio.html", "factor.html", "backtest.html", "treasury.html"]:
    try:
        t0 = time.time()
        r = requests.get(f"{BASE}/{page}", timeout=30)
        elapsed = time.time() - t0
        if r.status_code == 200 and len(r.text) > 100:
            PASS += 1
            size_kb = len(r.text) / 1024
            RESULTS.append(f"  PASS  Frontend: {page}  ({elapsed:.1f}s) {size_kb:.0f}KB")
        else:
            FAIL += 1
            RESULTS.append(f"  FAIL  Frontend: {page}  HTTP {r.status_code}")
    except Exception as e:
        FAIL += 1
        RESULTS.append(f"  FAIL  Frontend: {page}  {e}")


# ═════════════════════════════════════════════════════
# Summary Report
# ═════════════════════════════════════════════════════
print()
print("=" * 70)
print("  AlphaCore E2E Smoke Test Report")
print("  " + time.strftime("%Y-%m-%d %H:%M:%S"))
print("=" * 70)
for r in RESULTS:
    icon = "[OK]" if "PASS" in r else "[!!]"
    print(f"  {icon} {r.strip()}")
print("-" * 70)
total = PASS + FAIL
pct = (PASS / total * 100) if total > 0 else 0
print(f"  TOTAL: {PASS}/{total} PASSED ({pct:.0f}%)  |  {FAIL} FAILED")
if FAIL == 0:
    print("  STATUS: ALL TESTS PASSED")
else:
    print(f"  STATUS: {FAIL} TEST(S) FAILED")
print("=" * 70)

sys.exit(0 if FAIL == 0 else 1)
