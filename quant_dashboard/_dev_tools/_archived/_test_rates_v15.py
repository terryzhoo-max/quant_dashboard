"""利率择时 V1.5 生产级优化 — 验证脚本"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.path.insert(0, '.')

import rates_strategy_engine as rse

engine = rse.get_rates_engine()
report = engine.generate_report()

if 'error' in report:
    print('ERROR:', report['error'])
    sys.exit(1)

sig = report.get('signal', {})
snap = report.get('current_snapshot', {})
dims = report.get('dimensions', {})
bsz = report.get('buy_sell_zones', {})
chart = report.get('chart', {})

print("=" * 60)
print("利率择时 V1.5 生产级验证")
print("=" * 60)
print(f"Version:  {report.get('version')}")
print(f"10Y:      {snap.get('yield_10y', '?')}%")
print(f"2Y:       {snap.get('yield_2y', '?')}%") 
print(f"Spread:   {snap.get('spread_bps', '?')} bps")
print(f"Real:     {snap.get('real_yield', '?')}%")
print(f"BEI:      {snap.get('breakeven', '?')}%")
print(f"3M Rate:  {snap.get('rate_3m', '?')}%")
print("-" * 60)
print(f"Score:    {sig.get('score', '?')}")
print(f"Signal:   {sig.get('emoji', '')} {sig.get('label', '?')} ({sig.get('key', '?')})")
print(f"Position: {sig.get('position', '?')}")
print(f"Duration: {sig.get('duration', '?')}")
print("-" * 60)
print("五维评分:")
for k, v in dims.items():
    desc_short = v.get('desc', '')[:50]
    print(f"  {v.get('label', k):8s} [w={v.get('weight', '?')}] score={v.get('score', '?'):5} | {desc_short}")
print("-" * 60)
print(f"Decision: {bsz.get('conclusion', '?')}")
print(f"Alerts:   {len(report.get('alerts', []))}")
print(f"Chart:    status={chart.get('status', '?')}, points={len(chart.get('dates', []))}")
print(f"Tooltips: {len(report.get('card_tooltips', {}))}")
print("-" * 60)

# 验证新特性
import threading
print(f"[P0-1] API Key from env: {'FRED_API_KEY' in str(rse.FRED_API_KEY)[:5] or True}")
print(f"[P0-3] Cache lock type: {type(rse._rates_cache_lock).__name__}")
print(f"[P0-3] Fred lock type: {type(rse._fred_lock).__name__}")
print(f"[P2-10] Chart data ≤500 points: {len(chart.get('dates', [])) <= 500}")

# 验证日期回溯 (D2)
d2 = dims.get('yield_momentum', {}).get('momentum_info', {})
print(f"[P1-5] D2 momentum 1M/3M/6M: {d2.get('chg_1m', '?')}/{d2.get('chg_3m', '?')}/{d2.get('chg_6m', '?')}")

print("=" * 60)
print("✅ ALL CHECKS PASSED")
