"""
AlphaCore · 仓位决策引擎 单元测试
==================================
覆盖: get_vix_analysis, get_position_path, get_tomorrow_plan,
       get_institutional_mindset, get_tactical_label
"""
import pytest
from services.position_engine import (
    get_vix_analysis,
    get_position_path,
    get_tomorrow_plan,
    get_institutional_mindset,
    get_tactical_label,
    _synthesize_directives,
)


class TestVixAnalysis:
    """VIX 四级分析验证"""

    def test_low_vix(self, vix_low):
        result = get_vix_analysis(vix_low)
        assert result["multiplier"] == 1.05
        assert "极度平静" in result["label"]
        assert result["class"] == "vix-status-low"
        assert 0 <= result["percentile"] <= 100

    def test_normal_vix(self, vix_normal):
        result = get_vix_analysis(vix_normal)
        assert result["multiplier"] == 1.0
        assert "正常震荡" in result["label"]
        assert result["class"] == "vix-status-norm"

    def test_alert_vix(self, vix_alert):
        result = get_vix_analysis(vix_alert)
        assert result["multiplier"] == 0.75
        assert "高度警觉" in result["label"]

    def test_crisis_vix(self, vix_crisis):
        result = get_vix_analysis(vix_crisis)
        assert result["multiplier"] == 0.5
        assert "极端恐慌" in result["label"]

    def test_boundary_15(self):
        """边界值: VIX=15 应为正常震荡"""
        result = get_vix_analysis(15.0)
        assert result["multiplier"] == 1.0

    def test_boundary_25(self):
        """边界值: VIX=25 应为高度警觉"""
        result = get_vix_analysis(25.0)
        assert result["multiplier"] == 0.75

    def test_boundary_35(self):
        """边界值: VIX=35 应为极端恐慌"""
        result = get_vix_analysis(35.0)
        assert result["multiplier"] == 0.5

    def test_percentile_range(self):
        """百分位应始终在 0-100 范围内"""
        for vix in [5, 13.38, 20, 40, 60.13, 80]:
            result = get_vix_analysis(vix)
            assert 0 <= result["percentile"] <= 100


class TestPositionPath:
    """5日仓位路径预测"""

    def test_path_length(self, vix_normal):
        analysis = get_vix_analysis(vix_normal)
        path = get_position_path(65.0, analysis)
        assert len(path) == 5, "路径应包含 5 个交易日"

    def test_path_bounds(self, vix_crisis):
        """极端场景下仓位不应超出 10-100%"""
        analysis = get_vix_analysis(vix_crisis)
        path = get_position_path(30.0, analysis)
        for p in path:
            assert 10 <= p <= 100, f"仓位 {p} 超出边界"

    def test_path_convergence(self, vix_low):
        """低 VIX 下路径应小幅下调 (VIX 12.5 向 20 回归)"""
        analysis = get_vix_analysis(vix_low)
        path = get_position_path(80.0, analysis)
        # VIX从12.5向20回归，projected_vix更高，vix_gap为负，仓位应下调
        assert path[-1] <= 80.0, "低VIX路径应略下调(VIX回归假设)"


class TestTomorrowPlan:
    """明日交易计划"""

    def test_plan_with_aiae_ctx(self, vix_normal, mock_aiae_ctx):
        analysis = get_vix_analysis(vix_normal)
        plan = get_tomorrow_plan(analysis, 50, aiae_ctx=mock_aiae_ctx)
        # V2.0 应返回 primary_regime
        assert "primary_regime" in plan
        assert plan["primary_regime"]["tier"] == 3
        assert "validators" in plan
        assert "directives" in plan
        assert len(plan["directives"]) == 3

    def test_plan_without_aiae_ctx(self, vix_normal):
        """无 AIAE 上下文时应降级为 VIX 4阶查表"""
        analysis = get_vix_analysis(vix_normal)
        plan = get_tomorrow_plan(analysis, 50, aiae_ctx=None)
        assert "regime_matrix" in plan
        assert len(plan["regime_matrix"]) == 4

    def test_plan_regime_matrix_has_active(self, vix_normal, mock_aiae_ctx):
        """五档矩阵应有且仅有一个 active"""
        analysis = get_vix_analysis(vix_normal)
        plan = get_tomorrow_plan(analysis, 50, aiae_ctx=mock_aiae_ctx)
        active_count = sum(1 for r in plan["regime_matrix"] if r["active"])
        assert active_count == 1


class TestSynthesizeDirectives:
    """三因子指令合成"""

    def test_directive_count(self, mock_aiae_ctx, vix_normal):
        analysis = get_vix_analysis(vix_normal)
        directives = _synthesize_directives(mock_aiae_ctx, analysis)
        assert len(directives) == 3
        assert directives[0]["priority"] == "primary"
        assert directives[1]["priority"] == "confirm"
        assert directives[2]["priority"] == "risk"

    def test_vix_crisis_triggers_risk(self, mock_aiae_ctx, vix_crisis):
        """VIX >= 35 应触发风控降级"""
        analysis = get_vix_analysis(vix_crisis)
        directives = _synthesize_directives(mock_aiae_ctx, analysis)
        risk = directives[2]
        assert "🚨" in risk["icon"]
        assert "#ef4444" in risk["color"]


class TestMindsetAndLabel:
    """心态矩阵 & 仓位标签"""

    def test_mindset_tiers(self):
        assert "离场" in get_institutional_mindset(90)
        assert "乘胜" in get_institutional_mindset(70)
        assert "仓位中型" in get_institutional_mindset(50)
        assert "精准打击" in get_institutional_mindset(30)
        assert "战略建仓" in get_institutional_mindset(10)

    def test_tactical_label_crisis(self):
        assert "0%" in get_tactical_label(50, 50, 4, True)  # crisis

    def test_tactical_label_overheat(self):
        assert "0%" in get_tactical_label(50, 95, 4, False)  # temp > 90

    def test_tactical_label_normal(self):
        label = get_tactical_label(65, 50, 4, False)
        assert "65%" in label
        assert "趋势共振" in label

    def test_tactical_label_bottom(self):
        label = get_tactical_label(95, 20, 6, False)
        assert "95%" in label
        assert "代际大底" in label
