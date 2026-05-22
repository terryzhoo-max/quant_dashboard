"""8Y 最终验证: moms50+slope20 配置"""
import sys, os, math
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from strategies.momentum_backtest_engine import (
    MomentumBacktester, PerformanceEvaluator, FactorDataManager,
    load_price_matrix, BENCHMARK_CODE
)

dm = FactorDataManager()

FULL_POOL = [
    {"code": "159905.SZ", "group": "A"}, {"code": "159915.SZ", "group": "A"},
    {"code": "513500.SH", "group": "B"}, {"code": "159941.SZ", "group": "B"},
    {"code": "159949.SZ", "group": "A"}, {"code": "512100.SH", "group": "C"},
    {"code": "512560.SH", "group": "D"}, {"code": "512400.SH", "group": "E"},
    {"code": "512480.SH", "group": "F"}, {"code": "515000.SH", "group": "F"},
    {"code": "515880.SH", "group": "F"}, {"code": "515070.SH", "group": "F"},
    {"code": "512660.SH", "group": "D"}, {"code": "512720.SH", "group": "F"},
    {"code": "512760.SH", "group": "F"}, {"code": "512880.SH", "group": "G"},
    {"code": "159995.SZ", "group": "F"}, {"code": "515030.SH", "group": "E"},
    {"code": "159819.SZ", "group": "F"}, {"code": "515790.SH", "group": "E"},
    {"code": "516160.SH", "group": "E"}, {"code": "159870.SZ", "group": "E"},
    {"code": "159869.SZ", "group": "H"}, {"code": "513130.SH", "group": "H"},
]

all_codes = [e["code"] for e in FULL_POOL] + [BENCHMARK_CODE]
group_map = {e["code"]: e["group"] for e in FULL_POOL}

pm = load_price_matrix(all_codes, "2017-01-01", "2025-12-31", dm)
bench_prices = pm.get(BENCHMARK_CODE)
strat_prices = pm.drop(columns=[BENCHMARK_CODE], errors="ignore")
bench_returns = bench_prices.pct_change().dropna()
hs300 = load_price_matrix(["000300.SH"], "2017-01-01", "2025-12-31", dm).get("000300.SH")

# 8Y OPTIMAL: moms50+slope20
params = dict(
    top_n=4, rebalance_days=10, mom_s_window=20, mom_m_window=60,
    w_mom_s=0.50, w_mom_m=0.10, w_slope=0.20, w_sharpe=0.15, w_trend=0.10,
    stop_loss=-0.08, position_cap=0.90,
    cumulative_stop=True, stop_bull=-0.99, stop_range=-0.10, stop_bear=-0.07,
    adaptive_rebalance=True, rebal_bull=3, rebal_range=10, rebal_bear=20,
    dual_ma_regime=True,
)

# NOTE: weights sum to 1.05, need to fix
total_w = params["w_mom_s"] + params["w_mom_m"] + params["w_slope"] + params["w_sharpe"] + params["w_trend"]
print("Factor weight sum: %.2f" % total_w)
# Normalize: 0.50 + 0.10 + 0.20 + 0.15 + 0.10 = 1.05 → adjust sharpe to 0.10
params["w_sharpe"] = 0.10
total_w2 = params["w_mom_s"] + params["w_mom_m"] + params["w_slope"] + params["w_sharpe"] + params["w_trend"]
print("Adjusted weight sum: %.2f" % total_w2)

bt = MomentumBacktester(**params)

def run_eval(sp, br, label):
    r = bt.run(sp, hs300, group_map)
    return PerformanceEvaluator.evaluate(r["portfolio_returns"], br, label), r

# Full period
p_full, r_full = run_eval(strat_prices, bench_returns, "8Y Full")

