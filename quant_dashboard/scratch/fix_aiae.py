"""Fix strategy.html — handle encoding + line endings"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard\strategy.html', 'rb') as f:
    raw = f.read()

text = raw.decode('utf-8')
lines = text.split('\n')
print(f"Original: {len(lines)} lines")

# Verify
ok = True
if '禁止在 AIAE' not in lines[694]: print(f"L695 WRONG"); ok = False
if '禁止在档位' not in lines[695]: print(f"L696 WRONG"); ok = False
if '禁止因' not in lines[696]: print(f"L697 WRONG"); ok = False
if '禁止总仓位' not in lines[697]: print(f"L698 WRONG"); ok = False
if '</ul>' not in lines[698]: print(f"L699 WRONG"); ok = False
if '</section>' not in lines[701]: print(f"L702 WRONG"); ok = False

if not ok:
    print("ABORT: assertions failed")
    exit(1)

print("Assertions passed. Fixing...")

delete_set = {694, 695, 696, 697, 698}
new_lines = []
for i, line in enumerate(lines):
    if i in delete_set:
        continue
    elif i == 701:
        new_lines.append(line.replace('</section>', '</div>'))
    else:
        new_lines.append(line)

new_text = '\n'.join(new_lines)
print(f"New: {len(new_lines)} lines (removed {len(lines) - len(new_lines)})")

with open(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard\strategy.html', 'wb') as f:
    f.write(new_text.encode('utf-8'))

print("Written successfully!")
