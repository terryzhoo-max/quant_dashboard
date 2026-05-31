"""
AlphaCore · NLP 高可用与增量扫描集成测试 (P2-C)
==================================================
专门验证:
  1. 增量扫描去重新闻熔断 (Deduplication & Short-circuit)
  2. 多 Provider 容灾回退 (DeepSeek 402/500 -> Gemini-2.0-Flash)
  3. 规则级确定性降级保底 (Deterministic Fallback)
"""

import pytest
import json
import hashlib
from unittest.mock import patch, MagicMock

from engines.news_intelligence import (
    scan_news,
    _call_llm_json,
    _deterministic_rule_extraction,
    _generate_event_id,
)
from services.cache_service import cache_manager

# 模拟配置
_TEST_AI_CFG = {
    "provider": "deepseek",
    "timeout_seconds": 5,
    "deepseek": {"api_key": "sk-deepseek_mock_123456", "model": "deepseek-chat"},
    "gemini": {"api_key": "AIzaSyGemini_mock_123456", "model": "gemini-2.0-flash"},
}


class TestNewsHAAndIncremental:

    def setup_method(self):
        # 每次测试前清除去重缓存
        cache_manager.delete("processed_news_hashes")

    def teardown_method(self):
        cache_manager.delete("processed_news_hashes")

    # ═══════════════════════════════════════════════════
    #  1. 增量去重熔断测试
    # ═══════════════════════════════════════════════════

    @patch("engines.news_intelligence._fetch_news_tushare")
    @patch("engines.news_intelligence._call_llm_json")
    def test_incremental_deduplication_melt(self, mock_call_llm, mock_fetch):
        """测试增量扫描：已处理的新闻不重复调用大模型，触发去重熔断"""
        # Tushare 返回 2 条匹配的新闻
        news_item_1 = {"title": "央行今日降息50BP", "pub_time": "2026-05-31 09:30:00", "content": "降息释放流动性"}
        news_item_2 = {"title": "半导体板块大爆发", "pub_time": "2026-05-31 09:35:00", "content": "芯片大涨"}
        mock_fetch.return_value = [news_item_1, news_item_2]

        # 计算这两个新闻的哈希值
        h1 = hashlib.md5(f"{news_item_1['title']}:{news_item_1['pub_time']}".encode('utf-8')).hexdigest()
        h2 = hashlib.md5(f"{news_item_2['title']}:{news_item_2['pub_time']}".encode('utf-8')).hexdigest()

        # 首先，将这两个哈希注入已处理缓存，模拟之前已经扫过
        cache_manager.set_json("processed_news_hashes", [h1, h2])

        # 执行扫描
        result = scan_news()

        # 验证：应该直接触发熔断拦截，不调用大模型
        assert result["status"] == "success"
        assert result["events_count"] == 0
        assert "增量去重熔断" in result["message"]
        mock_call_llm.assert_not_called()

    # ═══════════════════════════════════════════════════
    #  2. 多路容灾 Failover 回退测试
    # ═══════════════════════════════════════════════════

    @patch("engines.news_intelligence._load_ai_config")
    @patch("engines.news_intelligence._call_deepseek_json_core")
    @patch("engines.news_intelligence._call_gemini_json_core")
    def test_failover_deepseek_to_gemini(self, mock_gemini, mock_deepseek, mock_config):
        """测试 Failover：DeepSeek 报错时，自动回退到 Gemini"""
        mock_config.return_value = _TEST_AI_CFG

        # 模拟 DeepSeek 调用失败（例如抛出 API 欠费/网络异常）
        mock_deepseek.side_effect = Exception("HTTP Error 402: Payment Required")

        # 模拟 Gemini 正常返回
        gemini_events = [
            {"title": "美联储维持利率不变", "category": "macro", "impact_score": 7.0, 
             "summary": "维持高利率", "affected_assets": [], "scenario_hint": "rate_hike"}
        ]
        mock_gemini.return_value = gemini_events

        # 调用 HA 大模型统一接口
        events = _call_llm_json("test prompt", [])

        # 验证：是否成功调用了 DeepSeek 发生异常，并优雅回退到 Gemini 获得数据
        mock_deepseek.assert_called_once()
        mock_gemini.assert_called_once()
        assert len(events) == 1
        assert events[0]["title"] == "美联储维持利率不变"

    # ═══════════════════════════════════════════════════
    #  3. 规则级兜底测试
    # ═══════════════════════════════════════════════════

    @patch("engines.news_intelligence._load_ai_config")
    @patch("engines.news_intelligence._call_deepseek_json_core")
    @patch("engines.news_intelligence._call_gemini_json_core")
    def test_deterministic_fallback_when_all_fail(self, mock_gemini, mock_deepseek, mock_config):
        """测试确定性降级保底：当所有大模型 API 均不可用时，降级为规则匹配，保障信号不断流"""
        mock_config.return_value = _TEST_AI_CFG

        # 模拟所有模型调用崩溃
        mock_deepseek.side_effect = Exception("DeepSeek Down")
        mock_gemini.side_effect = Exception("Gemini Down")

        # 输入 2 条新增新闻
        new_stories = [
            {"title": "半导体大厂追加投资", "pub_time": "2026", "content": "追加芯片项目"},
            {"title": "突发地缘贸易制裁", "pub_time": "2026", "content": "实施关税制裁"}
        ]

        # 调用统一接口，应当自动触发确定性规则降级
        events = _call_llm_json("test prompt", new_stories)

        # 验证：大模型全部调用，最后触发降级生成了 2 条规则匹配事件
        mock_deepseek.assert_called_once()
        mock_gemini.assert_called_once()
        assert len(events) == 2
        
        # 半导体匹配到 industry 分类
        assert events[0]["title"] == "半导体大厂追加投资"
        assert events[0]["category"] == "industry"
        assert events[0]["impact_score"] == 5.0
        
        # 制裁匹配到 risk 风险分类
        assert events[1]["title"] == "突发地缘贸易制裁"
        assert events[1]["category"] == "risk"
        assert events[1]["impact_score"] == 5.0
