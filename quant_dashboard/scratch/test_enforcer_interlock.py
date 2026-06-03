# -*- coding: utf-8 -*-
"""
验证 V9.0 统一联锁阻断与风控/因子实盘风控闭断的测试脚本
"""
import sys
import os
import json
import shutil
import unittest

# 确保能加载包
sys.path.insert(0, '.')
os.chdir(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard')

from engines import audit_enforcer

class TestEnforcerInterlock(unittest.TestCase):
    def setUp(self):
        # 备份原本的阻断文件和日志文件以防污染
        self.block_file = audit_enforcer.BLOCK_FILE
        self.log_file = audit_enforcer.LOG_FILE
        
        self.block_bak = self.block_file + ".bak"
        self.log_bak = self.log_file + ".bak"
        
        if os.path.exists(self.block_file):
            shutil.copy(self.block_file, self.block_bak)
        if os.path.exists(self.log_file):
            shutil.copy(self.log_file, self.log_bak)
            
        # 每次测试前确保初始为未阻断状态
        audit_enforcer.set_trade_block(False, "测试初始化")

    def tearDown(self):
        # 还原备份的阻断文件和日志
        for raw, bak in [(self.block_file, self.block_bak), (self.log_file, self.log_bak)]:
            if os.path.exists(raw):
                os.remove(raw)
            if os.path.exists(bak):
                shutil.move(bak, raw)

    def test_01_unified_halting_flow(self):
        """测试数据过期、风控FAIL、因子FAIL的硬熔断与自适应清除"""
        print("\n--- 1. 测试正常状态下不触发阻断 ---")
        mock_report = {
            "modules": {
                "data_quality": {
                    "score": 100,
                    "checks": [
                        {"name": "日线数据新鲜度", "status": "pass", "detail": "最新: 2026-06-03 (0天前)"}
                    ]
                },
                "risk_control": {
                    "score": 95,
                    "checks": []
                },
                "factor_decay": {
                    "score": 95,
                    "checks": []
                }
            }
        }
        
        res = audit_enforcer.run_post_audit_enforcement(mock_report)
        print(f"正常状态: trade_blocked={res['trade_blocked']}, reason='{res['trade_block_reason']}'")
        self.assertFalse(res['trade_blocked'])
        
        # ── 测试 2: 注入风控合规 FAIL (得分 50) ──
        print("\n--- 2. 注入风控合规 FAIL 触发硬红线联锁阻断 ---")
        mock_report["modules"]["risk_control"]["score"] = 50
        
        res = audit_enforcer.run_post_audit_enforcement(mock_report)
        print(f"风控异常状态: trade_blocked={res['trade_blocked']}, reason='{res['trade_block_reason']}'")
        self.assertTrue(res['trade_blocked'])
        self.assertIn("风控合规审计 FAIL", res['trade_block_reason'])
        
        blocked, reason = audit_enforcer.is_trade_blocked()
        self.assertTrue(blocked)
        self.assertIn("硬红线联锁熔断", reason)
        
        # ── 测试 3: 注入因子可用性崩溃 (得分 30) ──
        print("\n--- 3. 注入因子可用性崩溃触发安全交易阻断 ---")
        # 将风控分设回 100，把因子分设为 30
        mock_report["modules"]["risk_control"]["score"] = 100
        mock_report["modules"]["factor_decay"]["score"] = 30
        
        res = audit_enforcer.run_post_audit_enforcement(mock_report)
        print(f"因子异常状态: trade_blocked={res['trade_blocked']}, reason='{res['trade_block_reason']}'")
        self.assertTrue(res['trade_blocked'])
        self.assertIn("因子可用性审计崩溃", res['trade_block_reason'])
        
        # ── 测试 4: 修复指标，自适应自动解禁 ──
        print("\n--- 4. 数据恢复正常后自动解禁 ---")
        mock_report["modules"]["factor_decay"]["score"] = 90
        
        res = audit_enforcer.run_post_audit_enforcement(mock_report)
        print(f"恢复状态: trade_blocked={res['trade_blocked']}, reason='{res['trade_block_reason']}'")
        self.assertFalse(res['trade_blocked'])
        
        blocked, _ = audit_enforcer.is_trade_blocked()
        self.assertFalse(blocked, "系统修复后未能成功自动解除阻断")
        print("联锁阻断与自动解除闭环测试全部通过！")

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    unittest.main()
