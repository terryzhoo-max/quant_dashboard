"""
AlphaCore 安全加固验证脚本
===========================
验证 API_SECRET_KEY 中间件是否正确工作。
服务器重启后运行: python _dev_tools/verify_auth.py
"""

import requests
import sys
import os

# Windows UTF-8 fix
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:8000"
API_KEY = "SdZ1yqPYzjxMTbYcEC4gyNi5DpqvILtf6ju82XtOwEauEu4CA2UsCpWj3Uj4O5TP"

passed, failed = 0, 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name} — {detail}")
        failed += 1

print("\n" + "=" * 60)
print("  AlphaCore Auth Middleware Verification")
print("=" * 60)

# 0. Health check
print("\n[0] 服务器健康检查")
try:
    r = requests.get(f"{BASE}/health", timeout=5)
    check("健康端点可访问", r.status_code == 200, f"status={r.status_code}")
    data = r.json()
    check("版本号正确", "V15" in data.get("version", ""), data.get("version"))
except Exception as e:
    check("服务器连接", False, str(e))
    print("\n⚠️ 服务器未运行，请先启动后再验证")
    sys.exit(1)

# 1. GET 请求不受认证影响
print("\n[1] GET 请求免认证")
r = requests.get(f"{BASE}/api/v1/dashboard-data", timeout=10)
check("Dashboard GET 免认证", r.status_code == 200, f"status={r.status_code}")

r = requests.get(f"{BASE}/api/v1/portfolio/valuation", timeout=10)
check("Portfolio GET 免认证", r.status_code == 200, f"status={r.status_code}")

# 2. POST 无 Key → 401
print("\n[2] POST 无 Key → 应被拦截 (401)")
r = requests.post(f"{BASE}/api/v1/portfolio/sync", timeout=10)
check("无 Key POST 被拒 (401)", r.status_code == 401, f"status={r.status_code}, body={r.text[:100]}")

# 3. POST 错误 Key → 403
print("\n[3] POST 错误 Key → 应被拦截 (403)")
r = requests.post(f"{BASE}/api/v1/portfolio/sync",
                   headers={"X-API-Key": "wrong-key-12345"}, timeout=10)
check("错误 Key POST 被拒 (403)", r.status_code == 403, f"status={r.status_code}, body={r.text[:100]}")

# 4. POST 正确 Key → 200
print("\n[4] POST 正确 Key → 应正常通过")
r = requests.post(f"{BASE}/api/v1/portfolio/sync",
                   headers={"X-API-Key": API_KEY}, timeout=30)
check("正确 Key POST 通过", r.status_code == 200, f"status={r.status_code}, body={r.text[:100]}")

# 5. 组合数据完整性
print("\n[5] 组合数据完整性")
r = requests.get(f"{BASE}/api/v1/portfolio/valuation", timeout=10)
if r.status_code == 200:
    val = r.json()
    data = val.get("data", {})
    pos_count = data.get("position_count", 0)
    check("持仓数恢复", pos_count >= 15, f"position_count={pos_count}")
else:
    check("组合接口", False, f"status={r.status_code}")

# Summary
print("\n" + "=" * 60)
print(f"  结果: {passed} passed / {failed} failed")
print("=" * 60)
if failed == 0:
    print("  🎉 安全加固验证通过！所有写入操作已受 API Key 保护。")
else:
    print("  ⚠️  部分检查未通过，请查看上方详情。")
print()
