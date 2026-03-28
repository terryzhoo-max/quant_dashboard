import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')

# 1. stop_loss 符号检查
print('[ stop_loss 符号检查 ]')
with open('mr_per_regime_params.json', 'r', encoding='utf-8') as f:
    p = json.load(f)
for r, v in p.get('regimes', {}).items():
    sl = v.get('params', {}).get('stop_loss', 0)
    sign = 'POSITIVE(需确认触发方向)' if sl > 0 else 'NEGATIVE(正常)'
    print(f'  {r}: stop_loss={sl}  -> {sign}')

# 2. 动量引擎检查
print('\n[ 动量轮动引擎关键功能 ]')
with open('momentum_rotation_engine.py', 'r', encoding='utf-8') as f:
    mom = f.read()
for kw, desc in [
    ('detect_regime', '使用Regime识别'),
    ('CRASH', 'CRASH熔断保护'),
    ('stop_loss', '止损逻辑'),
    ('pos_cap', '仓位上限'),
    ('score_gate', '评分门槛'),
]:
    status = 'OK  ' if kw in mom else 'MISS'
    print(f'  [{status}] {desc}')

# 3. 红利引擎检查
print('\n[ 红利趋势引擎关键功能 ]')
with open('dividend_trend_engine.py', 'r', encoding='utf-8') as f:
    div = f.read()
for kw, desc in [
    ('detect_regime', '使用Regime识别'),
    ('CRASH', 'CRASH保护'),
    ('score_gate', '评分门槛'),
    ('stop_loss', '止损'),
    ('bollinger', 'Bollinger因子'),
    ('rsi', 'RSI因子'),
]:
    status = 'OK  ' if kw in div else 'MISS'
    print(f'  [{status}] {desc}')

# 4. 重复路由
print('\n[ API重复路由检查 ]')
with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()
routes = {}
for l in content.split('\n'):
    if '@app.get(' in l or '@app.post(' in l:
        key = l.strip()
        routes[key] = routes.get(key, 0) + 1
dupes = {k: v for k, v in routes.items() if v > 1}
if dupes:
    for r, cnt in dupes.items():
        print(f'  DUPE x{cnt}: {r}')
else:
    print('  无重复路由')

# 5. strategy.html 量级分析
size_h = os.path.getsize('strategy.html')
size_js = os.path.getsize('strategy.js')
size_css = os.path.getsize('strategy.css')
print(f'\n[ 前端文件量级 ]')
print(f'  strategy.html : {size_h:,}B ({size_h/1024:.0f}KB) {"-- 过大，需拆分" if size_h > 200000 else ""}')
print(f'  strategy.js   : {size_js:,}B ({size_js/1024:.0f}KB) {"-- 过大" if size_js > 100000 else ""}')
print(f'  strategy.css  : {size_css:,}B ({size_css/1024:.0f}KB)')

# 6. ThreadPoolExecutor max_workers 检查
mw_lines = [l.strip() for l in content.split('\n') if 'ThreadPoolExecutor' in l]
print(f'\n[ 并发配置 ]')
for l in mw_lines:
    print(f'  {l}')

# 7. 缓存策略检查
cache_lines = [l.strip() for l in content.split('\n') if 'STRATEGY_CACHE' in l or 'cache_ttl' in l.lower()]
print(f'\n[ 缓存配置 ]')
for l in cache_lines[:5]:
    print(f'  {l}')

print('\n=== 深度检查完成 ===')
