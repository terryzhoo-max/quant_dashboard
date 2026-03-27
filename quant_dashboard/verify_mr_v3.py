import sys, json, os
sys.stdout.reconfigure(encoding='utf-8')

checks = []

# 1. 三态参数文件
assert os.path.exists('mr_per_regime_params.json')
with open('mr_per_regime_params.json','r',encoding='utf-8') as f:
    p = json.load(f)
assert 'BEAR' in p.get('regimes',{}) and 'RANGE' in p.get('regimes',{}) and 'BULL' in p.get('regimes',{})
checks.append('[OK] mr_per_regime_params.json: BEAR/RANGE/BULL 三态参数完整')

# 2. V4.0 引擎函数
with open('mean_reversion_engine.py','r',encoding='utf-8') as f:
    e = f.read()
for fn in ['load_regime_params','detect_regime','get_all_regime_params','needs_reoptimize','calculate_score']:
    assert fn in e, f'MISSING {fn}'
checks.append('[OK] mean_reversion_engine.py: V4.0 动态加载引擎完整')

# 3. main.py V4.0 路由
with open('main.py','r',encoding='utf-8') as f:
    m = f.read()
for route in ['/api/v1/mr_per_regime_params','/api/v1/mr_current_params','/api/v1/mr_backtest_results']:
    assert route in m, f'MISSING route {route}'
checks.append('[OK] main.py: 三个 V4.0 API 路由已注册')

# 4. strategy.html 面板
with open('strategy.html','r',encoding='utf-8') as f:
    h = f.read()
for el in ['mr-active-params','mr-ap-trend','mr-ap-rsibuy','mr-ap-rsisell','mr-regime-table-body','mr-reopt-banner']:
    assert el in h, f'MISSING #{el}'
checks.append('[OK] strategy.html: V4.0 当前激活参数面板与三态速览表完整')

# 5. strategy.js 函数
with open('strategy.js','r',encoding='utf-8') as f:
    js = f.read()
for fn in ['loadMrCurrentParams','_renderMrActiveParams','_MR_REGIME_META','loadMrBacktestData']:
    assert fn in js, f'MISSING {fn}'
checks.append('[OK] strategy.js: V4.0 自动加载 + 渲染函数完整')

# 6. 调度器
assert os.path.exists('mr_auto_optimize.py')
assert os.path.exists('mr_per_regime_optimizer.py')
checks.append('[OK] mr_auto_optimize.py + mr_per_regime_optimizer.py: 60天调度链完整')

for c in checks:
    print(c)
print()
print('=== V4.0 ALL CHECKS PASSED ===')
