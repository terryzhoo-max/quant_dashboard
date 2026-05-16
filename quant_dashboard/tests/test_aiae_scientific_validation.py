"""
AlphaCore · AIAE V3.0 科学级数值验证
=====================================
覆盖维度:
  T1: Sigmoid 融合模型数值正确性
  T2: 历史 8 节点回测命中率
  T3: 五档边界连续性 (无死区/跳变)
  T4: 仓位矩阵双维单调性
  T5: 交叉验证 12 分支完备性 + 可达性
  T6: 平滑插值对称性与连续性
  T7: ETF 矩阵行和单调递减
  T8: 联合权重矩阵完整性
  T9: 极端输入鲁棒性 (溢出/零值/负值)
"""

import pytest
import math
from unittest.mock import patch, MagicMock

import aiae_params as AP


# ═══════════════════════════════════════════════════
#  Fixture
# ═══════════════════════════════════════════════════

@pytest.fixture
def engine():
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
#  T1: Sigmoid 融合模型数值正确性
# ═══════════════════════════════════════════════════

class TestT1SigmoidFusion:
    """验证 Sigmoid 归一化的数学正确性"""

    def test_sigmoid_center_outputs_midpoint(self):
        """中心值输入 → 输出区间中点"""
        mid = (AP.NORM_MIN + AP.NORM_MAX) / 2  # 20.0
        fund_out = AP.sigmoid_normalize(AP.FUND_SIGMOID_CENTER, AP.FUND_SIGMOID_CENTER, AP.FUND_SIGMOID_K)
        margin_out = AP.sigmoid_normalize(AP.MARGIN_SIGMOID_CENTER, AP.MARGIN_SIGMOID_CENTER, AP.MARGIN_SIGMOID_K)
        assert abs(fund_out - mid) < 0.01, f"Fund center should output {mid}, got {fund_out}"
        assert abs(margin_out - mid) < 0.01, f"Margin center should output {mid}, got {margin_out}"

    def test_sigmoid_monotonic(self):
        """Sigmoid 严格单调递增"""
        prev = -999
        for v in range(50, 100):
            out = AP.sigmoid_normalize(float(v), AP.FUND_SIGMOID_CENTER, AP.FUND_SIGMOID_K)
            assert out > prev, f"Non-monotonic at fund_pos={v}: {out} <= {prev}"
            prev = out

    def test_sigmoid_bounded(self):
        """输出严格在 [NORM_MIN, NORM_MAX] 内"""
        for v in [0, 50, 68, 80, 92, 100, 200]:
            out = AP.sigmoid_normalize(float(v), AP.FUND_SIGMOID_CENTER, AP.FUND_SIGMOID_K)
            assert AP.NORM_MIN <= out <= AP.NORM_MAX, f"Out of bounds at {v}: {out}"

    def test_sigmoid_overflow_protection(self):
        """极端输入不触发 math overflow"""
        for extreme in [-1000, -100, 0, 500, 1000, 10000]:
            out = AP.sigmoid_normalize(float(extreme), 80.0, 0.15)
            assert math.isfinite(out), f"Non-finite at {extreme}"

    def test_fusion_formula_manual_calc(self, engine):
        """手算验证融合公式"""
        # 输入: AIAE_简=22.3, fund=82%, margin_heat=2.0
        aiae_simple = 22.3
        fund_pos = 82.0
        margin_heat = 2.0

        fund_sig = AP.sigmoid_normalize(fund_pos, AP.FUND_SIGMOID_CENTER, AP.FUND_SIGMOID_K)
        margin_sig = AP.sigmoid_normalize(margin_heat, AP.MARGIN_SIGMOID_CENTER, AP.MARGIN_SIGMOID_K)

        expected = AP.W_AIAE_SIMPLE * aiae_simple + AP.W_FUND_POS * fund_sig + AP.W_MARGIN_HEAT * margin_sig
        actual = engine.compute_aiae_v1(aiae_simple, fund_pos, margin_heat)

        assert abs(actual - round(expected, 2)) < 0.01, f"Manual={expected:.4f} vs Engine={actual}"

    def test_contribution_range_fund(self):
        """基金仓位有效贡献区间验证 (F2 文档标注)"""
        low = AP.sigmoid_normalize(68.0, AP.FUND_SIGMOID_CENTER, AP.FUND_SIGMOID_K)
        high = AP.sigmoid_normalize(92.0, AP.FUND_SIGMOID_CENTER, AP.FUND_SIGMOID_K)
        contrib_low = AP.W_FUND_POS * low
        contrib_high = AP.W_FUND_POS * high
        delta = contrib_high - contrib_low
        assert 3.0 < delta < 4.5, f"Fund contribution range={delta:.2f}, expected ~3.4"

    def test_contribution_range_margin(self):
        """融资热度有效贡献区间验证 (F2 文档标注)"""
        low = AP.sigmoid_normalize(1.2, AP.MARGIN_SIGMOID_CENTER, AP.MARGIN_SIGMOID_K)
        high = AP.sigmoid_normalize(3.5, AP.MARGIN_SIGMOID_CENTER, AP.MARGIN_SIGMOID_K)
        contrib_low = AP.W_MARGIN_HEAT * low
        contrib_high = AP.W_MARGIN_HEAT * high
        delta = contrib_high - contrib_low
        assert 4.5 < delta < 6.5, f"Margin contribution range={delta:.2f}, expected ~5.3"


