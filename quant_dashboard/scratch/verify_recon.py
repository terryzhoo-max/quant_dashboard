"""Verify reconciliation report post-backfill."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from engines.backtest_reconciliation import get_reconciliation_engine
r = get_reconciliation_engine().generate_full_report()
m = r.get('maturity', {})
pos = r.get('position_reconciliation', {})
s = pos.get('summary', {})

print('=== Reconciliation Report ===')
print('Status:', r.get('status'))
print('Maturity:', 'MATURE' if m.get('is_mature') else 'IMMATURE',
      '| matched:', m.get('matched_days'), '| msg:', m.get('message'))
print('Score:', s.get('score'), '/ 100')
print('Avg Gap:', s.get('avg_gap_abs'), 'pt')
print('Max Gap:', s.get('max_gap_abs'), 'pt')
print('Compliance:', s.get('compliance_rate_pct'), '%')
print('Daily records:', len(pos.get('daily_records', [])))
print()
for dr in pos.get('daily_records', []):
    g = dr.get('gap')
    gs = dr.get('gap_severity', '')
    a = dr.get('actual_pct')
    su = dr.get('suggested_pct')
    print(f"  {dr['date']}: sugg={su}% act={a}% gap={g}pt [{gs}]")
