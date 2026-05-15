"""
AlphaCore P3-A · NLP 情报引擎单元测试
========================================
mock 掉 Tushare 和 Gemini API, 验证:
  - 关键词过滤逻辑
  - Gemini JSON 解析 (包含 markdown 包裹)
  - 事件 ID 生成
  - scan_news 集成流程
  - 情景模板映射
"""

import pytest
import json
from unittest.mock import patch, MagicMock

from engines.news_intelligence import (
    _keyword_filter,
    _generate_event_id,
    _SCENARIO_MAP,
    _KEYWORD_WHITELIST,
)


# ═══════════════════════════════════════════════════
#  关键词过滤
# ═══════════════════════════════════════════════════

class TestKeywordFilter:
    def test_matching_keywords(self):
        news = [
            {"title": "央行宣布降息50基点", "content": ""},
            {"title": "今日天气晴朗", "content": ""},
            {"title": "VIX暴涨至40", "content": ""},
        ]
        filtered = _keyword_filter(news)
        assert len(filtered) == 2
        assert any("央行" in n["title"] for n in filtered)
        assert any("VIX" in n["title"] for n in filtered)

    def test_content_match(self):
        """关键词可以在 content 中匹配"""
        news = [{"title": "今日快讯", "content": "半导体板块大涨5%"}]
        assert len(_keyword_filter(news)) == 1

    def test_no_match(self):
        news = [{"title": "今天吃什么", "content": "好好学习天天向上"}]
        assert len(_keyword_filter(news)) == 0

    def test_empty_list(self):
        assert len(_keyword_filter([])) == 0

    def test_whitelist_has_minimum_coverage(self):
        """确保关键词列表覆盖宏观/市场/行业/风险四大类"""
        combined = " ".join(_KEYWORD_WHITELIST)
        assert "央行" in combined
        assert "A股" in combined
        assert "半导体" in combined
        assert "制裁" in combined


# ═══════════════════════════════════════════════════
#  事件 ID 生成
# ═══════════════════════════════════════════════════

class TestEventIdGeneration:
    def test_deterministic(self):
        id1 = _generate_event_id("央行降息", "2026-05-15")
        id2 = _generate_event_id("央行降息", "2026-05-15")
        assert id1 == id2

    def test_different_title_different_id(self):
        id1 = _generate_event_id("央行降息", "2026-05-15")
        id2 = _generate_event_id("央行加息", "2026-05-15")
        assert id1 != id2

    def test_different_date_different_id(self):
        id1 = _generate_event_id("央行降息", "2026-05-15")
        id2 = _generate_event_id("央行降息", "2026-05-16")
        assert id1 != id2

    def test_length_is_12(self):
        event_id = _generate_event_id("test", "2026-01-01")
        assert len(event_id) == 12

    def test_hex_characters(self):
        event_id = _generate_event_id("test", "2026-01-01")
        assert all(c in "0123456789abcdef" for c in event_id)


# ═══════════════════════════════════════════════════
#  情景模板映射
# ═══════════════════════════════════════════════════

class TestScenarioMapping:
    def test_known_mappings(self):
        assert _SCENARIO_MAP["vix_spike"] == "vix_spike_40"
        assert _SCENARIO_MAP["rate_cut"] == "rate_cut_50bp"
        assert _SCENARIO_MAP["liquidity_crisis"] == "liquidity_crisis"

    def test_unknown_returns_none(self):
        assert _SCENARIO_MAP.get("unknown_event") is None

    def test_all_values_are_valid_scenario_ids(self):
        """所有映射的值都应是合法的情景 ID"""
        from dashboard_modules.decision.scenarios import SCENARIOS
        for key, scenario_id in _SCENARIO_MAP.items():
            assert scenario_id in SCENARIOS, f"'{scenario_id}' from '{key}' not in SCENARIOS"


# ═══════════════════════════════════════════════════
#  Gemini JSON 解析
# ═══════════════════════════════════════════════════

class TestGeminiJsonParsing:
    @patch("engines.news_intelligence._load_ai_config")
    @patch("engines.news_intelligence.urllib.request.urlopen")
    def test_clean_json_response(self, mock_urlopen, mock_config):
        mock_config.return_value = {
            "gemini": {"api_key": "test_key_12345", "model": "gemini-2.0-flash"},
            "timeout_seconds": 10,
        }
        response_body = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [{"text": json.dumps([
                        {"title": "央行降息", "category": "macro",
                         "impact_score": 8, "summary": "50bp降息",
                         "affected_assets": [], "scenario_hint": "rate_cut"}
                    ])}]
                }
            }]
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from engines.news_intelligence import _call_gemini_json
        events = _call_gemini_json("test prompt")
        assert len(events) == 1
        assert events[0]["title"] == "央行降息"

    @patch("engines.news_intelligence._load_ai_config")
    @patch("engines.news_intelligence.urllib.request.urlopen")
    def test_markdown_wrapped_json(self, mock_urlopen, mock_config):
        """Gemini 有时用 ```json 包裹"""
        mock_config.return_value = {
            "gemini": {"api_key": "test_key_12345", "model": "gemini-2.0-flash"},
            "timeout_seconds": 10,
        }
        wrapped = '```json\n[{"title":"test","category":"macro","impact_score":5,"summary":"x","affected_assets":[],"scenario_hint":""}]\n```'
        response_body = json.dumps({
            "candidates": [{"content": {"parts": [{"text": wrapped}]}}]
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        from engines.news_intelligence import _call_gemini_json
        events = _call_gemini_json("test prompt")
        assert len(events) == 1

    @patch("engines.news_intelligence._load_ai_config")
    def test_no_api_key_returns_empty(self, mock_config):
        mock_config.return_value = {"gemini": {"api_key": "", "model": "test"}}
        from engines.news_intelligence import _call_gemini_json
        assert _call_gemini_json("test") == []


# ═══════════════════════════════════════════════════
#  scan_news 集成
# ═══════════════════════════════════════════════════

class TestScanNews:
    @patch("engines.news_intelligence._fetch_news_tushare")
    def test_no_news_returns_empty(self, mock_fetch):
        mock_fetch.return_value = []
        from engines.news_intelligence import scan_news
        result = scan_news()
        assert result["status"] == "success"
        assert result["events_count"] == 0

    @patch("engines.news_intelligence._fetch_news_tushare")
    def test_no_matching_keywords(self, mock_fetch):
        mock_fetch.return_value = [{"title": "无关新闻", "content": "今天天气不错"}]
        from engines.news_intelligence import scan_news
        result = scan_news()
        assert result["status"] == "success"
        assert result["events_count"] == 0
