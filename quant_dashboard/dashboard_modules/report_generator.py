"""
AlphaCore V21.0 · 投委会日报生成器
====================================
聚合 JCS + AIAE + 矛盾检测 + 全球温度 + 尾部风险,
生成结构化 Markdown 投委会决策简报。

数据源:
  - get_hub_data()        → JCS / 矛盾 / AIAE / 执行建议 / 全球温度
  - compute_risk_matrix() → 尾部风险
  - db.get_decision_history(2) → 昨日快照 (计算 delta)

输出: 标准 Markdown 文本, 可直接粘贴企业微信/邮件
"""

from datetime import datetime
from typing import Optional
from services.logger import get_logger

logger = get_logger("ac.report")

# 星期中文映射
_WEEKDAY_CN = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"}

# AIAE Regime 中文
_REGIME_CN = {1: "I级·极度恐慌", 2: "II级·低配置区", 3: "III级·中性均衡", 4: "IV级·偏热区域", 5: "V级·极度过热"}
_REGIME_EMOJI = {1: "🟢", 2: "🔵", 3: "🟡", 4: "🟠", 5: "🔴"}

# JCS 级别中文
_JCS_LEVEL_CN = {"high": "🟢高", "medium": "🟡中", "low": "🔴低"}

# 引擎方向中文
_DIR_CN = {1: "⬆️ 看多", 0: "➡️ 中性", -1: "⬇️ 看空"}


def _safe(val, fmt="{:.1f}", fallback="--"):
    """安全格式化数值"""
    if val is None:
        return fallback
    try:
        return fmt.format(float(val))
    except (ValueError, TypeError):
        return fallback


def _delta_str(now, prev, fmt="{:.1f}", suffix=""):
    """计算并格式化 delta (▲/▼)"""
    if now is None or prev is None:
        return ""
    try:
        d = float(now) - float(prev)
        arrow = "▲" if d > 0 else "▼" if d < 0 else "→"
        return f"{arrow}{abs(d):.1f}{suffix}"
    except (ValueError, TypeError):
        return ""


def _regime_delta(now, prev):
    """Regime 级别变化文案"""
    if now is None or prev is None:
        return ""
    try:
        d = int(prev) - int(now)  # regime 越低越好
        if d > 0:
            return "▲改善"
        elif d < 0:
            return "▼恶化"
        return "→持平"
    except (ValueError, TypeError):
        return ""


def generate_daily_report(date_str: Optional[str] = None) -> dict:
    """
    生成投委会日报

    Args:
        date_str: 指定日期 (YYYY-MM-DD), None 表示今日

    Returns:
        {
            "status": "success",
            "date": "2026-05-03",
            "weekday": "周六",
            "markdown": "完整 Markdown 文本",
            "summary": { 简要数据字典 },
        }
    """
    from dashboard_modules.decision_engine import (
        get_hub_data, compute_risk_matrix
    )
    from services import db as ac_db

    now = datetime.now()
    report_date = date_str or now.strftime("%Y-%m-%d")
    weekday = _WEEKDAY_CN.get(now.weekday(), "")

    # ── 判断: 实时生成 还是 从历史回看 ──
    is_historical = (date_str is not None and date_str != now.strftime("%Y-%m-%d"))

    if is_historical:
        return _generate_historical_report(date_str)

    # ── 实时生成: 从当前缓存组装 ──
    try:
        hub = get_hub_data()
    except Exception as e:
        logger.error("日报生成失败: Hub 数据不可用 — %s", e)
        return {"status": "error", "error": f"Hub 数据不可用: {e}"}

    snapshot = hub.get("snapshot", {})
    jcs = hub.get("jcs", {})
    conflicts = hub.get("conflicts", {})
    action_plan = hub.get("action_plan", {})
    alerts = hub.get("alerts", [])
    global_temp = hub.get("global_temperature", {})

    # 尾部风险
    try:
        risk_matrix = compute_risk_matrix()
        tail_risk = risk_matrix.get("tail_risk", {})
    except Exception:
        tail_risk = {"score": 0, "level": "unknown", "label": "数据不可用"}

    # 昨日快照 (delta 计算)
    history = ac_db.get_decision_history(7)
    prev = None
    if len(history) >= 2:
        prev = history[-2]  # 倒数第二条 = 昨日
    elif len(history) == 1:
        prev = history[-1]

    # ── 拼接 Markdown ──
    md = _build_markdown(
        report_date, weekday, snapshot, jcs, conflicts,
        action_plan, alerts, global_temp, tail_risk, prev
    )

    # 简要摘要 (供前端卡片使用)
    summary = {
        "jcs_score": jcs.get("score"),
        "jcs_level": jcs.get("level"),
        "aiae_regime": snapshot.get("aiae_regime"),
        "suggested_position": snapshot.get("suggested_position"),
        "conflict_count": conflicts.get("conflict_count", 0),
        "tail_risk_score": tail_risk.get("score"),
        "tail_risk_level": tail_risk.get("level"),
        "alert_count": len(alerts),
    }

    # 缓存报告到 DB
    _save_report(report_date, md, summary)

    return {
        "status": "success",
        "date": report_date,
        "weekday": weekday,
        "markdown": md,
        "summary": summary,
    }


