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
#  Regime / TailRisk 规则 (P4 新增)
# ═══════════════════════════════════════════════════════

class TestP4Rules:
    """P4 新增的 Regime 切换和尾部风险规则"""

    def _find_rule(self, rule_id):
        return next(r for r in ALERT_RULES if r["id"] == rule_id)

    def test_regime_shift_triggers(self):
        rule = self._find_rule("regime_shift")
        assert rule["check"]({"_regime_shifted": True}) is True

    def test_regime_shift_no_trigger(self):
        rule = self._find_rule("regime_shift")
        assert rule["check"]({}) is False
        assert rule["check"]({"_regime_shifted": False}) is False

    def test_tail_risk_triggers(self):
        rule = self._find_rule("tail_risk_high")
        assert rule["check"]({"tail_risk_score": 60}) is True
        assert rule["check"]({"tail_risk_score": 85}) is True

    def test_tail_risk_no_trigger(self):
        rule = self._find_rule("tail_risk_high")
        assert rule["check"]({"tail_risk_score": 59}) is False
        assert rule["check"]({}) is False


# ═══════════════════════════════════════════════════════
#  推送渠道分发
# ═══════════════════════════════════════════════════════

from unittest.mock import patch, MagicMock
import json
from services.alert_monitor import (
    _push_all_channels, _push_serverchan, _push_email, _push_wecom,
)


class TestPushChannelDispatch:
    """多渠道推送分发逻辑"""

    def _alerts(self):
        return [{"icon": "⚠️", "title": "测试", "detail": "测试内容"}]

    def test_browser_only_no_external_push(self):
        """仅 browser 模式不调用任何外部推送"""
        with patch("services.alert_monitor._load_config",
                    return_value={"channels_enabled": ["browser"]}):
            with patch("services.alert_monitor._push_serverchan") as sc, \
                 patch("services.alert_monitor._push_email") as em, \
                 patch("services.alert_monitor._push_wecom") as wc:
                _push_all_channels(self._alerts())
                sc.assert_not_called()
                em.assert_not_called()
                wc.assert_not_called()

    def test_serverchan_dispatched(self):
        config = {"channels_enabled": ["serverchan"], "serverchan_sendkey": "k"}
        with patch("services.alert_monitor._load_config", return_value=config):
            with patch("services.alert_monitor._push_serverchan") as sc:
                _push_all_channels(self._alerts())
                sc.assert_called_once_with("k", "⚠️ 测试", "测试内容")

    def test_wecom_dispatched(self):
        config = {"channels_enabled": ["wecom"], "wecom_webhook_url": "https://wc.test"}
        with patch("services.alert_monitor._load_config", return_value=config):
            with patch("services.alert_monitor._push_wecom") as wc:
                _push_all_channels(self._alerts())
                wc.assert_called_once_with("https://wc.test", "⚠️ 测试", "测试内容")

    def test_multi_channel_all_called(self):
        config = {
            "channels_enabled": ["serverchan", "email", "wecom"],
            "serverchan_sendkey": "k",
            "email_smtp": {"host": "h", "user": "u", "password": "p"},
            "wecom_webhook_url": "https://wc",
        }
        with patch("services.alert_monitor._load_config", return_value=config):
            with patch("services.alert_monitor._push_serverchan") as sc, \
                 patch("services.alert_monitor._push_email") as em, \
                 patch("services.alert_monitor._push_wecom") as wc:
                _push_all_channels(self._alerts())
                sc.assert_called_once()
                em.assert_called_once()
                wc.assert_called_once()


class TestPushEndpoints:
    """各推送通道的防御逻辑"""

    def test_serverchan_no_key_skips(self):
        _push_serverchan("", "title", "body")  # 不抛异常

    def test_email_incomplete_skips(self):
        _push_email({}, "title", "body")  # 不抛异常

    def test_wecom_no_url_skips(self):
        _push_wecom("", "title", "body")  # 不抛异常

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_wecom_sends_markdown(self, mock_req, mock_open):
        resp = MagicMock()
        resp.read.return_value = json.dumps({"errcode": 0}).encode()
        resp.__enter__ = lambda s: resp
        resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = resp

        _push_wecom("https://wc.test/hook", "VIX 恐慌", "详情")
        call_args = mock_req.call_args
        # Request(url, data=payload, method="POST", headers=...)
        payload = json.loads(call_args[1].get("data", call_args[0][1] if len(call_args[0]) > 1 else b"{}"))
        assert payload["msgtype"] == "markdown"
        assert "VIX 恐慌" in payload["markdown"]["content"]


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


# ═══════════════════════════════════════════════════════
#  scan_and_alert 集成测试
# ═══════════════════════════════════════════════════════

from datetime import datetime, timedelta
from services.alert_monitor import scan_and_alert

class TestScanAndAlertIntegration:
    """完整扫描流程 (mock 外部依赖)"""

    @patch("services.alert_monitor.threading.Thread")
    @patch("dashboard_modules.decision_engine.compute_jcs")
    @patch("dashboard_modules.decision_engine._build_snapshot_from_cache")
    def test_no_snapshot_returns_empty(self, mock_snap, mock_jcs, mock_thread):
        mock_snap.return_value = None
        result = scan_and_alert()
        assert result == []
        mock_jcs.assert_not_called()

    @patch("services.alert_monitor.threading.Thread")
    def test_vix_panic_triggers(self, mock_thread):
        """VIX > 30 的快照应触发恐慌预警"""
        with patch("dashboard_modules.decision_engine._build_snapshot_from_cache") as mock_snap, \
             patch("dashboard_modules.decision_engine.compute_jcs") as mock_jcs, \
             patch("services.db.get_last_alert_time") as mock_last, \
             patch("services.db.get_decision_history") as mock_hist, \
             patch("services.db.save_alert") as mock_save, \
             patch("dashboard_modules.decision_engine.compute_risk_matrix",
                    return_value={"tail_risk": {"score": 30}}):
            mock_snap.return_value = {
                "aiae_regime": 4, "vix_val": 33, "suggested_position": 30,
            }
            mock_jcs.return_value = {"score": 45, "level": "medium"}
            mock_last.return_value = None
            mock_hist.return_value = []

            result = scan_and_alert()

            triggered_ids = [a["rule_id"] for a in result]
            assert "vix_panic" in triggered_ids
            mock_save.assert_called()

    @patch("services.alert_monitor.threading.Thread")
    def test_cooldown_suppresses_repeat(self, mock_thread):
        """Cooldown 期内同一规则不重复触发"""
        with patch("dashboard_modules.decision_engine._build_snapshot_from_cache") as mock_snap, \
             patch("dashboard_modules.decision_engine.compute_jcs") as mock_jcs, \
             patch("services.db.get_last_alert_time") as mock_last, \
             patch("services.db.get_decision_history") as mock_hist, \
             patch("services.db.save_alert"), \
             patch("dashboard_modules.decision_engine.compute_risk_matrix",
                    return_value={"tail_risk": {"score": 10}}):
            mock_snap.return_value = {
                "aiae_regime": 3, "vix_val": 33, "suggested_position": 50,
            }
            mock_jcs.return_value = {"score": 72, "level": "high"}
            # 2 小时前触发过 (vix_panic cooldown = 4h)
            two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat()
            mock_last.return_value = two_hours_ago
            mock_hist.return_value = []

            result = scan_and_alert()

            triggered_ids = [a["rule_id"] for a in result]
            assert "vix_panic" not in triggered_ids
