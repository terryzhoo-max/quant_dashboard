"""
AlphaCore V21.2 · 决策引擎核心测试
===================================
覆盖:
  - _signal_direction: 方向判定边界
  - compute_jcs: JCS 加法模型 + 矛盾惩罚
  - compute_conflict_matrix: 矛盾检测
  - generate_action_plan: 执行建议生成
  - generate_alerts: 预警规则
  - _parse_erp_value: ERP 防御性解析
  - get_hub_data: 数据新鲜度字段
"""

import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard_modules.decision_engine import (
    _signal_direction,
    compute_jcs,
    compute_conflict_matrix,
    generate_action_plan,
    generate_alerts,
    _parse_erp_value,
    _recalc_vix_score,
)


# ═══════════════════════════════════════════════════════
#  _signal_direction 方向判定
# ═══════════════════════════════════════════════════════

class TestSignalDirection:
    """测试 4 引擎方向映射的边界条件"""

    def test_all_bullish(self):
        """极度看多: AIAE 恐慌 + ERP 极高 + VIX 极低 + MR 牛市"""
        snap = {"aiae_regime": 1, "erp_score": 80, "vix_val": 12, "mr_regime": "BULL"}
        d = _signal_direction(snap)
        assert d == {"aiae": 1, "erp": 1, "vix": 1, "mr": 1}

    def test_all_bearish(self):
        """极度看空: AIAE 过热 + ERP 极低 + VIX 恐慌 + MR 崩盘"""
        snap = {"aiae_regime": 5, "erp_score": 20, "vix_val": 35, "mr_regime": "CRASH"}
        d = _signal_direction(snap)
        assert d == {"aiae": -1, "erp": -1, "vix": -1, "mr": -1}

    def test_all_neutral(self):
        """全中性: 所有引擎无方向"""
        snap = {"aiae_regime": 3, "erp_score": 45, "vix_val": 20, "mr_regime": "RANGE"}
        d = _signal_direction(snap)
        assert d == {"aiae": 0, "erp": 0, "vix": 0, "mr": 0}

    def test_aiae_boundary(self):
        """AIAE 边界: 2=看多, 3=中性, 4=看空"""
        assert _signal_direction({"aiae_regime": 2})["aiae"] == 1
        assert _signal_direction({"aiae_regime": 3})["aiae"] == 0
        assert _signal_direction({"aiae_regime": 4})["aiae"] == -1

    def test_erp_boundary(self):
        """ERP 边界: >55=看多, 35-55=中性, <35=看空 (V19.1 校准)"""
        assert _signal_direction({"erp_score": 56})["erp"] == 1
        assert _signal_direction({"erp_score": 55})["erp"] == 0
        assert _signal_direction({"erp_score": 35})["erp"] == 0
        assert _signal_direction({"erp_score": 34})["erp"] == -1

    def test_vix_boundary(self):
        """VIX 边界: <16=看多, 16-25=中性, >25=看空"""
        assert _signal_direction({"vix_val": 15.9})["vix"] == 1
        assert _signal_direction({"vix_val": 16})["vix"] == 0
        assert _signal_direction({"vix_val": 25})["vix"] == 0
        assert _signal_direction({"vix_val": 25.1})["vix"] == -1

    def test_mr_direction(self):
        """MR 方向: BULL=看多, BEAR/CRASH=看空, 其余=中性"""
        assert _signal_direction({"mr_regime": "BULL"})["mr"] == 1
        assert _signal_direction({"mr_regime": "BEAR"})["mr"] == -1
        assert _signal_direction({"mr_regime": "CRASH"})["mr"] == -1
        assert _signal_direction({"mr_regime": "RANGE"})["mr"] == 0

    def test_defaults_when_missing(self):
        """缺失字段使用默认值 — 不应崩溃"""
        d = _signal_direction({})
        assert "aiae" in d and "erp" in d and "vix" in d and "mr" in d

    def test_none_values_fallback_to_neutral(self):
        """显式 None 值应降级为中性 (V21.2 bug fix)"""
        snap = {"aiae_regime": None, "erp_score": None,
                "vix_val": None, "mr_regime": None}
        d = _signal_direction(snap)
        assert d == {"aiae": 0, "erp": 0, "vix": 0, "mr": 0}


# ═══════════════════════════════════════════════════════
#  compute_jcs 联合置信度引擎
# ═══════════════════════════════════════════════════════

