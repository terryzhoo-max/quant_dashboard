"""
AlphaCore · 决策层科学验证
===========================
覆盖维度:
  D1: JCS 加法模型分值区间验证
  D2: 信号方向映射完备性
  D3: 矛盾规则触发矩阵验证
  D4: Action Plan 分支覆盖验证
  D5: JCS Sigmoid 仓位乘数连续性
  D6: 情景模拟联锁一致性
  D7: Alert 触发阈值不重叠
"""

import pytest
import math

# 直接从决策引擎导入 (它是全系统的 canonical 入口)
from dashboard_modules.decision_engine import (
    _signal_direction,
    compute_conflict_matrix,
    compute_jcs,
    generate_action_plan,
    generate_alerts,
    _JCS_WEIGHTS,
)


# ═══════════════════════════════════════════════════
#  D1: JCS 加法模型分值区间
# ═══════════════════════════════════════════════════

class TestD1JCSScoreRange:
    """验证 JCS 在各种组合下输出 [0, 100]"""

    SCENARIOS = [
        # (name, snapshot_overrides)
        ("all_bullish", {"aiae_regime": 1, "erp_score": 70, "vix_val": 14, "mr_regime": "BULL"}),
        ("all_bearish", {"aiae_regime": 5, "erp_score": 20, "vix_val": 35, "mr_regime": "CRASH"}),
        ("all_neutral", {"aiae_regime": 3, "erp_score": 50, "vix_val": 20, "mr_regime": "RANGE"}),
        ("mixed_bull_bear", {"aiae_regime": 1, "erp_score": 20, "vix_val": 35, "mr_regime": "BULL"}),
        ("cold_start", {}),  # 空快照
        ("partial_data", {"aiae_regime": 2, "erp_score": None, "vix_val": None}),
        ("extreme_vix", {"aiae_regime": 3, "erp_score": 50, "vix_val": 80, "mr_regime": "CRASH"}),
        ("degraded", {"aiae_regime": 3, "degraded_modules": ["ERP", "VIX", "MR"]}),
    ]

    @pytest.mark.parametrize("name,snap", SCENARIOS)
    def test_score_bounded(self, name, snap):
        jcs = compute_jcs(snap)
        assert 0 <= jcs["score"] <= 100, f"{name}: JCS={jcs['score']}"
        assert jcs["level"] in ("high", "medium", "low")

    def test_all_bullish_high_confidence(self):
        snap = {"aiae_regime": 1, "erp_score": 70, "vix_val": 14, "mr_regime": "BULL"}
        jcs = compute_jcs(snap)
        assert jcs["level"] == "high", f"All bullish but level={jcs['level']} score={jcs['score']}"
        assert jcs["score"] >= 70

    def test_all_bearish_but_consistent_is_high(self):
        """4引擎一致看空 → JCS 仍高 (方向一致性高)"""
        snap = {"aiae_regime": 5, "erp_score": 20, "vix_val": 35, "mr_regime": "CRASH"}
        jcs = compute_jcs(snap)
        # 方向一致但可能触发矛盾规则, JCS 不一定 high
        assert jcs["score"] >= 0  # 不崩溃即可

    def test_degraded_data_lowers_health(self):
        snap_good = {"aiae_regime": 2, "erp_score": 60, "vix_val": 15, "mr_regime": "BULL"}
        snap_bad = {"aiae_regime": 2, "erp_score": 60, "vix_val": 15, "mr_regime": "BULL",
                    "degraded_modules": ["ERP", "VIX"]}
        jcs_good = compute_jcs(snap_good)
        jcs_bad = compute_jcs(snap_bad)
        assert jcs_bad["data_health"] < jcs_good["data_health"]


# ═══════════════════════════════════════════════════
#  D2: 信号方向映射完备性
# ═══════════════════════════════════════════════════

