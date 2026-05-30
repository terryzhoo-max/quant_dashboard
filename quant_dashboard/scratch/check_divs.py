import re

with open(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard\strategy.html', 'rb') as f:
    text = f.read().decode('utf-8')

lines = text.split('\n')

# Count divs in the ERP section (line 8118 to 8462, 1-indexed)
# The opening <div> at line 8118 is depth 1
depth = 0
for i in range(8117, 8462):
    if i >= len(lines):
        break
    l = lines[i]
    o = len(re.findall(r'<div[\s>]', l))
    c = l.count('</div>')
    if o or c:
        depth += o - c
        try:
            line_preview = l.strip()[:120]
            print(f'L{i+1}: depth={depth:+d} o={o} c={c} | {line_preview}')
        except:
            print(f'L{i+1}: depth={depth:+d} o={o} c={c} | (encoding)')
        if depth <= 0 and i > 8117:
            print(f'  *** st-erp-timing CLOSED at line {i+1}!')
            break

print(f"\nFinal depth at analysis end: {depth}")
