"""
AlphaCore · 仓位决策引擎 (从 main.py 提取)
=============================================
包含:
  - get_vix_analysis: VIX 四级分析
  - get_position_path: 5日仓位路径预测
  - _synthesize_directives: AIAE×ERP×波动 三因子指令合成 (VIX 仅作海外参考)
  - get_tomorrow_plan: 明日交易计划 (V2.0 五档主轴)
  - get_institutional_mindset: 实战对策心态矩阵
  - get_tactical_label: V3.6 仓位标签
"""

import math
import time
from collections.abc import Mapping

from aiae_engine import REGIMES as AIAE_REGIMES
from services.health_status import evaluate_aiae_context


def _has_valid_decision_payload(aiae_ctx):
    """Validate the minimum payload needed to emit position instructions."""
    if not isinstance(aiae_ctx, Mapping):
        return False
    regime = aiae_ctx.get("regime")
    cap = aiae_ctx.get("cap")
    regime_info = aiae_ctx.get("regime_info")
    if isinstance(regime, bool) or not isinstance(regime, int) or regime not in AIAE_REGIMES:
        return False
    if isinstance(cap, bool) or not isinstance(cap, (int, float)) or not math.isfinite(cap):
        return False
    if not 0 <= cap <= 100 or not isinstance(regime_info, Mapping):
        return False
    return all(regime_info.get(field) for field in ("emoji", "cn", "color", "action"))


def _usable_aiae_context(aiae_ctx):
    state = evaluate_aiae_context(aiae_ctx, now_ts=time.time())
    return aiae_ctx if state["usable"] and _has_valid_decision_payload(aiae_ctx) else None


def _locked_tomorrow_plan(aiae_state, vix_analysis):
    """Return a fail-closed plan without synthesizing executable tactics."""
    reason = aiae_state.get("reason") or "unverifiable"
    quality_score = aiae_state.get("data_quality_score", 0)
    age_sec = aiae_state.get("age_sec")
    max_age_sec = aiae_state.get("max_age_sec")

    if reason == "missing":
        message = "AIAE 数据缺失，停止生成交易指令"
    elif reason == "decision_locked":
        message = f"AIAE 数据质量/风控未通过（质量分 {quality_score}/100），停止生成交易指令"
    elif reason == "timestamp_missing_or_invalid":
        message = "AIAE 时间戳缺失或无效，停止生成交易指令"
    elif reason == "stale":
        message = f"AIAE 数据已过期（{age_sec}秒 > {max_age_sec}秒），停止生成交易指令"
    elif reason == "invalid_payload":
        message = "AIAE 决策字段缺失或无效，停止生成交易指令"
    else:
        message = "AIAE 状态不可验证，停止生成交易指令"

    directive = {
        "priority": "risk",
        "icon": "🔒",
        "text": message,
        "color": "#ef4444",
    }
    return {
        "mode": "locked",
        "decision_locked": True,
        "lock_reason": reason,
        "lock_message": message,
        "lock_details": {
            "present": aiae_state.get("present", False),
            "fresh": aiae_state.get("fresh", False),
            "age_sec": age_sec,
            "max_age_sec": max_age_sec,
            "data_quality_score": quality_score,
        },
        "primary_regime": None,
        "validators": {
            "vix": {
                "value": vix_analysis.get("vix_val"),
                "label": vix_analysis.get("label", ""),
                "advisory_only": True,
            },
        },
        "regime_matrix": [],
        "directives": [directive],
        "scenarios": [],
        "risk_panel": {},
        # 兼容旧消费者，但只暴露锁定信息，不生成任何 VIX 替代策略。
        "framework": [message],
        "current_tactics": {"regime": "🔒 决策锁定"},
    }


# ═══════════════════════════════════════════════════
#  VIX 分析
# ═══════════════════════════════════════════════════

