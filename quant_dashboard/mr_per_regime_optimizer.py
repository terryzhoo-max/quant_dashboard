"""
AlphaCore · 均值回归 V4.0 三态专属参数优化器
==============================================
核心设计：每种市场状态（BEAR/RANGE/BULL）单独做参数搜索，
          每态只使用该态历史数据训练，防止信号互相污染。

输出：mr_per_regime_params.json（按 Regime 存储最优参数）
运行：python mr_per_regime_optimizer.py
"""

import pandas as pd
import numpy as np
import os, json, itertools, warnings, sys, time
from datetime import datetime
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')

DAILY_PRICE_DIR = "data_lake/daily_prices"
BENCHMARK_CODE  = "510300.SH"
RISK_FREE_RATE  = 0.02
TRANSACTION_COST = 0.0010
OUTPUT_FILE     = "mr_per_regime_params.json"

# ─── 三态历史数据段（训练/验证按时段切） ─────────────────────────────────────
# 每段都要足够长：≥120个交易日
REGIME_PERIODS = {
    "BEAR": {
        "train": ("2022-01-01", "2022-09-30"),   # 单边熊市（CSI300 -21%）
        "valid": ("2022-10-01", "2022-12-31"),   # 熊市末段（超跌反弹）
        "desc": "熊市·大幅下跌期",
    },
    "RANGE": {
        "train": ("2023-01-01", "2023-09-30"),   # 震荡修复
        "valid": ("2023-10-01", "2023-12-31"),   # 年末震荡验证
        "desc": "震荡·横盘修复期",
    },
    "BULL": {
        "train": ("2024-09-24", "2025-06-30"),   # 924行情后牛市
        "valid": ("2025-07-01", "2026-03-27"),   # 高位震荡验证
        "desc": "牛市·趋势上涨期",
    },
}

# 三态专属参数搜索空间（针对各自特性设计）
REGIME_GRIDS = {
    "BEAR": {
        "N_trend":    [40, 60],              # 较短趋势线（熊市趋势下移快）
        "rsi_period": [14],
        "rsi_buy":    [40, 45, 50],          # 宽松（熊市超跌弹幅大，用更高阈值多捕信号）
        "rsi_sell":   [60, 65],              # 低位止盈（反弹快，不恋战）
        "bias_buy":   [-3.0, -4.0, -5.0],   # 深度乖离才买（熊市低位有效）
        "stop_loss":  [0.05, 0.06],          # 严格（熊市无底）
    },
    "RANGE": {
        "N_trend":    [60, 90],
        "rsi_period": [14],
        "rsi_buy":    [30, 35, 40],
        "rsi_sell":   [65, 70, 75],
        "bias_buy":   [-2.0, -3.0],
        "stop_loss":  [0.07, 0.08, 0.10],
    },
    "BULL": {
        "N_trend":    [90, 120],             # 长趋势线（牛市趋势稳定）
        "rsi_period": [14],
        "rsi_buy":    [40, 45, 50],          # 宽松（牛市RSI难破35）
        "rsi_sell":   [72, 75, 80],          # 高位卖出（让利润跑）
        "bias_buy":   [-1.5, -2.0],
        "stop_loss":  [0.06, 0.08],
    },
}

# ETF池（33只有效数据）
MR_POOL = [
    {"code": "510500.SH", "max_pos": 15, "defensive": False},
    {"code": "512100.SH", "max_pos": 15, "defensive": False},
    {"code": "510300.SH", "max_pos": 15, "defensive": True},
    {"code": "159915.SZ", "max_pos": 10, "defensive": False},
    {"code": "159949.SZ", "max_pos": 10, "defensive": False},
    {"code": "159781.SZ", "max_pos": 8,  "defensive": False},
    {"code": "512480.SH", "max_pos": 8,  "defensive": False},
    {"code": "588200.SH", "max_pos": 7,  "defensive": False},
    {"code": "159995.SZ", "max_pos": 7,  "defensive": False},
    {"code": "159516.SZ", "max_pos": 6,  "defensive": False},
    {"code": "588220.SH", "max_pos": 8,  "defensive": False},
    {"code": "515000.SH", "max_pos": 6,  "defensive": False},
    {"code": "515070.SH", "max_pos": 6,  "defensive": False},
    {"code": "159819.SZ", "max_pos": 6,  "defensive": False},
    {"code": "515880.SH", "max_pos": 6,  "defensive": False},
    {"code": "562500.SH", "max_pos": 5,  "defensive": False},
    {"code": "512400.SH", "max_pos": 6,  "defensive": False},
    {"code": "516160.SH", "max_pos": 7,  "defensive": False},
    {"code": "515790.SH", "max_pos": 7,  "defensive": False},
    {"code": "562550.SH", "max_pos": 5,  "defensive": False},
    {"code": "159870.SZ", "max_pos": 5,  "defensive": False},
    {"code": "512560.SH", "max_pos": 7,  "defensive": True},
    {"code": "159218.SZ", "max_pos": 5,  "defensive": False},
    {"code": "159326.SZ", "max_pos": 5,  "defensive": True},
    {"code": "159869.SZ", "max_pos": 5,  "defensive": False},
    {"code": "159851.SZ", "max_pos": 5,  "defensive": False},
    {"code": "159941.SZ", "max_pos": 8,  "defensive": True},
    {"code": "513500.SH", "max_pos": 8,  "defensive": True},
    {"code": "515100.SH", "max_pos": 5,  "defensive": True},
    {"code": "159545.SZ", "max_pos": 5,  "defensive": True},
    {"code": "513130.SH", "max_pos": 5,  "defensive": False},
    {"code": "513970.SH", "max_pos": 5,  "defensive": False},
    {"code": "513090.SH", "max_pos": 5,  "defensive": False},
    {"code": "513120.SH", "max_pos": 5,  "defensive": False},
]

