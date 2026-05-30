"""Find ALL unclosed elements in AIAE section"""
import re

with open(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard\strategy.html', 'rb') as f:
    text = f.read().decode('utf-8')

lines = text.split('\n')

# Track a stack of open elements
stack = []  # [(line_num, tag_name, brief_desc)]

for i in range(213, 782):
    l = lines[i]
    
    # Find all opening tags: <div, <section (not self-closing)
    for m in re.finditer(r'<(div|section)([\s>])', l):
        tag = m.group(1)
        # Check if self-closing on same line
        # Simple heuristic: count opens vs closes of this tag on this line
        # Just push to stack
        brief = l.strip()[:80]
        stack.append((i+1, tag, brief))
    
    # Find all closing tags
    for m in re.finditer(r'</(div|section)>', l):
        tag = m.group(1)
        if stack:
            stack.pop()
        else:
            print(f"EXTRA closing </{tag}> at L{i+1}")

    # Handle self-closing divs (open and close on same line)
    # We already pushed opens above, now need to pop for closes on same line
    # Actually this is already handled by the loop above since we process opens then closes

# Fix: re-do with proper per-line counting
stack = []
for i in range(213, 782):
    l = lines[i]
    opens_div = len(re.findall(r'<div[\s>]', l))
    closes_div = l.count('</div>')
    opens_sec = len(re.findall(r'<section[\s>]', l))
    closes_sec = l.count('</section>')
    
    # Process opens
    for _ in range(opens_div):
        brief = l.strip()[:80]
        stack.append((i+1, 'div', brief))
    for _ in range(opens_sec):
        brief = l.strip()[:80]
        stack.append((i+1, 'section', brief))
    
    # Process closes (LIFO)
    for _ in range(closes_div + closes_sec):
        if stack:
            stack.pop()

if stack:
    print(f"\n{len(stack)} UNCLOSED element(s) remaining:")
    for line_num, tag, brief in stack:
        print(f"  L{line_num}: <{tag}>  {brief}")
else:
    print("All elements properly closed!")
