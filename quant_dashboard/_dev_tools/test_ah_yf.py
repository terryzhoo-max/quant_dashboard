"""快速测试: AH溢价 yfinance 混合方案"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.chdir(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard')
sys.path.insert(0, '.')

from aiae_hk_engine import get_hk_aiae_engine
hk = get_hk_aiae_engine()
r = hk._compute_ah_premium_auto()
print(f"Index: {r.get('index_value', '?')}")
print(f"Source: {r.get('source', '?')}")
print(f"Coverage: {r.get('basket_coverage', '?')}%")
print(f"Count: {r.get('basket_count', '?')}")
print(f"Interp: {r.get('interpretation', '?')}")
for d in r.get('details', []):
    print(f"  {d['name']}: A={d['a']} H={d['h']} Premium={d['premium']}")
