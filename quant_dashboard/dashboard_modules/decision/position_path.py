"""
AlphaCore · 仓位调整路径 & 执行成本估算
==========================================
从 decision_engine.py 拆分 (P2-A)

公开 API:
  - generate_position_path(snapshot, jcs_data, target_weights) → dict
  - estimate_execution_cost(code, order_value, current_price) → dict
  - estimate_position_path_costs(path_result) → dict
  - _POSITION_RULES: dict
"""

from services.logger import get_logger
from dashboard_modules.decision.jcs import compute_jcs
from dashboard_modules.decision.snapshot import _build_snapshot_from_cache

logger = get_logger("ac.decision.position_path")

# 仓位调整优先级规则
_POSITION_RULES = {
    "max_single_stock": 20,      # 单票仓位上限 (%)
    "max_single_sector": 40,     # 单板块仓位上限 (%)
    "min_holdings": 5,           # 最少持仓数
    "profit_take_threshold": 20,  # 浮盈超过此值 → 优先止盈
    "loss_cut_threshold": -8,    # 浮亏超过此值 → 优先止损
    "step_count": 3,             # 分 3 批执行
    "step_intervals": [0, 2, 5], # T / T+2 / T+5
}


def generate_position_path(snapshot: dict = None, jcs_data: dict = None,
                           target_weights: dict = None) -> dict:
    """根据当前持仓 + 决策中枢输出, 生成 3 步仓位调整路径。"""
    if snapshot is None:
        snapshot = _build_snapshot_from_cache()
    if jcs_data is None:
        jcs_data = compute_jcs(snapshot)

    jcs_level = jcs_data.get("level", "medium")
    jcs_score = jcs_data.get("score", 50)
    aiae_regime = snapshot.get("aiae_regime", 3)
    vix_val = snapshot.get("vix_val", 20)
    suggested_pos = snapshot.get("suggested_position", 55)

    # ── 读取实际持仓 ──
    positions = []
    data_source = "signal"
    total_asset = 0
    try:
        from portfolio_engine import get_portfolio_engine
        pe = get_portfolio_engine()
        val = pe.get_valuation()
        positions = val.get("positions", [])
        total_asset = val.get("total_asset", 0)
        if positions:
            data_source = "portfolio"
    except Exception as e:
        logger.debug("仓位路径: 持仓读取失败, 回退策略信号: %s", e)

    # ── 无持仓时的纯建议模式 ──
    if not positions:
        return {
            "current_cap": 0,
            "target_cap": suggested_pos,
            "gap": suggested_pos,
            "direction": "increase" if suggested_pos > 30 else "hold",
            "steps": [{
                "day": "T",
                "actions": [{
                    "code": "--", "name": "无实际持仓数据",
                    "action": "increase", "current_weight": 0,
                    "target_weight": suggested_pos, "delta": suggested_pos,
                    "reason": f"JCS={jcs_score:.0f} · AIAE R{aiae_regime} · 目标{suggested_pos}%"
                }],
                "step_cap": suggested_pos,
            }],
            "warnings": ["当前无持仓数据，无法生成精确路径。请导入持仓文件。"],
            "data_source": "signal",
        }

    # ── 有持仓: 计算当前风险暴露 ──
    current_cap = round(100 - val.get("cash_weight", 100), 1) if total_asset > 0 else 0
    target_cap = suggested_pos
    gap = round(target_cap - current_cap, 1)

    if abs(gap) < 3:
        direction = "hold"
    elif gap > 0:
        direction = "increase"
    else:
        direction = "decrease"

    # ── 对持仓打分排序 ──
    MAX_SINGLE = _POSITION_RULES["max_single_stock"]
    PROFIT_TAKE = _POSITION_RULES["profit_take_threshold"]
    LOSS_CUT = _POSITION_RULES["loss_cut_threshold"]

    scored = []
    for p in positions:
        w = p.get("weight", 0)
        pnl_pct = p.get("pnl_pct", 0)
        code = p.get("ts_code", "--")

        if target_weights and code in target_weights:
            tw = target_weights[code]
            deviation = abs(w - tw)
            score = deviation * 3
            reasons = [f"优化器目标 {tw:.1f}% (偏离 {w - tw:+.1f}%)"]
        else:
            score = 0
            reasons = []
            if w > MAX_SINGLE:
                score += (w - MAX_SINGLE) * 2
                reasons.append(f"超配>{MAX_SINGLE}%上限")
            elif w > MAX_SINGLE * 0.75:
                score += (w - MAX_SINGLE * 0.75)
                reasons.append(f"接近{MAX_SINGLE}%上限")
            if pnl_pct > PROFIT_TAKE:
                score += pnl_pct * 0.5
                reasons.append(f"浮盈+{pnl_pct:.0f}%建议止盈")
            elif pnl_pct < LOSS_CUT:
                if jcs_level == "low" or vix_val > 25:
                    score += abs(pnl_pct) * 0.8
                    reasons.append(f"浮亏{pnl_pct:.0f}% · JCS低/VIX高建议止损")
                else:
                    reasons.append(f"浮亏{pnl_pct:.0f}% · 信号尚可暂持")

        scored.append({
            "code": code, "name": p.get("name", "Unknown"),
            "industry": p.get("industry", "其他"), "weight": w, "pnl_pct": pnl_pct,
            "market_value": p.get("market_value", 0),
            "priority_score": round(score, 1), "reasons": reasons,
            "target_weight": target_weights.get(code) if target_weights else None,
        })

    scored.sort(key=lambda x: x["priority_score"], reverse=True)

    # ── 生成 3 步路径 ──
    STEPS = _POSITION_RULES["step_intervals"]
    total_gap = gap
    steps = []
    warnings = []

    emergency_mode = False
    if vix_val > 30:
        warnings.append(f"⚠️ VIX={vix_val:.1f}>30: 首步优先减仓防御")
        emergency_mode = True
    if jcs_level == "low":
        warnings.append(f"⚠️ JCS={jcs_score:.0f}<40: 仅执行减仓操作，禁止新开仓位")
        emergency_mode = True
    if aiae_regime >= 4:
        warnings.append(f"⚠️ AIAE R{aiae_regime}: 过热区间，全路径禁止加仓")

    if emergency_mode:
        step_ratios = [0.60, 0.25, 0.15]
    else:
        step_ratios = [0.40, 0.35, 0.25]

    live_weights = {s["code"]: s["weight"] for s in scored}
    MIN_REDUCE = 0.3
    MIN_WEIGHT = 0.5
    cumulative_delta = 0.0

    for step_i, day_offset in enumerate(STEPS):
        step_gap = round(total_gap * step_ratios[step_i], 1)
        if step_i == len(STEPS) - 1:
            step_gap = round(total_gap - cumulative_delta, 1)

        step_actions = []
        remaining = step_gap

        if remaining < -MIN_REDUCE:
            for s in scored:
                if remaining >= -0.1:
                    break
                lw = live_weights.get(s["code"], 0)
                if lw <= MIN_WEIGHT:
                    continue
                max_reduce = min(abs(remaining), lw * 0.5, 15)
                reduce_amt = round(min(max_reduce, lw - MIN_WEIGHT), 1)
                if reduce_amt < MIN_REDUCE:
                    continue
                new_weight = round(lw - reduce_amt, 1)
                step_actions.append({
                    "code": s["code"], "name": s["name"], "action": "reduce",
                    "current_weight": round(lw, 2), "target_weight": new_weight,
                    "delta": round(-reduce_amt, 1),
                    "reason": " · ".join(s["reasons"][:2]) or "仓位调整",
                })
                remaining += reduce_amt
                live_weights[s["code"]] = new_weight
        elif remaining > MIN_REDUCE:
            if jcs_level == "low" or aiae_regime >= 4:
                warnings.append(f"Step {step_i+1}: JCS低/AIAE过热，跳过加仓 (需增加{remaining:.1f}%)")
            else:
                low_weight_items = sorted(scored, key=lambda x: live_weights.get(x["code"], 0))
                for s in low_weight_items:
                    if remaining <= 0.1:
                        break
                    lw = live_weights.get(s["code"], 0)
                    if lw >= MAX_SINGLE * 0.8:
                        continue
                    add_amt = round(min(remaining, MAX_SINGLE - lw, 10), 1)
                    if add_amt < MIN_REDUCE:
                        continue
                    new_weight = round(lw + add_amt, 1)
                    step_actions.append({
                        "code": s["code"], "name": s["name"], "action": "increase",
                        "current_weight": round(lw, 2), "target_weight": new_weight,
                        "delta": round(add_amt, 1),
                        "reason": f"低配分散 · 权重{lw:.1f}%→{new_weight:.1f}%",
                    })
                    remaining -= add_amt
                    live_weights[s["code"]] = new_weight

        step_delta = sum(a["delta"] for a in step_actions)
        cumulative_delta += step_delta
        step_cap = round(current_cap + cumulative_delta, 1)

        if step_i == 0:
            if emergency_mode:
                note = "紧急防御优先"
            elif any(a.get("delta", 0) < -3 for a in step_actions):
                note = "首批减持"
            elif step_actions:
                note = "初步调仓"
            else:
                note = "观察等待"
        elif step_i == 1:
            note = "主力调仓"
        else:
            note = "精细校准"

        day_label = f"T+{day_offset}" if day_offset > 0 else "T"
        steps.append({
            "day": day_label, "interval_days": day_offset,
            "actions": step_actions, "step_cap": step_cap, "note": note,
        })

    delta_error = abs(cumulative_delta - total_gap)
    if delta_error > 1.0 and steps:
        warnings.append(f"⚠️ 路径缺口: 目标{total_gap:.1f}% 实际{cumulative_delta:.1f}% 差异{delta_error:.1f}%")

    return {
        "current_cap": current_cap, "target_cap": target_cap,
        "gap": gap, "direction": direction,
        "steps": steps, "warnings": warnings, "data_source": data_source,
    }


