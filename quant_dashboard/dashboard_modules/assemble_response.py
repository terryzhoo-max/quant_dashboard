"""
Dashboard Module: 最终 JSON 响应组装
=====================================
将各子模块的计算结果组装为 /api/v1/dashboard-data 的完整响应。
"""

from datetime import datetime
from aiae_engine import REGIMES as AIAE_REGIMES

# V3.0: 前端阈值从参数中心读取 (消除硬编码漂移)
try:
    from erp_params import FRONTEND_ERP_BULLISH as _ERP_BULLISH_THRESH
    from erp_params import FRONTEND_ERP_BEARISH as _ERP_BEARISH_THRESH
except ImportError:
    _ERP_BULLISH_THRESH = 5.0
    _ERP_BEARISH_THRESH = 3.5


# ===== V10.0: 五策略加权共振系统 =====
# 设计理念: 宏观定方向，微观定强度 — 分层加权连续评分
_SIGNAL_WEIGHTS = {
    'aiae': 0.30,   # L1 宏观锚: 全市场配置温度 (与 JCS 32.5% 对齐)
    'erp':  0.25,   # L1 宏观锚: 股债溢价估值中枢 (与 JCS 22.5% 对齐)
    'div':  0.15,   # L2 情绪层: 红利趋势防御指标
    'mr':   0.15,   # L3 执行层: 个股均值回归选股信号
    'mom':  0.15,   # L3 执行层: 行业轮动动量信号
}

def _compute_signal_strength(mr_overview, mom_overview, div_overview, erp_z, aiae_regime):
    """V10.0: 五策略方向强度量化器
    每个策略输出连续强度 [-1.0, +1.0]:
      +1.0 = 极度看多, -1.0 = 极度看空, 0 = 中性

    方向约定: strength > 0 = 看多, < 0 = 看空, = 0 中性
    所有输入 None-safe: 降级时默认中性 (0.0)
    """
    strengths = {}

    # 1. AIAE (regime 线性映射: R1=+1.0 极看多, R3=0 中性, R5=-1.0 极看空)
    _regime = max(1, min(5, aiae_regime or 3))  # None → R3 中性, 越界裁剪
    strengths['aiae'] = round(-(_regime - 3) / 2.0, 3)

    # 2. ERP (Z-Score: Z>0=ERP高于均值=股票便宜=看多=正强度, ±1.5 裁剪)
    _erp_z = erp_z if erp_z is not None else 0.0  # None → 中性
    strengths['erp'] = round(max(-1.0, min(1.0, _erp_z / 1.5)), 3)

    # 3. 红利防线 (趋势向上数: 8/8=+1.0, 4/8=0, 0/8=-1.0)
    _trend_up = div_overview.get('trend_up_count') if div_overview else None
    _trend_up = _trend_up if _trend_up is not None else 4  # None → 中性
    strengths['div'] = round(max(-1.0, min(1.0, (_trend_up - 4) / 4.0)), 3)

    # 4. 均值回归 (买卖信号比 → [-1, +1])
    _sc = mr_overview.get('signal_count', {}) if mr_overview else {}
    mr_buy = _sc.get('buy', 0) or 0
    mr_sell = _sc.get('sell', 0) or 0
    total_mr = mr_buy + mr_sell
    if total_mr == 0:
        strengths['mr'] = 0.0
    else:
        strengths['mr'] = round((mr_buy - mr_sell) / total_mr, 3)

    # 5. 动量轮动 (买入信号 + 动量强度)
    _buy_count = (mom_overview.get('buy_count', 0) or 0) if mom_overview else 0
    _avg_mom = (mom_overview.get('avg_momentum', 0) or 0) if mom_overview else 0
    if _buy_count > 0 and _avg_mom > 0:
        strengths['mom'] = round(min(1.0, _avg_mom / 10.0), 3)  # 10%动量=满强度
    elif _buy_count > 0:
        strengths['mom'] = 0.3  # 有信号但弱
    else:
        # 深度负动量时允许看空, 但限幅 -0.5 (动量非主导策略)
        strengths['mom'] = round(max(-0.5, _avg_mom / 10.0), 3) if _avg_mom < -2 else 0.0

    return strengths


