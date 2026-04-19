# -*- coding: utf-8 -*-
"""Quick test: verify triggered/current fields in ERP API response"""
import urllib.request, json, sys

sys.stdout.reconfigure(encoding='utf-8')

r = urllib.request.urlopen('http://127.0.0.1:8000/api/v1/strategy/erp-timing')
d = json.loads(r.read())
tr = d.get('data', {}).get('trade_rules', {})

print("=== TAKE PROFIT ===")
for tp in tr.get('take_profit', []):
    triggered = tp.get('triggered')
    current = tp.get('current')
    t_type = type(triggered).__name__
    icon = "[YES]" if triggered else "[NO]"
    print(f"  {icon} {tp['trigger']}: triggered={triggered} (type={t_type}), current={current}")

print("\n=== STOP LOSS ===")
for sl in tr.get('stop_loss', []):
    triggered = sl.get('triggered')
    current = sl.get('current')
    t_type = type(triggered).__name__
    icon = "[YES]" if triggered else "[NO]"
    print(f"  {icon} {sl['trigger']}: triggered={triggered} (type={t_type}), current={current}")

# Validate types
all_rules = tr.get('take_profit', []) + tr.get('stop_loss', [])
errors = []
for rule in all_rules:
    if not isinstance(rule.get('triggered'), bool):
        errors.append(f"FAIL: '{rule['trigger']}' triggered={rule.get('triggered')} is {type(rule.get('triggered')).__name__}, expected bool")
    if rule.get('current') is not None and not isinstance(rule.get('current'), str):
        errors.append(f"FAIL: '{rule['trigger']}' current={rule.get('current')} is {type(rule.get('current')).__name__}, expected str")

print("\n=== TYPE VALIDATION ===")
if errors:
    for e in errors:
        print(f"  [X] {e}")
    print(f"\n  RESULT: FAIL ({len(errors)} errors)")
else:
    print(f"  [OK] All {len(all_rules)} rules have valid triggered(bool) and current(str) fields")
    print(f"\n  RESULT: PASS")