def get_vix_analysis(vix_val: float):
    """V4.2 VIX Professional 4-Tier Protocol (Institutional Grade)"""
    # 52周范围参考：13.38 - 60.13
    vix_min, vix_max = 13.38, 60.13
    percentile = min(100, max(0, (vix_val - vix_min) / (vix_max - vix_min) * 100))

    res = {}
    if vix_val < 15:
        res = {
            "label": "🟢 极度平静",
            "multiplier": 1.05,
            "class": "vix-status-low",
            "desc": "风险低估，避险布局",
            "percentile": round(percentile, 1)
        }
    elif vix_val < 25:
        res = {
            "label": "🟡 正常震荡",
            "multiplier": 1.0,
            "class": "vix-status-norm",
            "desc": "市场常态，结构性调仓",
            "percentile": round(percentile, 1)
        }
    elif vix_val < 35:
        res = {
            "label": "🔴 高度警觉",
            "multiplier": 0.75,
            "class": "vix-status-alert",
            "desc": "当前临界区，加强风控",
            "percentile": round(percentile, 1)
        }
    else:
        res = {
            "label": "🔴🔴 极端恐慌",
            "multiplier": 0.5,
            "class": "vix-status-crisis",
            "desc": "防守优先，等待企稳",
            "percentile": round(percentile, 1)
        }
    res["vix_val"] = vix_val
    return res


# ═══════════════════════════════════════════════════
#  仓位路径预测
# ═══════════════════════════════════════════════════

def get_position_path(current_pos: float, vix_analysis: dict,
                      aiae_ctx: dict = None) -> list[float]:
    """
    AlphaCore V4.6: 5-Day Position Pathing Engine
    外推未来 5 个交易日的阶梯式仓位建议路径

    P0-4 Fix: 增加 AIAE cap 上界约束
    当 AIAE=R5 (cap=15%) 但 VIX=18 (平静) 时,
    不再建议向上调仓 — 路径被 AIAE cap 钳位。

    AIAE 缺失、锁定或过期时冻结路径，防止 VIX 单因子绕过主轴风控。
    """
    v_val = vix_analysis.get('vix_val', 20)

    # 获取单一 AIAE 上下文；兼容旧调用方式时才从缓存读取。
    effective_ctx = aiae_ctx
    if effective_ctx is None:
        try:
            from services.cache_service import cache_manager
            effective_ctx = cache_manager.get_json("aiae_ctx")
        except Exception:
            effective_ctx = None

    usable_ctx = _usable_aiae_context(effective_ctx)
    if not usable_ctx:
        frozen_pos = round(max(10, min(100, float(current_pos))), 1)
        return [frozen_pos] * 5

    aiae_cap = usable_ctx.get("cap", 100)

    path = []
    # 模拟路径：基于 VIX 向常态(20)回归的假设进行预测
    for i in range(1, 6):
        # 回归步长：15% 每周期
        regression_factor = 0.15 * i
        projected_vix = v_val + (20 - v_val) * regression_factor

        # 仓位对冲逻辑：VIX 每变动 1点，对仓位影响约 2-3%
        vix_gap = v_val - projected_vix
        step_pos = current_pos * (1 + vix_gap * 0.02)

        # P0-4: 双重约束 — VIX 路径 ∩ AIAE cap 上界
        step_pos = min(step_pos, aiae_cap)

        # 边界约束 (10% - max(aiae_cap, 10)%)
        path.append(round(max(10, min(100, step_pos)), 1))
    return path


# ═══════════════════════════════════════════════════
#  三因子指令合成
# ═══════════════════════════════════════════════════

def _risk_directive(vol_overlay, vix_val):
    """第三行风控指令: 文案只描述真正生效的规则, 不再出现未执行的 "Cap×0.75"."""
    factor = vol_overlay.get("factor", 1.0)
    status = vol_overlay.get("status")
    ratio = vol_overlay.get("ratio")
    trig = vol_overlay.get("trigger_ratio") or 2.0
    if status == "disabled":
        a_part = "A股波动刹车已关闭 (配置) → 上限不变"
    elif status in ("stale", "missing"):
        a_part = f"A股波动数据{'过期' if status == 'stale' else '缺失'} → 上限×{factor:.2f} (保守)"
    elif (vol_overlay.get("brake_on") or (isinstance(factor, (int, float)) and factor < 1)) and ratio is None:
        a_part = f"A股波动刹车 上限×{factor:.2f}"
    elif vol_overlay.get("brake_on") or (isinstance(factor, (int, float)) and factor < 1):
        a_part = f"A股波动 {ratio:.1f}倍基准 ≥ {trig:.1f}倍 → 尾部刹车 上限×{factor:.2f}"
    elif ratio is not None:
        a_part = f"A股波动 {ratio:.1f}倍基准 (刹车线 {trig:.1f}倍) → 上限不变"
    else:
        a_part = "A股波动未接入 → 上限不变"

    if vix_val >= 35:
        icon, color, v_part = "🚨", "#ef4444", f"VIX {vix_val} 海外极端恐慌, 停手观望"
    elif vix_val >= 25:
        icon, color, v_part = "⚠️", "#f97316", f"VIX {vix_val} 海外紧张, 警惕传染"
    else:
        icon, color, v_part = "🛡️", "#94a3b8", f"VIX {vix_val} 正常"
    if (vol_overlay.get("brake_on") or status in ("stale", "missing")) and icon == "🛡️":
        icon, color = "⚠️", "#f97316"
    return {"priority": "risk", "icon": icon, "text": f"{a_part} · {v_part}", "color": color}


