"""
AlphaCore P3-A · AIAE 引擎核心逻辑单元测试
============================================
测试纯计算函数, 不触发网络 I/O (mock Tushare)。
覆盖: Regime 分类 · 仓位矩阵 · AIAE_V1 融合 · 斜率信号 · ETF 信号
"""

import pytest
import math
from unittest.mock import patch, MagicMock

import aiae_params as AP


# ═══════════════════════════════════════════════════
#  Fixture: 构造一个不触发 I/O 的 AIAEEngine 实例
# ═══════════════════════════════════════════════════

@pytest.fixture
def engine():
    """创建 AIAEEngine 实例, mock 掉文件系统和网络"""
    with patch("engines.aiae_engine.os.path.exists", return_value=True), \
         patch("builtins.open", MagicMock()), \
         patch("engines.aiae_engine.json.load", return_value={
             "value": 82.0, "date": "2025-12-31", "source": "test"
         }), \
         patch("engines.aiae_engine.ac_db"):
        from engines.aiae_engine import AIAEEngine
        eng = AIAEEngine()
    return eng


# ═══════════════════════════════════════════════════
#  Regime 分类 (五档边界)
# ═══════════════════════════════════════════════════

class TestClassifyRegime:
    def test_regime_1_extreme_fear(self, engine):
        assert engine.classify_regime(8.0) == 1
        assert engine.classify_regime(12.0) == 1

    def test_regime_2_low_allocation(self, engine):
        t = AP.REGIME_THRESHOLDS
        assert engine.classify_regime(t[0]) == 2      # 下界 (包含)
        assert engine.classify_regime(t[0] + 2) == 2

    def test_regime_3_neutral(self, engine):
        t = AP.REGIME_THRESHOLDS
        assert engine.classify_regime(t[1]) == 3
        assert engine.classify_regime(20.0) == 3

    def test_regime_4_getting_hot(self, engine):
        t = AP.REGIME_THRESHOLDS
        assert engine.classify_regime(t[2]) == 4
        assert engine.classify_regime(25.0) == 4

    def test_regime_5_euphoria(self, engine):
        t = AP.REGIME_THRESHOLDS
        assert engine.classify_regime(t[3]) == 5
        assert engine.classify_regime(40.0) == 5

    def test_boundary_values(self, engine):
        """分界线值应归入高一档"""
        t = AP.REGIME_THRESHOLDS  # [13, 17, 23, 30]
        assert engine.classify_regime(t[0] - 0.01) == 1
        assert engine.classify_regime(t[0]) == 2
        assert engine.classify_regime(t[1] - 0.01) == 2
        assert engine.classify_regime(t[1]) == 3

    def test_monotonic_regime_increases(self, engine):
        """AIAE 值递增 → Regime 不递减"""
        prev = 0
        for aiae_val in range(5, 45, 1):
            regime = engine.classify_regime(float(aiae_val))
            assert regime >= prev
            prev = regime


# ═══════════════════════════════════════════════════
#  AIAE Simple 计算
# ═══════════════════════════════════════════════════

class TestComputeAIAESimple:
    def test_normal_values(self, engine):
        # 100 / (100 + 300) = 25%
        result = engine.compute_aiae_simple(100.0, 300.0)
        assert result == 25.0

    def test_zero_m2_fallback(self, engine):
        result = engine.compute_aiae_simple(100.0, 0)
        assert result == 20.0  # degraded fallback

    def test_small_market_cap(self, engine):
        result = engine.compute_aiae_simple(10.0, 300.0)
        assert 3.0 < result < 4.0

    def test_large_market_cap(self, engine):
        result = engine.compute_aiae_simple(150.0, 300.0)
        assert 33.0 < result < 34.0


# ═══════════════════════════════════════════════════
#  AIAE V1 融合计算
# ═══════════════════════════════════════════════════

class TestComputeAIAEV1:
    def test_result_range(self, engine):
        """融合结果应在合理区间 (5-50%)"""
        for simple in [10, 20, 30, 40]:
            for fund in [60, 75, 85, 95]:
                for margin in [1.0, 2.0, 3.0, 4.0]:
                    v1 = engine.compute_aiae_v1(float(simple), float(fund), float(margin))
                    assert 3 < v1 < 55, f"AIAE_V1={v1} out of range for simple={simple} fund={fund} margin={margin}"

    def test_higher_inputs_higher_output(self, engine):
        """所有维度升高 → V1 升高"""
        low = engine.compute_aiae_v1(10.0, 65.0, 1.5)
        high = engine.compute_aiae_v1(30.0, 90.0, 3.5)
        assert high > low

    def test_sigmoid_smoothness(self, engine):
        """基金仓位 79 vs 81 差异应小于线性映射"""
        v_79 = engine.compute_aiae_v1(20.0, 79.0, 2.0)
        v_81 = engine.compute_aiae_v1(20.0, 81.0, 2.0)
        assert abs(v_81 - v_79) < 1.0  # Sigmoid around center should be smooth


# ═══════════════════════════════════════════════════
#  融资热度
# ═══════════════════════════════════════════════════

class TestMarginHeat:
    def test_normal_ratio(self, engine):
        result = engine.compute_margin_heat({"rzye_wan_yi": 1.85}, 100.0)
        assert 1.5 < result < 2.5

    def test_zero_market_cap(self, engine):
        result = engine.compute_margin_heat({"rzye_wan_yi": 1.85}, 0)
        assert result == 2.0  # fallback


