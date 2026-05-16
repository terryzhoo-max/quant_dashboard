"""
AlphaCore P4 · LLM 叙事引擎 V2.0
====================================
基于决策引擎全量快照数据，调用 LLM 生成每日市场分析报告。

特性:
  - 多 Provider 支持 (DeepSeek/Gemini/OpenAI/Claude, 按配置优先级)
  - 确定性引擎回退 (LLM 不可用时生成规则化报告)
  - SWR 缓存 (1 小时有效, 6 小时 stale)
  - 全球多市场+行业+波段守卫 上下文注入
  - 日志审计

成本控制:
  - 每日 1-2 次调用
  - 使用 flash/mini 模型
  - 输入 ~2500 tokens, 输出 ~900 tokens
  - 估算: DeepSeek ~¥0.02/次, Gemini Flash ~$0.005/次
"""

import json
import os
import urllib.request
import traceback
from datetime import datetime
from typing import Optional

from services.logger import get_logger

logger = get_logger("ac.narrative")

# ── 配置 ──
_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "ai_config.json"
)


def _load_ai_config() -> dict:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"enable_ai_narrative": False}


# ═══════════════════════════════════════════════════════
#  LLM Prompt
# ═══════════════════════════════════════════════════════

_NARRATIVE_PROMPT = """你是 AlphaCore 机构量化终端的首席策略分析师。
请基于以下系统快照数据，生成一份简洁专业的每日决策分析报告。

要求:
1. 语言: 中文
2. 结构: 5 段落，每段 2-3 句
   - 【市场温度】: 基于 AIAE Regime + 全球市场温度对比 (中/美/日/港横向分析)
   - 【行业轮动】: 基于 sector_heatmap 领涨/领跌板块，判断资金主线
   - 【策略信号】: JCS 置信度 + 仓位建议 + 4引擎方向共振/分歧分析
   - 【风险提示】: VIX恐慌/波段守卫状态/黄金国债避险信号/合规触发
   - 【操作建议】: 综合以上分析的具体行动建议 (含跨市场配置视角)
3. 风格: 专业、直接、数据驱动，避免含糊措辞
4. 引用具体数据 (如 "JCS 75.7" 而非 "较高", "美股ERP 3.2%" 而非 "偏低")
5. 不要使用 markdown 标记，直接输出纯文本
6. 总长度控制在 500 字以内

===== 系统快照 =====
{snapshot_json}
"""


# ═══════════════════════════════════════════════════════
#  多 Provider LLM 调用
# ═══════════════════════════════════════════════════════

def _call_llm(prompt: str, cfg: dict) -> Optional[str]:
    """统一 LLM 调用入口，按配置 provider 优先级尝试"""
    provider = cfg.get("provider", "gemini")
    timeout = cfg.get("timeout_seconds", 30)
    max_tokens = cfg.get("max_tokens", 1024)

    providers = [provider]
    # 回退链: 配置的 provider → gemini → deepseek
    for fallback in ["gemini", "deepseek"]:
        if fallback not in providers:
            providers.append(fallback)

    for p in providers:
        try:
            p_cfg = cfg.get(p, {})
            api_key = p_cfg.get("api_key", "")
            if not api_key or len(api_key) < 10:
                continue

            if p == "gemini":
                result = _call_gemini(prompt, p_cfg, timeout, max_tokens)
            elif p == "deepseek":
                result = _call_openai_compatible(
                    prompt, p_cfg,
                    base_url=p_cfg.get("base_url", "https://api.deepseek.com"),
                    timeout=timeout, max_tokens=max_tokens
                )
            elif p == "openai":
                result = _call_openai_compatible(
                    prompt, p_cfg,
                    base_url="https://api.openai.com",
                    timeout=timeout, max_tokens=max_tokens
                )
            elif p == "claude":
                result = _call_claude(prompt, p_cfg, timeout, max_tokens)
            else:
                continue

            if result:
                logger.info("[Narrative] LLM 调用成功 (provider=%s)", p)
                return result

        except Exception as e:
            logger.warning("[Narrative] Provider %s 失败: %s", p, e)
            continue

    logger.warning("[Narrative] 所有 LLM Provider 失败, 将使用确定性引擎")
    return None


def _call_gemini(prompt: str, cfg: dict, timeout: int, max_tokens: int) -> Optional[str]:
    """Gemini API 调用"""
    api_key = cfg["api_key"]
    model = cfg.get("model", "gemini-2.0-flash")
    url = (f"https://generativelanguage.googleapis.com/v1beta/"
           f"models/{model}:generateContent?key={api_key}")

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.5,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    candidates = result.get("candidates", [])
    if not candidates:
        return None
    return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")


def _call_openai_compatible(prompt: str, cfg: dict, base_url: str,
                             timeout: int, max_tokens: int) -> Optional[str]:
    """OpenAI 兼容 API (DeepSeek / OpenAI)"""
    api_key = cfg["api_key"]
    model = cfg.get("model", "deepseek-chat")
    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是专业的量化策略分析师"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.5,
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
        return None
    return choices[0].get("message", {}).get("content", "")


