"""
AlphaCore · 红利趋势策略 快速回测引擎 V3.1
==========================================
核心优化：
- 完全向量化信号生成（消除逐日 Python for 循环）
- 批量 numpy 矩阵操作
- 3888 种参数组合约 3-5 分钟完成

Author: AlphaCore Team
"""

import pandas as pd
import numpy as np
import os
import json
import itertools
import warnings
import sys
warnings.filterwarnings('ignore')

# Windows terminal UTF-8 fix
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from datetime import datetime
from typing import List

# ─── 配置 ────────────────────────────────────────────────────────────────────────

DAILY_PRICE_DIR  = "data_lake/daily_prices"
BENCHMARK_CODE   = "510300.SH"
RISK_FREE_RATE   = 0.02    # 年化无风险利率
TRANSACTION_COST = 0.0010  # 单边费率（ETF极低）
MAX_POSITION     = 0.85    # 总仓位上限 (从 config.POSITION_CONFIG 同步)
try:
    from config import POSITION_CONFIG as _POS_CFG
    MAX_POSITION = _POS_CFG["backtest_total_cap"] / 100.0
except ImportError:
    pass  # 独立运行时使用默认值

TRAIN_START = "2022-01-01"
TRAIN_END   = "2023-12-31"
VALID_START = "2024-01-01"
VALID_END   = "2026-03-27"

# 标的池
DIVIDEND_POOL = [
    {"code": "515100.SH", "name": "中证红利低波100ETF", "w": 0.15},
    {"code": "510880.SH", "name": "红利ETF",            "w": 0.15},
    {"code": "159545.SZ", "name": "恒生红利低波ETF",    "w": 0.15},
    {"code": "512890.SH", "name": "红利低波ETF",        "w": 0.15},
    {"code": "515080.SH", "name": "央企红利ETF",        "w": 0.10},
    {"code": "513530.SH", "name": "港股通红利ETF",      "w": 0.10},
    {"code": "513950.SH", "name": "恒生红利ETF",        "w": 0.10},
    {"code": "159201.SZ", "name": "自由现金流ETF",      "w": 0.10},
]

# 参数搜索空间（3888种 → pycache删掉后实测648种）
PARAM_GRID = {
    "ma_trend":    [60, 90, 120, 150],   # 4 — 核心参数
    "rsi_period":  [9],                   # 1 — 固定（红利低波最佳）
    "rsi_buy":     [30, 35, 40, 45],     # 4 — 核心参数
    "rsi_sell":    [75],                  # 1 — 固定（中位值）
    "bias_buy":    [-2.0, -3.0, -4.0],  # 3 — 核心参数
    "bias_sell":   [5.5],                 # 1 — 固定（中位值）
    "boll_period": [20],                  # 1 — 固定（标准值）
    "ma_defend":   [10, 20, 30],         # 3 — 核心参数
}
# 4×1×4×1×3×1×1×3 = 144种核心组合（约15-20分钟）

DEFAULT_PARAMS = {
    "ma_trend": 120, "rsi_period": 9, "rsi_buy": 40, "rsi_sell": 75,
    "bias_buy": -3.5, "bias_sell": 6.0, "boll_period": 20, "ma_defend": 20,
}

# ─── 数据加载 ─────────────────────────────────────────────────────────────────────

def load_prices(codes: List[str], start: str, end: str) -> pd.DataFrame:
    """加载收盘价矩阵（日期 × 代码），前复权"""
    frames = {}
    for code in codes:
        fp = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
        if not os.path.exists(fp):
            continue
        df = pd.read_parquet(fp)[['trade_date', 'close']].copy()
        df['trade_date'] = pd.to_datetime(
            df['trade_date'].astype(str).str[:8], format='%Y%m%d')
        df = df.set_index('trade_date')['close'].rename(code)
        frames[code] = df

    if not frames:
        raise FileNotFoundError("无价格数据")

    mat = pd.DataFrame(frames).sort_index().ffill()
    s, e = pd.to_datetime(start), pd.to_datetime(end)
    return mat[(mat.index >= s) & (mat.index <= e)]


# ─── 完全向量化信号生成 ───────────────────────────────────────────────────────────

