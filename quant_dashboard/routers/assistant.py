"""
AlphaCore · AI 决策助手 API (V27.0 P2-A)
==========================================
DeepSeek 驱动的对话式决策助手。
每次对话自动注入系统实时快照 (持仓/策略/宏观) 作为 context。

端点:
  POST /api/v1/assistant/chat  — 非流式对话 (JSON)
"""

import json
import traceback
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body
from services.logger import get_logger

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])
logger = get_logger("ac.assistant")


# ── 系统角色 Prompt ──
_SYSTEM_PROMPT = """你是 AlphaCore 量化决策终端的 AI 助手。

你的职责:
1. 基于注入的【系统实时数据快照】回答用户关于投资组合、策略信号、宏观环境的问题
2. 给出专业、量化驱动、有数据支撑的分析和建议
3. 当系统数据不足以回答时，明确告知并建议检查哪些模块

规则:
- 引用具体数字 (如 "JCS=72.3, 高置信" 而非 "置信度较高")
- 用中文回答
- 回答控制在 300 字以内，简洁直接
- 区分"事实查询"(来自系统数据)和"投资建议"(带免责声明)
- 当用户问题超出系统数据范围时,可基于你的通用知识回答,但注明"非来自系统数据"

===== 系统实时数据快照 =====
{context_json}
"""


def _build_system_context() -> dict:
    """构建系统实时快照作为 AI 助手的 context"""
    context = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # ── 1. 持仓估值 ──
    try:
        from portfolio_engine import get_portfolio_engine
        engine = get_portfolio_engine()
        val = engine.get_valuation()
        context["portfolio"] = {
            "total_asset": val.get("total_asset"),
            "market_value": val.get("market_value"),
            "cash": val.get("cash"),
            "total_pnl": val.get("total_pnl"),
            "total_pnl_pct": val.get("total_pnl_pct"),
            "position_count": val.get("position_count"),
            "top_positions": [
                {"name": p["name"], "weight": p.get("weight"), "pnl_pct": p.get("pnl_pct")}
                for p in sorted(val.get("positions", []), key=lambda x: x.get("market_value", 0), reverse=True)[:5]
            ],
        }
    except Exception:
        context["portfolio"] = {"error": "无法获取持仓数据"}

    # ── 2. 今日P&L ──
    try:
        from portfolio_engine import get_portfolio_engine
        engine = get_portfolio_engine()
        pnl = engine.get_intraday_pnl()
        if pnl.get("status") == "success":
            context["today_pnl"] = {
                "total_daily_pnl": pnl["total_daily_pnl"],
                "total_daily_pnl_pct": pnl["total_daily_pnl_pct"],
                "top_gainer": pnl["positions"][-1]["name"] if pnl["positions"] else None,
                "top_loser": pnl["positions"][0]["name"] if pnl["positions"] else None,
            }
    except Exception:
        pass

    # ── 3. 策略信号 (缓存) ──
    try:
        from services.cache_service import cache_manager
        sr = cache_manager.get_json("strategy_results", {})
        strategy_summary = {}

        for key in ["mr", "div", "mom"]:
            data = sr.get(key, {})
            if isinstance(data, dict):
                ov = data.get("data", data).get("market_overview", {})
                strategy_summary[key] = {
                    "buy_count": ov.get("buy_count", ov.get("signal_count", {}).get("buy", 0)),
                    "sell_count": ov.get("sell_count", ov.get("signal_count", {}).get("sell", 0)),
                }
        context["strategies"] = strategy_summary
    except Exception:
        pass

    # ── 4. 决策中枢核心指标 (缓存) ──
    try:
        from services.cache_service import cache_manager
        hub = cache_manager.get_json("swr_decision_hub")
        if hub and isinstance(hub, dict):
            data = hub.get("data", hub)
            core = data.get("core_metrics", {})
            context["decision_hub"] = {
                "jcs_score": core.get("jcs_score"),
                "jcs_level": core.get("jcs_level"),
                "suggested_position": core.get("suggested_position"),
                "aiae_regime": core.get("aiae_regime"),
                "aiae_regime_cn": core.get("aiae_regime_cn"),
                "vix": core.get("vix"),
            }
    except Exception:
        pass

    # ── 5. 全球 AIAE 温度 (缓存) ──
    try:
        from services.cache_service import cache_manager
        global_data = cache_manager.get_json("aiae_global_report_data")
        if global_data and isinstance(global_data, dict):
            markets = global_data.get("markets", {})
            global_summary = {}
            for mkt_key, mkt_data in markets.items():
                if isinstance(mkt_data, dict):
                    global_summary[mkt_key] = {
                        "aiae": mkt_data.get("aiae_v1"),
                        "regime": mkt_data.get("regime"),
                        "signal": mkt_data.get("signal"),
                    }
            if global_summary:
                context["global_markets"] = global_summary
    except Exception:
        pass

    return context