def _call_claude(prompt: str, cfg: dict, timeout: int, max_tokens: int) -> Optional[str]:
    """Anthropic Claude API"""
    api_key = cfg["api_key"]
    model = cfg.get("model", "claude-sonnet-4-20250514")
    url = "https://api.anthropic.com/v1/messages"

    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.5,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    content = result.get("content", [])
    if not content:
        return None
    return content[0].get("text", "")


# ═══════════════════════════════════════════════════════
#  V2.0: 全球上下文补充器
# ═══════════════════════════════════════════════════════

def _enrich_global_context(snapshot: dict, cache_manager) -> None:
    """
    从缓存中读取全球 ERP、行业轮动、波段守卫数据，注入到 snapshot。
    全部静默降级: 任一维度缺失不影响报告生成。
    """
    # ── 全球 ERP 矩阵 (erp-global 缓存) ──
    try:
        global_erp = cache_manager.get_json("aiae_global_report_data")
        if global_erp and isinstance(global_erp, dict):
            markets = global_erp.get("markets", {})
            summary = {}
            for mkt_key, mkt_data in markets.items():
                if isinstance(mkt_data, dict):
                    erp_val = mkt_data.get("erp_value") or mkt_data.get("erp")
                    signal = mkt_data.get("signal") or mkt_data.get("erp_signal")
                    if erp_val is not None:
                        summary[mkt_key] = {"erp": round(float(erp_val), 2), "signal": signal}
            if summary:
                snapshot["global_erp_summary"] = summary
    except Exception:
        pass

    # ── 行业热力全景图 (dashboard_data 缓存) ──
    try:
        dashboard = cache_manager.get_json("dashboard_data")
        if dashboard and isinstance(dashboard, dict):
            sectors = (dashboard.get("data", {})
                       .get("heatmap_data", {})
                       .get("sectors", []))
            if sectors and isinstance(sectors, list):
                # 按涨跌幅排序，取前 3 / 后 3
                sorted_secs = sorted(
                    [s for s in sectors if isinstance(s, dict) and s.get("pct") is not None],
                    key=lambda x: x.get("pct", 0), reverse=True
                )
                if len(sorted_secs) >= 3:
                    snapshot["sector_leaders"] = [
                        {"name": s.get("name", ""), "pct": round(s["pct"], 2)}
                        for s in sorted_secs[:3]
                    ]
                    snapshot["sector_laggards"] = [
                        {"name": s.get("name", ""), "pct": round(s["pct"], 2)}
                        for s in sorted_secs[-3:]
                    ]
    except Exception:
        pass

    # ── 波段守卫状态 (swing_guard 缓存) ──
    try:
        sg_data = cache_manager.get_json("swr_swing_guard")
        if sg_data and isinstance(sg_data, dict):
            guards = sg_data.get("guards", [])
            if guards:
                red_count = sum(1 for g in guards if g.get("signal") == "RED")
                yellow_count = sum(1 for g in guards if g.get("signal") == "YELLOW")
                snapshot["swing_guard_status"] = {
                    "total": len(guards),
                    "red": red_count,
                    "yellow": yellow_count,
                    "green": len(guards) - red_count - yellow_count,
                }
    except Exception:
        pass


# ═══════════════════════════════════════════════════════
#  确定性回退引擎
# ═══════════════════════════════════════════════════════

_REGIME_LABELS = {1: "极冷 (恐慌)", 2: "偏冷 (谨慎)", 3: "中性 (均衡)", 4: "偏热 (积极)", 5: "过热 (警戒)"}
_JCS_LABELS = {"high": "高置信", "medium": "中等置信", "low": "低置信"}
_DIRECTION_LABELS = {1: "看多", 0: "中性", -1: "看空"}


def _deterministic_report(snapshot: dict) -> str:
    """无 LLM 时的确定性报告生成器"""
    regime = snapshot.get("aiae_regime", 3)
    regime_label = _REGIME_LABELS.get(regime, f"R{regime}")
    jcs_score = snapshot.get("jcs_score", 0)
    jcs_level = _JCS_LABELS.get(snapshot.get("jcs_level", "medium"), "中等")
    vix = snapshot.get("vix_val", 0)
    position = snapshot.get("suggested_position", 50)

    report = (
        f"【市场温度】当前 AIAE Regime = R{regime} ({regime_label})。"
    )

    if vix and vix > 25:
        report += f"VIX 指数 {vix:.1f} 处于偏高水平，市场恐慌情绪升温。"
    elif vix:
        report += f"VIX 指数 {vix:.1f} 处于正常范围，情绪面稳定。"

    report += (
        f"\n\n【策略信号】JCS 联合置信度 {jcs_score:.1f} ({jcs_level})，"
        f"建议仓位 {position}%。"
    )

    directions = snapshot.get("signal_directions", {})
    if directions:
        bulls = sum(1 for v in directions.values() if v > 0)
        bears = sum(1 for v in directions.values() if v < 0)
        total = len(directions)
        report += f"引擎信号方向: {bulls}/{total} 看多, {bears}/{total} 看空。"

    report += "\n\n【风险提示】"
    risks = []
    if vix and vix > 30:
        risks.append(f"VIX {vix:.1f} 超过恐慌阈值 (>30)")
    tail_risk = snapshot.get("tail_risk_score", 0)
    if tail_risk and tail_risk >= 50:
        risks.append(f"尾部风险评分 {tail_risk:.0f} (≥50 警戒)")
    if not risks:
        risks.append("当前无重大风险触发")
    report += "；".join(risks) + "。"

    report += "\n\n【操作建议】"
    if regime >= 4 and jcs_score > 60:
        report += f"市场偏热且信号一致性较高，维持建议仓位 {position}%，注意止盈。"
    elif regime <= 2:
        report += f"市场偏冷，建议降低仓位至 {position}% 并保持观望。"
    else:
        report += f"市场中性，按建议仓位 {position}% 配置，等待方向确认后调整。"

    return report


