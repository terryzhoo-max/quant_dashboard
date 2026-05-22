"""用8Y+ ETF构建标的池并回测V3.0"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from pathlib import Path
from strategies.momentum_backtest_engine import (
    MomentumBacktester, PerformanceEvaluator, FactorDataManager,
    load_price_matrix, BENCHMARK_CODE, TRANSACTION_COST
)
from scipy import stats as sp_stats
import math

dm = FactorDataManager()

# ================================================================
# 8Y+ 行业/主题ETF池（排除纯宽基指数510300/510050/510500，保留分行业标的）
# ================================================================
POOL_8Y = [
    # 已确认8年+数据的ETF
    {"code": "159905.SZ", "name": "深100ETF",    "group": "宽基成长"},    # 2015+, 11.4Y — 深证100偏科技成长
    {"code": "159915.SZ", "name": "创业板ETF",   "group": "宽基成长"},    # 2015+, 11.4Y — 创业板
    {"code": "159941.SZ", "name": "纳指ETF",     "group": "海外"},        # 2015+, 10.9Y — 纳斯达克100
    {"code": "159949.SZ", "name": "创业板50ETF", "group": "宽基成长"},    # 2016+, 9.8Y — 创业板50
    {"code": "512100.SH", "name": "中证1000ETF", "group": "宽基小盘"},    # 2016+, 9.5Y — 小盘
    {"code": "512560.SH", "name": "军工ETF",     "group": "军工"},        # 2017+, 8.8Y — 国防军工
    {"code": "512400.SH", "name": "有色金属ETF", "group": "周期"},        # 2017+, 8.7Y — 有色金属
    {"code": "513500.SH", "name": "标普500ETF",  "group": "海外"},        # 2015+, 11.4Y — 美股

    # 补充6Y+ ETF扩大池子（确保行业覆盖）
    {"code": "512480.SH", "name": "半导体ETF",   "group": "科技"},        # 2019+, 6.9Y
    {"code": "515880.SH", "name": "通信ETF",     "group": "科技"},        # 2019+, 6.7Y
    {"code": "515000.SH", "name": "科技ETF",     "group": "科技"},        # 2019+, 6.8Y
    {"code": "515070.SH", "name": "AI ETF",      "group": "科技"},        # 2019+, 6.4Y
    {"code": "512660.SH", "name": "军工龙头ETF", "group": "军工"},        # 2020+, 6.4Y
    {"code": "512720.SH", "name": "计算机ETF",   "group": "科技"},        # 2020+, 6.4Y
    {"code": "512760.SH", "name": "芯片龙头ETF", "group": "科技"},        # 2020+, 6.4Y
    {"code": "512880.SH", "name": "证券ETF",     "group": "金融"},        # 2020+, 6.4Y
]

all_codes = [e["code"] for e in POOL_8Y] + [BENCHMARK_CODE]
group_map = {e["code"]: e["group"] for e in POOL_8Y}

# 起始日：以最晚上市的标的为准
# 512880等从2020-01-02开始，加上120日预热 → 2017-09-01开始load
# 但回测要8年 → 2017-09-01 ~ 2025-12-31 = 8.3年

# 先尝试纯8Y+池（8只）
print("=" * 80)
print("  STEP 1: Pure 8Y+ Pool (8 ETFs) — 2017-09-01 ~ 2025-12-31")
print("=" * 80)

codes_8y = [e["code"] for e in POOL_8Y[:8]]
gm_8y = {e["code"]: e["group"] for e in POOL_8Y[:8]}

pm_8y = load_price_matrix(codes_8y + [BENCHMARK_CODE], "2017-09-01", "2025-12-31", dm)
bench_8y = pm_8y.get(BENCHMARK_CODE)
strat_8y = pm_8y.drop(columns=[BENCHMARK_CODE], errors="ignore")
bench_ret_8y = bench_8y.pct_change().dropna() if bench_8y is not None else None
hs300_8y = load_price_matrix(["000300.SH"], "2017-09-01", "2025-12-31", dm).get("000300.SH")

# Available columns
avail = [c for c in strat_8y.columns if strat_8y[c].first_valid_index() is not None]
print("  Available ETFs in matrix: %d" % len(avail))
for c in avail:
    fv = strat_8y[c].first_valid_index()
    print("    %s first valid: %s" % (c, fv.date() if fv else "NONE"))

# V3.0 params (A-rated)
params = dict(
    top_n=min(4, len(avail)),  # 只有8只，取4
    rebalance_days=10, mom_s_window=20, mom_m_window=60,
    w_mom_s=0.40, w_mom_m=0.20, w_slope=0.15, w_sharpe=0.15, w_trend=0.10,
    stop_loss=-0.08, position_cap=0.90,
    cumulative_stop=True, stop_bull=-0.99, stop_range=-0.10, stop_bear=-0.07,
    adaptive_rebalance=True, rebal_bull=3, rebal_range=10, rebal_bear=20,
    dual_ma_regime=True,
)

bt = MomentumBacktester(**params)

# FULL 8Y
result = bt.run(strat_8y, hs300_8y, gm_8y)
perf = PerformanceEvaluator.evaluate(result["portfolio_returns"], bench_ret_8y, "8Y Full")

def print_perf(label, p):
    if "error" in p:
        print("  [%s] ERROR: %s" % (label, p["error"]))
        return
    print("  [%s]" % label)
    print("    CAGR:      %s%%" % p.get("cagr"))
    print("    MaxDD:     %s%%" % p.get("max_drawdown"))
    print("    Sharpe:    %s" % p.get("sharpe"))
    print("    Calmar:    %s" % p.get("calmar"))
    print("    WinRate:   %s%%" % p.get("monthly_win_rate"))
    print("    BenchCAGR: %s%%" % p.get("benchmark_cagr"))
    print("    ExCAGR:    %s%%" % p.get("excess_cagr"))
    print("    IR:        %s" % p.get("information_ratio"))
    print("    ExWinRate: %s%%" % p.get("excess_win_rate"))

print_perf("8Y FULL", perf)

# IS / OOS
r_is = bt.run(strat_8y.loc[:"2022-12-31"], hs300_8y, gm_8y)
p_is = PerformanceEvaluator.evaluate(r_is["portfolio_returns"], bench_ret_8y.loc[:"2022-12-31"], "IS")
r_oos = bt.run(strat_8y.loc["2023-01-01":], hs300_8y, gm_8y)
p_oos = PerformanceEvaluator.evaluate(r_oos["portfolio_returns"], bench_ret_8y.loc["2023-01-01":], "OOS")

print()
print_perf("IS 2017-2022", p_is)
print()
print_perf("OOS 2023-2025", p_oos)

# Statistical significance
if "error" not in perf:
    returns = result["portfolio_returns"].dropna()
    bench = bench_ret_8y.reindex(returns.index).fillna(0)
    n = len(returns)
    sharpe = perf.get("sharpe", 0)
    t_stat = sharpe * math.sqrt(n / 252)
    p_value = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n-1))

    excess = returns - bench
    ex_t = (excess.mean() / excess.std()) * math.sqrt(n) if excess.std() > 0 else 0
    ex_p = 2 * (1 - sp_stats.t.cdf(abs(ex_t), df=n-1))

    print()
    print("=" * 80)
    print("  STATISTICAL SIGNIFICANCE (n=%d, %.1f years)" % (n, n/252))
    print("=" * 80)
    print("  Sharpe t-test:  t=%.3f  p=%.4f  %s" % (
        t_stat, p_value,
        "SIGNIFICANT" if p_value < 0.05 else "MARGINAL" if p_value < 0.10 else "NOT SIGNIFICANT"))
    print("  Excess t-test:  t=%.3f  p=%.4f  %s" % (
        ex_t, ex_p,
        "SIGNIFICANT" if ex_p < 0.05 else "MARGINAL" if ex_p < 0.10 else "NOT SIGNIFICANT"))

# A-rating check
if "error" not in perf and "error" not in p_oos:
    print()
    print("=" * 80)
    print("  A-RATING CHECK (8Y)")
    print("=" * 80)
    checks = [
        ("Sharpe >= 0.5",              perf.get("sharpe", 0) >= 0.5),
        ("Excess CAGR >= 5%",          perf.get("excess_cagr", 0) >= 5.0),
        ("MaxDD < Bench MaxDD",        abs(perf.get("max_drawdown", -100)) < abs(perf.get("benchmark_max_dd", -100))),
        ("IR >= 0.4",                  perf.get("information_ratio", 0) >= 0.4),
        ("OOS Sharpe >= 0.3",          p_oos.get("sharpe", 0) >= 0.3),
        ("OOS beats benchmark",        p_oos.get("excess_cagr", 0) > 0),
        ("Monthly WinRate >= 45%",     perf.get("monthly_win_rate", 0) >= 45.0),
    ]
    passed = 0
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        print("  [%s] %s" % (status, name))
        if ok: passed += 1
    grade = "A" if passed >= 6 else "B" if passed >= 4 else "C"
    print("  GRADE: %s (%d/%d)" % (grade, passed, len(checks)))

# ================================================================
# Now try expanded pool (16 ETFs, start from 2020-01-02)
# ================================================================
print()
print("=" * 80)
print("  STEP 2: Expanded Pool (16 ETFs) — 2020-01-02 ~ 2025-12-31 (6Y)")
print("=" * 80)

pm_exp = load_price_matrix(all_codes, "2020-01-02", "2025-12-31", dm)
bench_exp = pm_exp.get(BENCHMARK_CODE)
strat_exp = pm_exp.drop(columns=[BENCHMARK_CODE], errors="ignore")
bench_ret_exp = bench_exp.pct_change().dropna() if bench_exp is not None else None
hs300_exp = load_price_matrix(["000300.SH"], "2020-01-02", "2025-12-31", dm).get("000300.SH")

avail_exp = [c for c in strat_exp.columns if strat_exp[c].first_valid_index() is not None]
print("  Available ETFs: %d" % len(avail_exp))

params_exp = {**params, "top_n": 5}
bt_exp = MomentumBacktester(**params_exp)

result_exp = bt_exp.run(strat_exp, hs300_exp, group_map)
perf_exp = PerformanceEvaluator.evaluate(result_exp["portfolio_returns"], bench_ret_exp, "Expanded")
print_perf("EXPANDED 6Y FULL", perf_exp)

# OOS
r_oos_exp = bt_exp.run(strat_exp.loc["2023-01-01":], hs300_exp, group_map)
p_oos_exp = PerformanceEvaluator.evaluate(r_oos_exp["portfolio_returns"], bench_ret_exp.loc["2023-01-01":], "OOS")
print()
print_perf("EXPANDED OOS 2023-2025", p_oos_exp)

print()
print("DONE")
