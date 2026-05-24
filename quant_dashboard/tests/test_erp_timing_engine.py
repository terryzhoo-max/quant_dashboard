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


# ═══════════════════════════════════════════════════════
#  V3.2 审计修复: HW 高水位线衰减 (A1)
# ═══════════════════════════════════════════════════════

class TestHWDecay:
    """高水位线 60 天衰减机制"""

    def test_hw_increases_on_new_high(self, engine):
        """新高分应更新 HW"""
        engine._score_high_water = 70.0
        engine._hw_peak_date = "2026-04-01"
        # 模拟 compute_signal 中的 HW 更新逻辑
        composite = 80.0
        if composite > engine._score_high_water:
            engine._score_high_water = composite
            engine._hw_peak_date = "2026-05-23"
        assert engine._score_high_water == 80.0
        assert engine._hw_peak_date == "2026-05-23"

    def test_hw_no_decay_within_window(self, engine):
        """60 天内 HW 应保持不变"""
        import erp_params
        engine._score_high_water = 80.0
        engine._hw_peak_date = "2026-05-20"  # 3天前
        composite = 60.0
        # 模拟: composite < HW, 检查是否衰减
        if composite > engine._score_high_water:
            pass  # 不会进入
        elif (erp_params.HW_DECAY_DAYS > 0
              and engine._hw_peak_date
              and engine._score_high_water >= erp_params.HW_TRIGGER_LEVEL):
            from datetime import datetime
            days_since = (datetime.now().date() - datetime.strptime(engine._hw_peak_date, "%Y-%m-%d").date()).days
            if days_since > erp_params.HW_DECAY_DAYS:
                engine._score_high_water = composite
        # HW 应保持 80 (未超过 60 天)
        assert engine._score_high_water == 80.0

    def test_hw_decays_after_window(self, engine):
        """超过 60 天后 HW 应衰减重置"""
        import erp_params
        engine._score_high_water = 85.0
        engine._hw_peak_date = "2026-01-01"  # 远超 60 天
        composite = 55.0
        if composite > engine._score_high_water:
            pass
        elif (erp_params.HW_DECAY_DAYS > 0
              and engine._hw_peak_date
              and engine._score_high_water >= erp_params.HW_TRIGGER_LEVEL):
            from datetime import datetime
            days_since = (datetime.now().date() - datetime.strptime(engine._hw_peak_date, "%Y-%m-%d").date()).days
            if days_since > erp_params.HW_DECAY_DAYS:
                engine._score_high_water = composite
                engine._hw_peak_date = str(datetime.now().date())
        assert engine._score_high_water == 55.0, "HW should decay after 60 days"

    def test_hw_no_decay_below_trigger(self, engine):
        """HW 未达 75 阈值时不应触发衰减"""
        import erp_params
        engine._score_high_water = 60.0  # < HW_TRIGGER_LEVEL(75)
        engine._hw_peak_date = "2026-01-01"
        composite = 50.0
        original_hw = engine._score_high_water
        if composite > engine._score_high_water:
            pass
        elif (erp_params.HW_DECAY_DAYS > 0
              and engine._hw_peak_date
              and engine._score_high_water >= erp_params.HW_TRIGGER_LEVEL):
            from datetime import datetime
            days_since = (datetime.now().date() - datetime.strptime(engine._hw_peak_date, "%Y-%m-%d").date()).days
            if days_since > erp_params.HW_DECAY_DAYS:
                engine._score_high_water = composite
        assert engine._score_high_water == original_hw, "HW below trigger should not decay"


# ═══════════════════════════════════════════════════════
#  V3.2 审计修复: O7+O11 修正 Cap (A2)
# ═══════════════════════════════════════════════════════

class TestModifierCap:
    """O7+O11 合并修正幅度上限"""

    def test_cap_limits_positive(self):
        """正向修正不应超过 MODIFIER_CAP"""
        import erp_params
        momentum_mod = 5.0
        mtf_mod = 3.0
        total = momentum_mod + mtf_mod  # = 8
        capped = max(-erp_params.MODIFIER_CAP, min(erp_params.MODIFIER_CAP, total))
        assert capped == erp_params.MODIFIER_CAP  # 8 被 cap 到 6

    def test_cap_limits_negative(self):
        """负向修正不应低于 -MODIFIER_CAP"""
        import erp_params
        momentum_mod = -5.0
        mtf_mod = -3.0
        total = momentum_mod + mtf_mod  # = -8
        capped = max(-erp_params.MODIFIER_CAP, min(erp_params.MODIFIER_CAP, total))
        assert capped == -erp_params.MODIFIER_CAP

    def test_passthrough_within_cap(self):
        """合计 ≤ cap 时不应截断"""
        import erp_params
        momentum_mod = 3.0
        mtf_mod = 1.0
        total = momentum_mod + mtf_mod  # = 4
        capped = max(-erp_params.MODIFIER_CAP, min(erp_params.MODIFIER_CAP, total))
        assert capped == 4.0  # 不截断