# ═══════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════

def generate_daily_narrative(force_deterministic: bool = False) -> dict:
    """
    生成每日市场分析叙事报告。

    Args:
        force_deterministic: 强制使用确定性引擎 (不调用 LLM)

    Returns:
        {
            "status": "success",
            "report": "...",
            "provider": "deepseek" | "gemini" | "deterministic",
            "generated_at": "2026-05-15T09:00:00",
            "snapshot_date": "2026-05-15"
        }
    """
    t0 = datetime.now()
    logger.info("═══ 叙事引擎启动 ═══")

    # 1. 构建快照数据
    try:
        from dashboard_modules.decision_engine import _build_snapshot_from_cache, compute_jcs
        from dashboard_modules.decision.conflicts import _signal_direction

        snapshot = _build_snapshot_from_cache()
        if not snapshot:
            return {"status": "error", "message": "快照数据不可用"}

        jcs = compute_jcs(snapshot)
        snapshot["jcs_score"] = jcs["score"]
        snapshot["jcs_level"] = jcs["level"]
        snapshot["signal_directions"] = _signal_direction(snapshot)
    except Exception as e:
        logger.warning("[Narrative] 快照构建失败: %s", e)
        return {"status": "error", "message": f"快照构建失败: {e}"}

    # 2. 生成报告
    provider = "deterministic"
    cfg = _load_ai_config()

    # 2.1 补充全球/行业/波段上下文 (静默降级: 缺失则跳过)
    try:
        from services.cache_service import cache_manager
        _enrich_global_context(snapshot, cache_manager)
    except Exception as e:
        logger.debug("[Narrative] 全球上下文补充跳过: %s", e)

    if not force_deterministic and cfg.get("enable_ai_narrative", False):
        # 构建精简快照 JSON (控制 token, ~2500tok)
        slim_snapshot = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            # ── A 股核心 ──
            "aiae_regime": snapshot.get("aiae_regime"),
            "aiae_v1": snapshot.get("aiae_v1"),
            "jcs_score": round(jcs["score"], 1),
            "jcs_level": jcs["level"],
            "suggested_position": snapshot.get("suggested_position"),
            "vix": snapshot.get("vix_val"),
            "erp_score": snapshot.get("erp_score"),
            "signal_directions": snapshot.get("signal_directions"),
            # ── 跨资产 ──
            "gold_signal": snapshot.get("gold_signal"),
            "bond_signal": snapshot.get("bond_signal"),
            # ── V2.0 全球视野 ──
            "global_erp": snapshot.get("global_erp_summary"),
            "sector_leaders": snapshot.get("sector_leaders"),
            "sector_laggards": snapshot.get("sector_laggards"),
            "swing_guard_status": snapshot.get("swing_guard_status"),
        }
        # 清理 None 值 (节省 token)
        slim_snapshot = {k: v for k, v in slim_snapshot.items() if v is not None}

        prompt = _NARRATIVE_PROMPT.format(
            snapshot_json=json.dumps(slim_snapshot, ensure_ascii=False, indent=2)
        )
        llm_text = _call_llm(prompt, cfg)
        if llm_text:
            report = llm_text.strip()
            provider = cfg.get("provider", "deepseek")
        else:
            report = _deterministic_report(snapshot)
    else:
        report = _deterministic_report(snapshot)

    # 3. 缓存结果
    result = {
        "status": "success",
        "report": report,
        "provider": provider,
        "generated_at": datetime.now().isoformat(),
        "snapshot_date": datetime.now().strftime("%Y-%m-%d"),
    }

    try:
        from services.cache_service import cache_manager
        cache_manager.set_json("daily_narrative", result, ttl_seconds=3600)
    except Exception:
        pass

    elapsed = (datetime.now() - t0).total_seconds()
    logger.info("═══ 叙事引擎完成: provider=%s · %.1fs ═══", provider, elapsed)

    return result


def get_daily_narrative() -> dict:
    """获取今日叙事 (优先缓存, 未命中则生成)"""
    try:
        from services.cache_service import cache_manager
        cached = cache_manager.get_json("daily_narrative")
        if cached and cached.get("report"):
            # 检查是否今日的
            if cached.get("snapshot_date") == datetime.now().strftime("%Y-%m-%d"):
                return cached
    except Exception:
        pass

    return generate_daily_narrative()
