"""
AlphaCore P3-A · 合规引擎单元测试
==================================
覆盖全部 7 条 COMPLIANCE_RULES 的 hard_block / soft_warn / info 路径。
"""

import pytest
import sys
from unittest.mock import patch, MagicMock


# ── 合规引擎直接导入 (纯函数, 无 I/O 依赖) ──
from engines.compliance_engine import (
    run_compliance_check,
    _check_single_stock_cap,
    _check_sector_concentration,
    _check_aiae_overheat,
    _check_jcs_threshold,
    _check_vix_emergency,
    _check_min_holdings,
    _check_position_vs_cap,
    COMPLIANCE_RULES,
)


# ═══════════════════════════════════════════════════
#  辅助
# ═══════════════════════════════════════════════════

def _snap(**overrides):
    """构造一个最小快照"""
    base = {
        "aiae_regime": 3, "aiae_v1": 20.0,
        "erp_score": 50, "erp_val": 4.5,
        "vix_val": 18, "mr_regime": "RANGE",
        "suggested_position": 55,
    }
    base.update(overrides)
    return base


def _positions(*specs):
    """构造持仓列表: _positions(('A', 15, '电子'), ('B', 10, '银行'))"""
    return [
        {"ts_code": f"{name}.SH", "name": name, "weight": w, "industry": ind}
        for name, w, ind in specs
    ]


def _ctx(direction="hold", jcs_level="medium", jcs_score=50):
    return {"direction": direction, "jcs_level": jcs_level, "jcs_score": jcs_score}


def _mock_cache_manager(cap_value=None):
    """创建 mock cache_manager 并注入 services.cache_service 模块"""
    mock_cm = MagicMock()
    mock_cm.get_json.return_value = {"cap": cap_value} if cap_value is not None else None
    return patch("services.cache_service.cache_manager", mock_cm)


def _mock_no_portfolio():
    """阻止 portfolio_engine 加载"""
    mock_pe_module = MagicMock()
    mock_pe_module.get_portfolio_engine.side_effect = Exception("no portfolio")
    return patch.dict(sys.modules, {"portfolio_engine": mock_pe_module})


# ═══════════════════════════════════════════════════
#  R1: 单票仓位上限 (hard_block, 20%)
# ═══════════════════════════════════════════════════

class TestSingleStockCap:
    def test_all_within_limit(self):
        passed, _ = _check_single_stock_cap({}, _positions(("A", 15, "电子"), ("B", 19, "银行")), {})
        assert passed is True

    def test_at_boundary_20(self):
        passed, _ = _check_single_stock_cap({}, _positions(("A", 20, "电子")), {})
        assert passed is True  # 20% exactly is ok (> 20 triggers)

    def test_over_limit(self):
        passed, detail = _check_single_stock_cap({}, _positions(("A", 25, "电子")), {})
        assert passed is False
        assert "25.0%" in detail

    def test_multiple_over(self):
        passed, detail = _check_single_stock_cap(
            {}, _positions(("A", 22, "电子"), ("B", 30, "银行")), {})
        assert passed is False
        assert "A" in detail

    def test_no_positions(self):
        passed, _ = _check_single_stock_cap({}, None, {})
        assert passed is True

    def test_empty_positions(self):
        passed, _ = _check_single_stock_cap({}, [], {})
        assert passed is True


# ═══════════════════════════════════════════════════
#  R2: 板块集中度 (soft_warn, 40%)
# ═══════════════════════════════════════════════════

class TestSectorConcentration:
    def test_diversified(self):
        passed, _ = _check_sector_concentration(
            {}, _positions(("A", 15, "电子"), ("B", 15, "银行"), ("C", 10, "医药")), {})
        assert passed is True

    def test_high_concentration(self):
        passed, detail = _check_sector_concentration(
            {}, _positions(("A", 20, "电子"), ("B", 25, "电子")), {})
        assert passed is False
        assert "45" in detail or "电子" in detail

    def test_warning_zone_30_to_40(self):
        passed, detail = _check_sector_concentration(
            {}, _positions(("A", 20, "电子"), ("B", 15, "电子")), {})
        assert passed is True
        assert "接近" in detail or "35" in detail

    def test_no_positions(self):
        passed, _ = _check_sector_concentration({}, [], {})
        assert passed is True


# ═══════════════════════════════════════════════════
#  R3: AIAE 过热限制 (hard_block)
# ═══════════════════════════════════════════════════

class TestAIAEOverheat:
    def test_regime_3_any_direction(self):
        passed, _ = _check_aiae_overheat(_snap(aiae_regime=3), [], _ctx("increase"))
        assert passed is True

    def test_regime_4_hold_allowed(self):
        passed, _ = _check_aiae_overheat(_snap(aiae_regime=4), [], _ctx("hold"))
        assert passed is True

    def test_regime_4_increase_blocked(self):
        passed, detail = _check_aiae_overheat(_snap(aiae_regime=4), [], _ctx("increase"))
        assert passed is False
        assert "禁止加仓" in detail

    def test_regime_5_all_blocked(self):
        passed, detail = _check_aiae_overheat(_snap(aiae_regime=5), [], _ctx("hold"))
        assert passed is False
        assert "全面禁止" in detail

    def test_regime_5_decrease_also_blocked(self):
        passed, _ = _check_aiae_overheat(_snap(aiae_regime=5), [], _ctx("decrease"))
        assert passed is False

    def test_regime_1_safe(self):
        passed, _ = _check_aiae_overheat(_snap(aiae_regime=1), [], _ctx("increase"))
        assert passed is True

    def test_no_context_defaults_to_hold(self):
        passed, _ = _check_aiae_overheat(_snap(aiae_regime=4), [], None)
        assert passed is True