def _synthesize_directives(aiae_ctx, vix_analysis):
    """V2.0 三因子决策树 → 3行可执行指令"""
    regime = aiae_ctx["regime"]
    cap = aiae_ctx["cap"]
    erp_tier = aiae_ctx.get("erp_tier", "neutral")
    vix_val = vix_analysis.get("vix_val", 20)
    regime_info = aiae_ctx["regime_info"]

    # Line 1: AIAE 主指令 (永远来自 regime); 有效上限已含市场波动刹车
    base_cap = aiae_ctx.get("base_cap", cap)
    cap_text = f"Cap{cap}%" if base_cap == cap else f"Cap{base_cap}%→{cap}% (波动刹车)"
    d1 = {
        "priority": "primary", "icon": "🎯",
        "text": f"AIAE {regime_info['emoji']} {regime_info['cn']} {cap_text} → {regime_info['action']}",
        "color": regime_info["color"],
    }

    # Line 2: ERP 验证 (确认 or 警告)
    erp_confirms = (erp_tier == "bull" and regime <= 3) or \
                   (erp_tier == "bear" and regime >= 4)
    if erp_confirms:
        d2_text = f"ERP {aiae_ctx.get('erp_val', '--')}% {aiae_ctx.get('erp_label', '--')} → 验证主轴方向"
        d2_color = "#10b981"
        d2_icon = "✅"
    elif erp_tier == "bull" and regime >= 4:
        d2_text = f"ERP {aiae_ctx.get('erp_val', '--')}% {aiae_ctx.get('erp_label', '--')} → ⚠ 矛盾! 估值低但AIAE偏热"
        d2_color = "#f59e0b"
        d2_icon = "⚠️"
    else:
        d2_text = f"ERP {aiae_ctx.get('erp_val', '--')}% {aiae_ctx.get('erp_label', '--')} → 中性参考"
        d2_color = "#94a3b8"
        d2_icon = "📊"
    d2 = {"priority": "confirm", "icon": d2_icon, "text": d2_text, "color": d2_color}

    # Line 3: 风控 — A 股实际波动 (已计入上限) + VIX (海外参考, 不直接改上限)
    d3 = _risk_directive(aiae_ctx.get("vol_overlay") or {}, vix_val)

    return [d1, d2, d3]


# ═══════════════════════════════════════════════════
#  明日交易计划
# ═══════════════════════════════════════════════════