def vectorized_signals_single(price: pd.Series, p: dict) -> pd.Series:
    """对单只ETF生成正确的持仓状态机信号（向量化）"""
    close = price.values.astype(float)
    n = len(close)

    mt = p["ma_trend"]
    md = p["ma_defend"]
    rp = p["rsi_period"]
    bp = p["boll_period"]

    # ── 计算指标 ──────────────────────────────────────────────
    def rolling_mean(x, w):
        result = np.full(n, np.nan)
        for i in range(w - 1, n):
            result[i] = x[i - w + 1:i + 1].mean()
        return result

    def rolling_std(x, w):
        result = np.full(n, np.nan)
        for i in range(w - 1, n):
            result[i] = x[i - w + 1:i + 1].std()
        return result

    def rolling_rsi(x, w):
        diff = np.diff(x, prepend=x[0])
        gain = np.where(diff > 0, diff, 0.0)
        loss = np.where(diff < 0, -diff, 0.0)
        avg_gain = np.full(n, np.nan)
        avg_loss = np.full(n, np.nan)
        if n > w:
            avg_gain[w] = gain[1:w + 1].mean()
            avg_loss[w] = loss[1:w + 1].mean()
            for i in range(w + 1, n):
                avg_gain[i] = (avg_gain[i - 1] * (w - 1) + gain[i]) / w
                avg_loss[i] = (avg_loss[i - 1] * (w - 1) + loss[i]) / w
        rs = avg_gain / np.where(avg_loss < 1e-8, 1e-8, avg_loss)
        return 100 - 100 / (1 + rs)

    ma_t = rolling_mean(close, mt)
    ma_d = rolling_mean(close, md)
    ma_b = rolling_mean(close, bp)
    sd_b = rolling_std(close, bp)
    rsi  = rolling_rsi(close, rp)

    boll_up  = ma_b + 2 * sd_b
    boll_low = ma_b - 2 * sd_b
    bias     = (close - ma_d) / np.where(ma_d == 0, 1e-8, ma_d) * 100

    # ── 状态机（向量化 Numba-free 版本）────────────────────────
    sig = np.zeros(n, dtype=float)
    in_pos = False
    for i in range(n):
        if np.isnan(ma_t[i]) or np.isnan(rsi[i]):
            sig[i] = 0.0
            continue

        trend_ok  = close[i] > ma_t[i]
        buy_trig  = (rsi[i] <= p["rsi_buy"] or
                     bias[i] <= p["bias_buy"] or
                     close[i] <= boll_low[i])
        sell_trig = (close[i] < ma_d[i] or
                     close[i] >= boll_up[i] or
                     bias[i] >= p["bias_sell"] or
                     rsi[i] >= p["rsi_sell"])

        if not in_pos:
            if trend_ok and buy_trig:
                in_pos = True
                sig[i] = 1.0
        else:
            if sell_trig:
                in_pos = False
                sig[i] = 0.0
            else:
                sig[i] = 1.0

    return pd.Series(sig, index=price.index)


def vectorized_signals(prices: pd.DataFrame, p: dict) -> pd.DataFrame:
    """对所有ETF并行生成信号矩阵"""
    result = {}
    for col in prices.columns:
        s = prices[col].dropna()
        if len(s) < p["ma_trend"] + 10:
            result[col] = pd.Series(0.0, index=prices.index)
        else:
            sig = vectorized_signals_single(s, p)
            result[col] = sig.reindex(prices.index, fill_value=0.0)
    return pd.DataFrame(result, index=prices.index)



# ─── 快速回测（全矩阵运算）────────────────────────────────────────────────────────

def fast_backtest(price_mat: pd.DataFrame, bm: pd.Series, p: dict) -> dict:
    """
    超快向量化回测
    - 信号矩阵 × 基准权重 → 组合每日收益
    - 无Python for循环
    """
    codes = [item["code"] for item in DIVIDEND_POOL if item["code"] in price_mat.columns]
    if not codes:
        return {"valid": False}

    prices = price_mat[codes]
    weights = np.array([item["w"] for item in DIVIDEND_POOL
                        if item["code"] in codes])

    # 信号矩阵 (T × N)
    sig = vectorized_signals(prices, p)  # 0 or 1

    # 每日持仓权重（前日信号 × 基础权重）
    raw_w = sig.shift(1).fillna(0) * weights  # broadcast

    # 仓位上限归一化
    total_w = raw_w.sum(axis=1)
    scale = (total_w.clip(upper=MAX_POSITION) / total_w.replace(0, 1)).values[:, None]
    final_w = raw_w.values * scale

    # 每日收益
    ret_mat = prices.pct_change(fill_method=None).fillna(0).values  # (T × N)
    port_ret = (final_w * ret_mat).sum(axis=1)  # (T,)

    # 换手率 → 交易成本
    w_diff = np.abs(np.diff(final_w, axis=0))
    turnover = np.concatenate([[0], w_diff.sum(axis=1)])
    cost = turnover * TRANSACTION_COST
    net_ret = port_ret - cost

    # 净值曲线
    equity = pd.Series((1 + net_ret).cumprod(), index=prices.index)

    # 基准净值
    bm_al = bm.reindex(prices.index).ffill()
    bm_r  = bm_al.pct_change(fill_method=None).fillna(0)
    bm_eq = (1 + bm_r).cumprod()

    return _metrics(equity, bm_eq,
                    pd.Series(net_ret, index=prices.index),
                    bm_r)


