# -*- coding: utf-8 -*-
"""Quick verification of rates V2.0 dynamic zones"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from rates_strategy_engine import get_rates_engine

e = get_rates_engine()
r = e.generate_report()

# Check chart
chart = r.get('chart', {})
ps = chart.get('percentile_stats', {})
lines = chart.get('lines', {})
ma = chart.get('mark_areas', [])

print("=" * 60)
print("  Rates V2.0 Dynamic Zones — Verification")
print("=" * 60)

print(f"\n📊 Percentile Stats (5Y window):")
print(f"  P25 = {ps.get('p25', '?')}%")
print(f"  P50 = {ps.get('p50', '?')}%")
print(f"  P75 = {ps.get('p75', '?')}%")
print(f"  σ   = {ps.get('std', '?')}")
print(f"  Mean = {ps.get('mean', '?')}%")

print(f"\n📈 Dynamic Chart Lines:")
for k, v in lines.items():
    print(f"  {k}: {v}%")

print(f"\n🎨 Mark Areas ({len(ma)}):")
for a in ma:
    print(f"  {a['name']}: {a['y_from']:.2f} -> {a['y_to']:.2f}")

# Check zones
bsz = r.get('buy_sell_zones', {})
print(f"\n🎯 Current Position:")
print(f"  10Y = {ps.get('current', '?')}% (Percentile: P{ps.get('current_pct', '?')})")
print(f"  Zone = {ps.get('current_zone_label', '?')}")

print(f"\n📋 Bond Buy Conditions:")
for c in bsz.get('bond_buy', []):
    mark = "✅" if c['met'] else "❌"
    pct_str = f" [P{c['pct']:.0f}]" if 'pct' in c else ""
    print(f"  {mark} {c['cond']} → {c['val']}{pct_str} ({c['why']})")

print(f"\n📋 Stock Buy Conditions:")
for c in bsz.get('stock_buy', []):
    mark = "✅" if c['met'] else "❌"
    pct_str = f" [P{c['pct']:.0f}]" if 'pct' in c else ""
    print(f"  {mark} {c['cond']} → {c['val']}{pct_str} ({c['why']})")

print(f"\n🏁 Conclusion: {bsz.get('conclusion', '?')}")

# Sanity checks
assert chart['status'] == 'success', "Chart should be success"
assert len(ma) == 4, f"Should have 4 mark areas, got {len(ma)}"
assert lines['high_zone'] > lines['neutral'] > lines['low_zone'], "Lines must be monotonically decreasing"
assert 'percentile_stats' in bsz, "buy_sell_zones should contain percentile_stats"
assert ps.get('bond_overweight', 0) > ps.get('bond_tilt', 0) > ps.get('stock_tilt', 0) > ps.get('full_equity', 0), "Zone thresholds must be ordered"

print(f"\n✅ All assertions passed! V2.0 dynamic zones working correctly.")
