import sys, re
sys.stdout.reconfigure(encoding='utf-8')
with open('strategy.html','r',encoding='utf-8') as f:
    content = f.read()

# 找出版本号出现位置
patterns = ['V4.0', 'V3.1', 'V1.0', 'V2.0', 'AlphaCore']
lines = content.split('\n')
for i, l in enumerate(lines, 1):
    for p in patterns:
        if p in l and any(t in l.lower() for t in ['button', 'h2', 'h3', 'span', 'title', 'data-report']):
            print(str(i) + ': ' + l.strip()[:120])
            break
