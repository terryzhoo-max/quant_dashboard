"""Quick test: monthly history seed"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from aiae_engine import AIAEEngine
e = AIAEEngine()

# Force seed
e._seed_monthly_history_if_needed(21.87, 3)

with open('data_lake/aiae_monthly_history.json', 'r', encoding='utf-8') as f:
    mh = json.load(f)

print(f"Total: {len(mh)} records")
for h in mh:
    print(f"  {h['month']}: {h['aiae_v1']}% [{h.get('source','live')}]")

prev = e._get_prev_month_aiae()
print(f"\nPrev month AIAE: {prev}")

if prev is not None:
    slope = e.compute_slope(21.87, prev)
    print(f"Slope: {slope}")
    print(f"  slope value: {slope.get('slope', 'N/A')}")
    print(f"  direction: {slope.get('direction', 'N/A')}")
    print(f"  signal: {slope.get('signal', 'None')}")
else:
    print("Slope: flat (no prev data)")