def get_tomorrow_plan(vix_analysis, temp_score, aiae_ctx=None):
    """V2.0: 明日交易计划 · AIAE五档主轴 + ERP/VIX 验证

    仅在 AIAE 状态、质量和新鲜度全部通过时生成三因子决策；
    任何缺失或降级状态都强制锁定，不允许 VIX 替代 AIAE 主轴。
    """
    v_val = vix_analysis.get('vix_val', 20)
    aiae_state = evaluate_aiae_context(aiae_ctx, now_ts=time.time())
    if not aiae_state["usable"]:
        return _locked_tomorrow_plan(aiae_state, vix_analysis)
    if not _has_valid_decision_payload(aiae_ctx):
        invalid_state = dict(aiae_state, usable=False, decision_locked=True, reason="invalid_payload")
        return _locked_tomorrow_plan(invalid_state, vix_analysis)

    # ========== 新版 V2.0 逻辑 ==========
    if aiae_ctx.get("regime"):
        regime = aiae_ctx["regime"]
        regime_info = aiae_ctx["regime_info"]
        cap = aiae_ctx["cap"]

        # 1. primary_regime: 决策锚
        primary_regime = {
            "tier": regime,
            "emoji": regime_info["emoji"],
            "cn": regime_info["cn"],
            "aiae_v1": aiae_ctx.get("aiae_v1", 0),
            "cap": cap,
            "base_cap": aiae_ctx.get("base_cap", cap),
            "vol_factor": (aiae_ctx.get("vol_overlay") or {}).get("factor", 1.0),
            "vol_status": (aiae_ctx.get("vol_overlay") or {}).get("status", "not_applied"),
            "cap_range": regime_info.get("position", "50-65%"),
            "action": regime_info["action"],
            "action_detail": regime_info.get("desc", ""),
        }

        # 2. validators: ERP + VIX 验证维度
        erp_tier = aiae_ctx.get("erp_tier", "neutral")
        erp_confirms = (erp_tier == "bull" and regime <= 3) or \
                       (erp_tier == "bear" and regime >= 4)
        risk_override = v_val >= 30
        vix_mult = vix_analysis.get("multiplier", 1.0)
        validators = {
            "erp": {
                "value": aiae_ctx.get("erp_val", 0),
                "label": aiae_ctx.get("erp_label", "--"),
                "erp_tier": erp_tier,
                "confirms": erp_confirms,
            },
            "vix": {
                "value": v_val,
                "label": vix_analysis.get("label", ""),
                "risk_override": risk_override,
                "multiplier": vix_mult,
                "advisory_only": True,  # 海外参考; A 股上限只受 vol_overlay 影响
            },
            "a_share_vol": dict(aiae_ctx.get("vol_overlay") or {"status": "not_applied", "factor": 1.0}),
        }

        # 3. regime_matrix: 五档操作矩阵
        _vix_cross = {
            1: "VIX>30时分批介入", 2: "VIX<20加速建仓", 3: "VIX>30启动减仓",
            4: "VIX<15警惕拥挤", 5: "任何VIX都清仓"
        }
        regime_matrix = []
        for t in range(1, 6):
            ri = AIAE_REGIMES.get(t, AIAE_REGIMES[3])
            regime_matrix.append({
                "tier": t,
                "emoji": ri["emoji"],
                "cn": ri["cn"],
                "range": ri["range"],
                "cap_range": ri["position"],
                "action": f"{ri['action']} · {ri['desc']}",
                "vix_cross": _vix_cross.get(t, ""),
                "active": t == regime,
            })

        # 4. directives: 三因子指令合成
        directives = _synthesize_directives(aiae_ctx, vix_analysis)

        # 5. scenarios: AIAE+VIX+ERP 三轴情景预判
        scenarios = [
            {"condition": f"AIAE上行至{'Ⅴ' if regime == 4 else 'Ⅳ'}级" if regime <= 4 else "AIAE维持Ⅴ级",
             "action": "启动系统减仓至40%以下" if regime <= 3 else ("3天清仓无例外" if regime >= 5 else "继续每周减仓5%"),
             "type": "aiae_upgrade"},
            {"condition": "A股波动升至2倍基准以上",
             "action": "尾部刹车自动生效: 上限按波动比例下调 (当日收盘计算, 次日执行)",
             "type": "vix_alert"},
            {"condition": "ERP跌破3%",
             "action": "估值吸引力下降·降低进攻权重",
             "type": "erp_shift"},
        ]

        # 6. risk_panel: 三大预警
        margin_heat_val = aiae_ctx.get("margin_heat", 2.0)
        slope_val = aiae_ctx.get("slope", 0)
        fund_pos_val = aiae_ctx.get("fund_position", 80)
        risk_panel = {
            "margin_heat": {
                "value": margin_heat_val,
                "threshold": 3.5,
                "status": "danger" if margin_heat_val > 3.5 else ("warning" if margin_heat_val > 2.5 else "safe"),
            },
            "slope": {
                "value": slope_val,
                "threshold": 1.5,
                "status": "danger" if abs(slope_val) > 1.5 else "safe",
                "direction": aiae_ctx.get("slope_direction", "flat"),
            },
            "fund_position": {
                "value": fund_pos_val,
                "threshold": 90,
                "status": "danger" if fund_pos_val > 90 else ("warning" if fund_pos_val > 85 else "safe"),
            },
            "overall_risk": "high" if margin_heat_val > 3.5 or abs(slope_val) > 1.5 else (
                "medium" if margin_heat_val > 2.5 or fund_pos_val > 85 else "low"
            ),
        }
        vol_budget = aiae_ctx.get("vol_budget")
        if isinstance(vol_budget, Mapping) and vol_budget.get("max_equity_pct") is not None:
            excess = vol_budget.get("equity_excess_pp") or 0
            risk_panel["vol_budget"] = {
                "target_vol": vol_budget.get("target_vol"),
                "portfolio_vol": vol_budget.get("portfolio_vol"),
                "invested_pct": vol_budget.get("invested_pct"),
                "max_equity_pct": vol_budget.get("max_equity_pct"),
                "equity_excess_pp": excess,
                "effective_bets": vol_budget.get("effective_bets"),
                "breach_count": vol_budget.get("breach_count"),
                "status": "danger" if excess > 10 else ("warning" if excess > 0 else "safe"),
            }
            risk_panel["effective_position_cap"] = round(min(float(cap), float(vol_budget["max_equity_pct"])), 1)
            if excess > 10:
                risk_panel["overall_risk"] = "high"

        # 7. 兼容旧字段
        framework_compat = [d["text"] for d in directives]
        tactics_compat = {"regime": f"{regime_info['emoji']} Ⅲ级 {regime_info['cn']}" if regime == 3 else f"{regime_info['emoji']} {'Ⅰ' if regime==1 else 'Ⅱ' if regime==2 else 'Ⅲ' if regime==3 else 'Ⅳ' if regime==4 else 'Ⅴ'}级 {regime_info['cn']}"}
        scenarios_compat = [{"case": s["condition"], "action": s["action"]} for s in scenarios]

        return {
            "mode": "decision",
            "decision_locked": False,
            "lock_reason": None,
            "primary_regime": primary_regime,
            "validators": validators,
            "regime_matrix": regime_matrix,
            "directives": directives,
            "scenarios": scenarios,
            "risk_panel": risk_panel,
            # 兼容旧字段
            "framework": framework_compat,
            "current_tactics": tactics_compat,
        }

    # 通过载荷校验后 regime 必然存在；保留防御性锁定以防未来协议扩展。
    invalid_state = dict(aiae_state, usable=False, decision_locked=True, reason="invalid_payload")
    return _locked_tomorrow_plan(invalid_state, vix_analysis)


