"""
Dashboard Module: 市场温度 + DMSO核心策略引擎
=============================================
包含:
  - A股得分维度 (Margin/Breadth/Turnover/ERP)
  - 港股得分维度 (HK ERP 引擎替代硬编码 · Issue #5)
  - PAT 恐慌修正温度
  - apply_strategy_filters 5策略过滤器 (Issue #15)
  - AIAE×ERP 联合仓位矩阵
"""

import tushare as ts
import numpy as np
from datetime import datetime, timedelta
from erp_timing_engine import get_erp_engine
from erp_hk_engine import get_hk_erp_engine
from aiae_engine import get_aiae_engine, REGIMES as AIAE_REGIMES


# ═══════════════════════════════════════════════════════════
#  DMSO 子引擎 (从 main.py 提取)
# ═══════════════════════════════════════════════════════════

def get_margin_risk_ratio(pro, date_str):
    """
    计算融资买入占比分位 (Margin Buying Ratio Percentile)
    权重: A股 25%
    """
    try:
        df = pro.margin_detail(trade_date=date_str)
        if df.empty:
            return 50.0
        df_index = pro.index_daily(ts_code='000001.SH', start_date=date_str, end_date=date_str)
        if df_index.empty: return 50.0
        total_margin_buy = df['rzmre'].sum()
        total_mkt_vol = df_index['amount'].iloc[0] * 1000
        ratio = total_margin_buy / total_mkt_vol if total_mkt_vol > 0 else 0
        percentile = min(100, max(0, (ratio - 0.07) / (0.12 - 0.07) * 100))
        return round(percentile, 1)
    except Exception as e:
        print(f"[Margin] 融资数据异常, 降级中性: {e}")
        return 50.0


def get_market_breadth(pro, date_str):
    """
    V11.0: 沪深300成分股高于250MA占比 (真实统计)
    权重: A股 20%
    """
    try:
        df_cons = pro.index_weight(index_code='399300.SZ', start_date=date_str, end_date=date_str)
        if df_cons is None or df_cons.empty:
            _start = (datetime.strptime(date_str, '%Y%m%d') - timedelta(days=30)).strftime('%Y%m%d')
            df_cons = pro.index_weight(index_code='399300.SZ', start_date=_start, end_date=date_str)
        if df_cons is None or df_cons.empty:
            print(f"[Breadth] 沪深300成分股数据缺失, 降级50.0")
            return 50.0
        codes = df_cons['con_code'].unique().tolist()

        above_count = 0
        valid_count = 0
        for code in codes[:50]:
            try:
                df_daily = ts.pro_bar(ts_code=code, adj='qfq', start_date=
                    (datetime.strptime(date_str, '%Y%m%d') - timedelta(days=400)).strftime('%Y%m%d'),
                    end_date=date_str)
                if df_daily is not None and len(df_daily) >= 250:
                    df_daily = df_daily.sort_values('trade_date')
                    ma250 = df_daily['close'].rolling(250).mean().iloc[-1]
                    close = df_daily['close'].iloc[-1]
                    valid_count += 1
                    if close > ma250:
                        above_count += 1
            except Exception:
                continue

        if valid_count < 10:
            print(f"[Breadth] 有效样本不足({valid_count}只), 降级50.0")
            return 50.0

        breadth = round(above_count / valid_count * 100, 1)
        print(f"[Breadth] 沪深300采样 {valid_count}只, 站上250MA: {above_count}只 ({breadth}%)")
        return breadth
    except Exception as e:
        print(f"[Breadth] 市场宽度计算异常, 降级中性: {e}")
        return 50.0