def _compute_weighted_consensus(strengths):
    """V10.0: 加权多空得分 [-100, +100]
    正 = 看多, 负 = 看空, 0 = 中性

    五档标签 (带迟滞):
      >= +30  强势共振 (强多)
      >= +15  偏多共振
      >  -15  中性均衡
      >  -30  偏空共振
      <= -30  强势看空
    """
    # 加权求和
    score = sum(strengths.get(k, 0) * _SIGNAL_WEIGHTS[k] for k in _SIGNAL_WEIGHTS)
    score_pct = round(score * 100, 1)

    # 方向标签 (五档, 含宏观锚校验)
    # 机构原则: "强势"标签需要宏观锚(AIAE)确认, AIAE 中性时标签上限为"偏多/偏空"
    aiae_s = strengths.get('aiae', 0)
    macro_confirmed = abs(aiae_s) > 0.1  # AIAE 非中性 = 宏观方向已确认

    if score_pct >= 30 and macro_confirmed:
        label = "强势共振"
    elif score_pct >= 15:
        label = "偏多共振"
    elif score_pct > -15:
        label = "中性均衡"
    elif score_pct > -30:
        label = "偏空共振"
    elif macro_confirmed:  # score <= -30 且宏观确认
        label = "强势看空"
    else:
        label = "偏空共振"  # 宏观中性时降级: 不允许仅凭微观信号定义"强势"

    # 方向简码
    if score_pct >= 15:     direction = "bull"
    elif score_pct > -15:   direction = "neutral"
    else:                   direction = "bear"

    # 置信度 (机构级: 加权方向一致性, 非简单计票)
    #   - high: 权重加权多数方 ≥ 70% (允许少数低权重反对)
    #   - low:  活跃信号 ≤ 1 (数据不足)
    #   - medium: 其余
    signs = {k: (1 if s > 0.1 else (-1 if s < -0.1 else 0)) for k, s in strengths.items()}
    bull_weight = sum(_SIGNAL_WEIGHTS.get(k, 0) for k, s in signs.items() if s == 1)
    bear_weight = sum(_SIGNAL_WEIGHTS.get(k, 0) for k, s in signs.items() if s == -1)
    active_count = sum(1 for s in signs.values() if s != 0)
    majority_weight = round(max(bull_weight, bear_weight), 4)  # 避免浮点精度 (0.30+0.15=0.449...)

    if active_count <= 1:
        confidence = "low"
    elif majority_weight >= 0.70:  # 70%+ 权重同向 = 高置信
        confidence = "high"
    elif majority_weight >= 0.45:  # 45-70% = 中置信
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "score": score_pct,
        "label": label,
        "direction": direction,
        "confidence": confidence,
        "bull_count": sum(1 for s in strengths.values() if s > 0.1),
        "bear_count": sum(1 for s in strengths.values() if s < -0.1),
        "neutral_count": sum(1 for s in strengths.values() if -0.1 <= s <= 0.1),
    }


def _compute_signal_consensus(mr_overview, mom_overview, div_overview, erp_z, aiae_regime):
    """五策略共振计算器 V10.0
    同时运行新旧逻辑:
      - legacy: 等权计票 (V9.0 向后兼容)
      - v10: 加权连续评分 (V10.0 新逻辑)
    返回: (ups, downs, consensus_str, label, directions, v10_result)
    """
    mr_buy = mr_overview.get('signal_count', {}).get('buy', 0)
    mr_sell = mr_overview.get('signal_count', {}).get('sell', 0)

    # === Legacy V9.0 计票 (保留兼容) ===
    directions = [
        'up' if mr_buy > mr_sell else ('down' if mr_sell > mr_buy else 'neutral'),
        'up' if mom_overview.get('buy_count', 0) > 0 else 'neutral',
        'up' if div_overview.get('trend_up_count', 0) >= 4 else ('down' if div_overview.get('trend_up_count', 0) <= 2 else 'neutral'),
        'up' if erp_z > 0.5 else ('down' if erp_z < -0.5 else 'neutral'),
        'up' if aiae_regime <= 2 else ('down' if aiae_regime >= 4 else 'neutral'),
    ]
    ups = sum(1 for d in directions if d == 'up')
    downs = sum(1 for d in directions if d == 'down')

    # === V10.0 加权共振 ===
    strengths = _compute_signal_strength(mr_overview, mom_overview, div_overview, erp_z, aiae_regime)
    v10 = _compute_weighted_consensus(strengths)

    # V10.0 主导: 标签和摘要从 v10 取值
    _sign = '+' if v10['score'] >= 0 else ''
    consensus_str = f"{_sign}{v10['score']}"
    label = v10["label"]

    # v10 结果附带完整数据 (供前端渲染)
    v10["strengths"] = strengths
    v10["legacy"] = {"ups": ups, "downs": downs}

    return ups, downs, consensus_str, label, directions, v10


