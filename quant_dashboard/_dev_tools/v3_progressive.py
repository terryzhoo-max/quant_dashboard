"""
V3.0 渐进式标的池回测
======================
核心思路：标的上市后即加入轮动池，模拟真实场景。
- 2017: 起步阶段（4-5只可用）
- 2019: 科技ETF批量上市（10只+）
- 2020: 完整池（16只+）
- 2021: 全量池（20只）

这样能充分利用8年数据，同时不存在回溯偏差。
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import math
from scipy import stats as sp_stats
from strategies.momentum_backtest_engine import (
    MomentumBacktester, PerformanceEvaluator, FactorDataManager,
    load_price_matrix, BENCHMARK_CODE
)

dm = FactorDataManager()

# 完整的长历史标的池（按上市日期排列）
FULL_POOL = [
    # 2015+
    {"code": "159905.SZ", "name": "深100ETF",      "group": "宽基成长",  "since": "2015-01-05"},
    {"code": "159915.SZ", "name": "创业板ETF",     "group": "宽基成长",  "since": "2015-01-05"},
    {"code": "513500.SH", "name": "标普500ETF",    "group": "海外",      "since": "2015-01-05"},
    {"code": "159941.SZ", "name": "纳指ETF",       "group": "海外",      "since": "2015-07-13"},
    # 2016+
    {"code": "159949.SZ", "name": "创业板50ETF",   "group": "宽基成长",  "since": "2016-07-22"},
    {"code": "512100.SH", "name": "中证1000ETF",   "group": "宽基小盘",  "since": "2016-11-04"},
    # 2017+
    {"code": "512560.SH", "name": "军工ETF",       "group": "军工制造",  "since": "2017-07-28"},
    {"code": "512400.SH", "name": "有色金属ETF",   "group": "新能源周期","since": "2017-09-01"},
    # 2019+
    {"code": "512480.SH", "name": "半导体ETF",     "group": "科技AI",    "since": "2019-06-12"},
    {"code": "515000.SH", "name": "科技ETF",       "group": "科技AI",    "since": "2019-08-16"},
    {"code": "515880.SH", "name": "通信ETF",       "group": "科技AI",    "since": "2019-09-06"},
    {"code": "515070.SH", "name": "AI ETF",        "group": "科技AI",    "since": "2019-12-24"},
    # 2020+
    {"code": "512660.SH", "name": "军工龙头ETF",   "group": "军工制造",  "since": "2020-01-02"},
    {"code": "512720.SH", "name": "计算机ETF",     "group": "科技AI",    "since": "2020-01-02"},
    {"code": "512760.SH", "name": "芯片龙头ETF",   "group": "科技AI",    "since": "2020-01-02"},
    {"code": "512880.SH", "name": "证券ETF",       "group": "金融",      "since": "2020-01-02"},
    {"code": "515030.SH", "name": "新能源车ETF",   "group": "新能源周期","since": "2020-03-04"},
    {"code": "159995.SZ", "name": "芯片ETF",       "group": "科技AI",    "since": "2020-02-10"},
    {"code": "159819.SZ", "name": "人工智能ETF",   "group": "科技AI",    "since": "2020-09-23"},
    # 2021+
    {"code": "516160.SH", "name": "新能源ETF",     "group": "新能源周期","since": "2021-02-04"},
    {"code": "515790.SH", "name": "光伏ETF",       "group": "新能源周期","since": "2020-12-18"},
    {"code": "159870.SZ", "name": "化工ETF",       "group": "新能源周期","since": "2021-03-03"},
    {"code": "159869.SZ", "name": "游戏ETF",       "group": "港股消费",  "since": "2021-03-05"},
    {"code": "513130.SH", "name": "恒生科技ETF",   "group": "港股消费",  "since": "2021-06-01"},
]

all_codes = [e["code"] for e in FULL_POOL] + [BENCHMARK_CODE]
group_map = {e["code"]: e["group"] for e in FULL_POOL}

# 加载全部数据 (2017-01-01 ~ 2025-12-31)
START = "2017-01-01"
END = "2025-12-31"

pm = load_price_matrix(all_codes, START, END, dm)
bench_prices = pm.get(BENCHMARK_CODE)
strat_prices = pm.drop(columns=[BENCHMARK_CODE], errors="ignore")
bench_returns = bench_prices.pct_change().dropna() if bench_prices is not None else None
hs300 = load_price_matrix(["000300.SH"], START, END, dm).get("000300.SH")

# 显示实际可用标的
print("=" * 80)
print("  渐进式标的池 — 按上市日自动加入")
print("=" * 80)
available_cols = [c for c in strat_prices.columns if strat_prices[c].first_valid_index() is not None]
print("  Total columns loaded: %d" % len(available_cols))
for c in sorted(available_cols, key=lambda x: strat_prices[x].first_valid_index()):
    fv = strat_prices[c].first_valid_index()
    name = next((e["name"] for e in FULL_POOL if e["code"] == c), "?")
    print("    %s %-16s first=%s" % (c, name, fv.date()))

# V3.0 A-rated params
params = dict(
    top_n=4,  # 早期只有4-8只
    rebalance_days=10, mom_s_window=20, mom_m_window=60,
    w_mom_s=0.40, w_mom_m=0.20, w_slope=0.15, w_sharpe=0.15, w_trend=0.10,
    stop_loss=-0.08, position_cap=0.90,
    cumulative_stop=True, stop_bull=-0.99, stop_range=-0.10, stop_bear=-0.07,
    adaptive_rebalance=True, rebal_bull=3, rebal_range=10, rebal_bear=20,
    dual_ma_regime=True,
)

bt = MomentumBacktester(**params)

def print_perf(label, p):
    if "error" in p:
        print("  [%s] ERROR: %s" % (label, p["error"]))
        return p
    print("  [%s]" % label)
    for k in ["cagr", "max_drawdown", "sharpe", "calmar", "ann_vol", "monthly_win_rate",
              "benchmark_cagr", "benchmark_max_dd", "excess_cagr", "information_ratio", "excess_win_rate"]:
        print("    %-20s: %s" % (k, p.get(k, "N/A")))
    return p

# ============ FULL PERIOD ============
print()
print("=" * 80)
print("  FULL PERIOD: %s ~ %s" % (START, END))
print("=" * 80)

result = bt.run(strat_prices, hs300, group_map)
perf = print_perf("FULL", PerformanceEvaluator.evaluate(result["portfolio_returns"], bench_returns, "Full"))

# ============ PERIODS ============
periods = [
    ("IS 2017-2021",  None,         "2021-12-31"),
    ("OOS 2022-2025", "2022-01-01", None),
    ("Period 2017-2019", None,         "2019-12-31"),
    ("Period 2020-2021", "2020-01-01", "2021-12-31"),
    ("Period 2022-2023", "2022-01-01", "2023-12-31"),
    ("Period 2024-2025", "2024-01-01", None),
]

print()
print("=" * 80)
print("  PERIOD BREAKDOWN")
print("=" * 80)

period_perfs = {}
for label, start, end in periods:
    sp = strat_prices
    br = bench_returns
    if start:
        sp = sp.loc[start:]
        br = br.loc[start:]
    if end:
        sp = sp.loc[:end]
        br = br.loc[:end]
    r = bt.run(sp, hs300, group_map)
    p = PerformanceEvaluator.evaluate(r["portfolio_returns"], br, label)
    period_perfs[label] = p
    print()
    print_perf(label, p)

# ============ STATISTICAL SIGNIFICANCE ============
if "error" not in perf:
    returns = result["portfolio_returns"].dropna()
    bench_r = bench_returns.reindex(returns.index).fillna(0)
    n = len(returns)
    sharpe = perf.get("sharpe", 0)
    t_stat = sharpe * math.sqrt(n / 252)
    p_value = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n-1))

    excess = returns - bench_r
    ex_t = (excess.mean() / excess.std()) * math.sqrt(n) if excess.std() > 0 else 0
    ex_p = 2 * (1 - sp_stats.t.cdf(abs(ex_t), df=n-1))

    print()
    print("=" * 80)
    print("  STATISTICAL SIGNIFICANCE (n=%d, %.1f years)" % (n, n/252))
    print("=" * 80)
    print("  Sharpe t-test:  t=%.3f  p=%.4f  %s" % (
        t_stat, p_value,
        "*** SIGNIFICANT ***" if p_value < 0.05 else "MARGINAL" if p_value < 0.10 else "NOT SIGNIFICANT"))
    print("  Excess t-test:  t=%.3f  p=%.4f  %s" % (
        ex_t, ex_p,
        "*** SIGNIFICANT ***" if ex_p < 0.05 else "MARGINAL" if ex_p < 0.10 else "NOT SIGNIFICANT"))

# ============ A-RATING CHECK ============
p_oos = period_perfs.get("OOS 2022-2025", {})
if "error" not in perf and "error" not in p_oos:
    print()
    print("=" * 80)
    print("  A-RATING CHECK")
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
    print("=" * 80)