def get_real_turnover_score(pro, date_str):
    """
    V11.0: 全市场换手率分位分数 (替代原硬编码 55.0)
    """
    try:
        df = pro.daily(trade_date=date_str)
        if df is None or df.empty:
            return 50.0

        today_median_turnover = df['turnover_rate'].median()

        _end = date_str
        _start = (datetime.strptime(date_str, '%Y%m%d') - timedelta(days=35)).strftime('%Y%m%d')
        df_idx = pro.index_daily(ts_code='000001.SH', start_date=_start, end_date=_end)
        if df_idx is not None and len(df_idx) >= 10:
            df_idx = df_idx.sort_values('trade_date')
            vol_series = df_idx['vol'].tail(20)
            vol_mean = vol_series.mean()
            vol_std = vol_series.std() if vol_series.std() > 0 else 1
            latest_vol = vol_series.iloc[-1]
            z = (latest_vol - vol_mean) / vol_std
            score = min(100, max(0, 50 + z * 20))
        else:
            score = min(100, max(0, (today_median_turnover - 0.5) / 3.0 * 100))

        print(f"[Turnover] 当日换手率中位数: {today_median_turnover:.2f}% → score={score:.1f}")
        return round(score, 1)
    except Exception as e:
        print(f"[Turnover] 换手率计算异常, 降级中性: {e}")
        return 50.0


def get_real_erp_data():
    """
    V8.1: 从真实 ERP 引擎获取估值数据 (双维度标签修正版)
    返回 dict: erp_val, erp_z, valuation_label, erp_score, signal_key, signal_label
    """
    try:
        engine = get_erp_engine()
        report = engine.compute_signal()
        if report.get('status') in ('success', 'fallback'):
            snap = report['current_snapshot']
            sig = report['signal']
            erp_val = snap['erp_value']
            erp_pct = snap['erp_percentile']
            erp_z = (erp_pct - 50) / 25

            # --- V8.1 双维度标签逻辑 ---
            if erp_val >= 6.0:    abs_label, abs_tier = "极度低估", 5
            elif erp_val >= 5.0:  abs_label, abs_tier = "偏低估", 4
            elif erp_val >= 4.0:  abs_label, abs_tier = "估值中性", 3
            elif erp_val >= 3.0:  abs_label, abs_tier = "偏高估", 2
            else:                 abs_label, abs_tier = "极度高估", 1

            if erp_pct >= 80:     pct_label, pct_tier = "历史极低估", 5
            elif erp_pct >= 60:   pct_label, pct_tier = "分位偏低", 4
            elif erp_pct >= 40:   pct_label, pct_tier = "分位中性", 3
            elif erp_pct >= 20:   pct_label, pct_tier = "分位偏高", 2
            else:                 pct_label, pct_tier = "历史极高估", 1

            blended_tier = abs_tier * 0.6 + pct_tier * 0.4
            if blended_tier >= 4.2:    vlabel = "极度低估"
            elif blended_tier >= 3.4:  vlabel = "偏低估"
            elif blended_tier >= 2.6:  vlabel = "估值中性"
            elif blended_tier >= 1.8:  vlabel = "偏高估"
            else:                      vlabel = "极度高估"

            erp_score = min(100, max(0, erp_pct))
            print(f"[ERP Real] ERP={erp_val:.2f}% Pct={erp_pct:.1f}% AbsTier={abs_tier} PctTier={pct_tier} Blended={blended_tier:.1f} Label={vlabel} Signal={sig['label']}")
            return {
                'erp_val': round(erp_val, 2), 'erp_z': round(erp_z, 2),
                'erp_pct': round(erp_pct, 1), 'valuation_label': vlabel,
                'abs_label': abs_label, 'pct_label': pct_label,
                'erp_score': round(erp_score, 1), 'signal_key': sig['key'],
                'signal_label': sig['label'], 'composite_score': sig['score'],
                'status': 'success'
            }
    except Exception as e:
        print(f"[ERP Real] engine error, fallback: {e}")
    return {
        'erp_val': 4.5, 'erp_z': 0.0, 'erp_pct': 50.0,
        'valuation_label': 'fallback', 'abs_label': '降级', 'pct_label': '降级',
        'erp_score': 50.0,
        'signal_key': 'hold', 'signal_label': 'hold(fallback)',
        'composite_score': 50, 'status': 'fallback'
    }


