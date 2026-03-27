"""
行业动量轮动策略 V2.0 — 独立参数优化脚本
运行方法: python run_optimizer.py
结果保存: optimizer_results.json
"""
import os, sys, json, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
import tushare as ts
from datetime import datetime, timedelta
from itertools import product

# ====================================================================
# 配置
# ====================================================================
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
RISK_FREE_RATE = 0.025
TRANSACTION_COST = 0.0015
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "optimizer_results.json")

# 标的池（20只行业ETF）
MOMENTUM_POOL = [
    {"code": "512480.SH", "name": "半导体ETF",     "group": "科技AI"},
    {"code": "588200.SH", "name": "科创芯片ETF",   "group": "科技AI"},
    {"code": "159995.SZ", "name": "芯片ETF",       "group": "科技AI"},
    {"code": "515070.SH", "name": "人工智能AIETF", "group": "科技AI"},
    {"code": "159819.SZ", "name": "人工AI易方达",  "group": "科技AI"},
    {"code": "515880.SH", "name": "通信ETF",       "group": "科技AI"},
    {"code": "516160.SH", "name": "新能源ETF",     "group": "新能源周期"},
    {"code": "515790.SH", "name": "光伏ETF",       "group": "新能源周期"},
    {"code": "512400.SH", "name": "有色金属ETF",   "group": "新能源周期"},
    {"code": "159870.SZ", "name": "化工ETF",       "group": "新能源周期"},
    {"code": "562550.SH", "name": "绿电ETF",       "group": "新能源周期"},
    {"code": "512560.SH", "name": "军工ETF",       "group": "军工制造"},
    {"code": "159218.SZ", "name": "卫星ETF",       "group": "军工制造"},
    {"code": "562500.SH", "name": "机器人ETF",     "group": "军工制造"},
    {"code": "159326.SZ", "name": "电网设备ETF",   "group": "军工制造"},
    {"code": "159851.SZ", "name": "金融科技ETF",   "group": "军工制造"},
    {"code": "513130.SH", "name": "恒生科技ETF",   "group": "港股消费"},
    {"code": "513120.SH", "name": "港股创新药ETF", "group": "港股消费"},
    {"code": "159869.SZ", "name": "游戏ETF",       "group": "港股消费"},
    {"code": "588220.SH", "name": "科创100ETF",    "group": "港股消费"},
]
BENCHMARK_CODE = "000300.SH"  # HS300 指数

# 参数搜索空间
PARAM_GRID = {
    "top_n":          [3, 4, 5],
    "rebalance_days": [5, 10, 15, 20],
    "mom_s_window":   [10, 15, 20, 30],
    "w_mom_s":        [0.30, 0.40, 0.50],
    "stop_loss":      [-0.05, -0.08, -0.12, None],
}

IN_SAMPLE_END   = "20231231"
OUT_SAMPLE_START = "20240101"
BACKTEST_START  = "20210101"
BACKTEST_END    = datetime.now().strftime("%Y%m%d")

# ====================================================================
# 数据获取
# ====================================================================
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

def fetch_prices(codes: list, start: str, end: str) -> pd.DataFrame:
    """获取多只品种历史收盘价，组成宽表"""
    print(f"\n[数据] 获取 {len(codes)} 只品种数据 ({start} ~ {end})...")
    frames = {}
    
    # 先尝试从本地 data_lake 读取
    data_lake_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_lake", "daily_prices")
    
    for code in codes:
        try:
            local_path = os.path.join(data_lake_dir, f"{code}.parquet")
            if os.path.exists(local_path):
                df = pd.read_parquet(local_path)
                df = df.sort_values("trade_date")
                df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str))
                df = df.set_index("trade_date")
                frames[code] = df["close"].astype(float)
                print(f"  [本地] {code}: {len(df)}条")
            else:
                # 从 Tushare 拉取
                import time
                time.sleep(0.31)  # 频率限制
                df = pro.fund_daily(ts_code=code, start_date=start, end_date=end,
                                    fields="trade_date,close")
                if df is None or df.empty:
                    df = pro.pro_bar(ts_code=code, asset="E", start_date=start, end_date=end,
                                     adj="qfq", fields="trade_date,close")
                if df is not None and not df.empty:
                    df = df.sort_values("trade_date")
                    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str))
                    df = df.set_index("trade_date")
                    frames[code] = df["close"].astype(float)
                    print(f"  [API]  {code}: {len(df)}条")
                else:
                    print(f"  [SKIP] {code}: 无数据")
        except Exception as e:
            print(f"  [ERR]  {code}: {e}")

    if not frames:
        return pd.DataFrame()
    
    matrix = pd.DataFrame(frames)
    s = pd.to_datetime(start)
    e = pd.to_datetime(end)
    matrix = matrix.loc[s:e].ffill()
    print(f"[数据] 价格矩阵: {matrix.shape[0]}日 × {matrix.shape[1]}只\n")
    return matrix


