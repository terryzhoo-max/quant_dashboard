import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('strategy.html', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# 找 mr-active-params section 起止行
start_ap = None
for i, l in enumerate(lines):
    if 'id="mr-active-params"' in l:
        start_ap = i
        break

end_ap = None
depth = 0
for i in range(start_ap, len(lines)):
    opens  = lines[i].count('<section')
    closes = lines[i].count('</section')
    depth += opens - closes
    if depth == 0 and i > start_ap:
        end_ap = i
        break

print(f'mr-active-params: lines {start_ap+1} to {end_ap+1}')

# 找均值回归tab中的 Hero section（无 style 属性的那个，在 st-mean-reversion div 内，行号 < start_ap）
start_hero = None
for i in range(0, start_ap):
    l = lines[i]
    if 'class="st-hero glass-panel">' in l and 'style=' not in l:
        start_hero = i
        break

end_hero = None
depth = 0
for i in range(start_hero, len(lines)):
    depth += lines[i].count('<section') - lines[i].count('</section')
    if depth == 0 and i > start_hero:
        end_hero = i
        break

print(f'Hero section: lines {start_hero+1} to {end_hero+1}')

hero_block = lines[start_hero:end_hero+1]
ap_block   = lines[start_ap:end_ap+1]

# 新顺序：Hero之前 + Hero + 中间内容 + ap_block + ap之后
# 用户要求：ap_block 移到 Hero **下方**
# 即：hero_block 先，中间原来 hero_end+1 到 start_ap-1 的内容，ap_block 在其后
new_lines = (
    lines[:start_hero] +           # hero 之前（tab容器等）
    hero_block +                   # Hero section
    [''] +                         # 空行
    lines[end_hero+1:start_ap] +   # 中间内容（标的池、参数表等）
    ap_block +                     # V4.0 激活参数面板
    lines[end_ap+1:]               # 面板之后（流程图、回测验证等）
)

with open('strategy.html', 'w', encoding='utf-8', newline='\r\n') as f:
    f.write('\n'.join(new_lines))

print('Done. New order: Hero -> ... -> V4.0 ActiveParams ->')
