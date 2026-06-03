# -*- coding: utf-8 -*-
"""
验证 V8.0 因子衰减审计 (随机双通道抽样与 NaN 穿透校验) 的测试脚本
"""
import sys
import os
import shutil
import pandas as pd
import numpy as np
import unittest
from unittest.mock import patch

# 确保能加载包
sys.path.insert(0, '.')
os.chdir(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard')

from engines import audit_engine

class TestFactorDecayAudit(unittest.TestCase):
    def test_01_factor_decay_basic_flow(self):
        """测试 1.1 基本面与技术面因子的正常校验"""
        print("\n--- 1. 测试正常数据下因子审计 ---")
        r = audit_engine.audit_factor_decay()
        c = [c for c in r['checks'] if c['name'] == '因子池可用性'][0]
        print(f"正常因子评分: {c['score']}  状态: {c['status']}")
        print(f"正常因子 Detail: {c['detail']}")
        print(f"正常因子 Meta: {c['meta']}")
        
        # 在干净的数据湖下，应该是 pass 状态
        self.assertEqual(c['status'], 'pass')
        self.assertGreaterEqual(c['score'], 90)
        self.assertIn("验证通过", c['detail'])

    def test_02_factor_nan_injection_mitigation(self):
        """测试因子池大面积 NaN 虚化数据拦截"""
        print("\n--- 2. 测试大面积 NaN 数据注入拦截 ---")
        
        # 创建临时数据文件夹
        temp_fina_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_financials_nan")
        temp_daily_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_daily_prices_nan")
        
        for d in [temp_fina_dir, temp_daily_dir]:
            if os.path.exists(d):
                shutil.rmtree(d)
            os.makedirs(d)
            
        try:
            # 1. 财务数据 (列存在但全是 NaN) - 写入 10 个以达到文件数门槛
            fina_data = {
                "ann_date": ["20260101", "20260101", "20260101"],
                "roe": [np.nan, np.nan, np.nan],
                "eps": [np.nan, np.nan, np.nan],
                "bps": [np.nan, np.nan, np.nan]
            }
            df_fina = pd.DataFrame(fina_data)
            for i in range(10):
                df_fina.to_parquet(os.path.join(temp_fina_dir, f"{i:06d}_nan_fina.parquet"))
            
            # 2. 日线数据 (列存在但全是 NaN) - 写入 30 个以达到文件数门槛
            daily_data = {
                "trade_date": ["20260101", "20260102", "20260103"],
                "vol": [np.nan, np.nan, np.nan],
                "close": [np.nan, np.nan, np.nan],
                "pct_chg": [np.nan, np.nan, np.nan]
            }
            df_daily = pd.DataFrame(daily_data)
            for i in range(30):
                df_daily.to_parquet(os.path.join(temp_daily_dir, f"{i:06d}_nan_daily.parquet"))
            
            # 利用 patch 临时把 FINA_DIR 和 DAILY_DIR 设为临时 NaN 库
            with patch('engines.audit_engine.FINA_DIR', temp_fina_dir), \
                 patch('engines.audit_engine.DAILY_DIR', temp_daily_dir):
                
                # 重新计算 glob 返回的文件列表
                fina_files = [os.path.join(temp_fina_dir, fn) for fn in os.listdir(temp_fina_dir)]
                daily_files = [os.path.join(temp_daily_dir, fn) for fn in os.listdir(temp_daily_dir)]
                
                def mock_glob(pathname):
                    if "financials" in pathname:
                        return fina_files
                    elif "daily_prices" in pathname:
                        return daily_files
                    return []
                
                with patch('glob.glob', side_effect=mock_glob):
                    r = audit_engine.audit_factor_decay()
                    c = [c for c in r['checks'] if c['name'] == '因子池可用性'][0]
                    print(f"NaN注入评分: {c['score']}  状态: {c['status']}")
                    print(f"NaN注入 Detail: {c['detail']}")
                    print(f"NaN注入 Meta: {c['meta']}")
                    
                    # 预期：由于可用率为 0% 且文件较少，触发扣分且状态降级
                    self.assertEqual(c['status'], 'warn')
                    self.assertEqual(c['score'], 60)
                    self.assertIn("数据不达标", c['detail'])
                    self.assertIn("可用率:0%", c['detail'])
                    
        finally:
            # 清理临时目录
            shutil.rmtree(temp_fina_dir)
            shutil.rmtree(temp_daily_dir)
            print("NaN 脏数据注入拦截测试完成。")

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    unittest.main()
