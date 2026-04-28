import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aiae_us_engine import get_us_aiae_engine
e = get_us_aiae_engine()
e.refresh()
r = e.generate_report()
c = r["current"]
raw = r.get("raw_data", {}).get("mkt", {})
print(f"Status: {r['status']}")
print(f"Source: {raw.get('source', 'unknown')}")
print(f"MktCap: ${c['market_cap_trillion']}T")
print(f"AIAE: {c['aiae_v1']}%  Regime: {c['regime']}")