def _generate_historical_report(date_str: str) -> dict:
    """从 daily_reports 表回看历史日报"""
    from services import db as ac_db

    cached = ac_db.get_daily_report(date_str)
    if cached:
        return {
            "status": "success",
            "date": date_str,
            "weekday": "",
            "markdown": cached["markdown"],
            "summary": {},
            "source": "cached",
        }

    # 从 decision_log 回溯生成 (有限信息)
    history = ac_db.get_decision_history(365)
    target = None
    prev = None
    for i, row in enumerate(history):
        if row.get("date") == date_str:
            target = row
            if i > 0:
                prev = history[i - 1]
            break

    if not target:
        return {"status": "error", "error": f"未找到 {date_str} 的历史决策记录"}

    md = _build_historical_markdown(date_str, target, prev)
    return {
        "status": "success",
        "date": date_str,
        "weekday": "",
        "markdown": md,
        "summary": {},
        "source": "reconstructed",
    }


def _build_markdown(date, weekday, snapshot, jcs, conflicts,
                     action_plan, alerts, global_temp, tail_risk, prev) -> str:
    """拼接完整投委会日报 Markdown"""

    jcs_score = jcs.get("score", 0)
    jcs_level = jcs.get("level", "medium")
    regime = snapshot.get("aiae_regime", 3)
    position = snapshot.get("suggested_position", 55)
    conflict_count = conflicts.get("conflict_count", 0)
    tail_score = tail_risk.get("score", 0)
    tail_level = tail_risk.get("level", "low")

    # Delta 计算
    prev_jcs = prev.get("jcs_score") if prev else None
    prev_pos = prev.get("suggested_position") if prev else None
    prev_regime = prev.get("aiae_regime") if prev else None
    prev_conflict = prev.get("conflict_count") if prev else None

    # 尾部风险文案
    tail_label_map = {"low": "✅安全", "medium": "🟡关注", "high": "🔴危险"}
    tail_text = tail_label_map.get(tail_level, tail_level)

    # 决策总结文案
    direction = action_plan.get("direction", "neutral")
    dir_text_map = {
        "bullish": "🟢 多引擎看多，可适度进攻",
        "bearish": "🔴 多引擎看空，建议防御",
        "neutral": "🟡 中等置信度，维持均衡持有",
        "conflicted": "⚠️ 引擎矛盾，建议观望",
    }
    decision_text = dir_text_map.get(direction, "🟡 维持均衡持有")

    lines = []
    lines.append(f"# 📊 AlphaCore 每日决策简报")
    lines.append(f"> {date} ({weekday}) · 收盘后自动生成 · V22.0")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 执行摘要 ──
    lines.append("## 🎯 执行摘要")
    lines.append("")
    lines.append("| 指标 | 今日 | 昨日 | Δ |")
    lines.append("|------|------|------|---|")
    lines.append(f"| **JCS 置信度** | {_safe(jcs_score)} {_JCS_LEVEL_CN.get(jcs_level, '')} | {_safe(prev_jcs)} | {_delta_str(jcs_score, prev_jcs)} |")
    lines.append(f"| **建议仓位** | {_safe(position, '{:.0f}')}% | {_safe(prev_pos, '{:.0f}')}% | {_delta_str(position, prev_pos, suffix='%')} |")
    lines.append(f"| **AIAE Regime** | {_REGIME_EMOJI.get(regime, '')} {_REGIME_CN.get(regime, '')} | {_REGIME_CN.get(prev_regime, '--') if prev_regime else '--'} | {_regime_delta(regime, prev_regime)} |")
    lines.append(f"| **尾部风险** | {_safe(tail_score)} {tail_text} | -- | -- |")
    lines.append(f"| **矛盾信号** | {conflict_count} 个 {'✅' if conflict_count == 0 else '⚠️'} | {prev_conflict if prev_conflict is not None else '--'} 个 | {_delta_str(conflict_count, prev_conflict, '{:.0f}')} |")
    lines.append("")
    lines.append(f"**今日决策**: {decision_text}")
    lines.append("")

    # V22.2: AI 叙事分析 (LLM 增强 + 确定性保底)
    narrative_result = _build_narrative(snapshot, jcs, conflicts, tail_risk, prev, global_temp)
    source_label = narrative_result.get("source", "规则引擎")
    lines.append(f"### 🧠 市场叙事 `{source_label}`")
    lines.append("")
    for para in narrative_result.get("paragraphs", []):
        lines.append(para)
        lines.append("")
    lines.append("")

    # ── 执行建议 ──
    actions = action_plan.get("actions", [])
    if actions:
        lines.append("**执行建议**:")
        for act in actions[:5]:
            lines.append(f"- {act}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── 四引擎信号面板 ──
    lines.append("## 📡 四引擎信号面板")
    lines.append("")
    lines.append("| 引擎 | 方向 | 权重 | 关键读数 |")
    lines.append("|------|------|------|----------|")

    directions = jcs.get("directions", {})
    aiae_v1 = snapshot.get("aiae_v1", 0)
    cap = snapshot.get("suggested_position", 55)
    erp_val = snapshot.get("erp_val", 4.5)
    erp_score = snapshot.get("erp_score", 50)
    vix_val = snapshot.get("vix_val", 20)
    mr_regime = snapshot.get("mr_regime", "RANGE")
    mr_cn = {"BULL": "上行趋势", "BEAR": "下行趋势", "CRASH": "崩盘", "RANGE": "区间震荡"}.get(mr_regime, mr_regime)

    lines.append(f"| AIAE | {_DIR_CN.get(directions.get('aiae', 0), '➡️')} | 35% | V1={_safe(aiae_v1)}%, Regime {_REGIME_CN.get(regime, '')}, Cap {_safe(cap, '{:.0f}')}% |")
    lines.append(f"| ERP | {_DIR_CN.get(directions.get('erp', 0), '➡️')} | 25% | ERP={_safe(erp_val)}%, Score {_safe(erp_score, '{:.0f}')} |")
    lines.append(f"| VIX | {_DIR_CN.get(directions.get('vix', 0), '➡️')} | 20% | VIX={_safe(vix_val)} (16-25 中性区) |")
    lines.append(f"| MR | {_DIR_CN.get(directions.get('mr', 0), '➡️')} | 20% | {mr_regime} {mr_cn} |")
    lines.append("")

    # ── 矛盾信号 ──
    conflict_list = conflicts.get("conflicts", [])
    if conflict_list:
        lines.append("### ⚠️ 引擎矛盾")
        lines.append("")
        for c in conflict_list:
            sev_icon = "🔴" if c.get("severity") == "high" else "🟡"
            lines.append(f"- {sev_icon} **{c.get('desc', '')}** — {c.get('action', '')}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── 风险警告 ──
    lines.append("## ⚠️ 风险与警报")
    lines.append("")
    if not alerts and conflict_count == 0:
        lines.append("- ✅ 零矛盾信号，各引擎间无方向冲突")
        lines.append(f"- ✅ 尾部风险 {_safe(tail_score)} ({tail_text})")
    else:
        for alert in alerts:
            lines.append(f"- {alert.get('icon', '⚠️')} **{alert.get('title', '')}**: {alert.get('detail', '')}")
            lines.append(f"  - {alert.get('rule', '')}")
        if conflict_count == 0:
            lines.append(f"- ✅ 尾部风险 {_safe(tail_score)} ({tail_text})")

    # 融资热度 + 斜率
    margin_heat = snapshot.get("margin_heat")
    slope = snapshot.get("aiae_slope")
    if margin_heat is not None and float(margin_heat) >= 3.5:
        lines.append(f"- 🔥 融资热度 {_safe(margin_heat)}% (警戒 >3.5%)")
    if slope is not None and abs(float(slope)) >= 1.5:
        lines.append(f"- 📐 月环比斜率 {_safe(slope, '{:+.2f}')} (警戒 |±1.5|)")
    lines.append("")

    lines.append("---")
    lines.append("")

    # ── 全球温度 (附录) ──
    markets = global_temp.get("markets", [])
    if markets:
        lines.append("## 🌍 全球市场温度 (参考附录)")
        lines.append("")
        lines.append("| 市场 | AIAE | Regime | 建议仓位 | 操作 |")
        lines.append("|------|------|--------|----------|------|")
        for m in markets:
            if m.get("status") != "ready" and m.get("status") != "fallback":
                lines.append(f"| {m.get('flag', '')} {m.get('name', '')} | 加载中 | -- | -- | -- |")
                continue
            lines.append(
                f"| {m.get('flag', '')} {m.get('name', '')} "
                f"| {_safe(m.get('aiae_v1'))}% "
                f"| {m.get('emoji', '')} {m.get('regime_cn', '')} "
                f"| {m.get('pos', '--')} "
                f"| {m.get('action', '--')} |"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── 合规声明 ──
    data_quality = snapshot.get("_data_quality", {})
    real_sources = data_quality.get("real_sources", 4)
    total_expected = data_quality.get("total_expected", 4)
    report_id = f"RPT-{date.replace('-', '')}-001"

    lines.append("## 📋 合规声明")
    lines.append("")
    lines.append("本报告由 AlphaCore V22.0 自动生成，含市场叙事分析。基于 AIAE/ERP/VIX/MR 四引擎联合分析。")
    lines.append("所有数据为收盘后快照，不构成投资建议。决策时请结合实际市场情况。")
    lines.append(f"数据质量: {real_sources}/{total_expected} 引擎正常 · 报告 ID: {report_id}")
    lines.append("")

    return "\n".join(lines)


def _build_historical_markdown(date, row, prev) -> str:
    """从 decision_log 行数据回溯生成精简报告"""
    regime = row.get("aiae_regime", 3)
    jcs_score = row.get("jcs_score")
    jcs_level = row.get("jcs_level", "medium")
    position = row.get("suggested_position")
    conflict_count = row.get("conflict_count", 0)

    prev_jcs = prev.get("jcs_score") if prev else None
    prev_pos = prev.get("suggested_position") if prev else None
    prev_regime = prev.get("aiae_regime") if prev else None

    lines = []
    lines.append(f"# 📊 AlphaCore 决策简报 (历史回看)")
    lines.append(f"> {date} · 从决策日志回溯生成")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🎯 执行摘要")
    lines.append("")
    lines.append("| 指标 | 当日 | 前日 | Δ |")
    lines.append("|------|------|------|---|")
    lines.append(f"| **JCS 置信度** | {_safe(jcs_score)} {_JCS_LEVEL_CN.get(jcs_level, '')} | {_safe(prev_jcs)} | {_delta_str(jcs_score, prev_jcs)} |")
    lines.append(f"| **建议仓位** | {_safe(position, '{:.0f}')}% | {_safe(prev_pos, '{:.0f}')}% | {_delta_str(position, prev_pos, suffix='%')} |")
    lines.append(f"| **AIAE Regime** | {_REGIME_EMOJI.get(regime, '')} {_REGIME_CN.get(regime, '')} | {_REGIME_CN.get(prev_regime, '--') if prev_regime else '--'} | {_regime_delta(regime, prev_regime)} |")
    lines.append(f"| **矛盾信号** | {conflict_count} 个 | -- | -- |")
    lines.append("")

    # 原始读数
    lines.append("## 📡 原始读数")
    lines.append("")
    lines.append(f"- ERP Score: {_safe(row.get('erp_score'), '{:.0f}')}")
    lines.append(f"- ERP Value: {_safe(row.get('erp_val'))}%")
    lines.append(f"- VIX: {_safe(row.get('vix_val'))}")
    lines.append(f"- MR Regime: {row.get('mr_regime', '--')}")
    lines.append(f"- Hub Composite: {_safe(row.get('hub_composite'))}")
    lines.append("")

    # 准确率回填
    ret_5d = row.get("market_return_5d")
    correct = row.get("signal_correct")
    if ret_5d is not None:
        result_icon = "✅" if correct == 1 else ("❌" if correct == 0 else "➖")
        lines.append(f"**T+5 验证**: 市场 5 日收益率 {_safe(ret_5d, '{:+.2%}')} → 信号 {result_icon}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*本报告从历史决策日志回溯生成，仅含核心指标，无全球温度和尾部风险数据。*")
    lines.append("")

    return "\n".join(lines)


def _save_report(date_str: str, markdown: str, summary: dict):
    """将日报缓存到 SQLite"""
    try:
        from services import db as ac_db
        ac_db.save_daily_report(date_str, markdown, summary)
        logger.info("日报已缓存: %s (%d 字符)", date_str, len(markdown))
    except Exception as e:
        logger.warning("日报缓存失败 (非致命): %s", e)


def auto_generate_report():
    """
    定时自动生成日报 (由 warmup_pipeline 在交易日 16:35 调用)
    仅在交易日执行，周末跳过。
    """
    now = datetime.now()
    if now.weekday() >= 5:  # 周六/周日
        logger.info("非交易日, 跳过日报自动生成")
        return

    try:
        result = generate_daily_report()
        if result.get("status") == "success":
            logger.info("📄 日报自动生成成功: %s (%d 字符)",
                         result["date"], len(result.get("markdown", "")))
        else:
            logger.warning("日报自动生成返回非成功状态: %s", result)
    except Exception as e:
        logger.error("日报自动生成异常: %s", e)


# ═══════════════════════════════════════════════════════════
#  V22.2: 混合叙事引擎 (LLM 增强 + 确定性保底)
#  优先尝试 LLM 生成专业叙事, 失败/禁用时回退确定性模板。
# ═══════════════════════════════════════════════════════════

def _build_narrative(snapshot: dict, jcs: dict, conflicts: dict,
                     tail_risk: dict, prev: dict,
                     global_temp: dict = None) -> dict:
    """
    混合叙事入口。返回 {"source": "AI增强"|"规则引擎", "paragraphs": [str]}
    """
    # 1. 尝试 LLM 增强
    if _is_ai_enabled():
        try:
            ai_paras = _generate_ai_narrative(
                snapshot, jcs, conflicts, tail_risk, prev, global_temp
            )
            if ai_paras and len(ai_paras) >= 2:
                return {"source": "AI 增强", "paragraphs": ai_paras}
        except Exception as e:
            logger.warning("AI 叙事失败, 回退确定性模板: %s", e)

    # 2. 确定性保底
    paras = _build_deterministic_narrative(
        snapshot, jcs, conflicts, tail_risk, prev
    )
    return {"source": "规则引擎", "paragraphs": paras}


def _build_deterministic_narrative(snapshot: dict, jcs: dict, conflicts: dict,
                                    tail_risk: dict, prev: dict) -> list:
    """
    V22.0 确定性叙事引擎 (原 _build_narrative)。
    基于 if/else 模板, 零外部依赖, 作为 LLM 失败时的保底。
    """
    paragraphs = []

    jcs_score = jcs.get("score", 50)
    jcs_level = jcs.get("level", "medium")
    directions = jcs.get("directions", {})
    regime = snapshot.get("aiae_regime", 3)
    aiae_v1 = snapshot.get("aiae_v1", 22)
    erp_val = snapshot.get("erp_val", 4.5)
    erp_score = snapshot.get("erp_score", 50)
    vix_val = snapshot.get("vix_val", 20)
    mr_regime = snapshot.get("mr_regime", "RANGE")
    position = snapshot.get("suggested_position", 55)
    conflict_count = conflicts.get("conflict_count", 0)
    tail_score = tail_risk.get("score", 0)

    # 计算方向一致性
    bull_count = sum(1 for d in directions.values() if d == 1)
    bear_count = sum(1 for d in directions.values() if d == -1)
    neutral_count = sum(1 for d in directions.values() if d == 0)
    majority = "bull" if bull_count > bear_count else ("bear" if bear_count > bull_count else "neutral")

    # ── 段落 1: 宏观环境 + 仓位锚 ──
    regime_desc = {
        1: ("极度恐慌", "VIX 高企而配置热度冰点。这是历史级别的左侧建仓窗口，但需承受短期波动。"),
        2: ("低配置区", "配置热度偏低，市场情绪谨慎。适合分批建仓，逐步提升仓位至建议水平。"),
        3: ("中性均衡", "配置热度处于中性区间，市场既无恐慌也无亢奋。维持均衡配置，等待方向性信号。"),
        4: ("偏热区域", "配置热度偏高，市场情绪趋向乐观。应系统性减仓，锁定已实现利润。"),
        5: ("极度过热", "配置热度达到极端，历史上此区间后 6 个月回撤概率最高。建议大幅降仓至防御水平。"),
    }
    rd = regime_desc.get(regime, regime_desc[3])

    p1 = (
        f"当前市场处于 **{rd[0]}** 状态，AIAE 配置热度 {aiae_v1:.1f}%，"
        f"对应建议仓位 {position:.0f}%。{rd[1]}"
    )

    # 添加 VIX 状态
    if vix_val > 30:
        p1 += f" VIX 恐慌指数 {vix_val:.1f}，处于极端恐慌区间，市场波动率显著高于正常水平，应严格控制仓位。"
    elif vix_val > 25:
        p1 += f" VIX {vix_val:.1f} 偏高，市场存在一定焦虑情绪，建议预留现金缓冲。"
    elif vix_val < 16:
        p1 += f" VIX {vix_val:.1f} 处于低波动区间，市场情绪稳定，适合执行常规配置计划。"
    else:
        p1 += f" VIX {vix_val:.1f} 处于正常区间，市场情绪平稳。"
    paragraphs.append(p1)

    # ── 段落 2: 信号方向 + 矛盾分析 ──
    if conflict_count == 0 and bull_count >= 3:
        p2 = (
            f"四引擎信号高度一致：**{bull_count}/4 引擎看多**，JCS 联合置信度 {jcs_score:.0f} 分（{jcs_level}）。"
            f"ERP 估值 {erp_val:.2f}%（得分 {erp_score:.0f}），"
            + ("处于低估区间，提供较高安全边际。" if erp_score > 55 else
               ("处于高估区间，需警惕估值回归风险。" if erp_score < 35 else "估值中性。"))
        )
    elif conflict_count == 0 and bear_count >= 3:
        p2 = (
            f"四引擎信号高度一致：**{bear_count}/4 引擎看空**，JCS 联合置信度 {jcs_score:.0f} 分（{jcs_level}）。"
            f"MR 技术面处于 **{mr_regime}** 状态，"
            + ("价格结构显示下行趋势，不宜逆势加仓。" if mr_regime in ("BEAR", "CRASH")
               else "技术面信号偏空，需确认是否为短期调整。")
        )
    elif conflict_count > 0:
        severe = conflicts.get("has_severe", False)
        conflict_desc = conflicts.get("conflicts", [])
        first_conflict = conflict_desc[0].get("desc", "") if conflict_desc else ""
        p2 = (
            f"检测到 **{conflict_count} 个引擎矛盾**{'（含严重矛盾）' if severe else ''}，JCS 降至 {jcs_score:.0f} 分。"
            f"主要矛盾：{first_conflict}。"
            f"在矛盾信号消解前，建议保持观望，不执行大幅调仓操作。"
        )
    else:
        p2 = (
            f"引擎信号方向分散（{bull_count} 看多 / {bear_count} 看空 / {neutral_count} 中性），"
            f"JCS 联合置信度 {jcs_score:.0f} 分（{jcs_level}）。"
            f"市场缺乏明确的单边方向，适合维持现有仓位，等待更强信号出现。"
        )
    paragraphs.append(p2)

    # ── 段落 3: 尾部风险 + 操作提示 ──
    if tail_score >= 60:
        p3 = (
            f"⚠️ **尾部风险偏高**（{tail_score:.0f} 分）。综合集中度、VIX、AIAE 和矛盾信号，"
            f"当前市场环境下行风险显著。建议：① 将仓位降至建议水平的 70%；② 严格单票止损；③ 增加现金或防御类资产配置。"
        )
    elif tail_score >= 30:
        p3 = (
            f"尾部风险 **中等**（{tail_score:.0f} 分），处于可控区间。"
            f"建议：① 单票仓位不超过 20%；② 关注板块集中度；③ 设置移动止盈保护已实现利润。"
        )
    else:
        p3 = (
            f"尾部风险 **较低**（{tail_score:.0f} 分），"
            f"组合风险暴露处于安全区间。可按照标准 SOP 执行常规仓位管理。"
        )

    # Delta 提示 (与前一日对比)
    if prev:
        prev_jcs = prev.get("jcs_score")
        prev_pos = prev.get("suggested_position")
        if prev_jcs is not None and abs(jcs_score - prev_jcs) > 5:
            direction = "上升" if jcs_score > prev_jcs else "下降"
            p3 += f" 较昨日 JCS {direction} {abs(jcs_score - prev_jcs):.0f} 分，信号{'改善' if jcs_score > prev_jcs else '恶化'}。"
        if prev_pos is not None and abs(position - prev_pos) > 5:
            direction = "上调" if position > prev_pos else "下调"
            p3 += f" 仓位目标{direction} {abs(position - prev_pos):.0f}%。"

    paragraphs.append(p3)

    return paragraphs


# ═══════════════════════════════════════════════════════════
#  V22.2: LLM 叙事增强层
#  Gemini / Claude / GPT 多后端支持, urllib 零依赖调用。
# ═══════════════════════════════════════════════════════════

import os as _rg_os
import json as _rg_json

_AI_CONFIG_PATH = _rg_os.path.join(
    _rg_os.path.dirname(_rg_os.path.dirname(_rg_os.path.abspath(__file__))),
    "config", "ai_config.json"
)


def _load_ai_config() -> dict:
    """加载 AI 配置 (带缓存)"""
    try:
        with open(_AI_CONFIG_PATH, "r", encoding="utf-8") as f:
            return _rg_json.load(f)
    except Exception:
        return {"enable_ai_narrative": False}


def _is_ai_enabled() -> bool:
    """检查 AI 叙事是否启用且有有效 Key"""
    cfg = _load_ai_config()
    if not cfg.get("enable_ai_narrative", False):
        return False
    provider = cfg.get("provider", "gemini")
    key = cfg.get(provider, {}).get("api_key", "")
    return bool(key and len(key) > 10)


def _build_ai_prompt(snapshot: dict, jcs: dict, conflicts: dict,
                     tail_risk: dict, prev: dict,
                     global_temp: dict = None) -> str:
    """将引擎读数组装为结构化 Prompt"""
    jcs_score = jcs.get("score", 50)
    jcs_level = jcs.get("level", "medium")
    directions = jcs.get("directions", {})
    regime = snapshot.get("aiae_regime", 3)
    aiae_v1 = snapshot.get("aiae_v1", 22)
    erp_val = snapshot.get("erp_val", 4.5)
    vix_val = snapshot.get("vix_val", 20)
    mr_regime = snapshot.get("mr_regime", "RANGE")
    position = snapshot.get("suggested_position", 55)
    conflict_count = conflicts.get("conflict_count", 0)
    tail_score = tail_risk.get("score", 0)

    regime_cn = _REGIME_CN.get(regime, "中性均衡")
    mr_cn = {"BULL": "上行趋势", "BEAR": "下行趋势",
             "CRASH": "崩盘", "RANGE": "区间震荡"}.get(mr_regime, mr_regime)

    bull = sum(1 for d in directions.values() if d == 1)
    bear = sum(1 for d in directions.values() if d == -1)

    ctx = f"""JCS联合置信度: {jcs_score:.0f}分 ({jcs_level})
AIAE配置热度: {aiae_v1:.1f}%, Regime {regime} ({regime_cn})
建议仓位: {position:.0f}%
ERP股债性价比: {erp_val:.2f}%
VIX恐慌指数: {vix_val:.1f}
MR技术面: {mr_regime} ({mr_cn})
引擎方向: {bull}/4看多, {bear}/4看空
矛盾信号: {conflict_count}个
尾部风险: {tail_score:.0f}分"""

    # 昨日对比
    delta_ctx = "无昨日数据"
    if prev:
        p_jcs = prev.get("jcs_score")
        p_pos = prev.get("suggested_position")
        p_regime = prev.get("aiae_regime")
        delta_parts = []
        if p_jcs is not None:
            delta_parts.append(f"JCS: {p_jcs:.0f}→{jcs_score:.0f}")
        if p_pos is not None:
            delta_parts.append(f"仓位: {p_pos:.0f}%→{position:.0f}%")
        if p_regime is not None:
            delta_parts.append(f"Regime: R{p_regime}→R{regime}")
        delta_ctx = ", ".join(delta_parts) if delta_parts else "无显著变化"

    # 近期事件
    events_ctx = "近期无重大市场事件"
    try:
        from dashboard_modules.decision_engine import get_recent_events
        events = get_recent_events(5)
        if events:
            events_ctx = "\n".join([
                f"- [{e.get('severity', '')}] {e.get('title', '')}: "
                f"{e.get('detail', '')}"
                for e in events
            ])
    except Exception:
        pass

    # 全球温度
    global_ctx = "全球数据不可用"
    if global_temp:
        markets = global_temp.get("markets", [])
        if markets:
            parts = []
            for m in markets:
                if m.get("status") in ("ready", "fallback"):
                    parts.append(
                        f"{m.get('name', '')}: AIAE={m.get('aiae_v1', '?')}% "
                        f"Regime={m.get('regime_cn', '?')}"
                    )
            global_ctx = "; ".join(parts) if parts else "全球数据加载中"

    prompt = f"""你是 AlphaCore 量化投委会的首席策略师。请根据以下引擎数据，撰写 2-3 段专业的市场分析叙事，供投委会决策简报使用。

要求:
1. 语言专业但不生硬，如同基金经理对投委会的口头汇报
2. 必须引用具体数据 (JCS、AIAE、VIX 等数值)
3. 如果存在引擎矛盾，必须解释矛盾的含义和应对建议
4. 如果有近期市场事件，需整合到分析中
5. 最后一段必须给出明确的操作建议
6. 总字数控制在 300-500 字
7. 每段之间用空行分隔，不要加标题或序号

===== 今日引擎读数 =====
{ctx}

===== 昨日对比 =====
{delta_ctx}

===== 近期市场事件 =====
{events_ctx}

===== 全球市场温度 =====
{global_ctx}"""

    return prompt


def _call_gemini(prompt: str, cfg: dict) -> str:
    """调用 Gemini API (标准库 urllib, 零依赖)"""
    import urllib.request

    gemini_cfg = cfg.get("gemini", {})
    api_key = gemini_cfg.get("api_key", "")
    model = gemini_cfg.get("model", "gemini-2.0-flash")
    timeout = cfg.get("timeout_seconds", 20)
    max_tokens = cfg.get("max_tokens", 1024)

    url = (f"https://generativelanguage.googleapis.com/v1beta/"
           f"models/{model}:generateContent?key={api_key}")

    payload = _rg_json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.7,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = _rg_json.loads(resp.read().decode("utf-8"))

    # 解析 Gemini 响应
    candidates = result.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini 返回空 candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise ValueError("Gemini 返回空 parts")
    return parts[0].get("text", "")


def _call_openai_compatible(prompt: str, cfg: dict, provider: str) -> str:
    """调用 OpenAI 兼容 API (DeepSeek / OpenAI / 其他兼容端点)"""
    import urllib.request

    provider_cfg = cfg.get(provider, {})
    api_key = provider_cfg.get("api_key", "")
    model = provider_cfg.get("model", "deepseek-chat")
    base_url = provider_cfg.get("base_url", "https://api.deepseek.com")
    timeout = cfg.get("timeout_seconds", 30)
    max_tokens = cfg.get("max_tokens", 1024)

    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    payload = _rg_json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一位专业的量化投资策略分析师。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = _rg_json.loads(resp.read().decode("utf-8"))

    choices = result.get("choices", [])
    if not choices:
        raise ValueError(f"{provider} 返回空 choices")
    return choices[0].get("message", {}).get("content", "")


def _generate_ai_narrative(snapshot: dict, jcs: dict, conflicts: dict,
                           tail_risk: dict, prev: dict,
                           global_temp: dict = None) -> list:
    """编排: Prompt构建 → LLM调用 → 段落解析"""
    cfg = _load_ai_config()
    provider = cfg.get("provider", "gemini")

    prompt = _build_ai_prompt(
        snapshot, jcs, conflicts, tail_risk, prev, global_temp
    )

    # 调用 LLM
    if provider == "gemini":
        raw_text = _call_gemini(prompt, cfg)
    elif provider in ("deepseek", "openai"):
        raw_text = _call_openai_compatible(prompt, cfg, provider)
    else:
        raise ValueError(f"不支持的 LLM 后端: {provider}")

    if not raw_text or len(raw_text) < 50:
        logger.warning("AI 叙事返回文本过短 (%d 字符), 放弃", len(raw_text or ""))
        return []

    # 解析段落 (按空行分段)
    paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]

    logger.info("AI 叙事生成成功 (%s): %d 段, %d 字符",
                provider, len(paragraphs), len(raw_text))
    return paragraphs

