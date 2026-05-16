"""
AlphaCore · NLP 情报引擎 (P2-C · DeepSeek)
=============================================
流程:
  1. Tushare major_news() 拉取最近财经新闻 (关键词预过滤)
  2. DeepSeek-Chat 结构化提取 (OpenAI-compatible JSON mode)
  3. 事件分类 (宏观/行业/个股) + 影响评分
  4. 自动匹配决策引擎情景模板
  5. SQLite 持久化 + 缓存推送

数据成本: ~¥0.30/月 (日均 1-2 次调用, deepseek-chat)
"""

import json
import hashlib
import os
import urllib.request
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from services.logger import get_logger
from services import db as ac_db

logger = get_logger("ac.nlp")

# ── 配置 ──
_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "ai_config.json"
)

# ── 关键词白名单 (预过滤, 降低 LLM 调用量) ──
_KEYWORD_WHITELIST = [
    # 宏观
    "央行", "降息", "加息", "降准", "LPR", "MLF", "GDP", "CPI", "PPI", "PMI",
    "美联储", "Fed", "利率", "通胀", "衰退", "滞胀", "就业",
    # 市场
    "A股", "沪深", "创业板", "科创板", "北交所", "港股", "美股",
    "涨停", "跌停", "熔断", "暴跌", "暴涨", "大跌", "大涨",
    "IPO", "退市", "减持", "增持", "回购",
    # 行业
    "半导体", "芯片", "新能源", "光伏", "锂电", "储能",
    "AI", "人工智能", "大模型", "算力",
    "军工", "国防", "航天",
    "医药", "创新药", "集采",
    # 风险
    "制裁", "关税", "贸易战", "地缘", "战争", "冲突",
    "暴雷", "违约", "爆仓", "黑天鹅",
    "VIX", "恐慌",
]

# ── 情景模板映射 ──
_SCENARIO_MAP = {
    "vix_spike": "vix_spike_40",
    "rate_cut": "rate_cut_50bp",
    "rate_hike": "stagflation",
    "liquidity_crisis": "liquidity_crisis",
    "tech_rotation": "tech_rotation",
    "erp_extreme": "erp_extreme_bull",
    "golden_cross": "golden_cross",
    "overheat": "aiae_overheat_v",
}

# ── DeepSeek 结构化提取 Prompt ──
_EXTRACTION_PROMPT = """你是一位专业的量化投资分析师。请从以下财经新闻中提取关键事件。

要求:
1. 只提取对 A 股市场有实际影响的事件
2. 忽略广告、软文、无实质信息的新闻
3. 每个事件必须包含以下字段:
   - title: 事件标题 (15字以内)
   - category: 分类, 必须是以下之一: macro(宏观), industry(行业), stock(个股), risk(风险)
   - impact_score: 影响程度 1-10 (1最小, 10最大)
   - summary: 一句话摘要 (50字以内)
   - affected_assets: 受影响的资产代码列表, 如 ["510300.SH", "159915.SZ"]
   - scenario_hint: 最匹配的情景关键词, 必须是以下之一或空字符串: vix_spike, rate_cut, rate_hike, liquidity_crisis, tech_rotation, erp_extreme, golden_cross, overheat

请以 JSON 数组格式返回, 最多提取 5 个最重要的事件。
如果没有值得提取的事件, 返回空数组 []。

===== 新闻内容 =====
{news_text}
"""


def _load_ai_config() -> dict:
    """加载 AI 配置"""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"enable_ai_narrative": False}


def _call_deepseek_json(prompt: str) -> list:
    """调用 DeepSeek (OpenAI-compatible) 并解析 JSON 响应"""
    cfg = _load_ai_config()
    ds_cfg = cfg.get("deepseek", {})
    api_key = ds_cfg.get("api_key", "")
    model = ds_cfg.get("model", "deepseek-chat")
    base_url = ds_cfg.get("base_url", "https://api.deepseek.com")
    timeout = cfg.get("timeout_seconds", 30)

    if not api_key or len(api_key) < 10:
        logger.warning("[NLP] DeepSeek API key 未配置, 跳过")
        return []

    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是专业量化投资分析师。请严格以 JSON 数组格式回复。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 1024,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    choices = result.get("choices", [])
    if not choices:
        return []

    text = choices[0].get("message", {}).get("content", "")

    # 解析 JSON (兼容 markdown 代码块包裹)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]

    try:
        parsed = json.loads(text)
        # DeepSeek JSON mode 可能返回 {"events": [...]} 或直接 [...]
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "events" in parsed:
            return parsed["events"]
        return []
    except json.JSONDecodeError:
        logger.warning("[NLP] DeepSeek 返回非 JSON: %s...", text[:100])
        return []


def _keyword_filter(news_list: list) -> list:
    """关键词白名单预过滤"""
    filtered = []
    for item in news_list:
        content = item.get("title", "") + item.get("content", "")
        if any(kw in content for kw in _KEYWORD_WHITELIST):
            filtered.append(item)
    return filtered


