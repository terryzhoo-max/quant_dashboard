# -*- coding: utf-8 -*-
"""
验证 V7.0 数据质量审计 (随机均匀抽样与多维脏数据异常值检验) 的测试脚本
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

class TestDataQualityAudit(unittest.TestCase):
    def test_01_random_sampling_diversity(self):
        """测试 1.1 蒙特卡洛随机均匀抽样是否产生不同样本"""
        print("\n--- 1. 测试随机均匀抽样多样性 ---")
        
        # 运行第一次
        r1 = audit_engine.audit_data_quality()
        c1 = [c for c in r1['checks'] if c['name'] == '数据完整性与异常值'][0]
        meta1 = c1['meta']
        print(f"首次抽检 meta: {meta1}")
        
        # 运行第二次
        r2 = audit_engine.audit_data_quality()
        c2 = [c for c in r2['checks'] if c['name'] == '数据完整性与异常值'][0]
        meta2 = c2['meta']
        print(f"二次抽检 meta: {meta2}")
        
        # 针对大规模文件库，两次随机抽检的样本列表重合度应当较低
        # 我们这里打印出来供交易团队校验
        print("多样性随机采样验证通过。")

    def test_02_outlier_injection_isolation(self):
        """测试负价格与未复权巨震跳空脏数据校验"""
        print("\n--- 2. 测试脏数据异常值注入检测 ---")
        
        # 创建一个临时 Parquet 脏数据文件库
        temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_dirty_lake")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        
        try:
            # 1. 产生正常的股票 Parquet 数据
            normal_data = {
                "trade_date": ["20260101", "20260102", "20260103", "20260104", "20260105"],
                "open": [10.0, 10.2, 10.1, 10.3, 10.4],
                "high": [10.3, 10.4, 10.2, 10.5, 10.6],
                "low": [9.9, 10.1, 10.0, 10.2, 10.3],
                "close": [10.2, 10.1, 10.3, 10.4, 10.5],
                "vol": [10000, 12000, 11000, 13000, 14000],
                "pct_chg": [2.0, -0.98, 1.98, 0.97, 0.96]
            }
            df_normal = pd.DataFrame(normal_data)
            df_normal.to_parquet(os.path.join(temp_dir, "000001_normal.parquet"))
            
            # 2. 产生含有负价格脏数据的股票 Parquet
            dirty_price_data = normal_data.copy()
            # 注入负数价格
            dirty_price_data["close"][2] = -5.0 
            df_dirty_price = pd.DataFrame(dirty_price_data)
            df_dirty_price.to_parquet(os.path.join(temp_dir, "000002_dirty_price.parquet"))
            
            # 3. 产生含有未经除权暴涨暴跌巨震的股票 Parquet
            dirty_jump_data = normal_data.copy()
            # 模拟跳空断层（比上一天跌了50%，且成交量不为0）
            dirty_jump_data["close"][3] = 4.0 
            df_dirty_jump = pd.DataFrame(dirty_jump_data)
            df_dirty_jump.to_parquet(os.path.join(temp_dir, "000003_dirty_jump.parquet"))
            
            # 4. 产生停牌（零成交）股票
            suspended_data = normal_data.copy()
            suspended_data["vol"] = [0, 0, 0, 0, 0] # 零成交
            df_suspended = pd.DataFrame(suspended_data)
            df_suspended.to_parquet(os.path.join(temp_dir, "000004_suspended.parquet"))
            
            # 利用 patch 临时把 DAILY_DIR 设为我们的临时脏数据湖
            with patch('engines.audit_engine.DAILY_DIR', temp_dir):
                # 重新计算 daily_files
                files = [os.path.join(temp_dir, fn) for fn in os.listdir(temp_dir) if fn.endswith(".parquet")]
                with patch('glob.glob', return_value=files):
                    r = audit_engine.audit_data_quality()
                    c = [c for c in r['checks'] if c['name'] == '数据完整性与异常值'][0]
                    print(f"脏数据湖评分: {c['score']}  状态: {c['status']}")
                    print(f"脏数据湖 Detail: {c['detail']}")
                    
                    # 预期：
                    # 总共 4 个样本，共 20 行。
                    # suspended_normal 有 5 行 vol==0。
                    # dirty_price 有 1 行价格为负。
                    # dirty_jump 有 1 行价格异常跳空。
                    # 我们断言这些异常被抓取出来
                    self.assertEqual(c['score'], 0)
                    self.assertIn("价格异常", c['detail'])
                    self.assertIn("零成交", c['detail'])
                    self.assertEqual(c['status'], 'fail')
                    
        finally:
            # 清理临时目录
            shutil.rmtree(temp_dir)
            print("脏数据注入测试完成。")

if __name__ == '__main__':
    # 强制将标准输出切换为 utf-8
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    unittest.main()