def get_liquidity_crisis_signal(pro, today_str):
    """监控流动性危机：个股跌停占比 > 10%"""
    try:
        df = pro.daily(trade_date=today_str)
        if df.empty: return False
        limit_down = len(df[df['pct_chg'] <= -9.8])
        ratio = limit_down / len(df)
        return ratio > 0.10
    except Exception as e:
        print(f"[LiqCrisis] 跌停监控异常: {e}")
        return False


def get_ah_premium_adj(pro, date_str):
    """AH 溢价调节因子 (H股吸引力乘数)"""
    try:
        df = pro.index_daily(ts_code='HSAHP.HI', start_date='20240101', end_date=date_str)
        if df.empty: return 1.0
        latest_val = df.sort_values('trade_date').iloc[-1]['close']
        if latest_val > 145: return 1.15
        if latest_val < 125: return 0.85
        return 1.0
    except Exception as e:
        print(f"[AH Premium] 溢价数据异常: {e}")
        return 1.0


def get_hk_erp_score():
    """
    Issue #5: 用 HK ERP 引擎替换硬编码 hsi_pe_score = 65.0。
    调用 HKERPTimingEngine.compute_signal() 获取五维综合评分 (0-100)。
    引擎内部有 30min 内存缓存 + 磁盘缓存降级，不会造成重复 API 调用。
    """
    try:
        hk_engine = get_hk_erp_engine("HSI")
        hk_signal = hk_engine.compute_signal()
        if hk_signal.get("status") in ("success", "fallback"):
            score = hk_signal["signal"]["score"]
            print(f"[HK ERP] HSI score={score} (live)")
            return float(score)
    except Exception as e:
        print(f"[HK ERP] 降级到硬编码 65.0: {e}")
    return 65.0


# ═══════════════════════════════════════════════════════════
#  apply_strategy_filters V2.0 · 5策略过滤 (Issue #15)
# ═══════════════════════════════════════════════════════════

def apply_strategy_filters(regime_weights: dict, mom_crowding: float = 60.0,
                           div_yield_gap: float = 1.7, mr_atr_ratio: float = 1.0,
                           erp_signal: str = "hold", erp_score: float = 50.0,
                           aiae_regime: int = 3) -> tuple:
    """
    V2.0 策略级风险过滤器 — 支持 5 策略 (mr/div/mom/erp/aiae_etf)
    
    原有 3 个过滤器:
      - mom: 动量拥挤过滤 (换手率分位 > 80)
      - div: 红利溢价不足 (Yield Gap < 1.0%)
      - mr:  均值回归高波门控 (ATR > 1.5x)
    
    新增 2 个过滤器 (Issue #15):
      - erp: ERP信号矛盾 (signal=sell 且 score<35 → 权重×0.5)
      - aiae_etf: AIAE极端过热 (regime>=5 → 权重×0.3)
    
    返回: (调整后权重 dict, 过滤器状态 dict)
    """
    adjusted = dict(regime_weights)
    filters = {k: "正常" for k in adjusted}

    # ── 原有 3 个过滤器 ──

    # 动量拥挤过滤: 换手率分位 > 80 时逐步削减
    if "mom" in adjusted and mom_crowding > 80:
        penalty = min(0.5, (mom_crowding - 80) / 40)
        adjusted["mom"] *= (1 - penalty)
        filters["mom"] = f"⚠️ 拥挤 P{int(mom_crowding)}"

    # 红利溢价不足: Yield Gap < 1.0% 时削减
    if "div" in adjusted and div_yield_gap < 1.0:
        adjusted["div"] *= max(0.5, div_yield_gap / 1.0)
        filters["div"] = f"⚠️ 溢价不足 {div_yield_gap:.1f}%"

    # 均值回归高波门控: ATR > 1.5倍均值时削减
    if "mr" in adjusted and mr_atr_ratio > 1.5:
        adjusted["mr"] *= max(0.5, 1.5 / mr_atr_ratio)
        filters["mr"] = f"⚠️ 高波 ATR×{mr_atr_ratio:.1f}"

    # ── 新增: Issue #15 · 5策略扩展 ──

    # ERP 信号矛盾过滤: ERP 引擎发出 sell 且 score < 35 时削减
    if "erp" in adjusted and erp_signal == "sell" and erp_score < 35:
        adjusted["erp"] *= 0.5
        filters["erp"] = f"⚠️ 信号矛盾 score={erp_score:.0f}"

    # AIAE 极端过热过滤: Ⅴ级过热时大幅削减
    if "aiae_etf" in adjusted and aiae_regime >= 5:
        adjusted["aiae_etf"] *= 0.3
        filters["aiae_etf"] = f"⚠️ Ⅴ级过热 降权70%"

    # 归一化
    total = sum(adjusted.values())
    if total > 0:
        for k in adjusted:
            adjusted[k] = round(adjusted[k] / total, 2)

    return adjusted, filters


