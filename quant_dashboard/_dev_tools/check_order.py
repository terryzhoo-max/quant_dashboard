import sys
sys.stdout.reconfigure(encoding='utf-8')
with open('strategy.html','r',encoding='utf-8') as f:
    lines = f.readlines()
for i, l in enumerate(lines):
    if ('st-hero glass-panel' in l or 'mr-active-params' in l or
        'mr-backtest-verify' in l or '标的池构成' in l or 'V3.0 核心参数' in l):
        print(f'{i+1}: {l.rstrip()[:110]}')