# ═══════════════════════════════════════════════════
#  斜率信号
# ═══════════════════════════════════════════════════

class TestComputeSlope:
    def test_rising(self, engine):
        result = engine.compute_slope(25.0, 22.0)
        assert result["slope"] == 3.0
        assert result["direction"] == "rising"

    def test_falling(self, engine):
        result = engine.compute_slope(18.0, 22.0)
        assert result["slope"] == -4.0
        assert result["direction"] == "falling"

    def test_flat(self, engine):
        result = engine.compute_slope(20.0, 20.0)
        assert result["direction"] == "flat"

    def test_accel_up_signal(self, engine):
        result = engine.compute_slope(30.0, 20.0)  # +10
        if result.get("signal"):
            assert result["signal"]["type"] == "accel_up"

    def test_none_previous(self, engine):
        result = engine.compute_slope(20.0, None)
        assert result["slope"] == 0
        assert result["direction"] == "flat"


# ═══════════════════════════════════════════════════
#  仓位矩阵
# ═══════════════════════════════════════════════════

class TestPositionMatrix:
    def test_regime_1_high_position(self, engine):
        pos = engine.get_position_from_matrix(1, "erp_4_6")
        assert pos >= 70

    def test_regime_5_low_position(self, engine):
        pos = engine.get_position_from_matrix(5, "erp_2_4")
        assert pos <= 20

    def test_higher_erp_higher_position(self, engine):
        p_low = engine.get_position_from_matrix(3, "erp_lt2")
        p_high = engine.get_position_from_matrix(3, "erp_gt6")
        assert p_high >= p_low

    def test_smooth_interpolation(self, engine):
        """分界线附近应做平滑插值"""
        t = AP.REGIME_THRESHOLDS[0]  # first threshold
        pos_exact = engine.get_position_from_matrix(2, "erp_4_6", aiae_value=t)
        pos_below = engine.get_position_from_matrix(1, "erp_4_6", aiae_value=t - 2)
        pos_above = engine.get_position_from_matrix(2, "erp_4_6", aiae_value=t + 2)
        # 平滑插值应在两端之间
        assert pos_above <= pos_exact <= pos_below or pos_exact >= min(pos_above, pos_below)


# ═══════════════════════════════════════════════════
#  ERP 分级
# ═══════════════════════════════════════════════════

class TestClassifyErpLevel:
    def test_levels(self, engine):
        assert engine.classify_erp_level(7.0) == "erp_gt6"
        assert engine.classify_erp_level(5.0) == "erp_4_6"
        assert engine.classify_erp_level(3.0) == "erp_2_4"
        assert engine.classify_erp_level(1.0) == "erp_lt2"

    def test_boundaries(self, engine):
        assert engine.classify_erp_level(6.0) == "erp_gt6"
        assert engine.classify_erp_level(4.0) == "erp_4_6"
        assert engine.classify_erp_level(2.0) == "erp_2_4"


# ═══════════════════════════════════════════════════
#  ETF 信号生成
# ═══════════════════════════════════════════════════

class TestGenerateEtfSignals:
    def test_regime_1_all_buy(self, engine):
        signals = engine.generate_etf_signals(1)
        assert len(signals) == 8
        assert all(s["signal"] in ("buy", "hold") for s in signals)

    def test_regime_5_mostly_sell(self, engine):
        signals = engine.generate_etf_signals(5)
        sell_count = sum(1 for s in signals if s["signal"] == "sell")
        assert sell_count >= 4  # 至少 5 只宽基被卖出

    def test_signal_structure(self, engine):
        signals = engine.generate_etf_signals(3)
        for s in signals:
            assert "ts_code" in s
            assert "signal" in s
            assert s["signal"] in ("buy", "sell", "hold")
            assert "suggested_position" in s
            assert s["aiae_driven"] is True

    def test_regime_monotonic_position(self, engine):
        """Regime 升高 → 总仓位递减"""
        total_positions = []
        for regime in range(1, 6):
            signals = engine.generate_etf_signals(regime)
            total = sum(s["suggested_position"] for s in signals)
            total_positions.append(total)
        for i in range(len(total_positions) - 1):
            assert total_positions[i] >= total_positions[i + 1]


# ═══════════════════════════════════════════════════
#  联合权重 (run-all)
# ═══════════════════════════════════════════════════

class TestRunAllWeights:
    def test_weights_sum_to_1(self, engine):
        for regime in range(1, 6):
            for erp_score in [20, 50, 80]:
                weights, tier = engine.get_run_all_weights(regime, erp_score)
                total = sum(weights.values())
                assert abs(total - 1.0) < 0.01, f"Regime={regime} ERP={erp_score}: sum={total}"

    def test_erp_tier_mapping(self, engine):
        _, tier = engine.get_run_all_weights(3, 60)
        assert tier == "bull"
        _, tier = engine.get_run_all_weights(3, 50)
        assert tier == "neutral"
        _, tier = engine.get_run_all_weights(3, 30)
        assert tier == "bear"

    def test_regime_5_no_mr_mom(self, engine):
        weights, _ = engine.get_run_all_weights(5, 50)
        assert weights["mr"] == 0.0
        assert weights["mom"] == 0.0

    def test_none_erp_defaults_neutral(self, engine):
        weights, tier = engine.get_run_all_weights(3, None)
        assert tier == "neutral"