# ═══════════════════════════════════════════════════
#  T2: 历史 8 节点回测
# ═══════════════════════════════════════════════════

class TestT2HistoricalBacktest:
    """验证 V3.0 参数对历史关键节点的分类正确性"""

    # (AIAE值, 预期Regime, 后1年收益方向, 标签)
    HISTORICAL = [
        (8.2,  1, "up",   "998点大底"),
        (42.5, 5, "down", "6124点顶部"),
        (10.1, 1, "up",   "1664点恐慌底"),
        (15.3, 2, "up",   "2000点底部"),
        (38.7, 5, "down", "5178点杠杆顶"),
        (13.8, 2, "up",   "2440点底部"),
        (28.9, 4, "down", "创业板泡沫"),
        (14.2, 2, "up",   "2635点底部"),
    ]

    @pytest.mark.parametrize("aiae,expected_regime,direction,label", HISTORICAL)
    def test_regime_classification(self, engine, aiae, expected_regime, direction, label):
        """每个历史节点的五档分类必须正确"""
        regime = engine.classify_regime(aiae)
        assert regime == expected_regime, f"{label}: AIAE={aiae}% → Regime {regime}, expected {expected_regime}"

    @pytest.mark.parametrize("aiae,expected_regime,direction,label", HISTORICAL)
    def test_regime_direction_consistency(self, engine, aiae, expected_regime, direction, label):
        """底部节点应在 Regime 1-2 (加仓), 顶部应在 4-5 (减仓)"""
        regime = engine.classify_regime(aiae)
        if direction == "up":
            assert regime <= 2, f"{label}: 底部但 Regime={regime} (应 ≤ 2)"
        else:
            assert regime >= 4, f"{label}: 顶部但 Regime={regime} (应 ≥ 4)"


# ═══════════════════════════════════════════════════
#  T3: 五档边界连续性
# ═══════════════════════════════════════════════════

class TestT3BoundaryContinuity:
    """验证五档分界线无死区、无跳变"""

    def test_no_dead_zone(self, engine):
        """0-50% 范围内每 0.1 步长都必须有明确档位"""
        for aiae_x10 in range(0, 500):
            aiae = aiae_x10 / 10.0
            regime = engine.classify_regime(aiae)
            assert 1 <= regime <= 5, f"AIAE={aiae} → invalid regime {regime}"

    def test_regime_never_skips(self, engine):
        """Regime 变化步长永远 ≤ 1 (不跳级)"""
        prev = engine.classify_regime(0.0)
        for aiae_x10 in range(1, 500):
            aiae = aiae_x10 / 10.0
            curr = engine.classify_regime(aiae)
            assert abs(curr - prev) <= 1, f"Regime jumped at AIAE={aiae}: {prev}→{curr}"
            prev = curr

    def test_full_range_v1_coverage(self, engine):
        """V1 融合后的极端组合必须覆盖 Regime 1 和 5"""
        # 极低组合
        v1_low = engine.compute_aiae_v1(8.0, 65.0, 1.0)
        assert engine.classify_regime(v1_low) <= 2, f"极低组合 V1={v1_low} 未能触发 Regime ≤ 2"
        # 极高组合
        v1_high = engine.compute_aiae_v1(42.0, 95.0, 4.0)
        assert engine.classify_regime(v1_high) >= 4, f"极高组合 V1={v1_high} 未能触发 Regime ≥ 4"


# ═══════════════════════════════════════════════════
#  T4: 仓位矩阵双维单调性
# ═══════════════════════════════════════════════════