MAX_TOTAL_POS = 0.85


# ─── 数据加载 ─────────────────────────────────────────────────────────────────

def load_prices(codes, start, end):
    frames = {}
    s_dt, e_dt = pd.to_datetime(start), pd.to_datetime(end)
    for code in codes:
        fp = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
        if not os.path.exists(fp): continue
        try:
            df = pd.read_parquet(fp)
            df['trade_date'] = pd.to_datetime(
                df['trade_date'].astype(str).str[:8], format='%Y%m%d')
            col = 'adj_close' if 'adj_close' in df.columns else 'close'
            frames[code] = df.set_index('trade_date')[col].rename(code)
        except: pass
    if not frames: raise FileNotFoundError("无数据")
    mat = pd.DataFrame(frames).sort_index().ffill()
    return mat[(mat.index >= s_dt) & (mat.index <= e_dt)]


# ─── 信号状态机（单只ETF） ────────────────────────────────────────────────────

def signal_state_machine(price_arr, p):
    n, nt, rp = len(price_arr), p["N_trend"], p["rsi_period"]
    if n < nt + rp + 5:
        return np.zeros(n)

    ma_t = np.array([price_arr[max(0,i-nt+1):i+1].mean() for i in range(n)])
    for i in range(nt - 1): ma_t[i] = np.nan

    with np.errstate(invalid='ignore', divide='ignore'):
        bias = np.where(ma_t > 0, (price_arr - ma_t) / ma_t * 100, np.nan)

    diff = np.diff(price_arr, prepend=price_arr[0])
    gain, loss = np.where(diff>0,diff,0.), np.where(diff<0,-diff,0.)
    avg_g, avg_l = np.full(n,np.nan), np.full(n,np.nan)
    if n > rp:
        avg_g[rp], avg_l[rp] = gain[1:rp+1].mean(), loss[1:rp+1].mean()
        for i in range(rp+1, n):
            avg_g[i] = (avg_g[i-1]*(rp-1)+gain[i])/rp
            avg_l[i] = (avg_l[i-1]*(rp-1)+loss[i])/rp
    with np.errstate(invalid='ignore', divide='ignore'):
        rsi = 100 - 100/(1 + np.where(avg_l<1e-8, 1e8, avg_g/avg_l))

    sig, in_pos, entry_px = np.zeros(n), False, 0.
    for i in range(1, n):
        if np.isnan(ma_t[i]) or np.isnan(rsi[i]): continue
        if not in_pos:
            if (price_arr[i] > ma_t[i] and
                (rsi[i] <= p["rsi_buy"] or
                 (not np.isnan(bias[i]) and bias[i] <= p["bias_buy"]))):
                in_pos, entry_px, sig[i] = True, price_arr[i], 1.
        else:
            cumret = price_arr[i]/entry_px - 1
            if rsi[i] >= p["rsi_sell"] or cumret < -p["stop_loss"] or price_arr[i] < ma_t[i]*0.97:
                in_pos = False
            else:
                sig[i] = 1.
    return sig


# ─── 组合回测 ─────────────────────────────────────────────────────────────────

