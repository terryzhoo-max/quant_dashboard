import sys, json, os
sys.stdout.reconfigure(encoding='utf-8')

checks = []

# 1. 回测结果文件
assert os.path.exists('mr_optimization_results.json')
with open('mr_optimization_results.json','r',encoding='utf-8') as f:
    r = json.load(f)
kpi = r.get('regime_overlay_kpi', {})
assert kpi.get('alpha', 0) > 0
checks.append(f"[OK] mr_optimization_results.json: alpha={kpi['alpha']}% max_dd={kpi['max_dd']}%")

# 2. HTML 区块
with open('strategy.html','r',encoding='utf-8') as f:
    html = f.read()
assert 'mr-backtest-verify' in html
assert 'mr-equity-chart' in html
assert 'Regime Overlay' in html
checks.append('[OK] strategy.html: V3.0 backtest section present')

# 3. JS 函数
with open('strategy.js','r',encoding='utf-8') as f:
    js = f.read()
assert 'loadMrBacktestData' in js
assert '_renderMrBacktest' in js
checks.append('[OK] strategy.js: chart render functions present')

# 4. main.py API 路由
with open('main.py','r',encoding='utf-8') as f:
    py = f.read()
assert 'mr_backtest_results' in py
checks.append('[OK] main.py: /api/v1/mr_backtest_results route present')

# 5. 实盘引擎参数
with open('mean_reversion_engine.py','r',encoding='utf-8') as f:
    eng = f.read()
assert 'rsi <= 35' in eng
assert 'rsi >= 70' in eng
assert 'bias <= -2.0' in eng
checks.append('[OK] mean_reversion_engine.py: V3.0 optimized params applied')

for c in checks:
    print(c)
print()
print('=== ALL CHECKS PASSED - Ready to commit ===')