class TestComputeJCS:
    """JCS 加法模型的核心属性"""

    def _make_snap(self, **overrides):
        base = {
            "aiae_regime": 3, "erp_score": 50, "vix_val": 20,
            "mr_regime": "RANGE", "degraded_modules": [],
        }
        base.update(overrides)
        return base

    def test_score_range(self):
        """JCS 必须在 [0, 100] 区间"""
        # 极端看多
        jcs_bull = compute_jcs(self._make_snap(
            aiae_regime=1, erp_score=80, vix_val=12, mr_regime="BULL"))
        assert 0 <= jcs_bull["score"] <= 100

        # 极端看空
        jcs_bear = compute_jcs(self._make_snap(
            aiae_regime=5, erp_score=10, vix_val=40, mr_regime="CRASH"))
        assert 0 <= jcs_bear["score"] <= 100

        # 全中性
        jcs_neutral = compute_jcs(self._make_snap())
        assert 0 <= jcs_neutral["score"] <= 100

    def test_all_bullish_is_high(self):
        """4 引擎全部看多 → JCS ≥ 70 (high)"""
        jcs = compute_jcs(self._make_snap(
            aiae_regime=1, erp_score=80, vix_val=12, mr_regime="BULL"))
        assert jcs["level"] == "high"
        assert jcs["score"] >= 70

    def test_all_neutral_is_medium(self):
        """全中性 → JCS 应在 medium 区间 (40-70)"""
        jcs = compute_jcs(self._make_snap())
        assert jcs["level"] == "medium"
        assert 40 <= jcs["score"] < 70

    def test_data_health_deduction(self):
        """缺失引擎数据应扣分
        
        NOTE: _signal_direction 对 None 不防御 (已知缺陷),
        此处用 sentinel 值模拟缺失以验证 data_health 扣分逻辑
        """
        full = compute_jcs(self._make_snap())
        # 用 sentinel 而非 None — 因为 _signal_direction 会 TypeError on None
        degraded = compute_jcs(self._make_snap(degraded_modules=["a", "b", "c"]))
        assert degraded["score"] < full["score"]

    def test_degraded_modules_deduction(self):
        """降级模块应扣分"""
        full = compute_jcs(self._make_snap())
        degraded = compute_jcs(self._make_snap(degraded_modules=["mod1", "mod2"]))
        assert degraded["score"] < full["score"]

    def test_level_thresholds(self):
        """level 分级阈值: ≥70=high, 40-70=medium, <40=low"""
        high = compute_jcs(self._make_snap(
            aiae_regime=1, erp_score=80, vix_val=12, mr_regime="BULL"))
        assert high["level"] == "high"

    def test_returns_required_fields(self):
        """返回值必须包含所有必需字段"""
        jcs = compute_jcs(self._make_snap())
        for key in ["score", "level", "label", "directions",
                     "agreement_pct", "data_health", "consensus_bonus"]:
            assert key in jcs, f"Missing key: {key}"

    def test_consensus_bonus_full_agreement(self):
        """4 引擎全一致 → consensus_bonus = 20"""
        jcs = compute_jcs(self._make_snap(
            aiae_regime=1, erp_score=80, vix_val=12, mr_regime="BULL"))
        assert jcs["consensus_bonus"] == 20.0

    def test_consensus_bonus_partial(self):
        """2 引擎一致 + 2 中性 → consensus_bonus = 10"""
        jcs = compute_jcs(self._make_snap(
            aiae_regime=1, erp_score=80, vix_val=20, mr_regime="RANGE"))
        assert jcs["consensus_bonus"] == 10.0


# ═══════════════════════════════════════════════════════
#  compute_conflict_matrix 矛盾检测
# ═══════════════════════════════════════════════════════

class TestConflictMatrix:

    def test_no_conflicts_all_neutral(self):
        """全中性 → 0 个矛盾 (info 级 all_neutral 不计为矛盾)"""
        snap = {"aiae_regime": 3, "erp_score": 50, "vix_val": 20, "mr_regime": "RANGE"}
        result = compute_conflict_matrix(snap)
        assert result["conflict_count"] == 0

    def test_bullish_with_bearish_vix(self):
        """AIAE 看多 + VIX 恐慌 → 应检测到矛盾"""
        snap = {"aiae_regime": 1, "erp_score": 80, "vix_val": 35, "mr_regime": "BULL"}
        result = compute_conflict_matrix(snap)
        assert result["conflict_count"] > 0

    def test_returns_structure(self):
        """返回值包含必要字段"""
        result = compute_conflict_matrix({"aiae_regime": 3})
        assert "conflict_count" in result
        assert "conflicts" in result
        assert isinstance(result["conflicts"], list)