# ═══════════════════════════════════════════════════════════
#  compute_market_temperature — 核心合成函数
# ═══════════════════════════════════════════════════════════

def compute_market_temperature(pro, today_str, latest_vix, latest_cny, liquidity_score, z_s,
                               aiae_regime, aiae_cap, aiae_v1_value, aiae_regime_cn, aiae_report, vix_analysis):
    """
    计算市场温度 + AIAE×ERP联合仓位矩阵。
    
    返回 dict 包含:
      - total_temp, temp_label, pos_advice, base_temp
      - erp_data, erp_val, erp_z, valuation_label, erp_score
      - score_a, score_hk, hsi_pe_score
      - regime_weights, strategy_positions, strategy_filters
      - final_pos_val, regime_name, erp_tier
      - hub_result, vix_score, cny_score
      - is_circuit_breaker
    """
    # 温度初始化
    low_pe_score = 65.0
    vix_score = max(0, min(100, 100 - (latest_vix - 10) * 3))
    cny_score = max(0, min(100, 100 - (latest_cny - 7.0) * 100))

    # A股得分维度 (权重: 60%)
    margin_score = get_margin_risk_ratio(pro, today_str)
    breadth_score = get_market_breadth(pro, today_str)
    turnover_score = get_real_turnover_score(pro, today_str)

    # V8.0: 真实 ERP 引擎
    erp_data = get_real_erp_data()
    erp_val = erp_data['erp_val']
    erp_z = erp_data['erp_z']
    valuation_label = erp_data['valuation_label']
    erp_score = erp_data['erp_score']

    score_a = margin_score * 0.25 + turnover_score * 0.25 + erp_score * 0.30 + breadth_score * 0.20

    # ── 港股得分维度 (权重: 40%) ──
    # Issue #5: 用 HK ERP 引擎替换硬编码 65.0
    hsi_pe_score = get_hk_erp_score()
    epfr_proxy = 50 + (z_s * 10)
    sb_flow_score = min(100, max(0, 50 + z_s * 15))
    score_hk = hsi_pe_score * 0.40 + epfr_proxy * 0.30 + sb_flow_score * 0.30

    # AH 溢价调节 (±15%)
    ah_adj = get_ah_premium_adj(pro, today_str)
    score_hk = min(100, score_hk * ah_adj)

    # 流动性熔断
    is_circuit_breaker = get_liquidity_crisis_signal(pro, today_str)

    # 最终合成温度 + PAT
    base_temp = round(score_a * 0.6 + score_hk * 0.4, 1)
    vix_p = vix_analysis.get('percentile', 50)
    panic_adj = min(1.0, 1.25 - (vix_p / 100.0))
    total_temp = round(base_temp * panic_adj, 1)

    # AIAE×ERP 联合仓位矩阵
    try:
        _aiae_engine = get_aiae_engine()
        weights_5, erp_tier = _aiae_engine.get_run_all_weights(aiae_regime, erp_score)
    except Exception as e:
        print(f"[Dashboard Matrix Error] {e}")
        weights_5 = {"mr": 0.15, "div": 0.30, "mom": 0.10, "erp": 0.15, "aiae_etf": 0.30}
        erp_tier = "neutral"

    # 仓位决策
    if is_circuit_breaker:
        final_pos_val = min(aiae_cap, 10)
        status_label = "流动性熔断"
        pos_advice = "0% (流动性熔断)"
    else:
        final_pos_val = aiae_cap
        status_label = "过热" if aiae_regime >= 4 else ("偏冷" if aiae_regime <= 2 else "中性")
        aiae_regime_info = AIAE_REGIMES.get(aiae_regime, AIAE_REGIMES[3])
        pos_advice = f"{aiae_regime_info['emoji']} {aiae_regime_cn} (Cap {aiae_cap}%)"

    temp_label = f"{status_label} | {valuation_label}"
    regime_name_map = {1: "极度恐慌", 2: "低配置区", 3: "中性均衡", 4: "偏热区域", 5: "极度过热"}
    regime_name = regime_name_map.get(aiae_regime, "中性均衡")

    # ── Issue #15: apply_strategy_filters 5策略过滤 ──
    # 直接传 5 键 dict + erp/aiae 参数 (不再先提取3键再合并)
    filtered_weights, strategy_filters = apply_strategy_filters(
        weights_5,
        erp_signal=erp_data.get('signal_key', 'hold'),
        erp_score=erp_score,
        aiae_regime=aiae_regime,
    )
    regime_weights = filtered_weights

    # 各策略名义仓位 (5策略)
    strategy_positions = {
        "mr_pos":  round(final_pos_val * regime_weights.get("mr", 0), 1),
        "mom_pos": round(final_pos_val * regime_weights.get("mom", 0), 1),
        "div_pos": round(final_pos_val * regime_weights.get("div", 0), 1),
        "erp_pos": round(final_pos_val * regime_weights.get("erp", 0), 1),
        "aiae_pos": round(final_pos_val * regime_weights.get("aiae_etf", 0), 1),
        "total":   round(final_pos_val, 1)
    }

    # hub_result (V7.0)
    total_money_z = liquidity_score / 12.0 - 50/12.0  # 反推 (仅供 label 用)
    hub_result = {
        "composite_score": aiae_cap,
        "confidence": aiae_cap,
        "position": final_pos_val,
        "position_label": pos_advice,
        "factors": {
            "aiae_regime": {"score": round(max(10, 100 - (aiae_regime - 1) * 22.5), 1), "weight": 0.40, "label": aiae_regime_cn},
            "erp_value":   {"score": round(erp_score, 1), "weight": 0.25, "label": valuation_label},
            "vix_fear":    {"score": round(vix_score, 1), "weight": 0.15, "label": vix_analysis.get('label', '—')},
            "capital_flow": {"score": round(liquidity_score, 1), "weight": 0.10,
                             "label": "资金流" if liquidity_score > 56 else ("资金流出" if liquidity_score < 44 else "资金中性")},
            "macro_temp":  {"score": round(100 - total_temp, 1), "weight": 0.10, "label": status_label},
        },
        "signal_detail": {},  # 由调用方注入
    }

    return {
        "total_temp": total_temp,
        "temp_label": temp_label,
        "pos_advice": pos_advice,
        "base_temp": base_temp,
        "erp_data": erp_data,
        "erp_val": erp_val,
        "erp_z": erp_z,
        "valuation_label": valuation_label,
        "erp_score": erp_score,
        "erp_tier": erp_tier,
        "score_a": score_a,
        "score_hk": score_hk,
        "hsi_pe_score": hsi_pe_score,
        "regime_weights": regime_weights,
        "strategy_positions": strategy_positions,
        "strategy_filters": strategy_filters,
        "final_pos_val": final_pos_val,
        "regime_name": regime_name,
        "hub_result": hub_result,
        "vix_score": vix_score,
        "cny_score": cny_score,
        "is_circuit_breaker": is_circuit_breaker,
        "weights_5_raw": weights_5,
    }
