# -*- coding: utf-8 -*-
"""测试风控合规硬红线联锁与安全隔离"""
import os
import sys

# 强迫 stdout 采用 UTF-8 编码，解决 Windows GBK 打印特殊符号崩溃问题
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from unittest.mock import patch, MagicMock

# 切换到 quant_dashboard 内部以便加载 modules
sys.path.insert(0, r'd:\FIONA\google AI\quant_dashboard\quant_dashboard')
os.chdir(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard')

from engines.audit_engine import audit_risk_control

# 1. 测试常规状态下的风控执行 (无违规)
print("=== Step 1: Running base risk control audit (no violation) ===")
res_base = audit_risk_control()
print(f"Base P&L Score: {res_base['score']} (Grade: {res_base['grade']})")
for c in res_base["checks"]:
    print(f"  - [{c['status'].upper()}] {c['score']:-3d}  {c['name']} (Detail: {c['detail']})")

# 2. 模拟止损违规联锁 (一票否决)
print("\n=== Step 2: Mocking stop-loss violations ===")
mock_pos = [
    {
        "ts_code": "600519.SH", "name": "贵州茅台", "amount": 100, "cost": 1800, "price": 1400,
        "market_value": 140000, "pnl": -40000, "pnl_pct": -22.2, "weight": 70.0, "industry": "食品饮料"
    },
    {
        "ts_code": "000858.SZ", "name": "五粮液", "amount": 200, "cost": 150, "price": 145,
        "market_value": 29000, "pnl": -1000, "pnl_pct": -3.3, "weight": 30.0, "industry": "食品饮料"
    }
]

@patch("engines.audit_engine._get_live_portfolio")
def run_violation_test(mock_portfolio):
    # Mock 返回的持仓 (包含茅台暴跌 -22.2% 突破个股 -12% 止损线)
    mock_portfolio.return_value = (mock_pos, 0, 169000, True, None, 169000)
    
    r = audit_risk_control()
    print(f"Violating P&L Score: {r['score']} (Grade: {r['grade']})")
    
    sl_check = next((c for c in r["checks"] if "止损合规" in c["name"]), None)
    if sl_check:
        print(f"  Stop-loss check: [{sl_check['status']}] Score: {sl_check['score']} Detail: {sl_check['detail']}")
        assert sl_check["status"] == "fail", "Error: Stop-loss status should be fail!"
    
    # 验证联锁：即使平均分可能及格，因为止损违规，总分应该锁在 59 分
    assert r["score"] == 59, f"Error: Risk score should be locked to 59, got {r['score']}"
    print("[SUCCESS] Step 2: Wind-control Hard-Stop Interlocking verified!")

run_violation_test()

# 3. 模拟合规引擎初始化崩溃 (Syntax/Runtime Exception Isolation)
print("\n=== Step 3: Mocking compliance engine initialization failure ===")
import sys
class BrokenModule:
    @property
    def COMPLIANCE_RULES(self):
        raise RuntimeError("Syntax Error inside compliance_engine")

# 注入坏模块模拟崩溃
sys.modules['engines.compliance_engine'] = BrokenModule()

try:
    r_crash = audit_risk_control()
    comp_check = next((c for c in r_crash["checks"] if "合规引擎" in c["name"]), None)
    if comp_check:
        print(f"  Compliance check: [{comp_check['status']}] Score: {comp_check['score']} Detail: {comp_check['detail']}")
        assert comp_check["status"] == "fail", "Error: Compliance status should be fail on crash!"
        assert comp_check["score"] == 40, "Error: Compliance score should be 40 on crash!"
        print("[SUCCESS] Step 3: Compliance Engine syntax failure isolated and bypassed safely!")
    else:
        print("Error: Compliance check item not found!")
finally:
    # 彻底复原，防止干扰其他测试
    sys.modules.pop('engines.compliance_engine', None)
