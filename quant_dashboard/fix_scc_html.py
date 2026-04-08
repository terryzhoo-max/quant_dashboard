import os

dashboard_dir = r"d:\FIONA\google AI\quant_dashboard"
scc_html = os.path.join(dashboard_dir, "scc_audit.html")

with open(scc_html, 'r', encoding='utf-8') as f:
    html_content = f.read()

# Replace wus prefixes
html_content = html_content.replace('wus-', 'scc-').replace('wus_', 'scc_')

# Remove duplicate SCC link
scc_link = '<a href="./scc_audit.html" class="nav-item active"><span class="icon">💻</span><span>深南电路</span><span class="badge-beta" style="background:rgba(236,72,153,0.15);color:#f472b6;border-color:rgba(236,72,153,0.3);">DEEP</span></a>\n'
html_content = html_content.replace(scc_link, '')

with open(scc_html, 'w', encoding='utf-8') as f:
    f.write(html_content)

print("Fixed scc_audit.html")

html_files = [f for f in os.listdir(dashboard_dir) if f.endswith('.html')]
scc_nav_link = '                <a href="./scc_audit.html" class="nav-item"><span class="icon">📡</span><span>深南电路</span><span class="badge-beta" style="background:rgba(139,92,246,0.15);color:#a855f7;border-color:rgba(139,92,246,0.3);">DEEP</span></a>'
scc_nav_link_active = scc_nav_link.replace('class="nav-item"', 'class="nav-item active"')

for hf in html_files:
    if hf == 'scc_audit.html': continue
    path = os.path.join(dashboard_dir, hf)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # If already has scc_audit, skip
    if 'scc_audit.html' in content: continue
    
    # Find wus_audit element and append
    lines = content.split('\n')
    new_lines = []
    for line in lines:
        new_lines.append(line)
        if 'wus_audit.html' in line:
            new_lines.append(scc_nav_link)
    
    # Avoid writing if no changes
    if len(new_lines) != len(lines):
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(new_lines))
        print(f"Updated {hf}")