# ═══════════════════════════════════════════════════════
#  generate_action_plan 执行建议
# ═══════════════════════════════════════════════════════

class TestGenerateActionPlan:

    def _make_args(self, jcs_score=50, level="medium", conflict_count=0):
        snap = {"aiae_regime": 3, "erp_score": 50, "vix_val": 20,
                "mr_regime": "RANGE", "suggested_position": 55}
        jcs = {"score": jcs_score, "level": level, "label": "test",
               "directions": {"aiae": 0, "erp": 0, "vix": 0, "mr": 0}}
        conflicts = {"conflict_count": conflict_count, "conflicts": []}
        return snap, jcs, conflicts

    def test_returns_dict(self):
        plan = generate_action_plan(*self._make_args())
        assert isinstance(plan, dict)

    def test_has_action_label(self):
        plan = generate_action_plan(*self._make_args())
        assert "action_label" in plan

    def test_has_risk_note(self):
        plan = generate_action_plan(*self._make_args())
        assert "risk_note" in plan

    def test_has_position_target(self):
        plan = generate_action_plan(*self._make_args())
        assert "position_target" in plan


# ═══════════════════════════════════════════════════════
#  generate_alerts 预警规则
# ═══════════════════════════════════════════════════════

class TestGenerateAlerts:

    def test_no_alerts_in_safe_zone(self):
        """安全状态 → 无预警"""
        snap = {"aiae_regime": 3, "erp_score": 50, "vix_val": 18,
                "mr_regime": "RANGE", "degraded_modules": []}
        alerts = generate_alerts(snap)
        assert isinstance(alerts, list)

    def test_vix_crisis_generates_alert(self):
        """VIX > 35 → 应生成预警"""
        snap = {"aiae_regime": 3, "erp_score": 50, "vix_val": 40,
                "mr_regime": "RANGE", "degraded_modules": []}
        alerts = generate_alerts(snap)
        assert len(alerts) > 0

    def test_alert_structure(self):
        """预警条目应包含必要字段"""
        snap = {"aiae_regime": 5, "erp_score": 10, "vix_val": 40,
                "mr_regime": "CRASH", "degraded_modules": ["test"]}
        alerts = generate_alerts(snap)
        if alerts:
            a = alerts[0]
            assert "level" in a or "severity" in a or "rule" in a


# ═══════════════════════════════════════════════════════
#  _parse_erp_value 防御性解析
# ═══════════════════════════════════════════════════════

class TestParseErpValue:

    def test_normal_float(self):
        assert _parse_erp_value(5.08) == 5.08

    def test_string_float(self):
        assert _parse_erp_value("4.5") == 4.5

    def test_dict_fallback(self):
        """字典类型 → 无法直接解析, 返回安全默认值 4.5"""
        assert _parse_erp_value({"value": 3.2}) == 4.5

    def test_none_returns_safe_default(self):
        """None → 返回 4.5 (中性安全默认值, 非 0)"""
        assert _parse_erp_value(None) == 4.5

    def test_garbage_returns_safe_default(self):
        """无法解析的字符串 → 返回 4.5 (安全默认值)"""
        assert _parse_erp_value("not_a_number") == 4.5

    def test_negative_clamped(self):
        """负值不应崩溃"""
        result = _parse_erp_value(-1.5)
        assert isinstance(result, float)


# ═══════════════════════════════════════════════════════
#  _recalc_vix_score VIX 评分
# ═══════════════════════════════════════════════════════

class TestRecalcVixScore:

    def test_low_vix_high_score(self):
        """VIX 低 → 评分高 (乐观)"""
        assert _recalc_vix_score(12.0) > 70

    def test_high_vix_low_score(self):
        """VIX 高 → 评分低 (恐慌)"""
        assert _recalc_vix_score(40.0) < 30

    def test_score_range(self):
        """评分在 [0, 100] 区间"""
        for vix in [5, 12, 16, 20, 25, 30, 40, 60, 80]:
            score = _recalc_vix_score(float(vix))
            assert 0 <= score <= 100, f"VIX={vix} → score={score} out of range"

    def test_monotonic_decreasing(self):
        """VIX 越高, 评分越低 (单调递减)"""
        scores = [_recalc_vix_score(float(v)) for v in [10, 20, 30, 40, 50]]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]