def _fetch_news_tushare() -> list:
    """从 Tushare 获取最新财经新闻"""
    try:
        import tushare as ts
        pro = ts.pro_api()
        today = datetime.now().strftime("%Y%m%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        df = pro.major_news(
            start_date=yesterday,
            end_date=today,
            fields="title,content,pub_time,src"
        )
        if df is None or df.empty:
            logger.info("[NLP] Tushare 无新闻数据")
            return []

        news = df.head(30).to_dict("records")  # 最多 30 条
        logger.info("[NLP] Tushare 拉取 %d 条新闻", len(news))
        return news
    except Exception as e:
        logger.warning("[NLP] Tushare 新闻拉取失败: %s", e)
        return []


def _generate_event_id(title: str, date_str: str) -> str:
    """基于标题+日期生成唯一 ID"""
    raw = f"{title}:{date_str}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def scan_news() -> dict:
    """
    主入口: 扫描新闻 → 预过滤 → DeepSeek 提取 → 持久化

    Returns:
        {"status": "success", "events_count": N, "events": [...]}
    """
    logger.info("═══ NLP 情报扫描启动 (DeepSeek) ═══")
    t0 = datetime.now()

    # 1. 拉取新闻
    raw_news = _fetch_news_tushare()
    if not raw_news:
        return {"status": "success", "events_count": 0, "events": [], "message": "无新闻数据"}

    # 2. 关键词预过滤
    filtered = _keyword_filter(raw_news)
    logger.info("[NLP] 关键词过滤: %d/%d 通过", len(filtered), len(raw_news))

    if not filtered:
        return {"status": "success", "events_count": 0, "events": [], "message": "无匹配关键词"}

    # 3. 拼接新闻文本 (截断到 3000 字, 控制 token)
    news_text = "\n\n".join([
        f"[{item.get('pub_time', '')}] {item.get('title', '')}\n{item.get('content', '')[:200]}"
        for item in filtered[:15]
    ])
    if len(news_text) > 3000:
        news_text = news_text[:3000] + "\n...(截断)"

    # 4. DeepSeek 提取
    try:
        prompt = _EXTRACTION_PROMPT.format(news_text=news_text)
        raw_events = _call_deepseek_json(prompt)
    except Exception as e:
        logger.error("[NLP] DeepSeek 调用失败: %s\n%s", e, traceback.format_exc())
        return {"status": "error", "message": f"DeepSeek 调用失败: {e}"}

    # 5. 结构化 + 持久化
    today_str = datetime.now().strftime("%Y-%m-%d")
    saved_events = []

    for ev in raw_events:
        if not isinstance(ev, dict) or not ev.get("title"):
            continue

        event_id = _generate_event_id(ev["title"], today_str)
        scenario_hint = ev.get("scenario_hint", "")
        scenario_id = _SCENARIO_MAP.get(scenario_hint)

        structured = {
            "event_id": event_id,
            "title": ev.get("title", "")[:100],
            "category": ev.get("category", "macro"),
            "impact_score": min(max(float(ev.get("impact_score", 5)), 1), 10),
            "summary": ev.get("summary", "")[:200],
            "affected_assets": ev.get("affected_assets", []),
            "scenario_id": scenario_id,
            "source": "tushare+deepseek",
            "raw_text": "",
        }

        try:
            ac_db.save_news_event(structured)
            saved_events.append(structured)
        except Exception as e:
            logger.warning("[NLP] 事件保存失败: %s - %s", event_id, e)

    elapsed = (datetime.now() - t0).total_seconds()
    logger.info("═══ NLP 情报扫描完成: %d 事件 · %.1fs ═══", len(saved_events), elapsed)

    # 6. 写入缓存 (供 Decision Hub 读取)
    #    保护策略: 0 事件时保留旧缓存, 避免空扫描清除有效情报
    if saved_events:
        try:
            from services.cache_service import cache_manager
            cache_manager.set_json("news_intelligence", {
                "status": "success",
                "scan_time": datetime.now().isoformat(),
                "events": saved_events,
            }, ttl_seconds=3600)
        except Exception:
            pass
    else:
        logger.info("[NLP] 0 事件, 保留旧缓存")

    return {
        "status": "success",
        "events_count": len(saved_events),
        "events": saved_events,
        "elapsed": round(elapsed, 1),
    }


def get_latest_intelligence(limit: int = 10) -> dict:
    """获取最新情报 (优先从缓存, 回退 DB)"""
    from services.cache_service import cache_manager

    cached = cache_manager.get_json("news_intelligence")
    if cached and cached.get("events"):
        return cached

    # 回退到 DB
    events = ac_db.get_news_events(limit=limit)
    return {
        "status": "success",
        "scan_time": None,
        "events": events,
    }
