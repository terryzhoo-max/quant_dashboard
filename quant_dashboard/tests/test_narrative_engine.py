"""
AlphaCore P4 · 叙事引擎单元测试
====================================
覆盖:
  - 确定性报告生成 (所有 Regime + JCS 级别组合)
  - LLM 调用链 (多 Provider 回退)
  - 配置加载防御
  - generate_daily_narrative 集成流程
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from services.narrative_engine import (
    _deterministic_report,
    _call_llm,
    _load_ai_config,
    generate_daily_narrative,
    get_daily_narrative,
    _REGIME_LABELS,
    _JCS_LABELS,
)


# ═══════════════════════════════════════════════════════
#  确定性报告
# ═══════════════════════════════════════════════════════

class TestDeterministicReport:
    """确定性引擎 (无 LLM) 的报告质量测试"""

    def _snapshot(self, **kwargs):
        base = {
            "aiae_regime": 3, "jcs_score": 60, "jcs_level": "medium",
            "vix_val": 18, "suggested_position": 55,
            "signal_directions": {"aiae": 1, "erp": 0, "vix": 1, "mr": -1},
        }
        base.update(kwargs)
        return base

    def test_basic_structure(self):
        """报告包含四个必需段落"""
        report = _deterministic_report(self._snapshot())
        for section in ["【市场温度】", "【策略信号】", "【风险提示】", "【操作建议】"]:
            assert section in report, f"缺少段落: {section}"

    def test_regime_cold(self):
        """冷市 (R1/R2) 报告包含降仓建议"""
        report = _deterministic_report(self._snapshot(aiae_regime=1, suggested_position=25))
        assert "偏冷" in report or "极冷" in report or "降低仓位" in report

    def test_regime_hot(self):
        """热市 (R4/R5) 报告包含止盈提示"""
        report = _deterministic_report(self._snapshot(
            aiae_regime=4, jcs_score=75, jcs_level="high", suggested_position=70
        ))
        assert "止盈" in report or "偏热" in report

    def test_vix_high_warning(self):
        """VIX > 25 时应有风险警告"""
        report = _deterministic_report(self._snapshot(vix_val=32))
        assert "恐慌" in report or "偏高" in report

    def test_vix_normal(self):
        """VIX 正常时情绪稳定"""
        report = _deterministic_report(self._snapshot(vix_val=15))
        assert "稳定" in report or "正常" in report

    def test_tail_risk_warning(self):
        """尾部风险高时应提醒"""
        report = _deterministic_report(self._snapshot(tail_risk_score=65))
        assert "尾部风险" in report

    def test_no_tail_risk(self):
        """无重大风险时应表明"""
        report = _deterministic_report(self._snapshot(vix_val=12))
        assert "无重大风险" in report

    def test_includes_data(self):
        """报告应引用具体数据"""
        report = _deterministic_report(self._snapshot(jcs_score=72.5))
        assert "72.5" in report

    def test_all_regimes(self):
        """所有 Regime 都能生成报告"""
        for r in range(1, 6):
            report = _deterministic_report(self._snapshot(aiae_regime=r))
            assert len(report) > 50

    def test_signal_directions_display(self):
        """显示看多/看空统计"""
        report = _deterministic_report(self._snapshot(
            signal_directions={"aiae": 1, "erp": 1, "vix": 1, "mr": 0, "gold": -1, "bond": 0}
        ))
        assert "看多" in report


# ═══════════════════════════════════════════════════════
#  LLM 调用链
# ═══════════════════════════════════════════════════════

class TestLLMCallChain:
    """多 Provider 回退逻辑"""

    def test_no_api_key_returns_none(self):
        """所有 provider 都没有 key 时返回 None"""
        cfg = {
            "provider": "gemini",
            "gemini": {"api_key": ""},
            "deepseek": {"api_key": ""},
        }
        result = _call_llm("test", cfg)
        assert result is None

    @patch("services.narrative_engine._call_openai_compatible")
    def test_primary_provider_used(self, mock_call):
        """优先使用配置的 provider"""
        mock_call.return_value = "测试报告"
        cfg = {
            "provider": "deepseek",
            "deepseek": {"api_key": "sk-test1234567890abcdef"},
        }
        result = _call_llm("test prompt", cfg)
        assert result == "测试报告"
        mock_call.assert_called_once()

    @patch("services.narrative_engine._call_gemini")
    @patch("services.narrative_engine._call_openai_compatible")
    def test_fallback_to_gemini(self, mock_ds, mock_gemini):
        """主 provider 失败后回退到 gemini"""
        mock_ds.side_effect = Exception("timeout")
        mock_gemini.return_value = "gemini 报告"
        cfg = {
            "provider": "deepseek",
            "deepseek": {"api_key": "sk-test1234567890abcdef"},
            "gemini": {"api_key": "AIzatest1234567890abcdef"},
        }
        result = _call_llm("test", cfg)
        assert result == "gemini 报告"

    @patch("services.narrative_engine._call_gemini")
    @patch("services.narrative_engine._call_openai_compatible")
    def test_all_fail_returns_none(self, mock_ds, mock_gemini):
        """所有 provider 都失败时返回 None"""
        mock_ds.side_effect = Exception("timeout")
        mock_gemini.side_effect = Exception("quota exceeded")
        cfg = {
            "provider": "deepseek",
            "deepseek": {"api_key": "sk-test1234567890abcdef"},
            "gemini": {"api_key": "AIzatest1234567890abcdef"},
        }
        result = _call_llm("test", cfg)
        assert result is None


# ═══════════════════════════════════════════════════════
#  配置加载
# ═══════════════════════════════════════════════════════

class TestNarrativeConfig:
    def test_missing_config_disables_ai(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            cfg = _load_ai_config()
            assert cfg.get("enable_ai_narrative") is False

    def test_loads_real_config(self):
        cfg = _load_ai_config()
        assert isinstance(cfg, dict)


# ═══════════════════════════════════════════════════════
#  集成流程
# ═══════════════════════════════════════════════════════

class TestGenerateNarrative:
    @patch("dashboard_modules.decision_engine._build_snapshot_from_cache")
    def test_no_snapshot_returns_error(self, mock_snap):
        mock_snap.return_value = None
        result = generate_daily_narrative(force_deterministic=True)
        assert result["status"] == "error"

    @patch("dashboard_modules.decision.conflicts._signal_direction")
    @patch("dashboard_modules.decision_engine.compute_jcs")
    @patch("dashboard_modules.decision_engine._build_snapshot_from_cache")
    def test_deterministic_mode(self, mock_snap, mock_jcs, mock_dirs):
        """强制确定性模式不调用 LLM"""
        mock_snap.return_value = {
            "aiae_regime": 3, "vix_val": 18, "suggested_position": 55,
        }
        mock_jcs.return_value = {"score": 65, "level": "medium"}
        mock_dirs.return_value = {"aiae": 1, "erp": 0, "vix": 1, "mr": -1}

        result = generate_daily_narrative(force_deterministic=True)

        assert result["status"] == "success"
        assert result["provider"] == "deterministic"
        assert "【市场温度】" in result["report"]
        assert result["snapshot_date"] is not None