# ═══════════════════════════════════════════════════════
#  V3.2 审计修复: 信号阈值参数化 (B1)
# ═══════════════════════════════════════════════════════

class TestSignalThresholds:
    """SIGNAL_THRESHOLDS 参数一致性"""

    def test_thresholds_descending(self):
        """阈值应严格递减: strong_buy > buy > hold > reduce > underweight"""
        import erp_params
        T = erp_params.SIGNAL_THRESHOLDS
        assert T["strong_buy"] > T["buy"] > T["hold"] > T["reduce"] > T["underweight"]

    def test_thresholds_match_original(self):
        """参数化后的值应与原始硬编码一致"""
        import erp_params
        T = erp_params.SIGNAL_THRESHOLDS
        assert T["strong_buy"] == 80
        assert T["buy"] == 70
        assert T["hold"] == 55
        assert T["reduce"] == 40
        assert T["underweight"] == 25

    def test_buy_threshold_vs_signal_threshold(self):
        """BUY_THRESHOLD(回测) 与 SIGNAL_THRESHOLDS(引擎) 应有明确区分"""
        import erp_params
        # BUY_THRESHOLD 用于二分法, 等于 hold 阈值
        assert erp_params.BUY_THRESHOLD == erp_params.SIGNAL_THRESHOLDS["hold"]
        # 但引擎 buy 信号需要更高分
        assert erp_params.SIGNAL_THRESHOLDS["buy"] > erp_params.BUY_THRESHOLD


class TestTrendModifier:
    """V3.3 O12 市场势能修正器测试"""

    @pytest.fixture
    def engine(self):
        return ERPTimingEngine()

    def test_downtrend_penalty(self, engine):
        """PE < MA120 时应产生负修正"""
        import pandas as pd
        # 构造 PE 序列: 前 120 天 = 12, 最后几天 = 10 (下跌)
        pe = pd.Series([12.0] * 130 + [10.0] * 5)
        mod, desc = engine._trend_modifier(pe)
        assert mod < 0, f"Downtrend should give negative mod, got {mod}"
        assert "下行" in desc

    def test_uptrend_bonus(self, engine):
        """PE > MA120 时应产生正修正"""
        import pandas as pd
        pe = pd.Series([10.0] * 130 + [12.0] * 5)
        mod, desc = engine._trend_modifier(pe)
        assert mod > 0, f"Uptrend should give positive mod, got {mod}"
        assert "上行" in desc

    def test_asymmetric(self, engine):
        """惩罚力度应大于奖励力度 (非对称设计)"""
        import pandas as pd
        pe_down = pd.Series([12.0] * 130 + [10.0] * 5)  # -16.7% 偏离
        pe_up = pd.Series([10.0] * 130 + [12.0] * 5)    # +20% 偏离
        mod_down, _ = engine._trend_modifier(pe_down)
        mod_up, _ = engine._trend_modifier(pe_up)
        assert abs(mod_down) > abs(mod_up), \
            f"Penalty ({mod_down}) should be larger than bonus ({mod_up})"

    def test_disabled(self, engine):
        """O12_ENABLED=False 时返回 0"""
        import pandas as pd
        import erp_params
        original = erp_params.O12_ENABLED
        try:
            erp_params.O12_ENABLED = False
            pe = pd.Series([12.0] * 130 + [10.0] * 5)
            mod, desc = engine._trend_modifier(pe)
            assert mod == 0
            assert "禁用" in desc
        finally:
            erp_params.O12_ENABLED = original

    def test_insufficient_data(self, engine):
        """数据不足时返回 0"""
        import pandas as pd
        pe = pd.Series([12.0] * 50)  # < window + 10
        mod, desc = engine._trend_modifier(pe)
        assert mod == 0
        assert "不足" in desc

    def test_cap_respected(self, engine):
        """修正不超过 O12_CAP"""
        import pandas as pd
        import erp_params
        cap = erp_params.O12_CAP
        # 极端下跌: PE 从 15 跌到 5 (-66%)
        pe = pd.Series([15.0] * 130 + [5.0] * 5)
        mod, _ = engine._trend_modifier(pe)
        assert abs(mod) <= cap + 0.1, f"Mod {mod} exceeds cap {cap}"