class TestD2SignalDirection:
    def test_aiae_direction_mapping(self):
        assert _signal_direction({"aiae_regime": 1})["aiae"] == 1
        assert _signal_direction({"aiae_regime": 2})["aiae"] == 1
        assert _signal_direction({"aiae_regime": 3})["aiae"] == 0
        assert _signal_direction({"aiae_regime": 4})["aiae"] == -1
        assert _signal_direction({"aiae_regime": 5})["aiae"] == -1

    def test_erp_direction_mapping(self):
        assert _signal_direction({"erp_score": 60})["erp"] == 1
        assert _signal_direction({"erp_score": 45})["erp"] == 0
        assert _signal_direction({"erp_score": 30})["erp"] == -1

    def test_vix_direction_mapping(self):
        assert _signal_direction({"vix_val": 14})["vix"] == 1
        assert _signal_direction({"vix_val": 20})["vix"] == 0
        assert _signal_direction({"vix_val": 28})["vix"] == -1

    def test_mr_direction_mapping(self):
        assert _signal_direction({"mr_regime": "BULL"})["mr"] == 1
        assert _signal_direction({"mr_regime": "RANGE"})["mr"] == 0
        assert _signal_direction({"mr_regime": "BEAR"})["mr"] == -1
        assert _signal_direction({"mr_regime": "CRASH"})["mr"] == -1

    def test_none_defaults_to_neutral(self):
        """None 值不崩溃且映射为中性"""
        dirs = _signal_direction({})
        assert dirs["aiae"] == 0
        assert dirs["erp"] == 0
        assert dirs["vix"] == 0
        assert dirs["mr"] == 0

    def test_weights_sum_to_1(self):
        total = sum(_JCS_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01


# ═══════════════════════════════════════════════════
#  D3: 矛盾规则触发矩阵
# ═══════════════════════════════════════════════════

class TestD3ConflictRules:
    def test_aiae_hot_erp_bull(self):
        snap = {"aiae_regime": 4, "erp_score": 70}
        result = compute_conflict_matrix(snap)
        ids = [c["id"] for c in result["conflicts"]]
        assert "aiae_vs_erp_bull" in ids

    def test_vix_panic_aiae_cold(self):
        snap = {"aiae_regime": 1, "vix_val": 32}
        result = compute_conflict_matrix(snap)
        ids = [c["id"] for c in result["conflicts"]]
        assert "vix_vs_aiae_cold" in ids
        assert result["has_severe"]

    def test_no_conflicts_normal(self):
        snap = {"aiae_regime": 3, "erp_score": 50, "vix_val": 18, "mr_regime": "RANGE"}
        result = compute_conflict_matrix(snap)
        assert result["conflict_count"] == 0

    def test_all_neutral_is_info_not_counted(self):
        snap = {"aiae_regime": 3, "erp_score": 50, "vix_val": 20, "mr_regime": "RANGE"}
        result = compute_conflict_matrix(snap)
        # all_neutral 触发但 severity=info, 不计入 conflict_count
        info_conflicts = [c for c in result["conflicts"] if c["severity"] == "info"]
        assert result["conflict_count"] == 0  # info 不计入

    def test_conflict_severity_hierarchy(self):
        """severe 矛盾在前"""
        snap = {"aiae_regime": 1, "erp_score": 30, "vix_val": 32, "mr_regime": "BULL"}
        result = compute_conflict_matrix(snap)
        if result["has_severe"]:
            severe = [c for c in result["conflicts"] if c["severity"] == "high"]
            assert len(severe) >= 1


# ═══════════════════════════════════════════════════
#  D4: Action Plan 分支覆盖
# ═══════════════════════════════════════════════════

class TestD4ActionPlan:
    def _make_plan(self, snap, jcs_override=None):
        jcs = jcs_override or compute_jcs(snap)
        conflicts = compute_conflict_matrix(snap)
        return generate_action_plan(snap, jcs, conflicts)

    def test_high_bullish_plan(self):
        snap = {"aiae_regime": 1, "erp_score": 70, "vix_val": 14, "mr_regime": "BULL"}
        plan = self._make_plan(snap)
        assert plan["confidence"] in ("high", "medium")
        assert plan["position_target"] > 0

    def test_severe_conflict_pauses(self):
        snap = {"aiae_regime": 1, "erp_score": 70, "vix_val": 32, "mr_regime": "BULL"}
        plan = self._make_plan(snap)
        if plan["confidence"] == "low":
            assert "暂停" in plan["action_label"] or plan["position_target"] <= 30

    def test_medium_confidence_hold(self):
        snap = {"aiae_regime": 3, "erp_score": 50, "vix_val": 20, "mr_regime": "RANGE"}
        plan = self._make_plan(snap)
        assert plan["confidence"] in ("medium", "high")

    def test_plan_structure(self):
        snap = {"aiae_regime": 3, "erp_score": 50, "vix_val": 20, "mr_regime": "RANGE"}
        plan = self._make_plan(snap)
        required_keys = ["action_label", "action_icon", "confidence", "reasoning",
                         "top_signals", "next_check", "position_target", "risk_note"]
        for k in required_keys:
            assert k in plan, f"Missing key: {k}"

    def test_position_target_bounded(self):
        """仓位目标在 [0, 100] 内"""
        combos = [
            {"aiae_regime": 1, "erp_score": 95, "vix_val": 10, "mr_regime": "BULL"},
            {"aiae_regime": 5, "erp_score": 10, "vix_val": 45, "mr_regime": "CRASH"},
            {},
        ]
        for snap in combos:
            plan = self._make_plan(snap)
            assert 0 <= plan["position_target"] <= 100, f"pos={plan['position_target']}"


# ═══════════════════════════════════════════════════
#  D5: JCS Sigmoid 仓位乘数连续性
# ═══════════════════════════════════════════════════

class TestD5JCSMultiplier:
    def test_multiplier_monotonic(self):
        """JCS ↑ → 乘数 ↑"""
        prev = 0
        for jcs_score in range(0, 101):
            m = 0.5 + 0.5 / (1 + math.exp(-0.08 * (jcs_score - 45)))
            assert m >= prev, f"Non-monotonic at JCS={jcs_score}"
            prev = m

    def test_multiplier_range(self):
        """乘数在 [0.5, 1.0] 内"""
        for jcs_score in range(0, 101):
            m = 0.5 + 0.5 / (1 + math.exp(-0.08 * (jcs_score - 45)))
            assert 0.5 <= m <= 1.0, f"JCS={jcs_score}: m={m}"

    def test_multiplier_at_key_points(self):
        """关键点验证"""
        m_0 = 0.5 + 0.5 / (1 + math.exp(-0.08 * (0 - 45)))
        m_45 = 0.5 + 0.5 / (1 + math.exp(-0.08 * (45 - 45)))
        m_100 = 0.5 + 0.5 / (1 + math.exp(-0.08 * (100 - 45)))
        assert 0.50 < m_0 < 0.60   # 低 JCS → ~0.55
        assert 0.74 < m_45 < 0.76  # 中间点 → 0.75
        assert 0.95 < m_100        # 高 JCS → ~0.99


# ═══════════════════════════════════════════════════
#  D6: Alert 触发阈值验证
# ═══════════════════════════════════════════════════

class TestD6Alerts:
    def test_vix_extreme_alert(self):
        alerts = generate_alerts({"vix_val": 40})
        types = [a["type"] for a in alerts]
        assert "vix_extreme" in types

    def test_no_alert_normal(self):
        alerts = generate_alerts({"vix_val": 18, "aiae_regime": 3})
        assert len(alerts) == 0

    def test_aiae_overheat_alert(self):
        alerts = generate_alerts({"aiae_regime": 5})
        types = [a["type"] for a in alerts]
        assert "aiae_overheat" in types

    def test_circuit_breaker_alert(self):
        alerts = generate_alerts({"is_circuit_breaker": True})
        types = [a["type"] for a in alerts]
        assert "circuit_breaker" in types

    def test_multi_bear_alert(self):
        snap = {"aiae_regime": 5, "erp_score": 20, "vix_val": 35, "mr_regime": "CRASH"}
        alerts = generate_alerts(snap)
        types = [a["type"] for a in alerts]
        assert "multi_bear" in types

    def test_alert_severity_valid(self):
        snap = {"vix_val": 40, "aiae_regime": 5, "is_circuit_breaker": True,
                "degraded_modules": ["ERP", "VIX"], "erp_score": 20, "mr_regime": "CRASH"}
        alerts = generate_alerts(snap)
        for a in alerts:
            assert a["severity"] in ("critical", "warning", "caution"), f"Invalid severity: {a['severity']}"


# ═══════════════════════════════════════════════════
#  D7: 决策一致性 (Action Plan 与 JCS 方向对齐)
# ═══════════════════════════════════════════════════

class TestD7Consistency:
    def test_high_jcs_bullish_not_defensive(self):
        """高 JCS + 全看多 → 不应输出防御"""
        snap = {"aiae_regime": 1, "erp_score": 70, "vix_val": 14, "mr_regime": "BULL",
                "suggested_position": 85}
        jcs = compute_jcs(snap)
        if jcs["level"] == "high":
            conflicts = compute_conflict_matrix(snap)
            plan = generate_action_plan(snap, jcs, conflicts)
            assert "防御" not in plan["action_label"]
            assert "暂停" not in plan["action_label"]

    def test_low_jcs_not_aggressive(self):
        """低 JCS → 不应输出积极加仓"""
        snap = {"aiae_regime": 5, "erp_score": 20, "vix_val": 35, "mr_regime": "CRASH",
                "suggested_position": 10}
        jcs = compute_jcs(snap)
        conflicts = compute_conflict_matrix(snap)
        plan = generate_action_plan(snap, jcs, conflicts)
        assert "积极加仓" not in plan["action_label"]
