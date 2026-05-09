import sys, os
sys.path.insert(0, '.')

from engines.compliance_engine import run_compliance_check

test_snapshot = {
    'aiae_regime': 3,
    'aiae_v1': 22.5,
    'vix_val': 18.2,
    'erp_score': 48,
    'mr_regime': 'RANGE',
}

test_positions = [
    {'ts_code': '688981.SH', 'name': '中芯国际', 'weight': 15.2, 'industry': 'AI算力'},
    {'ts_code': '601899.SH', 'name': '紫金矿业', 'weight': 12.1, 'industry': '有色金属'},
    {'ts_code': '002594.SZ', 'name': '比亚迪', 'weight': 10.5, 'industry': '新能源汽车'},
    {'ts_code': '300059.SZ', 'name': '东方财富', 'weight': 8.3, 'industry': '金融科技'},
    {'ts_code': '601138.SH', 'name': '工业富联', 'weight': 7.9, 'industry': 'AI算力'},
]

context = {'direction': 'hold', 'jcs_level': 'medium', 'jcs_score': 58.3}

result = run_compliance_check(test_snapshot, test_positions, context)

print('=== Compliance Check Result ===')
print('Status:', result['status'])
print('Summary:', result['summary'])
print('Passed:', result['passed_count'], 'Failed:', result['failed_count'])
print()
for c in result['checks']:
    icon = '  ' if c['passed'] else 'XX'
    status_str = 'PASS' if c['passed'] else 'FAIL'
    print('  [%s] %-12s %-12s | %s | %s' % (icon, c['severity'], c['rule_name'], status_str, c['detail']))

print()
print('=== JSON Keys (for frontend) ===')
print('Top-level keys:', list(result.keys()))
if result['checks']:
    print('Check[0] keys:', list(result['checks'][0].keys()))
