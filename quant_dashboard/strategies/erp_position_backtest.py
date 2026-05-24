"""
AlphaCore · ERP 仓位管理回测 V1.0
==================================
与生产引擎六级信号完全对齐的仓位比例回测。

核心区别 (vs 二分法回测):
  - 二分法: composite ≥ 55 → 全仓买入, ≤ 40 → 全仓卖出
  - 仓位管理: composite → 六级仓位映射, 按日调仓

信号 → 仓位映射 (对齐 erp_timing_engine SIGNAL_MAP):
  strong_buy (≥80 + 共振): 80-100%  → 取 90%
  buy        (≥70):         60-80%   → 取 70%
  hold       (≥55):         50-70%   → 取 60%
  reduce     (≥40):         30-50%   → 取 40%
  underweight(≥25):         10-30%   → 取 20%
  cash       (<25):         0-10%    → 取 5%

调仓规则:
  - 仓位变化 > 5% 才执行调仓 (避免微调产生的交易成本)
  - 调仓频率: 日频 (每天重新计算 composite → 目标仓位)
  - 交易成本: 单边 0.1% (含冲击成本)
"""

import pandas as pd
import numpy as np
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import erp_params


# ═══════════════════════════════════════════════════════════════
#  仓位映射 (V3.4 O13: 连续化)
# ═══════════════════════════════════════════════════════════════

# V3.3 阶梯映射 (保留, 用于对比测试)
def _score_to_position_step(score: float) -> float:
    """旧版阶梯映射 — V3.3 基线"""
    T = erp_params.SIGNAL_THRESHOLDS
    if score >= T["strong_buy"]:
        return 0.90
    elif score >= T["buy"]:
        return 0.70
    elif score >= T["hold"]:
        return 0.60
    elif score >= T["reduce"]:
        return 0.40
    elif score >= T["underweight"]:
        return 0.20
    else:
        return 0.05


def _score_to_position(score: float) -> float:
    """V3.4 O13: 连续仓位映射 — 分段线性插值, 消除阈值跳变

    锚点与 SIGNAL_THRESHOLDS 完全对齐 (阈值处仓位不变):
      Score  0 → 5%,  25 → 20%,  40 → 40%,  55 → 60%,
            70 → 70%, 80 → 90%, 100 → 95%

    阈值之间: 线性插值 (平滑过渡)
    """
    T = erp_params.SIGNAL_THRESHOLDS
    anchors = [
        (0,                  0.05),
        (T["underweight"],   0.15),  # 25 → 15% (压低, 原 20%)
        (T["reduce"],        0.35),  # 40 → 35% (压低, 原 40%)
        (T["hold"],          0.55),  # 55 → 55% (压低, 原 60%)
        (T["buy"],           0.70),  # 70 → 70% (不变)
        (T["strong_buy"],    0.90),  # 80 → 90% (不变)
        (100,                0.95),
    ]
    score = max(0.0, min(100.0, score))
    for i in range(len(anchors) - 1):
        s0, p0 = anchors[i]
        s1, p1 = anchors[i + 1]
        if score <= s1:
            t = (score - s0) / (s1 - s0) if s1 > s0 else 0
            return round(p0 + t * (p1 - p0), 4)
    return anchors[-1][1]


# 确保导入 strategies/ 目录下的模块 (而非根目录 shim)
import importlib
_sb_spec = importlib.util.spec_from_file_location(
    "strategies_backtest",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategies_backtest.py")
)
_sb_mod = importlib.util.module_from_spec(_sb_spec)
_sb_spec.loader.exec_module(_sb_mod)

_score_d1_erp_abs_vec = _sb_mod._score_d1_erp_abs_vec
_score_d2_erp_pct_vec = _sb_mod._score_d2_erp_pct_vec
_score_d3_m1_vec = _sb_mod._score_d3_m1_vec
_score_d4_vol_vec = _sb_mod._score_d4_vol_vec
_score_d5_credit_vec = _sb_mod._score_d5_credit_vec