def assemble_dashboard_response(
    # 宏观数据
    latest_vix, vix_change, vix_status, vix_analysis,
    # 资金流
    capital_a, capital_h, total_money_z,
    # 温度数据
    temp_data,
    # 策略结果
    mr_res, div_res, mom_res,
    # AIAE 数据
    aiae_regime, aiae_cap, aiae_v1_value, aiae_regime_cn, aiae_report,
    # 行业热力图
    sector_heatmap,
    # 辅助函数引用
    get_tomorrow_plan_fn, get_position_path_fn, get_institutional_mindset_fn,
    # 时间
    liquidity_score,
):
    """组装完整的 dashboard-data API 响应"""

    # 解包温度数据
    total_temp = temp_data["total_temp"]
    temp_label = temp_data["temp_label"]
    pos_advice = temp_data["pos_advice"]
    erp_data = temp_data["erp_data"]
    erp_val = temp_data["erp_val"]
    erp_z = temp_data["erp_z"]
    valuation_label = temp_data["valuation_label"]
    erp_score = temp_data["erp_score"]
    erp_tier = temp_data["erp_tier"]
    score_a = temp_data["score_a"]
    score_hk = temp_data["score_hk"]
    regime_weights = temp_data["regime_weights"]
    strategy_positions = temp_data["strategy_positions"]
    strategy_filters = temp_data["strategy_filters"]
    final_pos_val = temp_data["final_pos_val"]
    regime_name = temp_data["regime_name"]
    hub_result = temp_data["hub_result"]

    # 解析策略信号
    mr_overview = mr_res.get("data", {}).get("market_overview", {})
    mom_overview = mom_res.get("data", {}).get("market_overview", {})
    div_overview = div_res.get("data", {}).get("market_overview", {})

    # 策略卡片
    mr_status = {
        "status_text": f"发现 {mr_overview.get('signal_count', {}).get('buy', 0)} 只猎物",
        "status_class": "active" if mr_overview.get('signal_count', {}).get('buy', 0) > 0 else "dormant",
        "metric1": f"{mr_overview.get('above_3pct', 0)}只偏离",
        "metric2": f"{mr_overview.get('total_suggested_position', 0)}% 建议"
    }
    mom_status = {
        "status_text": f"动能主线: {mom_overview.get('top1_name', '---')}",
        "status_class": "active" if mom_overview.get('buy_count', 0) > 0 else "warning",
        "metric1": f"{mom_overview.get('avg_momentum', 0)}% 均动量",
        "metric2": f"满仓位:{mom_overview.get('position_cap', 0)}%"
    }
    div_status = {
        "status_text": f"趋势向上: {div_overview.get('trend_up_count', 0)}/8",
        "status_class": "active" if div_overview.get('trend_up_count', 0) >= 4 else "dormant",
        "metric1": f"买入信号: {div_overview.get('buy_count', 0)}",
        "metric2": f"建议 {div_overview.get('total_suggested_pos', 0)}%"
    }
    erp_status = {
        "status_text": f"ERP {valuation_label}",
        "status_class": "active" if erp_z > 0.5 else ("warning" if erp_z < -0.5 else "dormant"),
        "metric1": f"ERP {round(erp_val, 2)}%",
        "metric2": f"Z-Score {round(erp_z, 2)}"
    }
    aiae_regime_info = AIAE_REGIMES.get(aiae_regime, AIAE_REGIMES[3])
    aiae_status = {
        "status_text": f"{aiae_regime_info['emoji']} {aiae_regime_cn}",
        "status_class": "active" if aiae_regime <= 2 else ("warning" if aiae_regime >= 4 else "dormant"),
        "metric1": f"AIAE {round(aiae_v1_value, 1)}%",
        "metric2": f"Cap {aiae_cap}%"
    }

    # 买入/卖出区
    vetted_buy = []
    for s in mr_res.get("data", {}).get("buy_signals", [])[:2]:
        vetted_buy.append({"name": s.get('name', ''), "code": s.get('ts_code', s.get('code', '')),
                           "score": s.get('signal_score', s.get('score', 0)),
                           "pe": round(s.get('close', 0) / max(s.get('ma20', 1), 0.01), 2),
                           "badge": "均值回归", "badgeClass": "buy"})
    for s in mom_res.get("data", {}).get("buy_signals", [])[:1]:
        vetted_buy.append({"name": s.get('name', ''), "code": s.get('ts_code', s.get('code', '')),
                           "score": s.get('signal_score', 85),
                           "metric": f"动量:{s.get('momentum_pct', 0)}%",
                           "badge": "动量爆发", "badgeClass": "buy"})

    vetted_sell = []
    for s in mr_res.get("data", {}).get("sell_signals", [])[:2]:
        vetted_sell.append({"name": s.get('name', ''), "code": s.get('ts_code', s.get('code', '')),
                            "score": s.get('signal_score', s.get('score', 0)),
                            "pe": "超买", "badge": "偏离过大", "badgeClass": "sell"})

    # hub_result signal_detail 注入
    hub_result["signal_detail"] = {
        "buy_total": mr_overview.get('signal_count', {}).get('buy', 0) + mom_overview.get('buy_count', 0) + div_overview.get('buy_count', 0),
        "sell_total": mr_overview.get('signal_count', {}).get('sell', 0),
        "mr_buy": mr_overview.get('signal_count', {}).get('buy', 0),
        "mr_sell": mr_overview.get('signal_count', {}).get('sell', 0),
        "mom_buy": mom_overview.get('buy_count', 0),
        "div_buy": div_overview.get('buy_count', 0),
        "div_trend_up": div_overview.get('trend_up_count', 0),
    }

    # 共振
    _sig_consensus = _compute_signal_consensus(mr_overview, mom_overview, div_overview, erp_z, aiae_regime)

    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "macro_cards": {
                "vix": {
                    "value": round(latest_vix, 2),
                    "trend": f"{round(vix_change, 1)}%",
                    "status": vix_status,
                    "regime": vix_analysis["label"],
                    "class": vix_analysis["class"],
                    "desc": vix_analysis.get("desc", ""),
                    "percentile": vix_analysis.get("percentile", 0)
                },
                "tomorrow_plan": get_tomorrow_plan_fn(vix_analysis, total_temp, {
                    "regime": aiae_regime,
                    "regime_cn": aiae_regime_cn,
                    "regime_info": AIAE_REGIMES.get(aiae_regime, AIAE_REGIMES[3]),
                    "cap": aiae_cap,
                    "aiae_v1": round(aiae_v1_value, 1),
                    "slope": aiae_report.get("current", {}).get("slope", {}).get("slope", 0),
                    "slope_direction": aiae_report.get("current", {}).get("slope", {}).get("direction", "flat"),
                    "erp_val": round(erp_val, 2),
                    "erp_label": valuation_label,
                    "erp_tier": erp_tier,
                    "margin_heat": aiae_report.get("current", {}).get("margin_heat", 2.0),
                    "fund_position": aiae_report.get("current", {}).get("fund_position", 80),
                }),
                "capital_a": capital_a,
                "capital_h": capital_h,
                "signal": {
                    "strategies": [
                        {
                            "key": "mr", "icon": "📐", "name": "均值回归",
                            "signal": f"{mr_overview.get('signal_count', {}).get('buy', 0)}买/{mr_overview.get('signal_count', {}).get('sell', 0)}卖",
                            "metric": f"偏离{mr_overview.get('above_3pct', 0)}只",
                            "direction": "up" if mr_overview.get('signal_count', {}).get('buy', 0) > mr_overview.get('signal_count', {}).get('sell', 0)
                                else ("down" if mr_overview.get('signal_count', {}).get('sell', 0) > mr_overview.get('signal_count', {}).get('buy', 0) else "neutral"),
                            "strength": _sig_consensus[5]["strengths"].get("mr", 0),
                            "weight": _SIGNAL_WEIGHTS["mr"],
                        },
                        {
                            "key": "mom", "icon": "🚀", "name": "动量轮动",
                            "signal": mom_overview.get('top1_name', '—'),
                            "metric": f"动量{mom_overview.get('avg_momentum', 0)}%",
                            "direction": "up" if mom_overview.get('buy_count', 0) > 0 else "neutral",
                            "strength": _sig_consensus[5]["strengths"].get("mom", 0),
                            "weight": _SIGNAL_WEIGHTS["mom"],
                        },
                        {
                            "key": "div", "icon": "🛡️", "name": "红利防线",
                            "signal": f"{div_overview.get('trend_up_count', 0)}/8趋势",
                            "metric": f"买入{div_overview.get('buy_count', 0)}只",
                            "direction": "up" if div_overview.get('trend_up_count', 0) >= 4 else ("down" if div_overview.get('trend_up_count', 0) <= 2 else "neutral"),
                            "strength": _sig_consensus[5]["strengths"].get("div", 0),
                            "weight": _SIGNAL_WEIGHTS["div"],
                        },
                        {
                            "key": "erp", "icon": "🌐", "name": "ERP择时",
                            "signal": valuation_label,
                            "metric": f"{round(erp_val, 2)}%",
                            "direction": "up" if erp_z > 0.5 else ("down" if erp_z < -0.5 else "neutral"),
                            "strength": _sig_consensus[5]["strengths"].get("erp", 0),
                            "weight": _SIGNAL_WEIGHTS["erp"],
                        },
                        {
                            "key": "aiae", "icon": "🌡️", "name": "AIAE管控",
                            "signal": aiae_regime_cn,
                            "metric": f"Cap{aiae_cap}%",
                            "direction": "up" if aiae_regime <= 2 else ("down" if aiae_regime >= 4 else "neutral"),
                            "strength": _sig_consensus[5]["strengths"].get("aiae", 0),
                            "weight": _SIGNAL_WEIGHTS["aiae"],
                        },
                    ],
                    "consensus": _sig_consensus[2],
                    "consensus_label": _sig_consensus[3],
                    "status": "up" if _sig_consensus[0] >= 2 else "neutral",
                    "value": f"MR {mr_overview.get('signal_count', {}).get('buy', 0)}买/{mr_overview.get('signal_count', {}).get('sell', 0)}卖 · ERP {valuation_label}",
                    "trend": f"DT {div_overview.get('trend_up_count', 0)}/8趋 · AIAE {aiae_regime_cn} · MOM {mom_overview.get('top1_name', '—')}",
                    # V10.0: 加权共振评分
                    "v10_score": _sig_consensus[5]["score"],
                    "v10_label": _sig_consensus[5]["label"],
                    "v10_direction": _sig_consensus[5]["direction"],
                    "v10_confidence": _sig_consensus[5]["confidence"],
                    "v10_bull_count": _sig_consensus[5]["bull_count"],
                    "v10_bear_count": _sig_consensus[5]["bear_count"],
                    "v10_neutral_count": _sig_consensus[5]["neutral_count"],
                    "v10_legacy": _sig_consensus[5].get("legacy", {}),
                },
                "regime_banner": {
                    "regime": regime_name,
                    "temp": total_temp,
                    "advice": pos_advice,
                    "vix": round(latest_vix, 2),
                    "vix_label": vix_analysis.get('label', '—'),
                    "z_capital": round(total_money_z, 2),
                    "aiae_regime": aiae_regime,
                    "aiae_regime_cn": aiae_regime_cn,
                    "aiae_cap": aiae_cap,
                    "aiae_v1": round(aiae_v1_value, 1)
                },
                "aiae_thermometer": _build_aiae_thermometer(aiae_report, aiae_v1_value, aiae_regime, aiae_regime_cn, aiae_cap),
                "market_temp": {
                    "value": total_temp,
                    "label": temp_label,
                    "advice": pos_advice,
                    "advice_tier": aiae_regime,
                    "score_a": int(score_a),
                    "score_hk": int(score_hk),
                    "erp_z": erp_z,
                    "regime_name": regime_name,
                    "regime_weights": regime_weights,
                    "strategy_positions": strategy_positions,
                    "market_vix_multiplier": vix_analysis["multiplier"],
                    "strategy_filters": strategy_filters,
                    "pos_path": get_position_path_fn(final_pos_val, vix_analysis),
                    "mindset": get_institutional_mindset_fn(total_temp),
                    "holding_cycle_a": "5-8 个交易日",
                    "holding_cycle_hk": "15-22 个交易日",
                    "hub_factors": {**hub_result["factors"], "aiae_temp": {"score": round(max(10, 100 - (aiae_regime - 1) * 22.5), 1), "weight": 0.15, "label": aiae_regime_cn}},
                    "hub_confidence": hub_result["confidence"],
                    "hub_composite": hub_result["composite_score"],
                    "hub_signal_detail": hub_result["signal_detail"],
                    "z_capital": round(total_money_z, 2),
                    "degraded_modules": temp_data.get("degraded_modules", []),
                },
                "erp": {
                    "value": f"{round(erp_val, 2)}%",
                    "trend": valuation_label,
                    "desc": f"{erp_data.get('abs_label', '')} · 4Y分位{erp_data.get('erp_pct', '--')}%",
                    "status": "up" if erp_z > 0.5 else ("down" if erp_z < -0.5 else "neutral"),
                    "erp_pct": erp_data.get('erp_pct', 50),
                    "signal_label": erp_data.get('signal_label', '--'),
                    # V3.0: 前端阈值透传 (消除 script.js 硬编码漂移)
                    "erp_thresholds": {
                        "bullish": _ERP_BULLISH_THRESH,
                        "bearish": _ERP_BEARISH_THRESH,
                        "source": "erp_params_v3"
                    }
                }
            },
            "sector_heatmap": sector_heatmap,
            "strategy_status": {"mr": mr_status, "mom": mom_status, "div": div_status, "erp": erp_status, "aiae": aiae_status},
            "execution_lists": {"buy_zone": vetted_buy, "danger_zone": vetted_sell}
        }
    }


