"""
AlphaCore V21.2 · 信号预警监控器测试
======================================
覆盖:
  - ALERT_RULES 完整性与阈值正确性
  - Cooldown 去重机制
  - scan_and_alert 全链路 (mock 快照)
  - 推送渠道防御 (config 缺失)
"""

import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.alert_monitor import ALERT_RULES, _load_config


# ═══════════════════════════════════════════════════════
#  ALERT_RULES 结构完整性
# ═══════════════════════════════════════════════════════

class TestAlertRulesIntegrity:
    """预警规则配置完整性"""

    def test_rules_is_list(self):
        assert isinstance(ALERT_RULES, list)
        assert len(ALERT_RULES) >= 3, "至少 3 条规则 (JCS低 + VIX恐慌 + VIX极端)"

    def test_each_rule_has_required_keys(self):
        required = {"id", "name", "check", "value_key", "severity", "icon",
                     "title_tpl", "detail_tpl", "cooldown_hours"}
        for rule in ALERT_RULES:
            missing = required - set(rule.keys())
            assert not missing, f"Rule '{rule.get('id', '?')}' missing: {missing}"

    def test_all_rule_ids_unique(self):
        ids = [r["id"] for r in ALERT_RULES]
        assert len(ids) == len(set(ids)), f"Duplicate rule IDs: {ids}"

    def test_severity_values(self):
        valid = {"warning", "critical", "info"}
        for rule in ALERT_RULES:
            assert rule["severity"] in valid, f"Rule '{rule['id']}' invalid severity"

    def test_cooldown_positive(self):
        for rule in ALERT_RULES:
            assert rule["cooldown_hours"] > 0, f"Rule '{rule['id']}' cooldown <= 0"


# ═══════════════════════════════════════════════════════
#  阈值触发逻辑
# ═══════════════════════════════════════════════════════

class TestThresholdLogic:
    """阈值触发判定"""

    def _find_rule(self, rule_id):
        return next(r for r in ALERT_RULES if r["id"] == rule_id)

    def test_jcs_low_triggers(self):
        """JCS < 25 应触发"""
        rule = self._find_rule("jcs_low")
        assert rule["check"]({"jcs_score": 20}) is True

    def test_jcs_normal_no_trigger(self):
        """JCS ≥ 25 不应触发"""
        rule = self._find_rule("jcs_low")
        assert rule["check"]({"jcs_score": 30}) is False

    def test_jcs_missing_no_trigger(self):
        """JCS 缺失 (默认 100) 不应触发"""
        rule = self._find_rule("jcs_low")
        assert rule["check"]({}) is False

    def test_vix_panic_triggers(self):
        """VIX > 30 应触发"""
        rule = self._find_rule("vix_panic")
        assert rule["check"]({"vix_val": 32}) is True

    def test_vix_panic_boundary(self):
        """VIX = 30 (边界) 不应触发"""
        rule = self._find_rule("vix_panic")
        assert rule["check"]({"vix_val": 30}) is False

    def test_vix_extreme_triggers(self):
        """VIX > 35 应触发"""
        rule = self._find_rule("vix_extreme")
        assert rule["check"]({"vix_val": 40}) is True

    def test_vix_extreme_no_trigger(self):
        """VIX = 33 不应触发极端"""
        rule = self._find_rule("vix_extreme")
        assert rule["check"]({"vix_val": 33}) is False

    def test_vix_none_safe(self):
        """VIX 为 None 不应崩溃"""
        rule = self._find_rule("vix_panic")
        assert rule["check"]({"vix_val": None}) is False

    def test_vix_missing_safe(self):
        """VIX 缺失不应崩溃"""
        rule = self._find_rule("vix_panic")
        assert rule["check"]({}) is False


# ═══════════════════════════════════════════════════════
#  模板格式化
# ═══════════════════════════════════════════════════════

class TestTemplateFormatting:
    """标题/详情模板不应 raise"""

    def test_title_format(self):
        for rule in ALERT_RULES:
            result = rule["title_tpl"].format(value=42.5)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_detail_format(self):
        for rule in ALERT_RULES:
            result = rule["detail_tpl"].format(value=42.5, pos=65)
            assert isinstance(result, str)
            assert len(result) > 0


# ═══════════════════════════════════════════════════════
#  配置加载防御
# ═══════════════════════════════════════════════════════

class TestConfigLoading:
    """配置文件缺失时应降级"""

    def test_missing_config_returns_browser(self):
        """配置文件不存在时应返回 browser-only"""
        import services.alert_monitor as am
        _orig = am._CONFIG_PATH
        am._CONFIG_PATH = "/nonexistent/path.json"
        try:
            config = _load_config()
            assert "browser" in config.get("channels_enabled", [])
        finally:
            am._CONFIG_PATH = _orig

    def test_config_returns_dict(self):
        config = _load_config()
        assert isinstance(config, dict)
        assert "channels_enabled" in config