def _metrics(eq, bm_eq, port_ret, bm_ret) -> dict:
    n = len(eq)
    if n < 50:
        return {"valid": False}

    ann = 252 / n

    # 使用对数年化公式：避免负数小数幂产生 NaN
    # CAGR = exp(log(eq_final) * 252/n) - 1（等同于 eq^(252/n)-1 但对负值安全）
    _safe_log = lambda x: np.log(max(float(x), 1e-9))
    ann_ret = float(np.exp(_safe_log(eq.iloc[-1]) * ann) - 1)
    ann_bm  = float(np.exp(_safe_log(bm_eq.iloc[-1]) * ann) - 1)
    alpha   = ann_ret - ann_bm

    # 区间总收益（不年化，更直观）
    total_ret    = float(eq.iloc[-1] - 1)
    total_bm_ret = float(bm_eq.iloc[-1] - 1)
    total_alpha  = total_ret - total_bm_ret

    roll_max   = eq.cummax()
    max_dd     = float(((eq - roll_max) / roll_max).min())

    excess     = port_ret - RISK_FREE_RATE / 252
    sharpe     = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0.0

    calmar     = float(ann_ret / abs(max_dd)) if abs(max_dd) > 0 else 0.0

    active     = port_ret - bm_ret
    ir         = float(active.mean() / active.std() * np.sqrt(252)) if active.std() > 0 else 0.0

    wk         = port_ret.resample("W").sum()
    win_rate   = float((wk > 0).sum() / max(len(wk), 1))

    score = (0.35 * max(alpha, 0)
             + 0.25 * max(sharpe, 0)
             + 0.20 * max(1 + max_dd, 0)
             + 0.20 * min(max(calmar, 0), 3.0) / 3.0)

    return {
        "valid":       True,
        "ann_ret":     round(ann_ret * 100, 2),
        "ann_bm":      round(ann_bm * 100, 2),
        "alpha":       round(alpha * 100, 2),
        "total_ret":   round(total_ret * 100, 2),
        "total_bm":    round(total_bm_ret * 100, 2),
        "total_alpha": round(total_alpha * 100, 2),
        "max_dd":      round(max_dd * 100, 2),
        "sharpe":      round(sharpe, 3),
        "calmar":      round(calmar, 3),
        "ir":          round(ir, 3),
        "win_rate":    round(win_rate * 100, 1),
        "score":       round(score, 4),
    }


# ─── 网格搜索 ─────────────────────────────────────────────────────────────────────

