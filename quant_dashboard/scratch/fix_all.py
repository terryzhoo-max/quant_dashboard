"""
Complete fix for strategy.html AIAE nesting bug.

Root cause: In AIAE section, lines 695-699 contain orphaned <li>/<ul> tags 
that shouldn't be there. Line 702 has </section> instead of </div>.
Additionally, the last aiae-history-stat div (line 692) is missing its 
closing </div>.

This script:
1. Removes lines 695-699 (orphaned li/ul tags)
2. Changes line 702 </section> -> </div>
3. Adds missing </div> after line 694 to close aiae-history-stat

Also applies:
4. Version bump CSS/JS from v=201 -> v=203
5. ERP identity-bar display:flex fix
6. SW cache version bump (separate file)
"""
import sys, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

filepath = r'd:\FIONA\google AI\quant_dashboard\quant_dashboard\strategy.html'

with open(filepath, 'rb') as f:
    text = f.read().decode('utf-8')

lines = text.split('\n')
print(f"Original: {len(lines)} lines")

# === AIAE FIX ===
# Verify lines (1-indexed: 695-699 are orphaned, 702 is wrong </section>)
assert '禁止在 AIAE' in lines[694], f"L695 unexpected: {lines[694].strip()[:40]}"
assert '</ul>' in lines[698], f"L699 unexpected"
assert '</section>' in lines[701], f"L702 unexpected: {lines[701].strip()[:40]}"

# Build fix: delete lines 695-699, change 702 to </div>, add </div> after 694
delete_set = {694, 695, 696, 697, 698}  # 0-indexed (lines 695-699)

new_lines = []
for i, line in enumerate(lines):
    if i in delete_set:
        continue
    elif i == 701:  # Line 702: </section> -> </div>
        new_lines.append(line.replace('</section>', '</div>'))
    elif i == 693:  # After line 694 (stat-value), add missing </div> for stat
        new_lines.append(line)  # Keep the stat-label line
    else:
        new_lines.append(line)

# Now find where to insert the missing </div> for aiae-history-stat
# After deleting 5 lines, old line 694 (stat-value) becomes the line after 693 (stat-label)
# We need to add a closing </div> for aiae-history-stat after the stat-value
# Let's find the stat-value line in new_lines and add </div> after it
for idx, line in enumerate(new_lines):
    if 'Ⅰ级后均+90%' in line:
        # Insert </div> after this line to close aiae-history-stat
        indent = '                        '  # Match the indentation of sibling </div>s
        new_lines.insert(idx + 1, indent + '</div>\r')
        print(f"Inserted missing </div> after new line {idx+1}")
        break

# === VERSION BUMP ===
# CSS
for idx, line in enumerate(new_lines):
    if 'strategy.css?v=201' in line:
        new_lines[idx] = line.replace('strategy.css?v=201', 'strategy.css?v=203')
        print(f"Bumped strategy.css to v=203")
    # JS files
    for old, new in [
        ('alphacore_utils.js?v=201', 'alphacore_utils.js?v=203'),
        ('strategy.js?v=201', 'strategy.js?v=203'),
        ('strategy_erp.js?v=201', 'strategy_erp.js?v=203'),
        ('strategy_aiae.js?v=201', 'strategy_aiae.js?v=203'),
        ('strategy_gem.js?v=201', 'strategy_gem.js?v=203'),
        ('sidebar.js?v=201', 'sidebar.js?v=203'),
    ]:
        if old in line:
            new_lines[idx] = line.replace(old, new)
            print(f"Bumped {old.split('?')[0]} to v=203")

# === ERP IDENTITY BAR FIX ===
for idx, line in enumerate(new_lines):
    if 'id="erp-identity-bar"' in line and 'display:flex' not in line:
        old_style = 'style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 50%,#0c4a6e 100%);border-left:4px solid #f59e0b;position:relative;overflow:hidden;"'
        new_style = 'style="display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-radius:12px;background:linear-gradient(135deg,#0f172a 0%,#1e293b 50%,#0c4a6e 100%);border:1px solid rgba(245,158,11,0.15);border-left:4px solid #f59e0b;position:relative;overflow:hidden;"'
        if old_style in line:
            new_lines[idx] = line.replace(old_style, new_style)
            print(f"Fixed ERP identity-bar style at line {idx+1}")

# Write result
result_text = '\n'.join(new_lines)
with open(filepath, 'wb') as f:
    f.write(result_text.encode('utf-8'))

final_lines = result_text.split('\n')
print(f"\nFinal: {len(final_lines)} lines")
print("All fixes applied successfully!")