# ═══════════════════════════════════════════════════
#  标签 & 心态矩阵
# ═══════════════════════════════════════════════════

def get_institutional_mindset(temp: float) -> str:
    """实战对策心态矩阵 (V3.8) - 严格映射统一阶梯"""
    if temp >= 85: return "⚡ 离场观望，宁缺毋滥"
    if temp >= 65: return "🏹 乘胜追击，聚焦领涨"
    if temp >= 45: return "⚖️ 仓位中型，等待分歧"
    if temp >= 25: return "🎯 精准打击，聚焦 Alpha"
    return "💎 别人恐惧，战略建仓"


def get_tactical_label(final_pos, temp, erp_z, crisis):
    """根据 V3.6 矩阵生成实战标签 (Position Scaling Matrix)"""
    if crisis: return "0% (流动性熔断)"
    if temp > 90: return "0% (极度过热)"

    if final_pos >= 90: return f"{int(final_pos)}% (代际大底)"
    if final_pos >= 75: return f"{int(final_pos)}% (黄金布局)"
    if final_pos >= 55: return f"{int(final_pos)}% (趋势共振)"
    if final_pos >= 45: return f"{int(final_pos)}% (动态平衡)"
    if final_pos >= 35: return f"{int(final_pos)}% (战略超配)"
    if final_pos >= 25: return f"{int(final_pos)}% (防御窗口)"
    if final_pos >= 15: return f"{int(final_pos)}% (风险预警)"
    return f"{int(final_pos)}% (极端亢奋)"
