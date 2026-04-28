"""Quick API smoke test for V17.3 decision hub"""
import urllib.request
import json
import sys

ports = [8888, 8000, 5000, 3000]
url_path = "/api/v1/decision/hub"

for port in ports:
    try:
        url = f"http://127.0.0.1:{port}{url_path}"
        r = urllib.request.urlopen(url, timeout=3)
        d = json.loads(r.read())
        print(f"=== Port {port} SUCCESS ===")
        print(f"status:     {d.get('status')}")
        print(f"jcs_score:  {d.get('jcs', {}).get('score')}")
        print(f"jcs_level:  {d.get('jcs', {}).get('level')}")
        print(f"action:     {d.get('action_plan', {}).get('action_label')}")
        print(f"confidence: {d.get('action_plan', {}).get('confidence')}")
        print(f"conflicts:  {d.get('conflicts', {}).get('conflict_count')}")
        print(f"scenarios:  {len(d.get('scenarios', {}))}")
        alerts = d.get("alerts", [])
        print(f"alerts:     {len(alerts)}")
        for i, a in enumerate(alerts):
            print(f"  alert[{i}]: {a['type']} ({a['severity']}) - {a['title']}")
        if not alerts:
            print("  (no alerts - normal market)")
        
        # Check snapshot
        snap = d.get("snapshot", {})
        print(f"\n--- Snapshot ---")
        print(f"aiae_regime: {snap.get('aiae_regime')}")
        print(f"erp_score:   {snap.get('erp_score')}")
        print(f"vix_val:     {snap.get('vix_val')}")
        print(f"mr_regime:   {snap.get('mr_regime')}")
        print(f"hub_comp:    {snap.get('hub_composite')}")
        print(f"position:    {snap.get('suggested_position')}")
        
        # JCS details
        jcs = d.get("jcs", {})
        print(f"\n--- JCS Details ---")
        print(f"agreement:   {jcs.get('agreement_pct')}%")
        print(f"data_health: {jcs.get('data_health')}")
        print(f"consensus:   {jcs.get('consensus_bonus')}")
        print(f"directions:  {jcs.get('directions')}")
        
        sys.exit(0)
    except Exception as e:
        print(f"Port {port}: {e}")

print("\nERROR: No server found on any port!")
sys.exit(1)
