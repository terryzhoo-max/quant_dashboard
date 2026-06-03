# -*- coding: utf-8 -*-
"""
验证 V6.6 交易日历自维护与策略健康模块 Fail 断路器特性的测试脚本
"""
import sys
import os
import json
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, '.')
os.chdir(r'd:\FIONA\google AI\quant_dashboard\quant_dashboard')

from engines import audit_engine

class TestV66Features(unittest.TestCase):
    def setUp(self):
        # 每次测试前重置缓存，防止干扰
        audit_engine._TRADING_CAL_CACHE = None
        self.cal_file = os.path.join(audit_engine.DATA_LAKE, "trading_calendar.json")
        self.cal_bak = self.cal_file + ".bak"
        
        # 备份原本的 trading_calendar.json
        if os.path.exists(self.cal_file):
            import shutil
            shutil.copy(self.cal_file, self.cal_bak)

    def tearDown(self):
        # 恢复备份
        audit_engine._TRADING_CAL_CACHE = None
        if os.path.exists(self.cal_file):
            os.remove(self.cal_file)
        if os.path.exists(self.cal_bak):
            import shutil
            shutil.move(self.cal_bak, self.cal_file)

    def test_01_trading_calendar_cache_and_fallback(self):
        """测试 1.1 交易日历加载、缓存及降级过滤机制"""
        print("\n--- 1. 测试交易日历缓存加载与判定 ---")
        
        # 模拟写入交易日历 JSON 缓存（只有这三天是交易日，其余都是非交易日）
        test_dates = ["20260601", "20260602", "20260603"]
        with open(self.cal_file, "w", encoding="utf-8") as f:
            json.dump(test_dates, f)
            
        # 判定交易日 (在日历缓存中，应该是交易日)
        dt_1 = datetime.strptime("20260601", "%Y%m%d")
        dt_2 = datetime.strptime("20260602", "%Y%m%d")
        dt_3 = datetime.strptime("20260603", "%Y%m%d")
        # 即使是周四，但不在缓存中，判定为非交易日
        dt_4 = datetime.strptime("20260604", "%Y%m%d") 
        
        # 触发加载
        self.assertTrue(audit_engine._is_trading_day(dt_1))
        self.assertTrue(audit_engine._is_trading_day(dt_2))
        self.assertTrue(audit_engine._is_trading_day(dt_3))
        self.assertFalse(audit_engine._is_trading_day(dt_4))
        
        # 验证缓存已被正确命中并且是 set 形式
        self.assertIsNotNone(audit_engine._TRADING_CAL_CACHE)
        self.assertIn("20260601", audit_engine._TRADING_CAL_CACHE)
        print("交易日历缓存载入与精细判定验证通过。")
        
        # ── 测试降级路径 ──
        print("\n--- 2. 测试交易日历缺失时的降级兜底 ---")
        # 清空内存缓存并删除临时日历文件
        audit_engine._TRADING_CAL_CACHE = None
        os.remove(self.cal_file)
        
        # 自然日 2026-06-04 (周四) 降级判定时
        # 周四非节假日，兜底机制应返回 True
        self.assertTrue(audit_engine._is_trading_day(dt_4))
        
        # 自然日 2026-06-07 (周日) 降级判定时
        # 周末，兜底机制应返回 False
        dt_sun = datetime.strptime("20260607", "%Y%m%d")
        self.assertFalse(audit_engine._is_trading_day(dt_sun))
        
        # 验证降级后 `_TRADING_CAL_CACHE` 依然为 None 状态
        self.assertIsNone(audit_engine._TRADING_CAL_CACHE)
        print("无日历文件时的平滑降级验证通过。")

    def test_02_strategy_health_circuit_breaker(self):
        """测试 1.2 策略健康审计 Fail 数量断路器机制"""
        print("\n--- 3. 测试策略健康 Fail 计数断路器 (2项及3项FAIL) ---")
        
        # 我们模拟 mock_extract_optimize_meta
        # 使我们能随意定制策略审计的时效分数，产生不同数量的 fail
        # 均值回归: weight=0.35, 行业动量: weight=0.25, 红利趋势: weight=0.20, ERP择时: weight=0.20
        # 默认下：
        # - 如果我们要让它原本加权分很高（比如 90分），但有 2 个项目 fail
        #   我们让两个低权重项 (红利趋势、ERP择时) 严重过期 (得 0 分，状态为 fail)
        #   让两个高权重项 (均值回归、行业动量) 为 100 分 (状态为 pass)
        #   加权分 = (100*0.35 + 100*0.25 + 0*0.20 + 0*0.20) / 1.00 = 60分？
        #   等等，如果均值回归和行业动量是 100，加权分是 60，小于 65，触发不了 cap=65 的削顶。
        #   如果我们把加权比设大：
        #   若让 均值回归(100分/0.35)、行业动量(100分/0.25)、ERP(100分/0.20) 为 100，只让 红利(0分/0.20) 为 0。
        #   此时有 1 个 fail。加权分 = 80分。断路器不应触发。
        
        # 场景 A: 2个 fail，原始得分较高（加权分 80 分，但红利趋势与 ERP 均为 0分 / fail）
        # 此时权重为：均值回归 0.35 (100分)，行业动量 0.25 (100分)
        # 为了让原始分更高，假设我们将均值回归设为 100，行业动量设为 100，ERP 设为 100（权重共计 0.8，加权分 80分）
        # 但我们让 ERP (0分/fail) 且 红利 (0分/fail)。此时有 2 个 fail。
        # 此时加权分：(100 * 0.35 + 100 * 0.25 + 0 * 0.20 + 0 * 0.20) / 1.0 = 60分。
        # 咦，如果加权分是 60 分，本来就低于 65，那么 final_score 已经是 60，断路器不会修改 final_score。
        # 那么，如果我们改变 checks 内部的状态来直接检验断路器代码呢？
        # 没错！我们直接 mock 掉 `audit_strategy_health` 最后的 `checks` 生成，或者是
        # 让 4 个策略中：
        # 均值回归 (100分，权重 0.35)
        # 行业动量 (100分，权重 0.25)
        # 我们需要让原本分数超过 65。比如：
        # 均值回归 100 (0.35) -> 35
        # 行业动量 100 (0.25) -> 25
        # 红利趋势 90 (0.20) -> 18
        # ERP择时 90 (0.20) -> 18
        # 总分 = 96 分。此时 0 个 fail。
        # 如果我们想模拟 2 个 fail，我们可以通过 mock _optimized_age_days
        # 让 `_optimized_age_days` 返回一个极大的天数（比如 500 天前），这样该项就会被判为 0分/fail。
        # 为了让原始加权得分在 2 个 fail 时依然 > 65 分，我们可以把 均值回归 (权重 0.35) 和 行业动量 (权重 0.25) 设为 100 分。
        # 并且将 ERP择时 (权重 0.20) 设为 100 分，但是我们让它的 status 强行置为 fail？
        # 其实可以直接 mock 掉调用参数文件的流程，或者我们写一个测试：
        # 我们可以 mock 掉 `_optimized_age_days` 函数，使其针对特定策略返回极大的 age_days。
        
        # 我们可以这样测试：
        # 均值回归：100分 (age = 0)
        # 行业动量：100分 (age = 0)
        # 红利趋势：fail (age = 500天前 -> 0分)
        # ERP择时：fail (age = 500天前 -> 0分)
        # 这样有 2 个 fail，加权分是 60。
        # 为了让 2 个 fail 时加权分高于 65，我们可以：
        # 在 `audit_engine.py` 中，还有其它 checks 吗？
        # 对了！在 `audit_strategy_health()` 里面有 5 个检查项！
        # 我们用 view_file 检查 checks 列表里具体有哪 5 个检查项。
        # checks 包括：均值回归、行业动量、红利趋势、ERP择时 4个策略，外加 "Regime 三态参数"！
        # 哇！一共 5 个 checks！
        # "Regime 三态参数" 的权重是 0 吗？
        # 在 `audit_strategy_health` 里面，"Regime 三态参数" 通常不计入加权分（或者权重很低），但是它会作为一个 check！
        # 它的得分也是 100 分。
        # 所以，如果 "Regime 三态参数" 是 fail，且 "红利趋势" 是 fail，那么一共有 2 个 checks 处于 fail 状态。
        # 此时，我们让其它三项均值回归、行业动量、ERP择时都是 100 分。
        # 此时加权分：(100*0.35 + 100*0.25 + 100*0.20) / 0.8 = 100 分！（假设没有红利分）
        # 即使算上红利趋势 (0分)，加权分也是 (100*0.35 + 100*0.25 + 0*0.20 + 100*0.20) = 80 分！
        # 这时，原始加权分为 80 分，但有 2 个项目 (红利趋势、Regime三态) fail。
        # 2 个 fail 会触发 `cap=65`。
        # 这非常容易模拟！我们直接调用 `audit_strategy_health()`。
        # 为了确保我们能准确 mock，我们直接在 `audit_strategy_health` 的主流程中注入 mock 策略。
        
        # 我们可以更直接地编写测试：
        # 通过 mock 掉 `_extract_optimize_meta` 使其返回损坏/过期数据，
        # 并在测试中验证 `strategy_health` 返回字典里 `score` 是否被成功限制（cap），且 `circuit_breaker` 被填充。
        
        # 下面我们模拟 2 个项 fail：
        # 我们把 "行业动量" 和 "红利趋势" 的优化结果 mock 为过期 (500天前)
        # 均值回归和 ERP 正常
        original_age = audit_engine._optimized_age_days
        
        def mock_age(opt_at_str, mtime_fallback):
            # 我们根据当前的堆栈或者上下文，如果我们在算特定策略，就返回很大天数
            # 我们可以通过 mock 掉文件修改时间，或者直接根据 `mtime_fallback` 的不同值来判断
            # 但更简单的做法是：
            # 直接在测试里，我们 mock 掉文件元数据读取 `_extract_optimize_meta`
            return original_age(opt_at_str, mtime_fallback)

        # 我们模拟 2 个 fail (行业动量和红利趋势文件损坏)
        def mock_meta_2_fail(fp, name):
            if "optimizer_results.json" in fp or "dividend_optimization_results.json" in fp:
                # 返回损坏，直接造成这两项得分 0 (fail)
                return None, None, True
            return "2026-06-03 12:00:00", 0.8, False # 正常，100分

        with patch('engines.audit_engine._extract_optimize_meta', side_effect=mock_meta_2_fail):
            r = audit_engine.audit_strategy_health()
            print(f"2个FAIL得分: {r['score']}  Grade: {r['grade']}")
            self.assertIn("circuit_breaker", r)
            self.assertEqual(r['score'], 65) # 被断路器强限 65
            self.assertEqual(r['circuit_breaker']['cap'], 65)
            self.assertEqual(r['circuit_breaker']['reason'], "2项检查失败")
            
        # 模拟 3 个 fail (行业动量、红利趋势和 ERP择时文件损坏)
        def mock_meta_3_fail(fp, name):
            if "optimizer_results.json" in fp or "dividend_optimization_results.json" in fp or "erp_optimization_results.json" in fp:
                return None, None, True
            return "2026-06-03 12:00:00", 0.8, False

        with patch('engines.audit_engine._extract_optimize_meta', side_effect=mock_meta_3_fail):
            r = audit_engine.audit_strategy_health()
            print(f"3个FAIL得分: {r['score']}  Grade: {r['grade']}")
            self.assertIn("circuit_breaker", r)
            self.assertEqual(r['score'], 50) # 被断路器强限 50
            self.assertEqual(r['circuit_breaker']['cap'], 50)
            self.assertEqual(r['circuit_breaker']['reason'], "3项检查失败")

        print("策略健康断路器削顶限分与元数据填充验证通过。")

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    unittest.main()
