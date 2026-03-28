import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
print('=== ALPHACORE 系统完整性自检 ===\n')

# 1. 核心文件
core_files = {
    'main.py': '后端主服务',
    'mean_reversion_engine.py': '均值回归V4.0引擎',
    'dividend_trend_engine.py': '红利策略引擎',
    'momentum_rotation_engine.py': '动量轮动引擎',
    'mr_per_regime_params.json': '三态参数文件',
    'mr_per_regime_optimizer.py': '60天重优化器',
    'mr_auto_optimize.py': '自动调度器',
    'strategy.html': '策略中心页面',
    'strategy.js': '策略JS逻辑',
    'strategy.css': '样式文件',
    'index.html': '主仪表盘',
    'script.js': '主仪表盘JS',
    'styles.css': '主样式',
    'backtest.html': '回测平台',
    'portfolio.html': '投资组合',
    'industry.html': '产业追踪',
}
print('[ 核心文件完整性 ]')
for f, desc in core_files.items():
    exists = os.path.exists(f)
    size = os.path.getsize(f) if exists else 0
    status = 'OK   ' if exists and size > 1000 else ('SMALL' if exists else 'MISS ')
    print(f'  [{status}] {f:42} {desc}  ({size:,}B)')

# 2. 参数文件
print('\n[ 三态参数健康 ]')
with open('mr_per_regime_params.json', 'r', encoding='utf-8') as f:
    p = json.load(f)
reg = p.get('regimes', {})
for r in ['BEAR', 'RANGE', 'BULL']:
    if r in reg:
        pr = reg[r].get('params', {})
        ma = pr.get('N_trend')
        rb = pr.get('rsi_buy')
        rs = pr.get('rsi_sell')
        bb = pr.get('bias_buy')
        sl = pr.get('stop_loss')
        print(f'  {r:5}: MA{ma} RSI_buy={rb} RSI_sell={rs} bias={bb} stop={sl}')
print('  next_optimize_after:', p.get('next_optimize_after'))

# 3. API路由
print('\n[ API路由统计 ]')
with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()
routes = [l.strip() for l in content.split('\n') if '@app.get(' in l or '@app.post(' in l]
print(f'  共 {len(routes)} 个路由')
for r in routes:
    r2 = r.replace('@app.get(', 'GET ').replace('@app.post(', 'POST').strip()
    print(f'  {r2}')

# 4. strategy.html 关键元素
print('\n[ strategy.html 元素 ]')
with open('strategy.html', 'r', encoding='utf-8') as f:
    h = f.read()
checks = {
    'mr-active-params': 'V4.0激活参数面板',
    'mr-regime-badge': 'Regime徽章',
    'mr-regime-table-body': '三态速览表',
    'mr-reopt-banner': '重优化提示横幅',
    'st-signal-rules': '信号评分tab',
    'regime-result': '信号评分Regime面板',
    'calc-regime': '评分计算器-市场状态',
    'st-mean-reversion': '均值回归tab',
    'st-dividend': '红利策略tab',
    'st-momentum': '动量轮动tab',
    'mr-backtest-verify': '回测验证区块',
    'div-calc-regime': '红利评分-市场状态',
    'mr-three-regime-table': '三态对比表容器',
}
for elem, desc in checks.items():
    found = elem in h
    print(f'  [{"OK  " if found else "MISS"}] #{elem:30} {desc}')

# 5. strategy.js 关键函数
print('\n[ strategy.js 关键函数 ]')
with open('strategy.js', 'r', encoding='utf-8') as f:
    js = f.read()
fns = [
    ('loadMrCurrentParams', 'V4.0参数自动加载'),
    ('_renderMrActiveParams', 'V4.0参数渲染'),
    ('_classifyRegimeFromSeries', '统一Regime算法(JS备份)'),
    ('loadMarketRegime', '信号评分Regime'),
    ('renderRegime', '信号评分渲染'),
    ('calcSignalScore', '信号评分计算'),
    ('calcDividendScore', '红利评分计算'),
    ('loadMrBacktestData', 'MR回测数据加载'),
]
for fn, desc in fns:
    found = fn in js
    print(f'  [{"OK  " if found else "MISS"}] {fn:30} {desc}')

# 6. 数据湖检查
print('\n[ 数据湖检查 ]')
dl = 'data_lake'
if os.path.exists(dl):
    files = os.listdir(dl)
    print(f'  data_lake/ 共 {len(files)} 个缓存文件')
    if files:
        for f in files[:5]:
            fp = os.path.join(dl, f)
            size = os.path.getsize(fp)
            print(f'    {f}: {size:,}B')
        if len(files) > 5:
            print(f'    ... 另有 {len(files)-5} 个文件')
else:
    print('  data_lake/ 不存在')

print('\n=== 自检完成 ===')
