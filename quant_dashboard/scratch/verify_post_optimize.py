# -*- coding: utf-8 -*-
import sys, json
sys.path.insert(0, '.')

# 1. Check MR optimization result
print("=== MR Optimization Result ===")
try:
    d = json.load(open('mr_optimization_results.json', 'r', encoding='utf-8'))
    print(f"generated_at: {d.get('generated_at', 'N/A')}")
    print(f"combined_score: {d.get('combined_score', 'N/A')}")
except Exception as e:
    print(f"Error reading: {e}")

# 2. Re-run strategy health audit
print("\n=== Strategy Health Post-Optimization ===")
from engines.audit_engine import audit_strategy_health
r = audit_strategy_health()
print(f"Score: {r['score']}/{r['grade']}")
cb = r.get('circuit_breaker')
if cb:
    print(f"Circuit Breaker: {cb['reason']} ({cb['original']}->{cb['cap']})")
else:
    print("Circuit Breaker: NOT triggered")
for c in r['checks']:
    icon = {'pass': 'PASS', 'warn': 'WARN', 'fail': 'FAIL'}.get(c['status'], '?')
    print(f"  [{icon}] {c['name']}: {c['score']} - {c['detail']}")