# ═══════════════════════════════════════════════════════════
#  执行成本估算 (Almgren-Chriss 简化)
# ═══════════════════════════════════════════════════════════

def _estimate_volatility(code: str) -> float:
    """从 parquet 日线估算年化波动率"""
    import os
    try:
        import pandas as pd
        fpath = f"data_lake/daily_prices/{code}.parquet"
        if not os.path.exists(fpath):
            return 0.25
        df = pd.read_parquet(fpath)
        if "close" not in df.columns or len(df) < 20:
            return 0.25
        returns = df["close"].pct_change().dropna().tail(60)
        daily_vol = float(returns.std())
        annual_vol = daily_vol * (252 ** 0.5)
        return round(min(annual_vol, 0.80), 3)
    except Exception:
        return 0.25


def _estimate_daily_volume(code: str, price: float) -> float:
    """从 parquet 日线估算日均成交额 (万元)"""
    import os
    try:
        import pandas as pd
        fpath = f"data_lake/daily_prices/{code}.parquet"
        if not os.path.exists(fpath):
            return price * 10000
        df = pd.read_parquet(fpath)
        if "vol" in df.columns:
            avg_vol = float(df["vol"].tail(60).mean())
            if avg_vol > 0:
                return round(avg_vol * price / 10000, 1)
        if "amount" in df.columns:
            avg_amt = float(df["amount"].tail(60).mean())
            if avg_amt > 0:
                return round(avg_amt / 10000, 1)
        return price * 5000
    except Exception:
        return price * 5000