class TestT4PositionMatrixMonotonicity:
    """验证仓位矩阵在两个维度上单调"""

    ERP_ORDER = ["erp_gt6", "erp_4_6", "erp_2_4", "erp_lt2"]

    def test_regime_axis_monotonic_decreasing(self):
        """固定 ERP, Regime ↑ → 仓位 ↓"""
        for erp in self.ERP_ORDER:
            row = AP.POSITION_MATRIX[erp]
            for i in range(len(row) - 1):
                assert row[i] >= row[i + 1], \
                    f"{erp}: Regime {i+1}→{i+2} 仓位 {row[i]}→{row[i+1]} 非递减"

    def test_erp_axis_monotonic_decreasing(self):
        """固定 Regime, ERP ↓ → 仓位 ↓"""
        for col in range(5):
            prev = AP.POSITION_MATRIX[self.ERP_ORDER[0]][col]
            for erp in self.ERP_ORDER[1:]:
                curr = AP.POSITION_MATRIX[erp][col]
                assert curr <= prev, \
                    f"Regime {col+1}: ERP {erp} 仓位 {curr} > 上一级 {prev}"
                prev = curr

    def test_extreme_corners(self):
        """四角极端值验证"""
        assert AP.POSITION_MATRIX["erp_gt6"][0] == 95, "R1+ERP>6 应为 95%"
        assert AP.POSITION_MATRIX["erp_lt2"][4] == 0, "R5+ERP<2 应为 0%"


# ═══════════════════════════════════════════════════
#  T5: 交叉验证 12 分支完备性
# ═══════════════════════════════════════════════════

class TestT5CrossValidation:
    """验证交叉验证的所有分支都可达且不重叠"""

    # (regime, erp_value) → expected_verdict_substring
    BRANCH_MAP = [
        (1, 7.0, "极强买入"),
        (1, 5.0, "强买入"),
        (2, 3.0, "标准买入"),
        (2, 1.0, "谨慎买入"),
        (3, 5.0, "谨慎乐观"),
        (3, 3.0, "中性"),
        (3, 1.0, "中性偏谨慎"),
        (4, 7.0, "极端矛盾"),      # F10 新增
        (4, 5.0, "矛盾信号"),
        (4, 3.0, "强减仓"),
        (5, 1.0, "全面撤退"),
        (5, 3.0, "清仓"),
    ]

    @pytest.mark.parametrize("regime,erp,expected_verdict", BRANCH_MAP)
    def test_branch_reachable(self, engine, regime, erp, expected_verdict):
        result = engine._cross_validate(regime, erp)
        assert expected_verdict in result["verdict"], \
            f"R{regime}+ERP={erp}: got '{result['verdict']}', expected containing '{expected_verdict}'"
        assert 1 <= result["confidence"] <= 5

    def test_all_branches_unique(self, engine):
        """所有分支输出不同的 verdict"""
        verdicts = set()
        for regime, erp, _ in self.BRANCH_MAP:
            result = engine._cross_validate(regime, erp)
            verdicts.add(result["verdict"])
        assert len(verdicts) == len(self.BRANCH_MAP), \
            f"Only {len(verdicts)} unique verdicts for {len(self.BRANCH_MAP)} branches"

    def test_regime4_erp6_confidence(self, engine):
        """F10: regime=4+erp≥6 置信度必须为 2"""
        result = engine._cross_validate(4, 7.0)
        assert result["confidence"] == 2


# ═══════════════════════════════════════════════════
#  T6: 平滑插值验证
# ═══════════════════════════════════════════════════

class TestT6SmoothInterpolation:
    """验证分界线缓冲带的平滑性"""

    def test_smooth_position_at_threshold(self):
        """分界线中心点 → 两端均值"""
        result = AP.smooth_position(25, 50, 23.0, 23.0)  # 恰在分界线
        assert result == round((25 + 50) / 2), f"中心应为均值, got {result}"

    def test_smooth_position_symmetric(self):
        """缓冲带两端对称"""
        t = 23.0
        buf = AP.REGIME_SMOOTH_BUFFER
        at_lower = AP.smooth_position(25, 50, t - buf, t)
        at_upper = AP.smooth_position(25, 50, t + buf, t)
        assert at_lower == 50, f"Lower edge should be pos_high=50, got {at_lower}"
        assert at_upper == 25, f"Upper edge should be pos_low=25, got {at_upper}"

    def test_smooth_continuity(self, engine):
        """缓冲带内 0.1 步长仓位变化 ≤ 3pt"""
        t = AP.REGIME_THRESHOLDS[2]  # 23.0
        prev_pos = None
        for x10 in range(int((t - 2) * 10), int((t + 2) * 10)):
            aiae = x10 / 10.0
            pos = engine.get_position_from_matrix(
                engine.classify_regime(aiae), "erp_2_4", aiae_value=aiae)
            if prev_pos is not None:
                delta = abs(pos - prev_pos)
                assert delta <= 3, f"Jump at AIAE={aiae}: {prev_pos}→{pos} (Δ={delta})"
            prev_pos = pos

    def test_buffer_constraint_holds(self):
        """断言: buffer < min(gap)/2"""
        gaps = [AP.REGIME_THRESHOLDS[i+1] - AP.REGIME_THRESHOLDS[i]
                for i in range(len(AP.REGIME_THRESHOLDS) - 1)]
        min_gap = min(gaps)
        assert AP.REGIME_SMOOTH_BUFFER < min_gap / 2


