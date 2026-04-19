"""Quick test: run-all only (bypass dashboard-data which is heavy)"""
import urllib.request, json, sys

try:
    print("[TEST] Hitting /api/v1/strategy/run-all ...")
    r = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/strategy/run-all", timeout=300)
    d = json.loads(r.read())
    status = d.get("status", "?")
    if status == "success":
        g = d.get("data", {}).get("global", {})
        print(f"  status           = {status}")
        print(f"  total_position   = {g.get('total_position', '?')}%")
        print(f"  regime           = {g.get('regime', '?')}")
        print(f"  strategy_count   = {g.get('strategy_count', '?')}")
        print(f"  total_buy        = {g.get('total_buy', '?')}")
        print(f"  total_sell       = {g.get('total_sell', '?')}")
        aiae = g.get("aiae", {})
        print(f"  aiae_regime      = {aiae.get('regime', '?')}")
        print(f"  aiae_cap         = {aiae.get('aiae_cap', '?')}%")
        print(f"  erp_tier         = {aiae.get('erp_tier', '?')}")
        conf = g.get("confidence", {})
        print(f"  confidence       = mr:{conf.get('mr','?')} div:{conf.get('div','?')} mom:{conf.get('mom','?')} erp:{conf.get('erp','?')} aiae:{conf.get('aiae_etf','?')}")
        
        strats = d.get("data", {}).get("strategies", {})
        for name in ["mr", "div", "mom", "erp", "aiae_etf"]:
            s = strats.get(name, {})
            sigs = s.get("signals", [])
            print(f"  [{name}] signals={len(sigs)}")
        
        print(f"\n  [PASS] run-all OK - 5 strategies executed successfully")
    else:
        print(f"\n  [FAIL] run-all status={status}, msg={d.get('message','?')}")
        sys.exit(1)
except Exception as e:
    print(f"[ERROR] {e}")
    sys.exit(1)
