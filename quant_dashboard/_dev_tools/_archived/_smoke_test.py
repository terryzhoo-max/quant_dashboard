"""Dashboard API Smoke Test"""
import urllib.request, json, sys

URL = "http://127.0.0.1:8000/api/v1/dashboard-data"
print(f"Requesting {URL} ...")

try:
    req = urllib.request.Request(URL)
    with urllib.request.urlopen(req, timeout=180) as resp:
        d = json.loads(resp.read())
except Exception as e:
    print(f"FATAL: API request failed: {e}")
    sys.exit(1)

print("=" * 50)
print("  Dashboard API Smoke Test Results")
print("=" * 50)

# Unwrap nested response: {status, timestamp, data: {...}}
if "data" in d and isinstance(d["data"], dict):
    print(f"[0] Response wrapper: status={d.get('status')} timestamp={d.get('timestamp','?')[:19]}")
    d = d["data"]  # Unwrap to actual dashboard data

# 1. Status
status = d.get("status")
print(f"\n[1] Status: {status}  {'PASS' if status == 'success' else 'FAIL'}")

# 2. Top-level keys
keys = sorted(d.keys())
print(f"\n[2] Top-level keys ({len(keys)}): {keys}")

# 3. Macro Card
mc = d.get("macro_card", {})
print(f"\n[3] Macro Card keys: {sorted(mc.keys())}")
for k in ["vix", "cny", "margin_risk", "breadth", "turnover", "erp_val", "erp_label", "valuation_label"]:
    v = mc.get(k)
    print(f"    {k}: {v}")

# 4. VIX Analysis
va = d.get("vix_analysis", {})
print(f"\n[4] VIX: current={va.get('current_vix')} tier={va.get('tier')}")

# 5. Temperature
t = d.get("temperature", {})
print(f"\n[5] Temperature:")
print(f"    score: {t.get('score')}")
print(f"    score_hk: {t.get('score_hk')}")
print(f"    regime_label: {t.get('regime_label')}")

# 6. AIAE
print(f"\n[6] AIAE: regime={d.get('aiae_regime')} cap={d.get('aiae_pos_cap')}")
pa = str(d.get("pos_advice", ""))
print(f"    pos_advice: {pa[:150]}")

# 7. Strategy Filters (5 expected)
sf = d.get("strategy_filters", {})
print(f"\n[7] Strategy Filters ({len(sf)} keys): {list(sf.keys())}")
expected_sf = {"mr", "div", "mom", "erp", "aiae_etf"}
missing_sf = expected_sf - set(sf.keys())
print(f"    Missing: {missing_sf if missing_sf else 'NONE'}")
print(f"    {'PASS' if len(sf) >= 5 else 'FAIL'}: expected >= 5 filters")

# 8. Regime Weights (5 expected)
rw = d.get("regime_weights", {})
print(f"\n[8] Regime Weights ({len(rw)} keys): {rw}")
expected_rw = {"mr", "div", "mom", "erp", "aiae_etf"}
missing_rw = expected_rw - set(rw.keys())
print(f"    Missing: {missing_rw if missing_rw else 'NONE'}")
print(f"    {'PASS' if len(rw) >= 5 else 'FAIL'}: expected >= 5 weights")

# 9. Sector Heatmap
sh = d.get("sector_heatmap", [])
print(f"\n[9] Sector Heatmap: {len(sh)} ETFs")
if sh:
    print(f"    Sample: {sh[0].get('name', '?')} pct={sh[0].get('pct_chg', '?')}")
print(f"    {'PASS' if len(sh) >= 10 else 'FAIL'}: expected >= 10 ETFs")

# 10. Strategy Status
ss = d.get("strategy_status", {})
print(f"\n[10] Strategy Status keys: {list(ss.keys())}")

# 11. Strategy Results
for s in ["mr", "mom", "div"]:
    results_key = f"{s}_results"
    data = d.get(results_key)
    if data is None:
        # try alternative keys
        for alt in [f"{s}_data", f"{s}_signals", s]:
            data = d.get(alt)
            if data:
                results_key = alt
                break
    count = len(data) if isinstance(data, list) else ("present" if data else "MISSING")
    print(f"    {results_key}: {count}")

# 12. Null field check
nulls = [k for k, v in d.items() if v is None]
print(f"\n[12] Null fields: {nulls if nulls else 'NONE'}")
print(f"     {'PASS' if not nulls else 'WARN: some null fields'}")

# Summary
print("\n" + "=" * 50)
checks = [
    status == "success",
    len(sf) >= 5,
    len(rw) >= 5,
    len(sh) >= 10,
    not nulls,
]
passed = sum(checks)
print(f"  RESULT: {passed}/{len(checks)} checks passed")
print("=" * 50)
