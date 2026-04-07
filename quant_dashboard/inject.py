import os
import glob

target = '''<a href="./wus_audit.html" class="nav-item"><span class="icon">💻</span><span>沪电股份</span><span class="badge-beta" style="background:rgba(236,72,153,0.15);color:#f472b6;border-color:rgba(236,72,153,0.3);">DEEP</span></a>
            </div>'''

for f in glob.glob('*.html'):
    if f == 'wus_audit.html': continue
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    if 'wus_audit.html' in content: continue
    
    if 'fii_audit.html' in content:
        content = content.replace('</a>\n            </div>\n            <div class="nav-group-title">账 户 管 理</div>',
                                  '</a>\n                ' + target + '\n            <div class="nav-group-title">账 户 管 理</div>')
        with open(f, 'w', encoding='utf-8') as file:
            file.write(content)
print("Done")