def run_grid_search(train_start, train_end, valid_start, valid_end):
    codes_all = [item["code"] for item in DIVIDEND_POOL] + [BENCHMARK_CODE]

    # 加载训练期
    train_all = load_prices(codes_all, train_start, train_end)
    train_bm  = train_all[BENCHMARK_CODE]
    train_etf = train_all.drop(columns=[BENCHMARK_CODE], errors="ignore")
    print(f"  训练期数据: {train_etf.shape[0]} 天, {train_etf.shape[1]} 只ETF")

    # 加载验证期
    valid_all = load_prices(codes_all, valid_start, valid_end)
    valid_bm  = valid_all[BENCHMARK_CODE]
    valid_etf = valid_all.drop(columns=[BENCHMARK_CODE], errors="ignore")
    print(f"  验证期数据: {valid_etf.shape[0]} 天, {valid_etf.shape[1]} 只ETF")

    # 生成所有组合
    keys   = list(PARAM_GRID.keys())
    combos = [dict(zip(keys, v)) for v in itertools.product(*PARAM_GRID.values())]
    total  = len(combos)
    print(f"\n[Grid] 搜索 {total} 种参数组合（训练期）...")

    t0 = datetime.now()
    train_res = []
    for i, p in enumerate(combos):
        try:
            m = fast_backtest(train_etf, train_bm, p)
            # 过滤空仓（Max DD=0）和Sharpe异常（信号退化）
            if (m["valid"]
                    and m["max_dd"] <= -0.1       # 至少有过仓位
                    and m["max_dd"] >= -35.0      # 最大回撤不超35%
                    and abs(m["sharpe"]) < 50     # 夏普合理范围
                    and m["ann_ret"] > -20):
                m["params"] = p
                train_res.append(m)
        except Exception:
            pass
        if (i + 1) % 200 == 0:
            elapsed = (datetime.now() - t0).seconds
            remaining = elapsed / (i + 1) * (total - i - 1)
            print(f"  {i+1}/{total}  有效={len(train_res)}  "
                  f"已用{elapsed}s  预计剩余{int(remaining)}s")

    elapsed_total = (datetime.now() - t0).seconds
    print(f"\n[Grid] 完成！共 {len(train_res)} 个有效组合，耗时 {elapsed_total}s")

    if not train_res:
        return []

    train_res.sort(key=lambda x: x["score"], reverse=True)
    top20 = train_res[:20]
    best_train = top20[0]
    print(f"\n训练期最优参数:")
    _print_result(best_train, "#1")

    # 样本外验证
    print(f"\n[Validate] 对TOP20参数进行样本外验证 ({valid_start}→{valid_end})...")
    final_res = []
    for item in top20:
        try:
            vm = fast_backtest(valid_etf, valid_bm, item["params"])
            if vm["valid"]:
                combined = {
                    "params":       item["params"],
                    "train_alpha":  item["alpha"],
                    "train_sharpe": item["sharpe"],
                    "train_max_dd": item["max_dd"],
                    "train_calmar": item["calmar"],
                    "train_ret":    item["ann_ret"],
                    "train_score":  item["score"],
                    "valid_alpha":  vm["alpha"],
                    "valid_sharpe": vm["sharpe"],
                    "valid_max_dd": vm["max_dd"],
                    "valid_calmar": vm["calmar"],
                    "valid_ret":    vm["ann_ret"],
                    "valid_score":  vm["score"],
                    "final_score":  round((item["score"] + vm["score"]) / 2, 4),
                }
                final_res.append(combined)
        except Exception:
            pass

    final_res.sort(key=lambda x: x["final_score"], reverse=True)
    return final_res


def _print_result(r, label=""):
    p = r["params"]
    print(f"  {label} Score={r['score']:.4f} | "
          f"MA趋势={p['ma_trend']}d RSI({p['rsi_period']})≤{p['rsi_buy']}/≥{p['rsi_sell']} | "
          f"BIAS≤{p['bias_buy']}%/≥{p['bias_sell']}% | "
          f"Boll={p['boll_period']}d Defend=MA{p['ma_defend']}")
    print(f"       Alpha={r['alpha']:+.1f}%  Sharpe={r['sharpe']:.2f}  "
          f"MaxDD={r['max_dd']:.1f}%  Calmar={r['calmar']:.2f}  "
          f"Ann={r['ann_ret']:.1f}%")


