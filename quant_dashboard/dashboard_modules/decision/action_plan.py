"""
AlphaCore · 执行建议 & 警示生成器
====================================
从 decision_engine.py 拆分 (P2-A)

公开 API:
  - generate_action_plan(snapshot, jcs, conflicts) → dict
  - generate_alerts(snapshot) → list
"""

import math

from dashboard_modules.decision.conflicts import _signal_direction
from dashboard_modules.decision.jcs import _JCS_WEIGHTS


def _get_current_position() -> float:
    """获取当前实际仓位 (排除国债逆回购), 与投资组合页一致.
    Returns: 仓位百分比 (0-100), -1 表示不可用"""
    try:
        import re as _re
        from portfolio_engine import get_portfolio_engine
        val = get_portfolio_engine().get_valuation()
        total_asset = val.get("total_asset", 0)
        if total_asset <= 0:
            return 0.0
        equity_mv = sum(
            p.get("market_value", 0)
            for p in val.get("positions", [])
            if not (p.get("ts_code", "").split('.')[0][:3] in ('131', '204')
                    or '逆回购' in p.get("name", "")
                    or bool(_re.search(r'GC\d', p.get("name", ""))))
        )
        return round(equity_mv / total_asset * 100, 1)
    except Exception:
        return -1


def _apply_position_gap_note(base_note: str, target: float, current: float) -> str:
    """根据目标仓位与实际仓位的缺口, 动态生成 risk_note"""
    if current < 0:
        return base_note
    gap = target - current
    if abs(gap) <= 10:
        return f"仓位与目标基本匹配 (现{current:.0f}% → 目标{target}%)"
    if gap < 0:
        return f"当前仓位 {current:.0f}% 高于目标 {target}%，建议逐步减仓 {abs(gap):.0f}pp"
    return f"当前仓位 {current:.0f}% 低于目标 {target}%，可分批加仓 {gap:.0f}pp"


