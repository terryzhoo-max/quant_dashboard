"""Fix corrupted calc-vol/calc-rsi HTML in strategy.html"""
import re

with open('strategy.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and print context around line 990-1000 (0-indexed: 989-999)
print("=== Current lines 989-1002 ===")
for i in range(989, 1002):
    print(f"L{i+1}: {repr(lines[i])}")

# Rebuild the broken block (lines 990-999, 0-indexed 989-998)
# Replace lines 989-998 (inclusive of the entire broken block)
fixed_block = [
    '                        <div>\n',
    '                            <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:6px;">量比</label>\n',
    '                            <select id="calc-vol" onchange="calcSignalScore()" style="width:100%; background:rgba(255,255,255,0.05); color:#fff; border:1px solid rgba(255,255,255,0.1); border-radius:8px; padding:9px; font-family:inherit; outline:none;">\n',
    '                                <option value="15">≥ 1.5x (放量)</option>\n',
    '                                <option value="8" selected>1.0–1.5x</option>\n',
    '                                <option value="0">&lt; 1.0x (缩量)</option>\n',
    '                            </select>\n',
    '                        </div>\n',
    '                        <div>\n',
    '                            <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:6px;">RSI (技术位)</label>\n',
    '                            <select id="calc-rsi" onchange="calcSignalScore()" style="width:100%; background:rgba(255,255,255,0.05); color:#fff; border:1px solid rgba(255,255,255,0.1); border-radius:8px; padding:9px; font-family:inherit; outline:none;">\n',
    '                                <option value="15" selected>40–65 (健康)</option>\n',
    '                                <option value="10">30–40 (超卖)</option>\n',
    '                                <option value="5">&lt; 30 (极度超卖)</option>\n',
    '                                <option value="0">&gt; 70 (过热，否决)</option>\n',
    '                            </select>\n',
    '                        </div>\n',
]

# Check the content of lines 989-998
bad_marker = '.1); border-radius'
bad_idx = None
for i in range(988, 1005):
    if bad_marker in lines[i]:
        bad_idx = i
        break

if bad_idx is not None:
    print(f"\nFound bad line at index {bad_idx} (L{bad_idx+1}): {repr(lines[bad_idx])}")
    # The broken block starts 2 lines before bad_marker (the <div> and <label> lines)
    start = bad_idx - 2
    # End is after the next </select> and </div>
    end = bad_idx + 7  # covers through the closing </div>
    print(f"Replacing lines {start+1} to {end+1}")
    lines[start:end+1] = fixed_block
    with open('strategy.html', 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print("DONE - file saved")
else:
    print("\nBad marker not found!")
    # Also check if already fixed
    full = ''.join(lines)
    if 'id="calc-vol"' in full:
        print("calc-vol already present - may already be fixed")
    else:
        print("calc-vol MISSING - still broken")