def compute_composite_series(
    macro_df: pd.DataFrame,
    dates: pd.DatetimeIndex,
    erp_window: int = None,
    w_erp_abs: float = None,
    w_erp_pct: float = None,
    w_m1: float = None,
    w_vol: float = None,
    w_credit: float = None,
) -> pd.Series:
    """
    计算日频 Composite Score 序列 (V3 Sigmoid, 对齐生产引擎)

    返回: pd.Series, 索引=dates, 值=composite score [0-100]
    """
    from erp_params import OPTIMIZER_DEFAULTS as _D
    if erp_window is None: erp_window = _D["erp_window"]
    if w_erp_abs is None:  w_erp_abs  = _D["w_erp_abs"]
    if w_erp_pct is None:  w_erp_pct  = _D["w_erp_pct"]
    if w_m1 is None:       w_m1       = _D["w_m1"]
    if w_vol is None:      w_vol      = _D["w_vol"]
    if w_credit is None:   w_credit   = _D["w_credit"]

    # 对齐宏观数据到 ETF 交易日
    m = macro_df.copy()
    if 'trade_date' in m.columns:
        m['trade_date'] = pd.to_datetime(m['trade_date'])
        m = m.set_index('trade_date')
    m = m.sort_index()
    aligned = m.reindex(dates, method='ffill').ffill().bfill()

    # 五维评分
    d1 = _score_d1_erp_abs_vec(aligned['erp'])
    d2 = _score_d2_erp_pct_vec(aligned['erp'], window=erp_window)
    d3 = _score_d3_m1_vec(aligned['m1_yoy'])
    d4 = _score_d4_vol_vec(aligned['pe_vol'])
    d5 = _score_d5_credit_vec(aligned['scissor'], aligned['m1_yoy'])

    # 加权融合
    composite = (d1 * w_erp_abs + d2 * w_erp_pct + d3 * w_m1 +
                 d4 * w_vol + d5 * w_credit)

    # V3.3 O12: 市场势能修正 (对齐引擎 _trend_modifier)
    if erp_params.O12_ENABLED and 'pe_ttm' in aligned.columns:
        import math
        window = erp_params.O12_TREND_WINDOW
        pe_ma = aligned['pe_ttm'].rolling(window, min_periods=window).mean()
        deviation = (aligned['pe_ttm'] - pe_ma) / pe_ma

        k = erp_params.O12_K
        penalty_max = abs(erp_params.O12_PENALTY_MAX)
        bonus_max = erp_params.O12_BONUS_MAX
        cap = erp_params.O12_CAP

        def _o12_mod(dev):
            if pd.isna(dev):
                return 0.0
            if dev < 0:
                sv = 2.0 / (1.0 + math.exp(k * dev * 100)) - 1.0
                m = -penalty_max * sv
                m = max(erp_params.O12_PENALTY_MAX, m)
            else:
                sv = 2.0 / (1.0 + math.exp(-k * dev * 100)) - 1.0
                m = bonus_max * sv
                m = min(bonus_max, m)
            return max(-cap, min(cap, m))

        o12_mod = deviation.apply(_o12_mod)
        composite = (composite + o12_mod).clip(0, 100)

    # V3.4 O15: 右侧确认 (对齐引擎 _momentum_confirmation)
    if erp_params.O15_ENABLED and 'pe_ttm' in aligned.columns:
        window = erp_params.O15_MOMENTUM_WINDOW
        inv_pe = 1.0 / aligned['pe_ttm']
        momentum = inv_pe / inv_pe.shift(window) - 1.0

        def _o15_mod(mom):
            if pd.isna(mom):
                return 0.0
            if mom < erp_params.O15_PENALTY_THRESHOLD:
                return max(-erp_params.O15_CAP, erp_params.O15_PENALTY)
            elif mom > erp_params.O15_BONUS_THRESHOLD:
                return min(erp_params.O15_CAP, erp_params.O15_BONUS)
            return 0.0

        o15_mod = momentum.apply(_o15_mod)
        composite = (composite + o15_mod).clip(0, 100)

    return composite


# ═══════════════════════════════════════════════════════════════
#  仓位管理回测引擎
# ═══════════════════════════════════════════════════════════════

