"""AlphaCore V5.0 · 执行后完整验证"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')

print('=' * 60)
print('  AlphaCore V5.0 · 全量验证报告')
print('=' * 60)

results = []

def check(name, cond, detail=''):
    ok = bool(cond)
    status = 'PASS' if ok else 'FAIL'
    tag = '✅' if ok else '❌'
    print(f'  {tag} [{status}] {name}' + (f'  →  {detail}' if detail else ''))
    results.append(ok)
    return ok

print('\n[ 1. 核心文件存在性 ]')
for f in ['main.py','mean_reversion_engine.py','momentum_rotation_engine.py',
          'dividend_trend_engine.py','mr_per_regime_params.json','config.py',
          'strategy.html','strategy.js','strategy.css']:
    check(f, os.path.exists(f), f'{os.path.getsize(f):,}B' if os.path.exists(f) else 'MISSING')

print('\n[ 2. stop_loss 符号验证 ]')
with open('mr_per_regime_params.json','r',encoding='utf-8') as f:
    jp = json.load(f)
for r in ['BEAR','RANGE','BULL']:
    sl = jp['regimes'][r]['params']['stop_loss']
    check(f'{r}.stop_loss 为负数', sl < 0, str(sl))

print('\n[ 3. 重复路由消除验证 ]')
with open('main.py','r',encoding='utf-8') as f:
    mc = f.read()
cnt = mc.count('@app.get("/api/v1/industry-tracking")')
check('industry-tracking 路由唯一', cnt == 1, f'出现 {cnt} 次')

print('\n[ 4. 统一 Regime 算法接入 ]')
with open('momentum_rotation_engine.py','r',encoding='utf-8') as f:
    mom = f.read()
check('动量引擎导入 _classify_regime_from_series', '_classify_regime_from_series' in mom)
check('动量引擎有统一Regime覆盖', 'unified_regime' in mom)
check('动量引擎有CRASH熔断', 'CRASH' in mom)

with open('dividend_trend_engine.py','r',encoding='utf-8') as f:
    div = f.read()
check('红利引擎自动识别Regime', 'detect_regime' in div)
check('红利引擎V3.2升级', 'V3.2' in div)

print('\n[ 5. 缓存 TTL 智能化 ]')
check('main.py 有 _get_cache_ttl', '_get_cache_ttl' in mc)
check('main.py 盘中 300s', '300' in mc and '_get_cache_ttl' in mc)

with open('strategy.js','r',encoding='utf-8') as f:
    js = f.read()
check('strategy.js regime TTL 动态计算', '_getRegimeCacheTTL' in js)

print('\n[ 6. 新功能验证 ]')
check('计算器自动填入按钮', 'calc-auto-fill-btn' in open('strategy.html','r',encoding='utf-8').read())
check('autoFillCalcRegime 函数', 'autoFillCalcRegime' in js)
check('Regime 徽章发光 CSS', 'regime-bear-glow' in open('strategy.css','r',encoding='utf-8').read())
check('Skeleton loading CSS', 'skeleton-shimmer' in open('strategy.css','r',encoding='utf-8').read())

print('\n[ 7. 版本号统一 ]')
with open('strategy.html','r',encoding='utf-8') as f:
    html = f.read()
check('Tab显示V4.1', '均值回归策略 V4.1' in html)
check('Tab显示V3.2', '红利趋势策略 V3.2' in html)
check('Hero显示AlphaCore V5.0', 'AlphaCore V5.0' in html)
check('V4.1面板标题', 'V4.1 · 当前激活参数' in html)

print('\n[ 8. _dev_tools 整理 ]')
check('_dev_tools 目录存在', os.path.isdir('_dev_tools'))
dt_files = os.listdir('_dev_tools') if os.path.isdir('_dev_tools') else []
check('debug文件已归档', len(dt_files) > 10, f'{len(dt_files)} 个文件')
check('config.py 已创建', os.path.exists('config.py'))

print('\n[ 9. 语法检查 ]')
import subprocess
for f in ['main.py','mean_reversion_engine.py','momentum_rotation_engine.py',
          'dividend_trend_engine.py','config.py']:
    r = subprocess.run([sys.executable,'-m','py_compile',f], capture_output=True)
    check(f'{f} 语法正确', r.returncode == 0, r.stderr.decode(errors='ignore').strip() or 'OK')

print()
passed = sum(results)
total = len(results)
pct = int(passed / total * 100)
print('=' * 60)
print(f'  总计: {passed}/{total} 通过 ({pct}%)')
if pct == 100:
    print('  🎉 V5.0 全量验证 100% 通过！')
elif pct >= 90:
    print('  ✅ 主要功能验证通过，少量细节待确认')
else:
    print('  ⚠️  存在验证失败项，请检查')
print('=' * 60)
