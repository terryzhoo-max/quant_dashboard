"""
Deep dive: check if st-erp-timing is a DIRECT child of the content container,
or if it's accidentally nested inside another st-report div.
"""
import re

with open(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard\strategy.html', 'rb') as f:
    text = f.read().decode('utf-8')

lines = text.split('\n')

# Track depth from the content container to find each st-report's nesting level
# First, find "content pf-content"
content_line = None
for i, l in enumerate(lines):
    if 'class="content pf-content"' in l:
        content_line = i
        break

if content_line is None:
    print("ERROR: content pf-content not found!")
    exit()

print(f"Content container at line {content_line + 1}")

# Now track depth from content_line forward
depth = 0
# Start tracking from after the content div opens
for i in range(content_line, len(lines)):
    l = lines[i]
    opens = len(re.findall(r'<div[\s>]', l))
    closes = l.count('</div>')
    
    # Check if this line has an st-report
    if 'class="st-report' in l:
        m = re.search(r'id="([^"]*)"', l)
        report_id = m.group(1) if m else '?'
        print(f"  L{i+1}: st-report#{report_id} at depth={depth} (opens={opens})")
    
    # Check if line has st-tab-bar
    if 'class="st-tab-bar"' in l:
        print(f"  L{i+1}: st-tab-bar at depth={depth}")
    
    depth += opens - closes
    
    # Stop after st-erp-timing closing
    if '<!-- /st-erp-timing -->' in l:
        print(f"  L{i+1}: /st-erp-timing depth={depth}")
        break

print(f"\nFinal depth after ERP section: {depth}")

# Also check: are there any rogue </div> between st-execution close and st-erp-timing open?
print("\n--- Lines between st-execution close and st-erp-timing open ---")
exec_close = None
erp_open = None
for i, l in enumerate(lines):
    if '<!-- /st-execution -->' in l:
        exec_close = i
    if 'id="st-erp-timing"' in l:
        erp_open = i
        break

if exec_close and erp_open:
    for i in range(exec_close, erp_open + 1):
        l = lines[i].strip()
        if l and not l.startswith('<!--') and l != '':
            print(f"  L{i+1}: {l[:120]}")

# Check full div balance for EACH st-report section
print("\n--- Per-section div balance ---")
sections = []
for i, l in enumerate(lines):
    if 'class="st-report' in l:
        m = re.search(r'id="([^"]*)"', l)
        sections.append((i, m.group(1) if m else '?'))

for idx, (start, sid) in enumerate(sections):
    end_line = sections[idx + 1][0] if idx + 1 < len(sections) else len(lines)
    depth = 0
    min_depth = 999
    for i in range(start, end_line):
        l = lines[i]
        opens = len(re.findall(r'<div[\s>]', l))
        closes = l.count('</div>')
        depth += opens - closes
        min_depth = min(min_depth, depth)
    print(f"  {sid}: lines {start+1}-{end_line}, final_depth={depth}, min_depth={min_depth}")
