"""
erp_position_backtest 单元测试
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "strategies"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
import pandas as pd
import numpy as np


class TestScoreToPosition(unittest.TestCase):
    """V3.4 O13 连续仓位映射测试"""

    def setUp(self):
        from erp_position_backtest import _score_to_position
        self.fn = _score_to_position

    def test_strong_buy(self):
        """锚点 80 = 0.90"""
        self.assertAlmostEqual(self.fn(80.0), 0.90)
        self.assertGreater(self.fn(85.0), 0.90)
        self.assertAlmostEqual(self.fn(100.0), 0.95)

    def test_buy(self):
        """锚点 70 = 0.70"""
        self.assertAlmostEqual(self.fn(70.0), 0.70)
        self.assertGreater(self.fn(75.0), 0.70)
        self.assertLess(self.fn(75.0), 0.90)

    def test_hold(self):
        """锚点 55 = 0.55"""
        self.assertAlmostEqual(self.fn(55.0), 0.55)

    def test_reduce(self):
        """锚点 40 = 0.35"""
        self.assertAlmostEqual(self.fn(40.0), 0.35)

    def test_underweight(self):
        """锚点 25 = 0.15"""
        self.assertAlmostEqual(self.fn(25.0), 0.15)

    def test_cash(self):
        """锚点 0 = 0.05"""
        self.assertAlmostEqual(self.fn(0.0), 0.05)

    def test_boundary_exact(self):
        """所有锚点处仓位精确匹配"""
        self.assertAlmostEqual(self.fn(80.0), 0.90)
        self.assertAlmostEqual(self.fn(70.0), 0.70)
        self.assertAlmostEqual(self.fn(55.0), 0.55)
        self.assertAlmostEqual(self.fn(40.0), 0.35)
        self.assertAlmostEqual(self.fn(25.0), 0.15)

    def test_continuous_no_jump(self):
        """连续映射: 相邻 Score 差 0.1 时仓位差 < 1%"""
        for s in [25, 40, 55, 70, 80]:
            above = self.fn(s + 0.1)
            below = self.fn(s - 0.1)
            self.assertLess(abs(above - below), 0.01,
                            f"Jump at threshold {s}: {below:.4f} → {above:.4f}")

    def test_monotonic(self):
        """仓位随 Score 严格单调递增"""
        scores = list(range(0, 101, 5))
        positions = [self.fn(s) for s in scores]
        for i in range(1, len(positions)):
            self.assertGreaterEqual(positions[i], positions[i-1],
                                    f"Position should increase: score {scores[i]}")


class TestRunPositionBacktest(unittest.TestCase):
    """仓位管理回测引擎核心测试"""

    def _make_df(self, prices, start="2024-01-01"):
        """构造测试用 ETF DataFrame"""
        dates = pd.bdate_range(start, periods=len(prices))
        return pd.DataFrame({"close": prices}, index=dates)

    def _make_scores(self, values, index):
        """构造测试用 composite score 序列"""
        return pd.Series(values, index=index)

    def test_no_trade_when_within_threshold(self):
        """仓位变化 < threshold 时不调仓"""
        from erp_position_backtest import run_position_backtest
        df = self._make_df([10.0] * 20)
        # Score=55 → target 60%, 初始仓位 0%, 差距 60% > 5% → 首日会买入
        # 之后 Score 不变 → 不再调仓
        scores = self._make_scores([55.0] * 20, df.index)
        result = run_position_backtest(df, scores, rebalance_threshold=0.05)
        # 首次买入后不应再调仓
        self.assertEqual(result["metrics"]["total_trades"], 1)

    def test_cash_preserved_no_negative(self):
        """现金不会变为负数"""
        from erp_position_backtest import run_position_backtest
        df = self._make_df([10.0] * 10)
        scores = self._make_scores([90.0] * 10, df.index)  # 强买 → 90% 仓位
        result = run_position_backtest(df, scores, initial_cash=1000.0)
        # 检查日终组合价值始终 > 0
        for v in result["daily"]["portfolio_values"]:
            self.assertGreater(v, 0)

    def test_trade_cost_deducted(self):
        """交易成本被正确扣除"""
        from erp_position_backtest import run_position_backtest
        df = self._make_df([10.0] * 5)
        scores = self._make_scores([90.0] * 5, df.index)  # 90% 仓位
        result = run_position_backtest(df, scores, cost_per_trade=0.01)
        # 初始 100万, 买入90万权益, 成本 0.9万
        self.assertGreater(result["metrics"]["total_cost"], 0)
        # 组合价值 < 初始资金 (因交易成本)
        self.assertLess(result["daily"]["portfolio_values"][-1], 1000000.0)

    def test_score_index_alignment(self):
        """scores 和 df 索引不同源时自动对齐"""
        from erp_position_backtest import run_position_backtest
        df = self._make_df([10.0] * 10, start="2024-01-01")
        # scores 故意用不同的日期范围
        wrong_dates = pd.bdate_range("2024-01-01", periods=15)
        scores = pd.Series([55.0] * 15, index=wrong_dates)
        # 应不报错
        result = run_position_backtest(df, scores)
        self.assertEqual(len(result["daily"]["portfolio_values"]), 10)

    def test_position_changes_with_score(self):
        """Score 变化驱动仓位变化"""
        from erp_position_backtest import run_position_backtest
        prices = [10.0] * 20
        df = self._make_df(prices)
        # 前10天 Score=80 (strong_buy→90%), 后10天 Score=30 (underweight→20%)
        score_vals = [80.0] * 10 + [30.0] * 10
        scores = self._make_scores(score_vals, df.index)
        result = run_position_backtest(df, scores)
        # 应有 ≥2 次调仓 (首次买入 + 卖出调仓)
        self.assertGreaterEqual(result["metrics"]["total_trades"], 2)
        # 后半段仓位应明显低于前半段
        pos = result["daily"]["positions"]
        avg_first = np.mean(pos[:10])
        avg_second = np.mean(pos[10:])
        self.assertGreater(avg_first, avg_second)

    def test_sharpe_includes_risk_free(self):
        """Sharpe 计算包含无风险利率"""
        from erp_position_backtest import run_position_backtest
        # 价格小幅上涨
        prices = [10.0 + i * 0.01 for i in range(100)]
        df = self._make_df(prices)
        scores = self._make_scores([55.0] * 100, df.index)

        result_0 = run_position_backtest(df, scores, risk_free_rate=0.0)
        result_5 = run_position_backtest(df, scores, risk_free_rate=0.05)

        # rf=5% 时 Sharpe 应低于 rf=0%
        self.assertGreater(result_0["metrics"]["sharpe_ratio"],
                           result_5["metrics"]["sharpe_ratio"])

    def test_output_structure(self):
        """输出结构完整性"""
        from erp_position_backtest import run_position_backtest
        df = self._make_df([10.0] * 5)
        scores = self._make_scores([55.0] * 5, df.index)
        result = run_position_backtest(df, scores)

        self.assertIn("metrics", result)
        self.assertIn("grade", result)
        self.assertIn("daily", result)
        self.assertIn("trade_log", result)

        m = result["metrics"]
        for key in ["total_return", "annualized_return", "sharpe_ratio",
                     "max_drawdown", "calmar_ratio", "alpha",
                     "total_trades", "total_cost", "avg_position",
                     "bench_total_return", "bench_ann_return"]:
            self.assertIn(key, m, f"Missing metric: {key}")


if __name__ == "__main__":
    unittest.main()


class TestO16TrendGate(unittest.TestCase):
    """V3.4 O16 价格趋势门控单元测试"""

    def _make_df(self, prices, start="2020-01-01"):
        dates = pd.bdate_range(start, periods=len(prices))
        return pd.DataFrame({"close": prices}, index=dates)

    def _make_scores(self, values, index):
        return pd.Series(values, index=index)

    def test_o16_caps_position_in_downtrend(self):
        """双均线空头时仓位被 cap"""
        import erp_params
        from erp_position_backtest import run_position_backtest
        # 构造一个持续下跌序列 (200天 → MA60/120 都有值)
        prices = [100.0 - i * 0.3 for i in range(200)]
        df = self._make_df(prices)
        scores = self._make_scores([80.0] * 200, df.index)  # Score=80 → 应 90% 仓位
        old_enabled = erp_params.O16_ENABLED
        erp_params.O16_ENABLED = True
        result = run_position_backtest(df, scores)
        erp_params.O16_ENABLED = old_enabled
        # 后半段 (MA60/120 生效后) 实际仓位应被 cap < 60%
        avg_pos_late = np.mean(result["daily"]["positions"][150:])
        self.assertLess(avg_pos_late, 0.60,
                        f"O16 should cap position in downtrend, got {avg_pos_late:.2f}")

    def test_o16_no_cap_in_uptrend(self):
        """价格在 MA60 上方时不限仓"""
        import erp_params
        from erp_position_backtest import run_position_backtest
        prices = [50.0 + i * 0.5 for i in range(200)]
        df = self._make_df(prices)
        scores = self._make_scores([80.0] * 200, df.index)
        old_enabled = erp_params.O16_ENABLED
        erp_params.O16_ENABLED = True
        result = run_position_backtest(df, scores)
        erp_params.O16_ENABLED = old_enabled
        avg_pos_late = np.mean(result["daily"]["positions"][130:])
        self.assertGreater(avg_pos_late, 0.70,
                           f"O16 should not cap in uptrend, got {avg_pos_late:.2f}")

    def test_o16_disabled_no_effect(self):
        """O16 禁用时不影响仓位"""
        import erp_params
        from erp_position_backtest import run_position_backtest
        prices = [100.0 - i * 0.3 for i in range(200)]
        df = self._make_df(prices)
        scores = self._make_scores([80.0] * 200, df.index)
        erp_params.O16_ENABLED = False
        result_off = run_position_backtest(df, scores)
        erp_params.O16_ENABLED = True
        result_on = run_position_backtest(df, scores)
        erp_params.O16_ENABLED = True
        # 禁用时仓位应更高
        avg_off = np.mean(result_off["daily"]["positions"][150:])
        avg_on = np.mean(result_on["daily"]["positions"][150:])
        self.assertGreater(avg_off, avg_on,
                           f"O16 disabled should have higher pos: off={avg_off:.2f} on={avg_on:.2f}")

    def test_o16_cross_confirm_relaxes_cap(self):
        """Score 高时交叉确认放松 cap"""
        import erp_params
        from erp_position_backtest import run_position_backtest
        prices = [100.0 - i * 0.3 for i in range(200)]
        df = self._make_df(prices)
        # Score=80 (> CROSS_CONFIRM_THRESH=65) → RELAX_CAP=0.50
        scores_high = self._make_scores([80.0] * 200, df.index)
        # Score=40 (< 65) → POS_CAP_BOTH=0.30
        scores_low = self._make_scores([40.0] * 200, df.index)
        erp_params.O16_ENABLED = True
        result_high = run_position_backtest(df, scores_high)
        result_low = run_position_backtest(df, scores_low)
        avg_high = np.mean(result_high["daily"]["positions"][150:])
        avg_low = np.mean(result_low["daily"]["positions"][150:])
        self.assertGreater(avg_high, avg_low,
                           f"Cross-confirm should relax cap: high={avg_high:.2f} low={avg_low:.2f}")


class TestO17TurnoverBoost(unittest.TestCase):
    """V3.4 O17 换手率动量加码单元测试"""

    def _make_df(self, prices, start="2020-01-01"):
        dates = pd.bdate_range(start, periods=len(prices))
        return pd.DataFrame({"close": prices}, index=dates)

    def _make_scores(self, values, index):
        return pd.Series(values, index=index)

    def test_o17_boosts_in_bull_with_volume(self):
        """牛市 + 换手率突然放量 → 仓位加码 (过渡期 z-score > 1)"""
        import erp_params
        from erp_position_backtest import run_position_backtest
        # 300 天上涨序列 (确保 MA60/120 生效)
        N = 300
        prices = [50.0 + i * 0.5 for i in range(N)]
        df = self._make_df(prices)
        scores = self._make_scores([55.0] * N, df.index)

        # 放量模式: 前200天低(0.5), 第200天起突然放量(3.0)
        # z-score 在过渡期 (200-260天) 会显著 > 1
        turnover_spike = pd.Series([0.5] * 200 + [3.0] * 100, index=df.index)
        turnover_flat = pd.Series([0.5] * N, index=df.index)

        erp_params.O16_ENABLED = True
        erp_params.O17_ENABLED = True
        result_spike = run_position_backtest(df, scores, turnover_series=turnover_spike)
        result_flat = run_position_backtest(df, scores, turnover_series=turnover_flat)

        # 检查过渡期 (201-230天) 的 target_positions
        tp_spike = result_spike["daily"]["target_positions"][201:230]
        tp_flat = result_flat["daily"]["target_positions"][201:230]
        avg_spike = np.mean(tp_spike)
        avg_flat = np.mean(tp_flat)
        self.assertGreater(avg_spike, avg_flat,
                           f"O17 should boost during volume surge: spike={avg_spike:.3f} flat={avg_flat:.3f}")

    def test_o17_no_boost_in_bear(self):
        """熊市中 O17 不生效 (O16 门控优先)"""
        import erp_params
        from erp_position_backtest import run_position_backtest
        prices = [100.0 - i * 0.3 for i in range(200)]
        df = self._make_df(prices)
        scores = self._make_scores([55.0] * 200, df.index)
        turnover_high = pd.Series([2.0] * 200, index=df.index)

        erp_params.O16_ENABLED = True
        erp_params.O17_ENABLED = True
        result = run_position_backtest(df, scores, turnover_series=turnover_high)
        avg_pos = np.mean(result["daily"]["positions"][150:])
        self.assertLess(avg_pos, 0.55,
                        f"O17 should not boost in bear market, got {avg_pos:.2f}")

    def test_o17_disabled_no_boost(self):
        """O17 禁用时无加码"""
        import erp_params
        from erp_position_backtest import run_position_backtest
        prices = [50.0 + i * 0.5 for i in range(200)]
        df = self._make_df(prices)
        scores = self._make_scores([55.0] * 200, df.index)
        turnover = pd.Series([2.0] * 200, index=df.index)

        erp_params.O16_ENABLED = True
        erp_params.O17_ENABLED = False
        result_off = run_position_backtest(df, scores, turnover_series=turnover)
        erp_params.O17_ENABLED = True
        result_on = run_position_backtest(df, scores, turnover_series=turnover)

        avg_off = np.mean(result_off["daily"]["positions"][150:])
        avg_on = np.mean(result_on["daily"]["positions"][150:])
        self.assertGreaterEqual(avg_on, avg_off,
                                f"O17 enabled should >= disabled: on={avg_on:.2f} off={avg_off:.2f}")


class TestParameterFingerprint(unittest.TestCase):
    """参数指纹 — 检测参数漂移"""

    def test_critical_params_unchanged(self):
        """关键参数值不被意外修改"""
        import erp_params
        critical = {
            "BUY_THRESHOLD": 55,
            "SELL_THRESHOLD": 40,
            "O16_MA_SHORT": 60,
            "O16_MA_LONG": 120,
            "O16_POS_CAP_BOTH": 0.30,
            "O16_POS_CAP_SHORT": 0.45,
            "O16_CROSS_CONFIRM_THRESH": 65,
            "O16_RELAX_CAP": 0.50,
            "O17_VOL_WINDOW": 60,
            "O17_ZSCORE_THRESH": 1.0,
            "O17_BOOST": 0.10,
        }
        for name, expected in critical.items():
            actual = getattr(erp_params, name)
            self.assertEqual(actual, expected,
                             f"Parameter drift detected: {name}={actual}, expected={expected}")

    def test_weights_sum_to_one(self):
        """维度权重之和 = 1.0"""
        import erp_params
        w = erp_params.WEIGHTS
        total = sum(w.values())
        self.assertAlmostEqual(total, 1.0, places=6,
                               msg=f"Weights sum={total}, expected 1.0")