# ═══════════════════════════════════════════════════
#  R4: 仓位 vs AIAE Cap (hard_block)
# ═══════════════════════════════════════════════════

class TestPositionVsCap:
    def test_within_cap(self):
        with _mock_cache_manager(55), _mock_no_portfolio():
            passed, _ = _check_position_vs_cap(_snap(suggested_position=50), [], {})
        assert passed is True

    def test_over_cap_by_15(self):
        with _mock_cache_manager(40), _mock_no_portfolio():
            passed, detail = _check_position_vs_cap(_snap(suggested_position=55), [], {})
        assert passed is False
        assert "超过" in detail

    def test_no_cap_data(self):
        with _mock_cache_manager(None), _mock_no_portfolio():
            passed, _ = _check_position_vs_cap(_snap(), [], {})
        assert passed is True  # no data → skip


# ═══════════════════════════════════════════════════
#  R5: JCS 置信度门槛 (hard_block)
# ═══════════════════════════════════════════════════

class TestJCSThreshold:
    def test_high_jcs_increase_ok(self):
        passed, _ = _check_jcs_threshold({}, [], _ctx("increase", "high", 78))
        assert passed is True

    def test_low_jcs_increase_blocked(self):
        passed, detail = _check_jcs_threshold({}, [], _ctx("increase", "low", 30))
        assert passed is False
        assert "禁止加仓" in detail

    def test_low_jcs_decrease_allowed(self):
        passed, _ = _check_jcs_threshold({}, [], _ctx("decrease", "low", 30))
        assert passed is True

    def test_medium_jcs_any_ok(self):
        passed, _ = _check_jcs_threshold({}, [], _ctx("increase", "medium", 55))
        assert passed is True


# ═══════════════════════════════════════════════════
#  R6: VIX 紧急刹车 (hard_block)
# ═══════════════════════════════════════════════════

class TestVIXEmergency:
    def test_normal_vix(self):
        passed, _ = _check_vix_emergency(_snap(vix_val=18), [], {})
        assert passed is True

    def test_vix_31(self):
        passed, detail = _check_vix_emergency(_snap(vix_val=31), [], {})
        assert passed is False
        assert "30%" in detail

    def test_vix_40(self):
        passed, detail = _check_vix_emergency(_snap(vix_val=40), [], {})
        assert passed is False
        assert "35" in detail or "极端" in detail

    def test_none_vix_defaults_to_20(self):
        passed, _ = _check_vix_emergency(_snap(vix_val=None), [], {})
        assert passed is True


# ═══════════════════════════════════════════════════
#  R7: 最低分散持仓 (info)
# ═══════════════════════════════════════════════════

class TestMinHoldings:
    def test_6_holdings_ok(self):
        passed, detail = _check_min_holdings(
            {}, _positions(*[(f"S{i}", 10, "X") for i in range(6)]), {})
        assert passed is True
        assert "分散化满足" in detail

    def test_2_holdings_warning(self):
        passed, detail = _check_min_holdings(
            {}, _positions(("A", 50, "X"), ("B", 50, "Y")), {})
        assert passed is True
        assert "集中度" in detail

    def test_4_holdings_near_limit(self):
        passed, detail = _check_min_holdings(
            {}, _positions(*[(f"S{i}", 10, "X") for i in range(4)]), {})
        assert passed is True
        assert "接近" in detail


# ═══════════════════════════════════════════════════
#  集成: run_compliance_check
# ═══════════════════════════════════════════════════

class TestRunComplianceCheck:
    def test_all_pass_returns_passed(self):
        """健康快照 → 全部通过"""
        snap = _snap(aiae_regime=2, vix_val=15)
        ctx = _ctx("hold", "medium", 55)
        with _mock_cache_manager(85), _mock_no_portfolio():
            result = run_compliance_check(snap, positions=[], context=ctx)
        assert result["status"] == "passed"
        assert result["failed_count"] == 0
        assert len(result["checks"]) == 7

    def test_vix_crisis_returns_blocked(self):
        """VIX 危机 → 硬阻断"""
        snap = _snap(vix_val=38, aiae_regime=2)
        ctx = _ctx("hold", "medium", 55)
        with _mock_cache_manager(85), _mock_no_portfolio():
            result = run_compliance_check(snap, positions=[], context=ctx)
        assert result["status"] == "blocked"
        assert any(r["rule_id"] == "vix_emergency" for r in result["blocks"])

    def test_sector_warning_returns_warning(self):
        """板块集中 → 软警告"""
        snap = _snap(aiae_regime=2, vix_val=15)
        ctx = _ctx("hold", "medium", 55)
        positions = _positions(("A", 18, "电子"), ("B", 18, "电子"), ("C", 15, "电子"), ("D", 10, "银行"))
        with _mock_cache_manager(85), _mock_no_portfolio():
            result = run_compliance_check(snap, positions=positions, context=ctx)
        assert result["status"] == "warning"
        assert result["warn_count"] >= 1

    def test_has_summary(self):
        snap = _snap()
        with _mock_cache_manager(None), _mock_no_portfolio():
            result = run_compliance_check(snap, positions=[], context=_ctx())
        assert "summary" in result
        assert isinstance(result["summary"], str)

    def test_rule_count_is_7(self):
        assert len(COMPLIANCE_RULES) == 7
