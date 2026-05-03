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
    lines.append(f"> {date} ({weekday}) · 收盘后自动生成 · V21.0")
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
    lines.append("本报告由 AlphaCore V21.0 自动生成，基于 AIAE/ERP/VIX/MR 四引擎联合分析。")
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