def portfolio_backtest(price_mat, bm_series, p):
    valid_codes = [e["code"] for e in MR_POOL if e["code"] in price_mat.columns]
    max_pos_map = {e["code"]: e["max_pos"]/100. for e in MR_POOL}
    n_days = len(price_mat)
    if n_days < 40:
        return {"valid": False}

    sig_mat = pd.DataFrame(0., index=price_mat.index, columns=valid_codes)
    for code in valid_codes:
        arr = price_mat[code].ffill().bfill().values.astype(float)
        if len(arr) < p["N_trend"] + p["rsi_period"] + 10: continue
        sig_mat[code] = signal_state_machine(arr, p)

    sig_t1 = sig_mat.shift(1).fillna(0)
    max_pos_arr = np.array([max_pos_map.get(c, 0.10) for c in valid_codes])
    raw_w = sig_t1.values * max_pos_arr
    row_sum = raw_w.sum(axis=1, keepdims=True)
    scale = np.minimum(MAX_TOTAL_POS / np.where(row_sum>0, row_sum, 1.), 1.)
    final_w = raw_w * scale

    ret_mat = price_mat[valid_codes].pct_change(fill_method=None).fillna(0).values
    port_ret = (final_w * ret_mat).sum(axis=1)
    w_diff   = np.abs(np.diff(final_w, axis=0, prepend=final_w[:1]))
    cost     = w_diff.sum(axis=1) * TRANSACTION_COST
    net_ret  = port_ret - cost

    equity   = pd.Series((1+net_ret).cumprod(), index=price_mat.index)
    bm_al    = bm_series.reindex(price_mat.index).ffill()
    bm_ret   = bm_al.pct_change(fill_method=None).fillna(0)
    bm_eq    = (1+bm_ret).cumprod()

    n = len(equity)
    if n < 20: return {"valid": False}
    ann = 252 / n

    sl = lambda x: np.log(max(float(x), 1e-9))
    ann_ret  = float(np.exp(sl(equity.iloc[-1]) * ann) - 1)
    ann_bm   = float(np.exp(sl(bm_eq.iloc[-1])  * ann) - 1)
    alpha    = ann_ret - ann_bm
    max_dd   = float(((equity - equity.cummax()) / equity.cummax()).min())
    ex       = pd.Series(net_ret) - RISK_FREE_RATE/252
    sharpe   = float(ex.mean()/ex.std()*np.sqrt(252)) if ex.std()>1e-8 else 0.
    calmar   = float(ann_ret/abs(max_dd)) if abs(max_dd)>1e-6 else 0.
    act      = pd.Series(net_ret) - bm_ret.values
    ir       = float(act.mean()/act.std()*np.sqrt(252)) if act.std()>1e-6 else 0.

    # 信号覆盖率（防止全程空仓假高分）
    total_pos_days = (final_w.sum(axis=1) > 0.01).sum()
    coverage = total_pos_days / max(n, 1)

    opt_score = (
        0.35 * min(max(alpha / 0.20, 0), 1.0)
      + 0.25 * min(max(sharpe / 2.0, 0), 1.0)
      + 0.20 * min(max(1 + max_dd, 0.70), 1.0) / 0.30 * 0.30
      + 0.10 * min(max(calmar / 1.5, 0), 1.0)
      + 0.10 * min(coverage * 3, 1.0)           # 覆盖率惩罚：空仓太多扣分
    )

    return {
        "valid": True,
        "ann_ret": round(ann_ret*100, 2), "ann_bm": round(ann_bm*100, 2),
        "alpha": round(alpha*100, 2), "max_dd": round(max_dd*100, 2),
        "sharpe": round(sharpe, 3), "calmar": round(calmar, 3),
        "ir": round(ir, 3), "coverage": round(coverage*100, 1),
        "opt_score": round(opt_score, 4),
    }


# ─── 单态优化 ─────────────────────────────────────────────────────────────────

