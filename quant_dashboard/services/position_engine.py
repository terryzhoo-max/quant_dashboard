"""
AlphaCore · 仓位决策引擎 (从 main.py 提取)
=============================================
包含:
  - get_vix_analysis: VIX 四级分析
  - get_position_path: 5日仓位路径预测
  - _synthesize_directives: AIAE×ERP×VIX 三因子指令合成
  - get_tomorrow_plan: 明日交易计划 (V2.0 五档主轴)
  - get_institutional_mindset: 实战对策心态矩阵
  - get_tactical_label: V3.6 仓位标签
"""

from aiae_engine import REGIMES as AIAE_REGIMES


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

def get_position_path(current_pos: float, vix_analysis: dict) -> list[float]:
    """
    AlphaCore V4.5: 5-Day Position Pathing Engine
    外推未来 5 个交易日的阶梯式仓位建议路径
    """
    v_val = vix_analysis.get('vix_val', 20)

    path = []
    # 模拟路径：基于 VIX 向常态(20)回归的假设进行预测
    for i in range(1, 6):
        # 回归步长：15% 每周期
        regression_factor = 0.15 * i
        projected_vix = v_val + (20 - v_val) * regression_factor

        # 仓位对冲逻辑：VIX 每变动 1点，对仓位影响约 2-3%
        vix_gap = v_val - projected_vix
        step_pos = current_pos * (1 + vix_gap * 0.02)

        # 边界约束 (10% - 100%)
        path.append(round(max(10, min(100, step_pos)), 1))
    return path


# ═══════════════════════════════════════════════════
#  三因子指令合成
# ═══════════════════════════════════════════════════

def _synthesize_directives(aiae_ctx, vix_analysis):
    """V2.0 三因子决策树 → 3行可执行指令"""
    regime = aiae_ctx["regime"]
    cap = aiae_ctx["cap"]
    erp_tier = aiae_ctx.get("erp_tier", "neutral")
    vix_val = vix_analysis.get("vix_val", 20)
    regime_info = aiae_ctx["regime_info"]

    # Line 1: AIAE 主指令 (永远来自 regime)
    d1 = {
        "priority": "primary", "icon": "🎯",
        "text": f"AIAE {regime_info['emoji']} {regime_info['cn']} Cap{cap}% → {regime_info['action']}",
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

    # Line 3: VIX 风控 (通过 or 警报)
    if vix_val >= 35:
        d3 = {"priority": "risk", "icon": "🚨",
              "text": f"VIX {vix_val} 极端恐慌 → 风控降级Cap×0.5, 停手观望",
              "color": "#ef4444"}
    elif vix_val >= 25:
        d3 = {"priority": "risk", "icon": "⚠️",
              "text": f"VIX {vix_val} 高度紧张 → 风控边际Cap×0.75, 增配红利",
              "color": "#f97316"}
    else:
        d3 = {"priority": "risk", "icon": "🛡️",
              "text": f"VIX {vix_val} 正常 → 风控不触发",
              "color": "#94a3b8"}

    return [d1, d2, d3]


# ═══════════════════════════════════════════════════
#  明日交易计划
# ═══════════════════════════════════════════════════

def get_tomorrow_plan(vix_analysis, temp_score, aiae_ctx=None):
    """V2.0: 明日交易计划 · AIAE五档主轴 + ERP/VIX 验证

    当 aiae_ctx 传入时, 使用 AIAE×ERP×VIX 三因子决策树; 否则降级为旧版 VIX 4阶查表。
    """
    v_val = vix_analysis.get('vix_val', 20)

    # ========== 新版 V2.0 逻辑 ==========
    if aiae_ctx and aiae_ctx.get("regime"):
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
            },
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
            {"condition": "VIX突破30+",
             "action": f"风控降级Cap×0.75 + 增配红利" if v_val < 30 else "维持风控降级状态",
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

        # 7. 兼容旧字段
        framework_compat = [d["text"] for d in directives]
        tactics_compat = {"regime": f"{regime_info['emoji']} Ⅲ级 {regime_info['cn']}" if regime == 3 else f"{regime_info['emoji']} {'Ⅰ' if regime==1 else 'Ⅱ' if regime==2 else 'Ⅲ' if regime==3 else 'Ⅳ' if regime==4 else 'Ⅴ'}级 {regime_info['cn']}"}
        scenarios_compat = [{"case": s["condition"], "action": s["action"]} for s in scenarios]

        return {
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

    # ========== 旧版降级: VIX 4阶查表 (无 aiae_ctx) ==========
    matrix = [
        {"id": "calm", "regime": "🟢 极度活跃", "vix_range": "< 15",
         "tactics": "进攻：主攻低位AI/算力", "pos": "85-100%", "active": v_val < 15},
        {"id": "normal", "regime": "🟡 常态回归", "vix_range": "15-25",
         "tactics": "稳健：20日线择时对焦", "pos": "60-85%", "active": 15 <= v_val < 25},
        {"id": "alert", "regime": "🔴 高度警觉", "vix_range": "25-35",
         "tactics": "防御：增配红利/低波", "pos": "35-60%", "active": 25 <= v_val < 35},
        {"id": "crisis", "regime": "🔴🔴 极端恐慌", "vix_range": "> 35",
         "tactics": "熔断：现金为王，观察", "pos": "10-35%", "active": v_val >= 35},
    ]
    curr = next((m for m in matrix if m['active']), matrix[1])
    if v_val < 25:
        framework = ["🔥 优先：适度加仓硬科技龙头", "💎 持有：算力/AI 核心资产", "📊 布局：科创50/创业板ETF"]
    elif v_val < 35:
        framework = ["🛡️ 优先：严格执行20日止损线", "🌊 避险：增配中字头红利", "⚖️ 调仓：卖出高波非核心标的"]
    else:
        framework = ["⚠️ 核心：战略防御，保留现金", "🥇 避险：关注黄金/避险资产", "🛑 熔断：拒绝一切左侧接盘"]
    scenarios = [{"case": "VIX<18", "action": "加仓科技主线"}, {"case": "VIX>30", "action": "降仓至50%以下"}]
    return {"regime_matrix": matrix, "current_tactics": curr, "framework": framework, "scenarios": scenarios}


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
