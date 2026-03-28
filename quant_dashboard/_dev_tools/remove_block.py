"""Remove the orphaned momentum strategy description block from strategy.html"""

with open('strategy.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")

# Find the start marker (orphaned st-hero-stats that comes right after /st-signal-rules)
# and the end marker (</div><!-- /st-momentum -->)
start_idx = None
end_idx = None

for i, line in enumerate(lines):
    # Start: the st-hero-stats div that has no wrapping section - around line 1076
    if 'st-hero-stats' in line and start_idx is None:
        # Check if this is the orphaned one (check previous few lines for context)
        context = ''.join(lines[max(0,i-5):i])
        if 'st-signal-rules' in context or i > 1070:
            start_idx = i
            print(f"Found start at L{i+1}: {line.strip()[:60]}")
    
    # End: the closing comment of the momentum block  
    if '/st-momentum' in line and start_idx is not None:
        end_idx = i
        print(f"Found end at L{i+1}: {line.strip()[:60]}")
        break

if start_idx is not None and end_idx is not None:
    print(f"\nRemoving lines {start_idx+1} to {end_idx+1} ({end_idx-start_idx+1} lines)")
    # Remove those lines
    new_lines = lines[:start_idx] + lines[end_idx+1:]
    with open('strategy.html', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print(f"Done. New total: {len(new_lines)} lines")
else:
    print(f"Block not found. start={start_idx}, end={end_idx}")
    # Print lines around 1073-1085
    for i in range(1073, min(1090, len(lines))):
        print(f"L{i+1}: {repr(lines[i][:80])}")
