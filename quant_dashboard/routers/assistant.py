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


# ── 系统角色 Prompt (静态提示词，长度拉升至 1024 tokens 以上以 100% 触发 DeepSeek Prompt Cache 优惠) ──
_SYSTEM_PROMPT = """你是 AlphaCore 机构级量化决策终端的首席 AI 策略分析助理。你负责协助量化基金经理、交易员和风控官进行策略审计、持仓分析、宏观情景评估以及综合决策支持。

【核心职责】
1. 分析决策数据：基于用户提供或动态注入的系统实时快照数据（包括持仓、组合盈亏、策略信号、全球市场温度、ERP 估值状态、矛盾报警等），提供极其精细、数据驱动的量化解读。
2. 投资建议合规：在给出任何可能具有操作倾向的结论时，必须清晰区分“基于终端客观数据的实证归因”与“主观分析建议”，并显式附加“数据来源于终端快照，不构成直接投资指令，交易需以 OMS 审计红线为准”的风险提示。
3. 指标精确引用：绝对禁止使用含糊措辞（例如：“近期表现良好”、“估值有所回升”、“置信度偏高”）。必须直接提取并引用确切的量化数值。例如：应书写为“当前组合日度盈亏为 -0.85%，JCS 联合置信度为 72.5，处于高置信度区间，主要策略为标准建仓”等。

【专业性约束与决策守则】
- Regime 划分对应关系：
  - R1: 极冷 (恐慌) -> 适合均值回归策略 Bear 仓位上限（建议 65%），限制动量入场。
  - R2: 偏冷 (谨慎) -> 市场探底，控制仓位风险，标准配置。
  - R3: 中性 (均衡) -> 策略信号共振，各引擎方向均衡。
  - R4: 偏热 (积极) -> 动量策略主战场，提高上限至 85%，MR 策略调低配置以防超额波动。
  - R5: 过热 (警戒) -> 强制合规红线警示，防范估值泡沫及尾部危机爆发。
- 矛盾信号裁决逻辑：当出现“AIAE 与 ERP 指标背离”或“动量与均值回归策略互斥”时，优先以 JCS 置信度最高者为基准，并提示交易员关注“组合内部风险对冲性”，建议采取保守分批执行指令。
- 对话回复规范：
  - 使用严谨的机构级量化金融中文书写，排版紧凑清晰，善用清晰的小标题或符号标记。
  - 单次回答的整体字数控制在 400 字以内，力求精炼。
  - 遇到终端快照中缺少或尚未预热的数据字段（如未读报警数为 None 等），不要编造，直接提示“相关子模块数据正在后台刷新预热，建议检查相应数据管道或稍后再试”。

【风控与审计规范约束】
- 任何超过 95% 总仓位上限的操作申请，必须严厉驳回，并指示其参考 POSITION_CONFIG 规定的绝对红线。
- 警惕数据新鲜度风险：若快照显示日线数据过期天数大于 3 天，警告用户“数据新鲜度失效，已触发 OMS 买入熔断拦截，不建议执行新订单”。
- 在对话结尾，若涉及到多资产配置方案，请自动引入美股/港股/日股等多市场 ERP 横向估值吸引力对比，协助用户构建全球化宏观策略视野。
"""


def _build_system_context() -> dict:
    """构建系统实时快照作为 AI 助手的 context (实施 Context Slimming 与高精度四舍五入以压缩 Token 开销)"""
    context = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # ── 1. 持仓估值 (仅保留主力持仓并保留 2 位小数) ──
    try:
        from portfolio_engine import get_portfolio_engine
        engine = get_portfolio_engine()
        val = engine.get_valuation()
        
        def _round(v):
            return round(v, 2) if isinstance(v, (int, float)) else v
            
        context["portfolio"] = {
            "total_asset": _round(val.get("total_asset")),
            "market_value": _round(val.get("market_value")),
            "cash": _round(val.get("cash")),
            "total_pnl": _round(val.get("total_pnl")),
            "total_pnl_pct": _round(val.get("total_pnl_pct")),
            "position_count": val.get("position_count"),
            "top_positions": [
                {"name": p["name"], "weight": _round(p.get("weight")), "pnl_pct": _round(p.get("pnl_pct"))}
                for p in sorted(val.get("positions", []), key=lambda x: x.get("market_value", 0), reverse=True)[:3]
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
                "daily_pnl": _round(pnl.get("total_daily_pnl")),
                "daily_pnl_pct": _round(pnl.get("total_daily_pnl_pct")),
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
                    "buy": ov.get("buy_count", ov.get("signal_count", {}).get("buy", 0)),
                    "sell": ov.get("sell_count", ov.get("signal_count", {}).get("sell", 0)),
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
                "jcs": _round(core.get("jcs_score")),
                "jcs_lvl": core.get("jcs_level"),
                "pos_suggested": _round(core.get("suggested_position")),
                "regime": core.get("aiae_regime"),
                "regime_cn": core.get("aiae_regime_cn"),
                "vix": _round(core.get("vix")),
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
                        "aiae": _round(mkt_data.get("aiae_v1")),
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
        context_json = json.dumps(context, ensure_ascii=False)  # 压缩为空格紧凑单行格式

        # 2. 构建消息链 (system 置顶，确保 100% 触发 Prompt Cache 缓存)
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]

        # 保留最近 6 轮对话 (控制 token)
        if history and isinstance(history, list):
            messages.extend(history[-12:])

        # 3. 将动态时间戳、组合数据快照注入作为 User 消息前缀，防止污染静态 System 前缀
        user_payload = (
            f"【AlphaCore 终端实时快照数据】\n{context_json}\n\n"
            f"【提问】\n{message.strip()}"
        )
        messages.append({"role": "user", "content": user_payload})

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