def fetch_benchmark(start: str, end: str) -> pd.Series:
    """获取沪深300"""
    try:
        import time; time.sleep(0.31)
        df = pro.index_daily(ts_code=BENCHMARK_CODE, start_date=start, end_date=end)
        if df is not None and not df.empty:
            df = df.sort_values("trade_date")
            df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str))
            df = df.set_index("trade_date")["close"].astype(float)
            print(f"[数据] 沪深300 指数: {len(df)}条")
            return df
    except Exception as e:
        print(f"[WARN] 沪深300获取失败: {e}")
    return pd.Series(dtype=float)


# ====================================================================
# 向量化回测核心
# ====================================================================

def rolling_slope(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """线性回归斜率（向量化）"""
    log_p = np.log(prices.replace(0, np.nan))
    x = np.arange(window, dtype=float)
    xm = x - x.mean()
    xvar = (xm**2).sum()
    result = pd.DataFrame(np.nan, index=prices.index, columns=prices.columns)
    arr = log_p.values
    for i in range(window - 1, len(arr)):
        chunk = arr[i - window + 1: i + 1]
        ym = chunk - np.nanmean(chunk, axis=0)
        slopes = np.nansum(xm[:, None] * ym, axis=0) / xvar
        result.iloc[i] = slopes
    return result


def compute_scores(price_matrix: pd.DataFrame, mom_s: int, w_s: float) -> pd.DataFrame:
    """计算4因子复合评分（向量化）"""
    mom_m = mom_s * 3
    w_m   = round(1.0 - w_s - 0.30, 2)
    w_sl  = 0.15
    w_sh  = 0.15

    mom_s_ret  = price_matrix.pct_change(mom_s)
    mom_m_ret  = price_matrix.pct_change(mom_m)
    slope      = rolling_slope(price_matrix, mom_s)
    vol        = price_matrix.pct_change().rolling(mom_s).std() * np.sqrt(252)
    sharpe_f   = mom_s_ret / vol.replace(0, np.nan)

    def zs(df):
        μ = df.mean(axis=1)
        σ = df.std(axis=1).replace(0, 1)
        return df.sub(μ, axis=0).div(σ, axis=0)

    return w_s * zs(mom_s_ret) + w_m * zs(mom_m_ret) + w_sl * zs(slope) + w_sh * zs(sharpe_f)


def run_backtest(price_matrix: pd.DataFrame, scores: pd.DataFrame,
                 hs300: pd.Series, group_map: dict,
                 top_n: int, rebalance_days: int, stop_loss) -> pd.Series:
    """向量化回测主循环，返回日度策略收益序列"""
    daily_ret = price_matrix.pct_change()

    # HS300 仓位系数
    ma120 = hs300.reindex(price_matrix.index).ffill().rolling(120).mean()
    hs300_a = hs300.reindex(price_matrix.index).ffill()
    pos_mult = pd.Series(1.0, index=price_matrix.index)
    pos_mult[hs300_a < ma120] = 0.5
    pos_mult[(hs300_a >= ma120) & (hs300_a.diff(5) < 0)] = 0.7

    warmup = max(90, 120) + 5
    dates = price_matrix.index.tolist()
    holdings = {}
    last_rebalance = warmup
    nav = [1.0] * (warmup + 1)

    for i in range(warmup + 1, len(dates)):
        date = dates[i]
        # 当日盈亏
        day_ret = sum(
            w * (daily_ret.loc[date, c] if c in daily_ret.columns and pd.notna(daily_ret.loc[date, c]) else 0)
            for c, w in holdings.items()
        )
        # 止损
        if stop_loss is not None:
            holdings = {c: w for c, w in holdings.items()
                       if not (c in daily_ret.columns and pd.notna(daily_ret.loc[date, c]) and daily_ret.loc[date, c] <= stop_loss)}

        nav.append(nav[-1] * (1 + day_ret))

        # 调仓
        if i - last_rebalance >= rebalance_days:
            last_rebalance = i
            if date in scores.index:
                row = scores.loc[date].dropna().sort_values(ascending=False)
                selected, group_cnt = [], {}
                for code in row.index:
                    g = group_map.get(code, "X")
                    if len(selected) >= top_n: break
                    if group_cnt.get(g, 0) >= 2: continue
                    selected.append(code)
                    group_cnt[g] = group_cnt.get(g, 0) + 1

                if selected:
                    pm = pos_mult.get(date, 1.0)
                    raw = row[selected] - row[selected].min() + 1e-6
                    w = (raw / raw.sum()) * 0.85 * pm
                    w = w.clip(upper=0.85 / max(top_n - 1, 1))
                    # 换手成本
                    new_h = w.to_dict()
                    all_c = set(holdings) | set(new_h)
                    turnover = sum(abs(new_h.get(c, 0) - holdings.get(c, 0)) for c in all_c) / 2
                    nav[-1] *= (1 - turnover * TRANSACTION_COST)
                    holdings = new_h

    s = pd.Series(nav, index=dates[:len(nav)])
    return s.pct_change().dropna()


def evaluate(ret: pd.Series, bench_ret: pd.Series) -> dict:
    if len(ret) < 30: return {}
    n_y = len(ret) / 252
    cum = float((1 + ret).prod() - 1)
    cagr = float((1 + cum) ** (1 / n_y) - 1) if n_y > 0 else 0
    pv = (1 + ret).cumprod()
    dd = (pv / pv.cummax() - 1).min()
    vol = float(ret.std() * np.sqrt(252))
    sharpe = (cagr - RISK_FREE_RATE) / vol if vol > 0 else 0
    calmar = cagr / abs(dd) if dd < 0 else float("inf")

    bench = bench_ret.reindex(ret.index).fillna(0)
    excess = ret - bench
    excess_cum = float((1 + excess).prod() - 1)
    excess_cagr = float((1 + excess_cum) ** (1 / n_y) - 1) if n_y > 0 else 0
    te = float(excess.std() * np.sqrt(252))
    ir = excess_cagr / te if te > 0 else 0

    monthly = ret.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    bmonthly = bench.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    win = float((monthly - bmonthly.reindex(monthly.index).fillna(0) > 0).mean())

    b_cagr = float((1 + bench_ret.reindex(ret.index).fillna(0)).prod() ** (1 / n_y) - 1) if n_y > 0 else 0

    return dict(
        cagr=round(cagr * 100, 2),
        excess_cagr=round(excess_cagr * 100, 2),
        max_dd=round(float(dd) * 100, 2),
        sharpe=round(sharpe, 3),
        calmar=round(calmar, 3),
        ir=round(ir, 3),
        win_rate=round(win * 100, 1),
        benchmark_cagr=round(b_cagr * 100, 2),
        ann_vol=round(vol * 100, 2),
    )


def score_result(r: dict) -> float:
    if not r: return -999
    return (0.40 * min(max(r.get("excess_cagr", -99) / 10, -2), 4) +
            0.30 * min(max(r.get("sharpe", -2), -2), 3) +
            0.20 * max(0, 20 + r.get("max_dd", -100)) / 20 +
            0.10 * min(max(r.get("ir", -2), -2), 2))


# ====================================================================
# 主流程
# ====================================================================
if __name__ == "__main__":
    print("=" * 65)
    print("  行业动量轮动策略 V2.0 · 参数优化引擎")
    print("=" * 65)

    codes = [e["code"] for e in MOMENTUM_POOL]
    group_map = {e["code"]: e["group"] for e in MOMENTUM_POOL}

    # 拉数据
    all_data = fetch_prices(codes, BACKTEST_START, BACKTEST_END)
    hs300 = fetch_benchmark(BACKTEST_START, BACKTEST_END)

    if all_data.empty:
        print("[ERROR] 无法获取价格数据，退出")
        sys.exit(1)

    print(f"实际获取标的数: {all_data.shape[1]}/{len(codes)}")
    available_codes = list(all_data.columns)

    # 过滤 group_map
    group_map = {k: v for k, v in group_map.items() if k in available_codes}

    # 日度收益（基准）
    if len(hs300) < 100:
        print("[WARN] 沪深300数据不足，以等权日回报作为基准")
        bench_ret = all_data.mean(axis=1).pct_change().dropna()
    else:
        bench_ret = hs300.pct_change().dropna()

    # 样本分割
    in_end   = pd.to_datetime(IN_SAMPLE_END)
    oos_start = pd.to_datetime(OUT_SAMPLE_START)
    pm_in  = all_data.loc[:in_end]
    pm_oos = all_data.loc[oos_start:]
    br_in  = bench_ret.loc[:in_end]
    br_oos = bench_ret.loc[oos_start:]

    # 网格搜索
    keys = list(PARAM_GRID.keys())
    combos = list(product(*[PARAM_GRID[k] for k in keys]))
    total = len(combos)
    print(f"\n[优化] 开始网格搜索，共 {total} 组参数...\n")

    results = []
    best_score = -999

    for idx, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        try:
            # 计算样本内评分矩阵
            scores_in = compute_scores(pm_in, params["mom_s_window"], params["w_mom_s"])
            ret_in = run_backtest(pm_in, scores_in, hs300, group_map,
                                  params["top_n"], params["rebalance_days"], params["stop_loss"])
            perf_in = evaluate(ret_in, br_in)
            sc = score_result(perf_in)

            results.append({
                "params":    params,
                "in_sample": perf_in,
                "score":     round(sc, 4),
            })

            if sc > best_score:
                best_score = sc
                marker = "  ★ 新最优"
            else:
                marker = ""

            if (idx + 1) % 10 == 0 or sc > best_score - 0.01:
                print(f"  [{idx+1:03d}/{total}] top_n={params['top_n']} "
                      f"rb={params['rebalance_days']} win={params['mom_s_window']} "
                      f"wS={params['w_mom_s']} sl={params['stop_loss']} "
                      f"→ ExcessCAGR={perf_in.get('excess_cagr','—')}% "
                      f"Sharpe={perf_in.get('sharpe','—')}  "
                      f"Score={sc:.4f}{marker}")
        except Exception as e:
            print(f"  [SKIP] {combo}: {e}")

    if not results:
        print("[ERROR] 所有参数组合均失败")
        sys.exit(1)

    # 排序
    results.sort(key=lambda r: r["score"], reverse=True)
    best = results[0]
    bp = best["params"]

    # 样本外验证
    print(f"\n[验证] 对最优参数执行样本外验证 (2024-2025)...")
    try:
        scores_oos = compute_scores(pm_oos, bp["mom_s_window"], bp["w_mom_s"])
        ret_oos = run_backtest(pm_oos, scores_oos, hs300, group_map,
                               bp["top_n"], bp["rebalance_days"], bp["stop_loss"])
        perf_oos = evaluate(ret_oos, br_oos)
    except Exception as e:
        perf_oos = {"error": str(e)}
        print(f"  [WARN] 样本外验证失败: {e}")

    # 全样本回测（最终报告用）
    print(f"\n[全样本] 对最优参数运行全样本回测 ({BACKTEST_START} ~ {BACKTEST_END})...")
    try:
        scores_full = compute_scores(all_data, bp["mom_s_window"], bp["w_mom_s"])
        ret_full = run_backtest(all_data, scores_full, hs300, group_map,
                                bp["top_n"], bp["rebalance_days"], bp["stop_loss"])
        perf_full = evaluate(ret_full, bench_ret)
    except Exception as e:
        perf_full = {"error": str(e)}

    # 汇总输出
    output = {
        "run_time": datetime.now().isoformat(),
        "data_summary": {
            "available_etfs": len(available_codes),
            "total_etfs": len(codes),
            "backtest_start": BACKTEST_START,
            "backtest_end": BACKTEST_END,
            "in_sample_end": IN_SAMPLE_END,
            "oos_start": OUT_SAMPLE_START,
        },
        "optimal_params": {
            "top_n": bp["top_n"],
            "rebalance_days": bp["rebalance_days"],
            "mom_s_window": bp["mom_s_window"],
            "mom_m_window": bp["mom_s_window"] * 3,
            "w_mom_s": bp["w_mom_s"],
            "w_mom_m": round(1.0 - bp["w_mom_s"] - 0.30, 2),
            "w_slope": 0.15,
            "w_sharpe": 0.15,
            "stop_loss": bp["stop_loss"],
            "position_cap": 0.85,
            "group_cap": 0.40,
        },
        "in_sample_performance": best["in_sample"],
        "out_of_sample_performance": perf_oos,
        "full_sample_performance": perf_full,
        "composite_score": best["score"],
        "top10_params": [
            {
                "rank": i + 1,
                "params": r["params"],
                "score": r["score"],
                "excess_cagr": r["in_sample"].get("excess_cagr"),
                "sharpe": r["in_sample"].get("sharpe"),
                "max_dd": r["in_sample"].get("max_dd"),
                "ir": r["in_sample"].get("ir"),
            }
            for i, r in enumerate(results[:10])
        ],
        "total_combinations_tested": len(results),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 65)
    print("✅ 优化完成！最优参数：")
    for k, v in output["optimal_params"].items():
        print(f"   {k}: {v}")
    print("\n📊 样本内绩效：")
    for k, v in best["in_sample"].items():
        print(f"   {k}: {v}")
    print(f"\n✅ 详细结果已保存至: {OUTPUT_FILE}")
    print("=" * 65)
