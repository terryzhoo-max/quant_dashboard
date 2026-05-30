"""V6.0 策略健康审计验证脚本"""
import sys, os
sys.path.insert(0, '.')
os.chdir(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard')
from engines.audit_engine import audit_strategy_health

r = audit_strategy_health()
print(f"=== Strategy Health V6.0 ===")
print(f"Total Score: {r['score']}  Grade: {r['grade']}")
print(f"Checks: {len(r['checks'])}")
print("-" * 80)
for c in r['checks']:
    icon = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}.get(c['status'], '?')
    print(f"  [{icon:4s}] {c['score']:3d}  {c['name']}")
    print(f"         Detail: {c['detail']}")
    if c.get('meta'):
        print(f"         Meta:   {c['meta']}")
    print()
