# -*- coding: utf-8 -*-
"""Final integration regression test"""
import sys
sys.path.insert(0, '.')
from engines.audit_engine import run_full_audit

r = run_full_audit()
print(f"Trust: {r['trust_score']}/{r['trust_grade']}")
print(f"Checks: {r['pass_count']}pass {r['warn_count']}warn {r['fail_count']}fail")
for m in r['modules'].values():
    cb = f" [CB: {m['circuit_breaker']['reason']}]" if m.get('circuit_breaker') else ''
    print(f"  {m['label']}: {m['score']}/{m['grade']}{cb}")
print(f"Elapsed: {r['elapsed_seconds']}s")