def optimize_regime(regime_name, period_cfg, grid):
    print(f"\n{'='*55}")
    print(f"  优化 [{regime_name}] 状态 — {period_cfg['desc']}")
    print(f"  训练: {period_cfg['train'][0]} ~ {period_cfg['train'][1]}")
    print(f"  验证: {period_cfg['valid'][0]} ~ {period_cfg['valid'][1]}")
    print(f"{'='*55}")

    all_codes = list(dict.fromkeys([e["code"] for e in MR_POOL] + [BENCHMARK_CODE]))
    extended_start = pd.to_datetime(period_cfg["train"][0]) - pd.Timedelta(days=180)

    prices_full = load_prices(all_codes, extended_start.strftime("%Y-%m-%d"),
                              period_cfg["valid"][1])
    bm_full     = prices_full[BENCHMARK_CODE].copy()
    etf_cols    = [c for c in prices_full.columns if c != BENCHMARK_CODE]

    train_mat = prices_full[etf_cols][(prices_full.index >= period_cfg["train"][0]) &
                                       (prices_full.index <= period_cfg["train"][1])]
    valid_mat = prices_full[etf_cols][(prices_full.index >= period_cfg["valid"][0]) &
                                       (prices_full.index <= period_cfg["valid"][1])]
    bm_train  = bm_full[(bm_full.index >= period_cfg["train"][0]) &
                         (bm_full.index <= period_cfg["train"][1])]
    bm_valid  = bm_full[(bm_full.index >= period_cfg["valid"][0]) &
                         (bm_full.index <= period_cfg["valid"][1])]

    keys   = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    total  = len(combos)
    print(f"[GRID] {total} 种组合 | 训练集 {len(train_mat)} 天 | 验证集 {len(valid_mat)} 天")

    train_results = []
    t0 = time.time()
    for idx, combo in enumerate(combos):
        p   = dict(zip(keys, combo))
        res = portfolio_backtest(train_mat, bm_train, p)
        if res.get("valid"):
            train_results.append({"params": p, "train": res})
        if (idx+1) % 50 == 0:
            print(f"  [{idx+1}/{total}] 完成 | {time.time()-t0:.0f}s")

    if not train_results:
        print(f"[WARN] {regime_name}: 无有效训练结果")
        return None

    train_results.sort(key=lambda x: x["train"]["opt_score"], reverse=True)
    top = train_results[:20]

    print(f"\n[VALID] 对 Top {len(top)} 组合做验证集测试...")
    final_results = []
    for item in top:
        p   = item["params"]
        res = portfolio_backtest(valid_mat, bm_valid, p)
        if not res.get("valid"): continue
        combined = item["train"]["opt_score"] * 0.35 + res["opt_score"] * 0.65
        final_results.append({
            "params":         p,
            "train":          item["train"],
            "valid":          res,
            "combined_score": round(combined, 4),
        })

    if not final_results:
        print(f"[WARN] {regime_name}: 验证集无有效结果，使用训练集最优参数")
        best = train_results[0]
        return {
            "regime": regime_name, "desc": period_cfg["desc"],
            "params": best["params"], "train_kpi": best["train"],
            "valid_kpi": {}, "combined_score": best["train"]["opt_score"],
            "optimized_at": datetime.now().isoformat(),
        }

    final_results.sort(key=lambda x: x["combined_score"], reverse=True)
    best = final_results[0]

    print(f"\n  🏆 [{regime_name}] 最优参数: {best['params']}")
    print(f"     训练集 Alpha: {best['train']['alpha']:+.2f}%  coverage={best['train']['coverage']:.0f}%")
    print(f"     验证集 Alpha: {best['valid']['alpha']:+.2f}%  coverage={best['valid']['coverage']:.0f}%")
    print(f"     综合评分: {best['combined_score']:.4f}")

    return {
        "regime":          regime_name,
        "desc":            period_cfg["desc"],
        "params":          best["params"],
        "train_kpi":       best["train"],
        "valid_kpi":       best["valid"],
        "combined_score":  best["combined_score"],
        "optimized_at":    datetime.now().isoformat(),
    }


# ─── 主入口 ───────────────────────────────────────────────────────────────────

def run_per_regime_optimization():
    t_start = time.time()
    print("\n" + "="*55)
    print("  AlphaCore 均值回归 V4.0 · 三态参数专项优化器")
    print("="*55)

    results = {}
    for regime_name, period_cfg in REGIME_PERIODS.items():
        grid   = REGIME_GRIDS[regime_name]
        result = optimize_regime(regime_name, period_cfg, grid)
        if result:
            results[regime_name] = result

    # 元数据
    output = {
        "generated_at":  datetime.now().isoformat(),
        "next_optimize_after": (
            pd.Timestamp.now() + pd.Timedelta(days=60)
        ).strftime("%Y-%m-%d"),
        "regimes":       results,
        "summary": {
            r: {
                "params":      results[r]["params"],
                "train_alpha": results[r]["train_kpi"].get("alpha"),
                "valid_alpha": results[r]["valid_kpi"].get("alpha"),
                "score":       results[r]["combined_score"],
            }
            for r in results
        }
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t_start
    print(f"\n{'='*55}")
    print(f"  ✅ 三态优化完成 | 总耗时 {elapsed/60:.1f} 分钟")
    print(f"  结果已保存：{OUTPUT_FILE}")
    print(f"  下次自动重优化：{output['next_optimize_after']}")
    print(f"{'='*55}\n")
    for r, v in output["summary"].items():
        print(f"  [{r}] {v['params']}")
        print(f"       训练Alpha={v['train_alpha']:+.1f}%  验证Alpha={v.get('valid_alpha', 'N/A')}")
    return output


if __name__ == "__main__":
    run_per_regime_optimization()
