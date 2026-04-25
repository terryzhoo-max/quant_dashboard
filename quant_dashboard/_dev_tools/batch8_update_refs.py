"""Batch 8: 批量更新 HTML 文件中的 CSS/JS 引用路径"""
import re
import os
import glob

ROOT = r"d:\FIONA\google AI\quant_dashboard"

CSS_FILES = [
    "styles.css", "audit.css", "audit_bridge.css", "backtest.css",
    "byd_audit.css", "eastmoney_audit.css", "factor.css", "fii_audit.css",
    "industry.css", "portfolio.css", "scc_audit.css", "smic_audit.css",
    "strategy.css", "treasury.css", "wus_audit.css", "zijin_audit.css",
]

JS_FILES = [
    "script.js", "strategy.js", "strategy_aiae.js", "strategy_erp.js",
    "audit.js", "audit_core.js", "backtest.js", "factor.js",
    "industry.js", "treasury.js", "portfolio.js", "portfolio_manager.js",
    "alphacore_utils.js", "byd_data.js", "eastmoney_data.js", "fii_data.js",
    "scc_data.js", "smic_data.js", "wus_data.js", "zijin_data.js",
]

total = 0

for html_path in glob.glob(os.path.join(ROOT, "*.html")):
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    count = 0

    for css in CSS_FILES:
        old_patterns = [f'href="./{ css}', f"href='./{css}", f'href="{css}', f"href='{css}"]
        for old in old_patterns:
            new = old.replace(css, f"static/css/{css}")
            if old in content:
                content = content.replace(old, new)
                count += 1

    for js in JS_FILES:
        old_patterns = [f'src="./{js}', f"src='./{js}", f'src="{js}', f"src='{js}"]
        for old in old_patterns:
            new = old.replace(js, f"static/js/{js}")
            if old in content:
                content = content.replace(old, new)
                count += 1

    # echarts vendor
    for pat in ['src="./echarts.min.js"', "src='./echarts.min.js'"]:
        new = pat.replace("echarts.min.js", "static/vendor/echarts.min.js")
        if pat in content:
            content = content.replace(pat, new)
            count += 1

    # inline fallback
    old_fb = 'src=\\"./echarts.min.js\\"'
    new_fb = 'src=\\"./static/vendor/echarts.min.js\\"'
    if old_fb in content:
        content = content.replace(old_fb, new_fb)
        count += 1

    if content != original:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  [OK] {os.path.basename(html_path)}: {count} refs updated")
        total += count
    else:
        print(f"  [--] {os.path.basename(html_path)}: no changes")

print(f"\nTotal: {total} references updated")