def _call_deepseek_chat(messages: list, max_tokens: int = 800) -> Optional[str]:
    """调用 DeepSeek Chat API (带柔性指数退避重试)"""
    import urllib.request
    import time
    from config import get_ai_config

    cfg = get_ai_config()

    ds_cfg = cfg.get("deepseek", {})
    api_key = ds_cfg.get("api_key", "")
    if not api_key or len(api_key) < 10:
        return None

    model = ds_cfg.get("model", "deepseek-chat")
    base_url = ds_cfg.get("base_url", "https://api.deepseek.com")
    timeout = cfg.get("timeout_seconds", 30)

    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.6,
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
    )
    
    max_retries = 3
    retry_delay = 1.5
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            
            choices = result.get("choices", [])
            if not choices:
                return None
            
            usage = result.get("usage", {})
            logger.info("[Assistant] DeepSeek tokens: prompt=%d completion=%d",
                        usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
            
            return choices[0].get("message", {}).get("content", "")
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error("[Assistant] DeepSeek 调用最终失败: %s", e)
                raise e
            logger.warning("[Assistant] DeepSeek 调用失败: %s。将在 %.1fs 后进行重试 (%d/%d)", 
                           e, retry_delay, attempt + 1, max_retries)
            time.sleep(retry_delay)
            retry_delay *= 2.0
    return None


@router.post("/chat")
def chat(
    message: str = Body(..., embed=True),
    history: list = Body(default=[], embed=True),
):
    """
    AI 助手对话端点。

    请求 Body:
        { "message": "我的组合今天表现怎么样？", "history": [] }

    history 格式: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    """
    t0 = datetime.now()

    if not message or not message.strip():
        return {"code": 1, "message": "消息不能为空"}

    try:
        # 1. 构建系统上下文
        context = _build_system_context()
        context_json = json.dumps(context, ensure_ascii=False, indent=1)

        system_prompt = _SYSTEM_PROMPT.format(context_json=context_json)

        # 2. 构建消息链 (system + history + user)
        messages = [{"role": "system", "content": system_prompt}]

        # 保留最近 6 轮对话 (控制 token)
        if history and isinstance(history, list):
            messages.extend(history[-12:])

        messages.append({"role": "user", "content": message.strip()})

        # 3. 调用 DeepSeek
        reply = _call_deepseek_chat(messages)

        if reply:
            elapsed = (datetime.now() - t0).total_seconds()
            logger.info("[Assistant] 对话完成: %.1fs | user=%s...", elapsed, message[:30])
            return {
                "code": 0,
                "data": {
                    "reply": reply,
                    "provider": "deepseek",
                    "elapsed_ms": round(elapsed * 1000),
                    "context_keys": list(context.keys()),
                }
            }
        else:
            return {
                "code": 0,
                "data": {
                    "reply": "⚠️ AI 助手暂时不可用 (DeepSeek API Key 未配置或连接超时)。请检查 config/ai_config.json 中的 deepseek.api_key 配置。",
                    "provider": "fallback",
                }
            }

    except Exception as e:
        logger.error("[Assistant] Error: %s\n%s", e, traceback.format_exc())
        return {"code": 1, "message": f"助手错误: {str(e)}"}
