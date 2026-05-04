"""
AlphaCore V21.2 · ERP Timing Engine 核心测试
=============================================
覆盖:
  - D1: ERP 绝对值评分 (V2 分段线性 + V3 Sigmoid)
  - D4: 波动率评分
  - D5: 信用环境评分
  - EMA 平滑
  - 降级信号
  - 信号级别映射
"""

import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from erp_timing_engine import ERPTimingEngine


@pytest.fixture
def engine():
    """创建干净的 ERP 引擎实例 (不加载持久化历史)"""
    e = ERPTimingEngine()
    return e


# ═══════════════════════════════════════════════════════
#  D1: ERP 绝对值评分
# ═══════════════════════════════════════════════════════

class TestD1ErpAbsolute:
    """ERP 绝对值 → 0-100 评分"""

    def test_extreme_low_erp_is_overvalued(self, engine):
        """ERP < 2% → 极度高估, 评分应接近 0"""
        score, desc = engine._score_d1_erp_absolute(1.5)
        assert score < 10

    def test_normal_erp_mid_score(self, engine):
        """ERP ~4.5% → 中间区间"""
        score, desc = engine._score_d1_erp_absolute(4.5)
        assert 40 < score < 80

    def test_high_erp_is_undervalued(self, engine):
        """ERP ≥ 6% → 极度低估, 评分应接近 100"""
        score, desc = engine._score_d1_erp_absolute(7.0)
        assert score >= 90

    def test_score_range(self, engine):
        """评分始终在 [0, 100]"""
        for erp in [0, 1, 2, 3, 4, 5, 6, 7, 8, 10]:
            score, _ = engine._score_d1_erp_absolute(float(erp))
            assert 0 <= score <= 100, f"ERP={erp} → score={score}"

    def test_monotonic_increasing(self, engine):
        """ERP 越高, 评分越高 (股票越便宜)"""
        scores = [engine._score_d1_erp_absolute(float(e))[0] for e in range(1, 8)]
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], f"Not monotonic at ERP={i+1}"


# ═══════════════════════════════════════════════════════
#  D4: 波动率评分 (V3 Sigmoid)
# ═══════════════════════════════════════════════════════

class TestD4Volatility:
    """波动率评分 (用 V3 公开接口)"""

    def test_calm_market_positive(self, engine):
        """低波动 (calm) → 评分偏高"""
        score, _ = engine._score_d4_v3(0.15, 15.0, "calm")
        assert score >= 60

    def test_turbulent_market_negative(self, engine):
        """高波动 (turbulent) → 评分偏低"""
        score, _ = engine._score_d4_v3(0.50, 90.0, "turbulent")
        assert score < 40

    def test_score_range(self, engine):
        """评分在 [0, 100]"""
        for vol, pct, regime in [
            (0.10, 5, "calm"), (0.25, 50, "normal"), (0.60, 95, "turbulent")
        ]:
            score, _ = engine._score_d4_v3(vol, pct, regime)
            assert 0 <= score <= 100


# ═══════════════════════════════════════════════════════
#  D5: 信用环境评分 (V3)
# ═══════════════════════════════════════════════════════

class TestD5Credit:
    """M1-M2 剪刀差 → 信用评分"""

    def test_positive_scissor_bullish(self, engine):
        """剪刀差 > 0 (信用扩张) → 高分"""
        score, _ = engine._score_d5_v3(2.0, "rising")
        assert score >= 65

    def test_negative_scissor_bearish(self, engine):
        """剪刀差 < -5 (严重收缩) → 低分"""
        score, _ = engine._score_d5_v3(-6.0, "falling")
        assert score < 35

    def test_narrowing_bonus(self, engine):
        """收窄中的负剪刀差比扩大中的好"""
        score_rising, _ = engine._score_d5_v3(-3.0, "rising")
        score_falling, _ = engine._score_d5_v3(-3.0, "falling")
        assert score_rising >= score_falling


# ═══════════════════════════════════════════════════════
#  EMA 平滑
# ═══════════════════════════════════════════════════════

class TestEMASmooth:
    """EMA 平滑器属性"""

    def test_first_call_with_clean_state(self, engine):
        """平滑器初始化后应返回有效值"""
        engine._prev_smooth_score = None  # 强制重置
        result = engine._smooth_composite(60.0)
        assert result == 60.0

    def test_smooth_dampens_spike(self, engine):
        """平滑应阻尼突变"""
        engine._prev_smooth_score = None  # 强制重置
        engine._smooth_composite(50.0)  # init
        smoothed = engine._smooth_composite(90.0)  # spike
        assert 50 < smoothed < 90, "Spike should be dampened"

    def test_convergence(self, engine):
        """连续相同输入应收敛"""
        engine._prev_smooth_score = None
        engine._smooth_composite(50.0)
        for _ in range(20):
            result = engine._smooth_composite(80.0)
        assert abs(result - 80.0) < 2.0  # 应非常接近 80


# ═══════════════════════════════════════════════════════
#  降级信号
# ═══════════════════════════════════════════════════════

class TestFallbackSignal:
    """数据异常时的降级输出"""

    def test_returns_dict(self, engine):
        result = engine._fallback_signal("test error")
        assert isinstance(result, dict)

    def test_has_fallback_status(self, engine):
        result = engine._fallback_signal("test error")
        assert result["status"] == "fallback"

    def test_has_signal(self, engine):
        result = engine._fallback_signal("test error")
        assert "signal" in result
        assert result["signal"]["key"] == "hold"

    def test_has_dimensions(self, engine):
        result = engine._fallback_signal("test error")
        assert "dimensions" in result

    def test_has_trade_rules(self, engine):
        result = engine._fallback_signal("test error")
        assert "trade_rules" in result


# ═══════════════════════════════════════════════════════
#  信号级别映射
# ═══════════════════════════════════════════════════════

class TestSignalMap:
    """SIGNAL_MAP 完整性"""

    def test_all_levels_exist(self, engine):
        """6 个信号级别必须存在"""
        required = {"strong_buy", "buy", "hold", "reduce", "underweight", "cash"}
        assert required.issubset(set(engine.SIGNAL_MAP.keys()))

    def test_each_has_required_fields(self, engine):
        """每个信号必须有 label/position/color/emoji"""
        for key, sig in engine.SIGNAL_MAP.items():
            for field in ["label", "position", "color", "emoji"]:
                assert field in sig, f"Signal '{key}' missing '{field}'"

    def test_signal_levels_ordered(self, engine):
        """level 值应单调递增 (1=最保守, 6=最激进)"""
        levels = [engine.SIGNAL_MAP[k]["level"] for k in
                  ["cash", "underweight", "reduce", "hold", "buy", "strong_buy"]]
        for i in range(len(levels) - 1):
            assert levels[i] < levels[i + 1]