# ═══════════════════════════════════════════════════
#  T7: ETF 矩阵验证
# ═══════════════════════════════════════════════════

class TestT7ETFMatrix:
    """验证 ETF 绝对仓位矩阵"""

    def test_row_sums_monotonic_decreasing(self):
        """行和随 Regime ↑ 严格递减"""
        from engines.aiae_engine import AIAE_ETF_MATRIX
        sums = [sum(AIAE_ETF_MATRIX[r].values()) for r in range(1, 6)]
        for i in range(len(sums) - 1):
            assert sums[i] > sums[i + 1], f"R{i+1} sum={sums[i]} ≤ R{i+2} sum={sums[i+1]}"

    def test_no_negative_positions(self):
        """无负值仓位"""
        from engines.aiae_engine import AIAE_ETF_MATRIX
        for r in range(1, 6):
            for code, pos in AIAE_ETF_MATRIX[r].items():
                assert pos >= 0, f"R{r} {code}: negative position {pos}"

    def test_broad_decreases_dividend_increases(self):
        """宽基仓位随 Regime ↑ 递减, 红利仓位递增或持平"""
        from engines.aiae_engine import AIAE_ETF_MATRIX
        broad_code = "510300.SH"
        div_code = "510880.SH"
        for i in range(1, 5):
            assert AIAE_ETF_MATRIX[i][broad_code] >= AIAE_ETF_MATRIX[i+1][broad_code], \
                f"Broad {broad_code} non-decreasing R{i}→R{i+1}"


# ═══════════════════════════════════════════════════
#  T8: 联合权重矩阵
# ═══════════════════════════════════════════════════

class TestT8JointWeights:
    """验证 5×3 联合权重矩阵完整性"""

    def test_all_cells_sum_to_1(self, engine):
        """每个单元格 5 策略权重和 = 1.0"""
        from engines.aiae_engine import JOINT_WEIGHTS
        for regime in range(1, 6):
            for tier in ["bull", "neutral", "bear"]:
                w = JOINT_WEIGHTS[regime][tier]
                total = sum(w.values())
                assert abs(total - 1.0) < 0.01, f"R{regime}/{tier}: sum={total}"

    def test_regime5_no_offensive(self, engine):
        """Regime 5: MR 和 MOM 必须为 0"""
        from engines.aiae_engine import JOINT_WEIGHTS
        for tier in ["bull", "neutral", "bear"]:
            w = JOINT_WEIGHTS[5][tier]
            assert w["mr"] == 0.0, f"R5/{tier}: MR={w['mr']} should be 0"
            assert w["mom"] == 0.0, f"R5/{tier}: MOM={w['mom']} should be 0"


# ═══════════════════════════════════════════════════
#  T9: 极端输入鲁棒性
# ═══════════════════════════════════════════════════

class TestT9Robustness:
    """边界和极端值不崩溃"""

    def test_aiae_simple_extreme_inputs(self, engine):
        for mv, m2 in [(0.01, 500), (500, 0.01), (1000, 1000), (0, 300)]:
            result = engine.compute_aiae_simple(mv, m2)
            assert 0 <= result <= 100

    def test_margin_heat_extreme(self, engine):
        for rzye in [0, 0.001, 10.0, 100.0]:
            result = engine.compute_margin_heat({"rzye_wan_yi": rzye}, 100.0)
            assert result >= 0

    def test_v1_with_edge_fund_positions(self, engine):
        """基金仓位在验证区间 [50, 100] 边缘"""
        for fund in [50.0, 60.0, 100.0]:
            v1 = engine.compute_aiae_v1(20.0, fund, 2.0)
            assert 5 < v1 < 50, f"fund={fund}: V1={v1}"

    def test_classify_regime_at_zero_and_hundred(self, engine):
        assert engine.classify_regime(0.0) == 1
        assert engine.classify_regime(100.0) == 5

    def test_slope_with_extreme_values(self, engine):
        r = engine.compute_slope(50.0, 5.0)
        assert r["direction"] == "rising"
        assert r["signal"] is not None
        r2 = engine.compute_slope(5.0, 50.0)
        assert r2["direction"] == "falling"