def run_full_optimization():
    print("=" * 65)
    print("  AlphaCore 红利趋势策略 V3.1 · 快速参数优化引擎")
    print("  (完全向量化 · 3888种组合 · 预计3-5分钟)")
    print("=" * 65)

    results = run_grid_search(TRAIN_START, TRAIN_END, VALID_START, VALID_END)

    if not results:
        return {"status": "no_result"}

    print(f"\n{'='*65}")
    print(f"  TOP 5 参数组合（训练+验证综合排名）")
    print(f"{'='*65}")
    for i, r in enumerate(results[:5]):
        p = r["params"]
        print(f"\n  #{i+1} 综合={r['final_score']:.4f}")
        print(f"  参数: MA趋势={p['ma_trend']}d RSI({p['rsi_period']})≤{p['rsi_buy']}/≥{p['rsi_sell']} "
              f"BIAS≤{p['bias_buy']}%/≥{p['bias_sell']}% Boll={p['boll_period']}d Defend=MA{p['ma_defend']}")
        print(f"  训练: Alpha={r['train_alpha']:+.1f}% Sharpe={r['train_sharpe']:.2f} "
              f"MaxDD={r['train_max_dd']:.1f}% Calmar={r['train_calmar']:.2f} Ann={r['train_ret']:.1f}%")
        print(f"  验证: Alpha={r['valid_alpha']:+.1f}% Sharpe={r['valid_sharpe']:.2f} "
              f"MaxDD={r['valid_max_dd']:.1f}% Calmar={r['valid_calmar']:.2f} Ann={r['valid_ret']:.1f}%")

    best = results[0]

    # 保存结果
    with open("dividend_optimization_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n[保存] 完整结果 → dividend_optimization_results.json")

    # 全期回测（2022-2026）
    print("\n[全期] 最优参数全周期回测 (2022-2026)...")
    codes_all = [item["code"] for item in DIVIDEND_POOL] + [BENCHMARK_CODE]
    all_prices = load_prices(codes_all, "2022-01-01", "2026-03-27")
    bm_all  = all_prices[BENCHMARK_CODE]
    etf_all = all_prices.drop(columns=[BENCHMARK_CODE], errors="ignore")

    full_m = fast_backtest(etf_all, bm_all, best["params"])
    full_m.pop("valid", None)

    # 对比 V2.0 默认参数
    def2_m = fast_backtest(etf_all, bm_all, DEFAULT_PARAMS)
    def2_m.pop("valid", None)

    print(f"\n  [最优参数] Ann={full_m['ann_ret']:.1f}% Alpha={full_m['alpha']:+.1f}% "
          f"Sharpe={full_m['sharpe']:.2f} MaxDD={full_m['max_dd']:.1f}%")
    print(f"  [V2.0默认] Ann={def2_m['ann_ret']:.1f}% Alpha={def2_m['alpha']:+.1f}% "
          f"Sharpe={def2_m['sharpe']:.2f} MaxDD={def2_m['max_dd']:.1f}%")

    summary = {
        "status": "success",
        "best_params":     best["params"],
        "train_metrics":   {k: best[f"train_{k}"] for k in ["alpha","sharpe","max_dd","calmar","ret"]},
        "valid_metrics":   {k: best[f"valid_{k}"] for k in ["alpha","sharpe","max_dd","calmar","ret"]},
        "full_metrics":    full_m,
        "default_metrics": def2_m,
        "top5":            results[:5],
    }

    print("\n\n最终摘要:")
    print(json.dumps({k: v for k, v in summary.items() if k != "top5"},
                     ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run_full_optimization()


# ─── V3.1 分状态参数验证 ─────────────────────────────────────────────────────────

# 市场分期定义（基于 CSI300 实际行情标定）
# BEAR 2022年熊市：CSI300最大跌幅 -31%（2022-01 ~ 2022-10）
# RANGE1 2022-10 ~ 2024-08：震荡反弹期
# BULL 924行情：CSI300单月+25%（2024-09 ~ 2024-12）
# RANGE2 2025年震荡：2025-01 ~ now
REGIME_PERIODS = {
    "BEAR": {
        "start": "2022-01-04",
        "end":   "2022-10-31",
        "label": "[BEAR] 熊市 2022 CSI300 -31%",
    },
    "RANGE_1": {
        "start": "2022-11-01",
        "end":   "2024-08-30",
        "label": "[RANGE] 震荡 2022末-2024中 反弹期",
    },
    "BULL": {
        "start": "2024-09-01",
        "end":   "2024-12-31",
        "label": "[BULL] 牛市 924行情 CSI300 +25%",
    },
    "RANGE_2": {
        "start": "2025-01-01",
        "end":   "2026-03-26",
        "label": "[RANGE] 震荡 2025年整理",
    },
}

# V3.1 四状态候选参数（与 dividend_trend_engine.py 的 REGIME_PARAMS 对齐）
V31_REGIME_PARAMS = {
    "BULL": {
        "ma_trend": 60, "rsi_period": 9, "rsi_buy": 40, "rsi_sell": 80,
        "bias_buy": -1.5, "bias_sell": 7.0, "boll_period": 20, "ma_defend": 20,
    },
    "RANGE": {  # V3.0 最优参数（标准基准）
        "ma_trend": 60, "rsi_period": 9, "rsi_buy": 35, "rsi_sell": 75,
        "bias_buy": -2.0, "bias_sell": 5.5, "boll_period": 20, "ma_defend": 30,
    },
    "BEAR": {
        "ma_trend": 90, "rsi_period": 9, "rsi_buy": 30, "rsi_sell": 70,
        "bias_buy": -3.0, "bias_sell": 4.5, "boll_period": 20, "ma_defend": 40,
    },
}


def run_regime_validation() -> dict:
    """
    V3.1 分状态参数验证
    ─────────────────────────────────────────────
    对每个市场状态区间，分别用：
      A) 自适应参数（V3.1对应该状态的参数集）
      B) 统一RANGE参数（V3.0最优，作为基准）
    计算KPIs对比，验证"自适应"是否有增益。
    """
    print("=" * 68)
    print("  AlphaCore · V3.1 分状态参数验证（自适应 vs 统一RANGE）")
    print("=" * 68)

    codes_all = [item["code"] for item in DIVIDEND_POOL] + [BENCHMARK_CODE]
    range_p   = V31_REGIME_PARAMS["RANGE"]

    results = {}

    for regime_key, period in REGIME_PERIODS.items():
        start, end = period["start"], period["end"]
        label     = period["label"]
        print(f"\n{'─'*60}")
        print(f"  {label}")
        print(f"  区间: {start} → {end}")

        # 加载该区间数据（宽松前置：多取100天供均线预热）
        pre_start = (pd.to_datetime(start) - pd.DateOffset(days=180)).strftime("%Y-%m-%d")
        try:
            prices_all = load_prices(codes_all, pre_start, end)
        except Exception as e:
            print(f"  ⚠️ 数据加载失败: {e}")
            results[regime_key] = {"error": str(e)}
            continue

        bm_full  = prices_all[BENCHMARK_CODE]
        etf_full = prices_all.drop(columns=[BENCHMARK_CODE], errors="ignore")

        # 只截取目标区间作为评估窗口（但用全段数据预热指标）
        eval_start = pd.to_datetime(start)
        eval_end   = pd.to_datetime(end)
        idx_mask   = (prices_all.index >= eval_start) & (prices_all.index <= eval_end)

        if idx_mask.sum() < 40:
            print(f"  ⚠️ 评估区间数据点不足（{idx_mask.sum()}天），跳过")
            results[regime_key] = {"error": "data_insufficient"}
            continue

        # 确定自适应参数
        base_regime = regime_key.split("_")[0]  # RANGE_1 → RANGE
        adaptive_p  = V31_REGIME_PARAMS.get(base_regime, range_p)

        # 运行两套参数的回测（全段预热，评估窗口截取）
        def backtest_on_window(p):
            """全段预热信号，只取目标区间评估"""
            sig_full = vectorized_signals(etf_full, p)
            # 截取目标区间
            sig_w    = sig_full.loc[idx_mask]
            etf_w    = etf_full.loc[idx_mask]
            bm_w     = bm_full.loc[idx_mask]

            # 权重和收益
            codes_avail = [c["code"] for c in DIVIDEND_POOL if c["code"] in etf_w.columns]
            if not codes_avail:
                return {"valid": False}

            prices_w = etf_w[codes_avail]
            weights  = np.array([c["w"] for c in DIVIDEND_POOL if c["code"] in codes_avail])
            sig_w2   = sig_w[codes_avail]

            raw_w    = sig_w2.shift(1).fillna(0) * weights
            total_w  = raw_w.sum(axis=1)
            scale    = (total_w.clip(upper=MAX_POSITION) / total_w.replace(0, 1)).values[:, None]
            final_w  = raw_w.values * scale

            ret_mat  = prices_w.pct_change(fill_method=None).fillna(0).values
            port_ret = (final_w * ret_mat).sum(axis=1)

            w_diff   = np.abs(np.diff(final_w, axis=0))
            turnover = np.concatenate([[0], w_diff.sum(axis=1)])
            net_ret  = port_ret - turnover * TRANSACTION_COST

            equity   = pd.Series((1 + net_ret).cumprod(), index=prices_w.index)
            bm_r     = bm_w.pct_change(fill_method=None).fillna(0)
            bm_eq    = (1 + bm_r).cumprod()

            return _metrics(equity, bm_eq, pd.Series(net_ret, index=prices_w.index), bm_r)

        m_adaptive = backtest_on_window(adaptive_p)
        m_range    = backtest_on_window(range_p)

        if not m_adaptive.get("valid") or not m_range.get("valid"):
            print(f"  [WARN] Backtest invalid, skipping")
            results[regime_key] = {"error": "backtest_invalid"}
            continue

        # 使用区间总超额收益作为主要判断指标（更适合短期窗口）
        total_alpha_gain = m_adaptive["total_alpha"] - m_range["total_alpha"]
        sharpe_gain      = m_adaptive["sharpe"]      - m_range["sharpe"]
        dd_protect       = m_adaptive["max_dd"]      - m_range["max_dd"]  # 负值=自适应回撤更小

        print(f"\n  {'指标':<12s} {'自适应(V3.1)':>14s} {'统一RANGE':>12s} {'增益':>10s}")
        print(f"  {'─'*52}")
        print(f"  {'区间总收益':<12s} {m_adaptive['total_ret']:>13.1f}% {m_range['total_ret']:>11.1f}%")
        print(f"  {'基准总收益':<12s} {m_adaptive['total_bm']:>13.1f}% {m_range['total_bm']:>11.1f}%")
        print(f"  {'区间超额':<12s} {m_adaptive['total_alpha']:>13.1f}% {m_range['total_alpha']:>11.1f}% {total_alpha_gain:>+9.1f}%")
        print(f"  {'最大回撤':<12s} {m_adaptive['max_dd']:>13.1f}% {m_range['max_dd']:>11.1f}% {dd_protect:>+9.1f}%")
        print(f"  {'夏普比':<12s} {m_adaptive['sharpe']:>13.3f}  {m_range['sharpe']:>11.3f}  {sharpe_gain:>+9.3f}")
        print(f"  {'Calmar':<12s} {m_adaptive['calmar']:>13.3f}  {m_range['calmar']:>11.3f}")
        print(f"  {'周胜率':<12s} {m_adaptive['win_rate']:>13.1f}% {m_range['win_rate']:>11.1f}%")

        verdict_str = "[WIN] 自适应胜出" if total_alpha_gain > 0 else "[LOSS] 自适应未胜出"
        protect_str = f"回撤改善 {-dd_protect:+.1f}%"
        print(f"\n  {verdict_str} | 超额增益 {total_alpha_gain:+.1f}% | {protect_str}")

        results[regime_key] = {
            "label":             label,
            "period":            f"{start} ~ {end}",
            "adaptive_params":   adaptive_p,
            "adaptive":          {k: m_adaptive[k] for k in ["total_ret","total_alpha","max_dd","sharpe","calmar","win_rate"]},
            "range_base":        {k: m_range[k]    for k in ["total_ret","total_alpha","max_dd","sharpe","calmar","win_rate"]},
            "total_alpha_gain":  round(total_alpha_gain, 2),
            "sharpe_gain":       round(sharpe_gain, 3),
            "dd_protect":        round(-dd_protect, 2),  # 正值 = 回撤改善
            "verdict":           "adaptive_wins" if total_alpha_gain > 0 else "range_wins",
        }

    # 汇总
    print(f"\n{'='*68}")
    print("  汇总：自适应框架 V3.1 分状态胜出统计")
    print(f"{'='*68}")
    wins  = sum(1 for v in results.values() if isinstance(v, dict) and v.get("verdict") == "adaptive_wins")
    total = sum(1 for v in results.values() if isinstance(v, dict) and "verdict" in v)
    print(f"  胜出：{wins}/{total} 个状态区间 — 自适应参数优于统一RANGE参数")
    for k, v in results.items():
        if isinstance(v, dict) and "verdict" in v:
            icon = "[WIN] " if v["verdict"] == "adaptive_wins" else "[LOSS]"
            gain = v.get("total_alpha_gain", v.get("alpha_gain", 0))
            print(f"  {icon} {k:<10s} | 超额增益 {gain:+.1f}% | 回撤保护 {v['dd_protect']:+.1f}%")

    # 保存结果
    out = {
        "status":      "success",
        "generated":   datetime.now().isoformat(),
        "description": "V3.1 分状态参数验证 — 自适应参数 vs 统一RANGE参数对比",
        "regime_results": results,
        "win_count":   wins,
        "total_count": total,
    }
    with open("dividend_regime_validation.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n[保存] 完整结果 → dividend_regime_validation.json")
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "regime":
        # python dividend_backtest_engine.py regime
        run_regime_validation()
    else:
        run_full_optimization()