def generate_action_plan(snapshot: dict, jcs: dict, conflicts: dict) -> dict:
    """
    根据 JCS + 矛盾状态 + 快照数据 → 生成可执行的操作建议。

    返回:
    {
        "action_label": str,       # 核心行动标签
        "action_icon": str,        # 图标
        "confidence": str,         # high/medium/low
        "reasoning": str,          # 一句话推理逻辑
        "top_signals": [str],      # 最强信号摘要 (最多3个)
        "next_check": str,         # 下次检查条件
        "position_target": float,  # 目标仓位
        "risk_note": str,          # 风控提示
    }
    """
    jcs_score = jcs.get("score", 50)
    jcs_level = jcs.get("level", "medium")
    directions = jcs.get("directions", {})
    has_severe = conflicts.get("has_severe", False)
    conflict_count = conflicts.get("conflict_count", 0)
    raw_pos = snapshot.get("suggested_position", 55)
    aiae_regime = snapshot.get("aiae_regime", 3)
    mr_regime = snapshot.get("mr_regime", "RANGE")
    erp_score = snapshot.get("erp_score", 50)
    vix_val = snapshot.get("vix_val", 20)

    # V19.1: 平滑 Sigmoid 曲线代替硬分档
    # JCS=0→0.55, JCS=45→0.80, JCS=70→0.95, JCS=100→1.0
    jcs_multiplier = 0.5 + 0.5 / (1 + math.exp(-0.08 * (jcs_score - 45)))
    pos = round(raw_pos * jcs_multiplier)

    top_signals = []
    risk_note = ""

    # V25.0: 读取实际仓位 (用于缺口分析)
    current_pos = _get_current_position()

    # ── 高置信场景 ──
    if jcs_level == "high" and not has_severe:
        bullish = sum(1 for d in directions.values() if d == 1)
        bearish = sum(1 for d in directions.values() if d == -1)
        # V25.0: 加权方向 [-1, +1] (反映引擎权重差异)
        weighted_dir = sum(directions.get(k, 0) * _JCS_WEIGHTS.get(k, 0) for k in _JCS_WEIGHTS)

        if bullish >= 3:
            # ── 强多: 3+引擎看多 ──
            action_label = "积极加仓"
            action_icon = "🚀"
            reasoning = f"JCS {jcs_score}分，{bullish}/4引擎看多，方向明确"
            if mr_regime == "BULL":
                top_signals.append("MR技术面处于牛市区间")
            if erp_score > 60:
                top_signals.append(f"ERP估值偏低({erp_score:.0f}分)")
            if aiae_regime <= 2:
                top_signals.append(f"AIAE处于冷配区(R{aiae_regime})")
            next_check = "AIAE升至R4或VIX突破28时减仓"
            risk_note = f"仓位上限 {pos}%，注意单票不超过20%"
        elif bearish >= 3:
            # ── 强空: 3+引擎看空 ──
            action_label = "防御减仓"
            action_icon = "🛡️"
            reasoning = f"JCS {jcs_score}分但方向偏空，{bearish}/4引擎看空"
            if aiae_regime >= 4:
                top_signals.append(f"AIAE过热(R{aiae_regime})")
            if erp_score < 40:
                top_signals.append("ERP估值偏高")
            if vix_val > 28:
                top_signals.append(f"VIX恐慌({vix_val:.1f})")
            next_check = "VIX回落至25以下 或 AIAE降至R3"
            risk_note = "严格止损，不抄底"
        elif weighted_dir <= -0.30:
            # ── V25.0 中等偏空 ──
            action_label = "逐步减仓"
            action_icon = "📉"
            reasoning = f"JCS {jcs_score}分，加权方向 {weighted_dir:+.2f} 偏空，{bearish}/4引擎看空"
            if aiae_regime >= 4:
                top_signals.append(f"AIAE过热(R{aiae_regime})，主锚看空")
            if erp_score < 45:
                top_signals.append(f"ERP估值偏高({erp_score:.0f}分)")
            if vix_val > 20:
                top_signals.append(f"VIX={vix_val:.1f}，波动中性偏高")
            next_check = "AIAE降至R3 或 加权方向转正时停止减仓"
            risk_note = "分批减仓，优先减非核心持仓"
        elif weighted_dir >= 0.30:
            # ── V25.0 中等偏多 ──
            action_label = "择机加仓"
            action_icon = "📈"
            reasoning = f"JCS {jcs_score}分，加权方向 {weighted_dir:+.2f} 偏多，{bullish}/4引擎看多"
            if aiae_regime <= 2:
                top_signals.append(f"AIAE冷配区(R{aiae_regime})，主锚看多")
            if erp_score > 55:
                top_signals.append(f"ERP估值偏低({erp_score:.0f}分)")
            next_check = "确认MR技术面共振后可加大力度"
            risk_note = f"分批加仓至 {pos}%，单次不超5%"
        else:
            # ── 真正中性 ──
            action_label = "持仓优化"
            action_icon = "⚖️"
            reasoning = f"JCS {jcs_score}分，加权方向 {weighted_dir:+.2f} 接近中性"
            top_signals.append("多引擎无对冲，可小幅调仓")
            next_check = "明日收盘后复查"
            risk_note = "维持现有仓位结构"

        # V25.0: 仓位缺口覆盖 risk_note
        risk_note = _apply_position_gap_note(risk_note, pos, current_pos)

        return {
            "action_label": action_label, "action_icon": action_icon,
            "confidence": "high", "reasoning": reasoning,
            "top_signals": top_signals[:3], "next_check": next_check,
            "position_target": pos, "risk_note": risk_note,
            "current_position": current_pos,
            "position_gap": round(pos - current_pos, 1) if current_pos >= 0 else None,
        }

    # ── 矛盾场景 ──
    if has_severe or conflict_count >= 2:
        action_label = "暂停操作"
        action_icon = "⏸️"
        reasoning = f"检测到{conflict_count}个矛盾(含{'严重矛盾' if has_severe else '中度矛盾'})，JCS={jcs_score}"
        for c in conflicts.get("conflicts", [])[:2]:
            top_signals.append(c["desc"])
        next_check = conflicts.get("conflicts", [{}])[0].get("action", "等待矛盾消解")
        risk_note = _apply_position_gap_note("不新建仓位，已有持仓设严格止损", min(pos, 30), current_pos)

        return {
            "action_label": action_label, "action_icon": action_icon,
            "confidence": "low", "reasoning": reasoning,
            "top_signals": top_signals[:3], "next_check": next_check,
            "position_target": min(pos, 30), "risk_note": risk_note,
            "current_position": current_pos,
            "position_gap": round(min(pos, 30) - current_pos, 1) if current_pos >= 0 else None,
        }

    # ── 中置信 / 默认场景 ──
    action_label = "持仓观望"
    action_icon = "👁️"
    reasoning = f"JCS {jcs_score}分，信号不够强烈，等待明确方向"
    neutral_count = sum(1 for d in directions.values() if d == 0)
    if neutral_count >= 3:
        top_signals.append(f"{neutral_count}/4引擎中性，市场缺乏方向")
    if conflict_count == 1:
        top_signals.append("存在轻度矛盾，不宜大幅调仓")
    top_signals.append(f"当前仓位目标: {pos}%")
    next_check = "明日收盘后复查 或 VIX出现异动"
    risk_note = _apply_position_gap_note("维持现有仓位，不追涨杀跌", pos, current_pos)

    return {
        "action_label": action_label, "action_icon": action_icon,
        "confidence": "medium", "reasoning": reasoning,
        "top_signals": top_signals[:3], "next_check": next_check,
        "position_target": pos, "risk_note": risk_note,
        "current_position": current_pos,
        "position_gap": round(pos - current_pos, 1) if current_pos >= 0 else None,
    }


