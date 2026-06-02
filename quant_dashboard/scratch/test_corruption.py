# -*- coding: utf-8 -*-
"""测试 JSON 损坏熔断机制"""
import os
import sys

# 切换到 quant_dashboard 内部以便加载 modules
sys.path.insert(0, r'd:\FIONA\google AI\quant_dashboard\quant_dashboard')
os.chdir(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard')

from engines.audit_engine import audit_strategy_health

JSON_FILE = "dividend_optimization_results.json"

if not os.path.exists(JSON_FILE):
    print(f"Error: {JSON_FILE} not found!")
    sys.exit(1)

# 1. 备份原文件
with open(JSON_FILE, "r", encoding="utf-8") as f:
    original_content = f.read()

try:
    # 2. 写入损坏的 JSON (大于 50 字节，以绕过文件大小非空检查)
    print("Writing corrupted JSON data (>50 bytes)...")
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        f.write("{ corrupted json: [invalid data, repeat to bypass size limit] " * 2)

    # 3. 运行审计引擎并检查
    r = audit_strategy_health()
    
    print("Available checks:")
    for c in r["checks"]:
        print(f"  - {c['name']} (Type: {type(c['name'])})")
        
    div_check = next((c for c in r["checks"] if c["name"] == "红利趋势"), None)
    if div_check:
        print("--- Check Result for Dividend Trend ---")
        print(f"Name:   {div_check['name']}")
        print(f"Status: {div_check['status']}")
        print(f"Score:  {div_check['score']}")
        print(f"Detail: {div_check['detail']}")
        
        # 验证是否成功处罚
        assert div_check['status'] == "fail", "Error: status should be fail!"
        assert div_check['score'] == 20, "Error: score should be 20!"
        assert "损坏" in div_check['detail'], "Error: detail should mention corruption!"
        print("\n[SUCCESS] Corruption Wind-control Interlocking verification passed!")
    else:
        print("Error: Dividend Trend check item not found in checks!")

finally:
    # 4. 还原原文件
    print("Restoring original JSON data...")
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        f.write(original_content)
    print("Restore complete.")