def _build_aiae_thermometer(aiae_report, aiae_v1_value, aiae_regime, aiae_regime_cn, aiae_cap):
    """构建 AIAE 温度计数据"""
    import aiae_params as AP
    is_v5 = getattr(AP, 'V5_ENABLED', False)
    fallback_thresholds = list(AP.V5_REGIME_THRESHOLDS) if is_v5 else list(AP.REGIME_THRESHOLDS)
    fallback_mode = "V5_simple" if is_v5 else "V3_composite"

    if aiae_report:
        r = aiae_report
        curr = r.get("current", {})
        basis_val = curr.get("regime_basis_value", curr.get("aiae_v1", aiae_v1_value))
        return {
            "aiae_v1": basis_val,
            "regime": curr.get("regime", aiae_regime),
            "regime_cn": curr.get("regime_info", {}).get("cn", aiae_regime_cn),
            "regime_emoji": curr.get("regime_info", {}).get("emoji", "🟡"),
            "regime_color": curr.get("regime_info", {}).get("color", "#eab308"),
            "regime_name": curr.get("regime_info", {}).get("name", "Regime III"),
            "cap": r.get("position", {}).get("matrix_position", aiae_cap),
            "slope": curr.get("slope", {}).get("slope", 0),
            "slope_direction": curr.get("slope", {}).get("direction", "flat"),
            "margin_heat": curr.get("margin_heat", 0),
            "fund_position": curr.get("fund_position", 0),
            "aiae_simple": curr.get("aiae_simple", 0),
            "erp_value": r.get("position", {}).get("erp_value", 0),
            "status": r.get("status", "fallback"),
            # V5 dynamic metadata
            "regime_basis_value": basis_val,
            "regime_thresholds": curr.get("regime_thresholds", fallback_thresholds),
            "regime_mode": curr.get("regime_mode", fallback_mode),
        }
    return {
        "aiae_v1": aiae_v1_value, "regime": aiae_regime, "regime_cn": aiae_regime_cn,
        "regime_emoji": "🟡", "regime_color": "#eab308", "regime_name": "Regime III",
        "cap": aiae_cap, "slope": 0, "slope_direction": "flat",
        "margin_heat": 0, "fund_position": 0, "aiae_simple": 0,
        "erp_value": 0, "status": "fallback",
        # V5 dynamic metadata
        "regime_basis_value": aiae_v1_value,
        "regime_thresholds": fallback_thresholds,
        "regime_mode": fallback_mode,
    }