def generate_alerts(snapshot: dict) -> list:
    """
    扫描快照，生成市场警报列表。
    只在极端或异常条件下触发，正常市场不产生警报。

    返回: [{type, severity, icon, title, detail, rule}]
    severity: critical / warning / caution
    """
    alerts = []
    vix = snapshot.get("vix_val") or 20
    aiae_regime = snapshot.get("aiae_regime") or 3
    directions = _signal_direction(snapshot)
    degraded = snapshot.get("degraded_modules", [])
    if isinstance(degraded, str):
        degraded = [d.strip() for d in degraded.split(",") if d.strip()]

    # 1. VIX 极端恐慌
    if vix >= 35:
        alerts.append({
            "type": "vix_extreme",
            "severity": "critical",
            "icon": "🚨",
            "title": f"VIX 极端恐慌 ({vix:.1f})",
            "detail": "全球恐慌指数超过 35，触发全策略风控降权",
            "rule": "规则: VIX ≥ 35 → 仓位上限 30%，禁止新建仓",
        })

    # 2. 流动性熔断
    if snapshot.get("is_circuit_breaker"):
        alerts.append({
            "type": "circuit_breaker",
            "severity": "critical",
            "icon": "🛑",
            "title": "流动性熔断触发",
            "detail": "个股跌停占比超限，市场流动性极度恶化",
            "rule": "规则: 熔断触发 → 仓位归零，等待流动性恢复",
        })

    # 3. 多引擎共振看空 (≥3 个引擎 -1)
    bear_count = sum(1 for d in directions.values() if d == -1)
    if bear_count >= 3:
        bear_names = [k.upper() for k, v in directions.items() if v == -1]
        alerts.append({
            "type": "multi_bear",
            "severity": "warning",
            "icon": "⚠️",
            "title": f"{bear_count} 引擎共振看空",
            "detail": f"{', '.join(bear_names)} 同时发出看空信号",
            "rule": "规则: ≥3 引擎看空 → 降至防御仓位，严格止损",
        })

    # 4. 数据降级警告
    if len(degraded) >= 2:
        alerts.append({
            "type": "data_degraded",
            "severity": "caution",
            "icon": "⚡",
            "title": f"{len(degraded)} 个模块数据降级",
            "detail": f"{', '.join(degraded)} 数据过期，JCS 置信度可能偏离",
            "rule": "规则: ≥2 模块降级 → 不依据 JCS 执行，等待数据恢复",
        })

    # 5. AIAE 极度过热
    if aiae_regime >= 5:
        alerts.append({
            "type": "aiae_overheat",
            "severity": "warning",
            "icon": "🔥",
            "title": "市场极度过热 (Ⅴ级)",
            "detail": "AIAE 配置热度达到极端，历史回撤概率最高",
            "rule": "规则: AIAE R5 → 仓位上限 15%，禁止追涨",
        })

    return alerts