def run_position_backtest(
    df: pd.DataFrame,
    composite_scores: pd.Series,
    initial_cash: float = 1000000.0,
    rebalance_threshold: float = 0.10,
    cost_per_trade: float = 0.001,
    risk_free_rate: float = 0.02,
    turnover_series: pd.Series = None,
) -> dict:
    """
    仓位管理回测 — 日频调仓

    参数:
        df: ETF 价格 DataFrame (需含 close 列, DatetimeIndex)
        composite_scores: 日频 composite score 序列
        initial_cash: 初始资金
        rebalance_threshold: 调仓触发阈值 (仓位变化 > 此值才调仓)
        cost_per_trade: 单边交易成本 (含冲击)
        risk_free_rate: 年化无风险利率 (默认 2%, 用于 Sharpe 计算)
        turnover_series: 日频换手率序列 (O17, 可选)

    返回: dict 含 metrics / daily_positions / trade_log
    """
    close = df['close'].values
    dates = df.index
    n = len(close)

    # 索引对齐: 确保 composite_scores 与 df 按日期对齐
    if hasattr(composite_scores, 'index') and not composite_scores.index.equals(df.index):
        composite_scores = composite_scores.reindex(df.index, method='ffill').fillna(50.0)

    # 初始化
    cash = initial_cash
    shares = 0.0
    portfolio_values = np.zeros(n)
    positions = np.zeros(n)          # 实际权益仓位比例
    target_positions = np.zeros(n)   # 目标仓位
    trade_log = []
    total_cost = 0.0
    peak_value = initial_cash        # O14: 组合高水位
    dd_cap_active = False            # O14: 回撤限制是否激活

    # V3.4 O16: 预计算价格均线 (避免循环内重复计算)
    ma_short = np.full(n, np.nan)
    ma_long = np.full(n, np.nan)
    if erp_params.O16_ENABLED:
        ws = erp_params.O16_MA_SHORT
        wl = erp_params.O16_MA_LONG
        close_series = pd.Series(close)
        ma_short = close_series.rolling(ws, min_periods=ws).mean().values
        ma_long = close_series.rolling(wl, min_periods=wl).mean().values

    # V3.4 O17: 预计算换手率 z-score
    tr_zscore = np.zeros(n)
    if erp_params.O17_ENABLED and turnover_series is not None:
        tr_aligned = turnover_series.reindex(dates, method='ffill')
        tr_mean = tr_aligned.rolling(erp_params.O17_VOL_WINDOW, min_periods=20).mean()
        tr_std = tr_aligned.rolling(erp_params.O17_VOL_WINDOW, min_periods=20).std().replace(0, 1)
        tr_zscore = ((tr_aligned - tr_mean) / tr_std).fillna(0).values

    for i in range(n):
        price = close[i]
        date = dates[i]

        # 当前组合市值
        equity = shares * price
        total_value = cash + equity
        current_pos = equity / total_value if total_value > 0 else 0

        # 目标仓位
        score = composite_scores.iloc[i] if i < len(composite_scores) else 50.0
        target_pos = _score_to_position(score)

        # V3.4 O14: 回撤抑制器 — 组合级仓位硬上限
        if erp_params.O14_ENABLED:
            peak_value = max(peak_value, total_value)
            current_dd = (total_value - peak_value) / peak_value if peak_value > 0 else 0

            if current_dd < erp_params.O14_DD_THRESHOLD_2:
                target_pos = min(target_pos, erp_params.O14_POS_CAP_2)
                dd_cap_active = True
            elif current_dd < erp_params.O14_DD_THRESHOLD_1:
                target_pos = min(target_pos, erp_params.O14_POS_CAP_1)
                dd_cap_active = True
            elif dd_cap_active:
                # 恢复判断: 回撤恢复超过 RECOVERY_RATIO 后解除
                recovery = 1.0 - (peak_value - total_value) / (peak_value * abs(erp_params.O14_DD_THRESHOLD_1))
                if recovery >= erp_params.O14_RECOVERY_RATIO:
                    dd_cap_active = False

        # V3.4 O16: 价格趋势门控 + 交叉确认
        if erp_params.O16_ENABLED and not np.isnan(ma_short[i]):
            if not np.isnan(ma_long[i]) and price < ma_short[i] and price < ma_long[i]:
                # 双均线空头 + Score×Price 交叉确认
                if score >= erp_params.O16_CROSS_CONFIRM_THRESH:
                    # 估值说"便宜" → 放松 cap (信任估值但留余地)
                    target_pos = min(target_pos, erp_params.O16_RELAX_CAP)
                else:
                    target_pos = min(target_pos, erp_params.O16_POS_CAP_BOTH)
            elif price < ma_short[i]:
                # 短期弱势: close < MA60 → 限仓
                target_pos = min(target_pos, erp_params.O16_POS_CAP_SHORT)
            else:
                # V3.4 O17: 价格在 MA60 上方 + 高换手 → 牛市高确信度加码
                if erp_params.O17_ENABLED and tr_zscore[i] > erp_params.O17_ZSCORE_THRESH:
                    target_pos = min(target_pos + erp_params.O17_BOOST, 0.95)

        target_positions[i] = target_pos

        # 调仓判断: 仓位偏离 > 阈值
        pos_diff = target_pos - current_pos
        if abs(pos_diff) > rebalance_threshold:
            target_equity = total_value * target_pos
            delta_equity = target_equity - equity

            if delta_equity > 0:
                # 买入: 需要花费 delta_equity 买股票 + cost 交易成本
                cost = abs(delta_equity) * cost_per_trade
                total_spend = delta_equity + cost   # 总支出 = 目标增量 + 成本
                if total_spend <= cash and price > 0:
                    new_shares = delta_equity / price  # 买到的股票价值 = delta_equity
                    shares += new_shares
                    cash -= total_spend
                    total_cost += cost
                    trade_log.append({
                        "date": str(date.date()) if hasattr(date, 'date') else str(date),
                        "action": "buy",
                        "score": round(float(score), 1),
                        "target_pos": round(target_pos, 2),
                        "prev_pos": round(current_pos, 2),
                        "shares": round(new_shares, 2),
                        "price": round(price, 3),
                        "cost": round(cost, 2),
                    })
            else:
                # 卖出
                sell_shares = min(shares, abs(delta_equity) / price) if price > 0 else 0
                sell_value = sell_shares * price
                cost = sell_value * cost_per_trade
                cash += sell_value - cost
                shares -= sell_shares
                total_cost += cost
                trade_log.append({
                    "date": str(date.date()) if hasattr(date, 'date') else str(date),
                    "action": "sell",
                    "score": round(float(score), 1),
                    "target_pos": round(target_pos, 2),
                    "prev_pos": round(current_pos, 2),
                    "shares": round(sell_shares, 2),
                    "price": round(price, 3),
                    "cost": round(cost, 2),
                })

        # 记录
        equity = shares * price
        total_value = cash + equity
        portfolio_values[i] = total_value
        positions[i] = (equity / total_value) if total_value > 0 else 0

    # ─── 计算指标 ───
    returns = pd.Series(portfolio_values).pct_change().dropna()
    bench_returns = pd.Series(close).pct_change().dropna()

    # 年化收益
    total_return = (portfolio_values[-1] / initial_cash) - 1
    years = n / 252
    ann_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    # 基准年化
    bench_total = (close[-1] / close[0]) - 1
    bench_ann = (1 + bench_total) ** (1 / years) - 1 if years > 0 else 0

    # Alpha
    alpha = ann_return - bench_ann

    # Sharpe (年化, 扣除无风险利率)
    rf_daily = (1 + risk_free_rate) ** (1/252) - 1
    if len(returns) > 0 and returns.std() > 0:
        excess_returns = returns - rf_daily
        sharpe = (excess_returns.mean() * 252) / (returns.std() * np.sqrt(252))
    else:
        sharpe = 0

    # 最大回撤
    cummax = pd.Series(portfolio_values).cummax()
    drawdown = (pd.Series(portfolio_values) - cummax) / cummax
    max_dd = drawdown.min()

    # Calmar
    calmar = ann_return / abs(max_dd) if max_dd != 0 else 0

    # 平均仓位
    avg_position = float(np.mean(positions))

    # 评级 (简化)
    grade_score = 0
    if sharpe > 1.5: grade_score += 30
    elif sharpe > 1.0: grade_score += 25
    elif sharpe > 0.5: grade_score += 15
    elif sharpe > 0: grade_score += 10

    if max_dd > -0.10: grade_score += 25
    elif max_dd > -0.15: grade_score += 20
    elif max_dd > -0.20: grade_score += 15
    elif max_dd > -0.30: grade_score += 5

    if alpha > 0.05: grade_score += 25
    elif alpha > 0.02: grade_score += 20
    elif alpha > 0: grade_score += 15
    elif alpha > -0.02: grade_score += 10

    if len(trade_log) >= 5: grade_score += 10
    elif len(trade_log) >= 2: grade_score += 5

    if grade_score >= 80: grade = "A+"
    elif grade_score >= 70: grade = "A"
    elif grade_score >= 60: grade = "B+"
    elif grade_score >= 50: grade = "B"
    elif grade_score >= 40: grade = "C"
    elif grade_score >= 30: grade = "D"
    else: grade = "F"

    return {
        "metrics": {
            "total_return": round(total_return, 4),
            "annualized_return": round(ann_return, 4),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown": round(float(max_dd), 4),
            "calmar_ratio": round(calmar, 3),
            "alpha": round(alpha, 4),
            "total_trades": len(trade_log),
            "total_cost": round(total_cost, 2),
            "avg_position": round(avg_position, 3),
            "bench_total_return": round(bench_total, 4),
            "bench_ann_return": round(bench_ann, 4),
        },
        "grade": {
            "grade": grade,
            "score": grade_score,
        },
        "daily": {
            "portfolio_values": portfolio_values.tolist(),
            "positions": positions.tolist(),
            "target_positions": target_positions.tolist(),
        },
        "trade_log": trade_log,
    }