# Periods
p_is, _ = run_eval(strat_prices.loc[:"2021-12-31"], bench_returns.loc[:"2021-12-31"], "IS 2017-2021")
p_oos, _ = run_eval(strat_prices.loc["2022-01-01":], bench_returns.loc["2022-01-01":], "OOS 2022-2025")
p_17_19, _ = run_eval(strat_prices.loc[:"2019-12-31"], bench_returns.loc[:"2019-12-31"], "2017-2019")
p_20_21, _ = run_eval(strat_prices.loc["2020-01-01":"2021-12-31"], bench_returns.loc["2020-01-01":"2021-12-31"], "2020-2021")
p_22_23, _ = run_eval(strat_prices.loc["2022-01-01":"2023-12-31"], bench_returns.loc["2022-01-01":"2023-12-31"], "2022-2023")
p_24_25, _ = run_eval(strat_prices.loc["2024-01-01":], bench_returns.loc["2024-01-01":], "2024-2025")

print()
print("=" * 80)
print("  8Y FINAL REPORT: moms50+slope20 (adjusted weights)")
print("=" * 80)

for label, p in [("FULL 8Y", p_full), ("IS 2017-2021", p_is), ("OOS 2022-2025", p_oos),
                 ("2017-2019", p_17_19), ("2020-2021", p_20_21), ("2022-2023", p_22_23), ("2024-2025", p_24_25)]:
    if "error" in p:
        print("  [%s] ERROR: %s" % (label, p["error"]))
        continue
    print("  [%s]  CAGR=%s%%  MaxDD=%s%%  Sharpe=%s  ExCAGR=%s%%  IR=%s  WR=%s%%" % (
        label, p.get("cagr"), p.get("max_drawdown"), p.get("sharpe"),
        p.get("excess_cagr"), p.get("information_ratio"), p.get("monthly_win_rate")))

# Statistical significance
if "error" not in p_full:
    returns = r_full["portfolio_returns"].dropna()
    bench_r = bench_returns.reindex(returns.index).fillna(0)
    n = len(returns)
    sharpe = p_full.get("sharpe", 0)
    t_stat = sharpe * math.sqrt(n / 252)
    p_value = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n-1))

    excess = returns - bench_r
    ex_t = (excess.mean() / excess.std()) * math.sqrt(n) if excess.std() > 0 else 0
    ex_p = 2 * (1 - sp_stats.t.cdf(abs(ex_t), df=n-1))

    print()
    print("  STATISTICAL SIGNIFICANCE (n=%d, %.1f years)" % (n, n/252))
    print("  Sharpe:  t=%.3f  p=%.4f  %s" % (
        t_stat, p_value,
        "*** SIGNIFICANT (5%%) ***" if p_value < 0.05 else
        "* MARGINAL (10%%) *" if p_value < 0.10 else "NOT SIGNIFICANT"))
    print("  Excess:  t=%.3f  p=%.4f  %s" % (
        ex_t, ex_p,
        "*** SIGNIFICANT (5%%) ***" if ex_p < 0.05 else
        "* MARGINAL (10%%) *" if ex_p < 0.10 else "NOT SIGNIFICANT"))

# A-rating
if "error" not in p_full and "error" not in p_oos:
    print()
    print("  A-RATING CHECK (8Y)")
    checks = [
        ("Sharpe >= 0.5",              p_full.get("sharpe", 0) >= 0.5),
        ("Excess CAGR >= 5%",          p_full.get("excess_cagr", 0) >= 5.0),
        ("MaxDD < Bench MaxDD",        abs(p_full.get("max_drawdown", -100)) < abs(p_full.get("benchmark_max_dd", -100))),
        ("IR >= 0.4",                  p_full.get("information_ratio", 0) >= 0.4),
        ("OOS Sharpe >= 0.3",          p_oos.get("sharpe", 0) >= 0.3),
        ("OOS beats benchmark",        p_oos.get("excess_cagr", 0) > 0),
        ("Monthly WinRate >= 45%",     p_full.get("monthly_win_rate", 0) >= 45.0),
        ("Sharpe significant (p<0.10)", p_value < 0.10 if 'p_value' in dir() else False),
    ]
    passed = 0
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        print("  [%s] %s" % (status, name))
        if ok: passed += 1
    grade = "A" if passed >= 7 else "B+" if passed >= 6 else "B" if passed >= 4 else "C"
    print("  GRADE: %s (%d/%d)" % (grade, passed, len(checks)))
    print("=" * 80)