def estimate_execution_cost(code: str, order_value: float,
                            current_price: float = None) -> dict:
    """Almgren-Chriss 简化冲击成本模型。"""
    vol = _estimate_volatility(code)
    dv = _estimate_daily_volume(code, current_price or 10.0)
    dv_value = dv * 10000

    if dv_value <= 0 or order_value <= 0:
        return {
            "impact_cost_pct": 0.05,
            "impact_cost_value": round(order_value * 0.0005, 2),
            "annual_vol": vol, "daily_volume_wan": dv,
            "liquidity_grade": "unknown", "recommended_window": "T+0 (当日)",
        }

    participation = order_value / dv_value
    daily_vol = vol / (252 ** 0.5)
    impact_pct = daily_vol * (participation ** 0.5) * 1.5 * 100

    if participation < 0.01:
        liquidity_grade = "🟢 极高流动性"
        recommended_window = "T+0 (当日)"
    elif participation < 0.05:
        liquidity_grade = "🟡 正常流动性"
        recommended_window = "T+0 (当日)"
    elif participation < 0.20:
        liquidity_grade = "🟠 一般流动性"
        recommended_window = "T+0~T+1 分批"
    else:
        liquidity_grade = "🔴 低流动性"
        recommended_window = "T+0~T+2 分批"

    return {
        "impact_cost_pct": round(min(impact_pct, 5.0), 3),
        "impact_cost_value": round(order_value * min(impact_pct, 5.0) / 100, 2),
        "annual_vol": vol, "daily_volume_wan": dv,
        "participation_pct": round(participation * 100, 2),
        "liquidity_grade": liquidity_grade,
        "recommended_window": recommended_window,
    }


def estimate_position_path_costs(path_result: dict) -> dict:
    """为仓位调整路径的每个操作追加执行成本估算。"""
    for step in path_result.get("steps", []):
        for action in step.get("actions", []):
            code = action.get("code", "")
            if not code or code == "--":
                action["execution_cost"] = None
                continue
            delta_pct = abs(action.get("delta", 0))
            mv = action.get("market_value", 0)
            order_value = mv * (delta_pct / 100) if mv > 0 else 50000
            try:
                cost = estimate_execution_cost(code, order_value)
                action["execution_cost"] = cost
            except Exception:
                action["execution_cost"] = None
    return path_result