# ═══════════════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time, json

    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    from erp_backtest_data import prepare_erp_backtest_data
    from backtest_engine import AlphaBacktester

    print("=" * 70)
    print("  AlphaCore ERP 仓位管理回测 V1.0")
    print(f"  参数版本: {erp_params.VERSION}")
    print(f"  评分公式: {erp_params.SCORING_VERSION}")
    print("=" * 70)

    ETF_CODE = "510300.SH"
    IS_START, IS_END = "20180101", "20231231"
    OOS_START, OOS_END = "20240101", "20251231"
    MACRO_PRE = "20150101"

    # 数据
    print("\n📦 加载数据...")
    t0 = time.time()
    macro_df = prepare_erp_backtest_data(MACRO_PRE, OOS_END)
    bt = AlphaBacktester(initial_cash=1000000.0)
    df_full = bt.fetch_tushare_data(ETF_CODE, IS_START, OOS_END)
    if df_full.empty:
        print("❌ ETF数据拉取失败!")
        sys.exit(1)

    is_end_ts = pd.Timestamp(IS_END)
    os_start_ts = pd.Timestamp(OOS_START)
    df_in = df_full[df_full.index <= is_end_ts].copy()
    df_out = df_full[df_full.index >= os_start_ts].copy()

    print(f"   IS: {len(df_in)}天 | OOS: {len(df_out)}天 ({time.time()-t0:.0f}s)")

    for label, df_period, period_name in [
        ("IS", df_in, f"{IS_START}→{IS_END}"),
        ("OOS", df_out, f"{OOS_START}→{OOS_END}"),
    ]:
        print(f"\n{'═'*70}")
        print(f"  {label}: {period_name}")
        print(f"{'═'*70}")

        # 计算 composite 序列
        scores = compute_composite_series(macro_df, df_period.index)

        # 运行仓位管理回测
        result = run_position_backtest(df_period, scores)
        m = result["metrics"]
        g = result["grade"]

        print(f"  年化收益:   {m['annualized_return']*100:>7.2f}%")
        print(f"  基准年化:   {m['bench_ann_return']*100:>7.2f}%")
        print(f"  Alpha:      {m['alpha']*100:>7.2f}%")
        print(f"  Sharpe:     {m['sharpe_ratio']:>7.3f}")
        print(f"  最大回撤:   {m['max_drawdown']*100:>7.2f}%")
        print(f"  Calmar:     {m['calmar_ratio']:>7.3f}")
        print(f"  调仓次数:   {m['total_trades']:>7d}")
        print(f"  交易成本:   {m['total_cost']:>7.0f}")
        print(f"  平均仓位:   {m['avg_position']*100:>7.1f}%")
        print(f"  评级:       {g['grade']} ({g['score']}分)")

        # 打印最近5次调仓
        if result["trade_log"]:
            print(f"\n  最近调仓记录 (共{len(result['trade_log'])}次):")
            for t in result["trade_log"][-5:]:
                print(f"    {t['date']} {t['action']:>4} Score={t['score']:>5.1f} "
                      f"仓位 {t['prev_pos']*100:.0f}%→{t['target_pos']*100:.0f}% "
                      f"成本 ¥{t['cost']:.0f}")

    # 保存
    out_file = os.path.join("data_lake", "erp_v32_position_backtest.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"version": erp_params.VERSION, "timestamp": str(pd.Timestamp.now())},
                  f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  💾 结果: {out_file}")
    print(f"  ⏱️ 总耗时: {time.time()-t0:.0f}s")
    print("=" * 70)
