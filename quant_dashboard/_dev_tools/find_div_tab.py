import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
with open('strategy.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    s = line.strip()
    if 'st-dividend-trend' in s:
        print(f'L{i+1}: {s[:120]}')
