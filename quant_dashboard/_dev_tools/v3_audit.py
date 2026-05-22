"""
V3.0 机构级鲁棒性审计
=====================
1. 参数敏感性分析（关键参数±扰动）
2. 换手率 & 实际摩擦成本
3. 滚动窗口分析（12个月滚动夏普/超额）
4. 最大回撤持续期
5. 收益分布偏度/尖度
6. 统计显著性检验
"""
import sys, os, math
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from strategies.momentum_backtest_engine import (
    MomentumBacktester, PerformanceEvaluator, FactorDataManager,
    load_price_matrix, MOMENTUM_POOL_V2, BENCHMARK_CODE, TRANSACTION_COST
)

dm = FactorDataManager()
all_codes = [etf["code"] for etf in MOMENTUM_POOL_V2] + [BENCHMARK_CODE]
group_map = {etf["code"]: etf["group"] for etf in MOMENTUM_POOL_V2}
price_matrix = load_price_matrix(all_codes, "2021-01-01", "2025-12-31", dm)
benchmark_prices = price_matrix.get(BENCHMARK_CODE)
strategy_prices = price_matrix.drop(columns=[BENCHMARK_CODE], errors="ignore")
benchmark_returns = benchmark_prices.pct_change().dropna()
hs300_prices = load_price_matrix(["000300.SH"], "2021-01-01", "2025-12-31", dm).get("000300.SH")

# A-rated baseline params
BASE = dict(
    top_n=5, rebalance_days=10, mom_s_window=20, mom_m_window=60,
    w_mom_s=0.40, w_mom_m=0.20, w_slope=0.15, w_sharpe=0.15, w_trend=0.10,
    stop_loss=-0.08, position_cap=0.90,
    cumulative_stop=True, stop_bull=-0.99, stop_range=-0.10, stop_bear=-0.07,
    adaptive_rebalance=True, rebal_bull=3, rebal_range=10, rebal_bear=20,
    dual_ma_regime=True,
)

def run_full(params):
    bt = MomentumBacktester(**params)
    result = bt.run(strategy_prices, hs300_prices, group_map)
    perf = PerformanceEvaluator.evaluate(result["portfolio_returns"], benchmark_returns, "test")
    return perf, result

# ====================================================================
# 1. PARAMETER SENSITIVITY
# ====================================================================
print("=" * 80)
print("  1. PARAMETER SENSITIVITY ANALYSIS")
print("=" * 80)
print("  Testing: does the result collapse with small parameter perturbations?")
print()

perturbations = [
    ("rebal_bear", [15, 18, 20, 22, 25, 30]),
    ("rebal_bull", [2, 3, 4, 5, 7]),
    ("rebal_range", [7, 8, 10, 12, 15]),
    ("top_n", [3, 4, 5, 6]),
    ("position_cap", [0.80, 0.85, 0.90, 0.95]),
    ("stop_range", [-0.08, -0.10, -0.12, -0.15]),
    ("stop_bear", [-0.05, -0.07, -0.08, -0.10]),
    ("w_mom_s", [0.30, 0.35, 0.40, 0.45, 0.50]),
]

for param_name, values in perturbations:
    results = []
    for v in values:
        params = {**BASE, param_name: v}
        perf, _ = run_full(params)
        if "error" in perf:
            results.append((v, "ERR", "ERR", "ERR", "ERR"))
        else:
            results.append((
                v,
                perf.get("cagr", 0),
                perf.get("sharpe", 0),
                perf.get("excess_cagr", 0),
                perf.get("max_drawdown", 0)
            ))

    print("  %s:" % param_name)
    for v, cagr, sh, ex, mdd in results:
        marker = " <-- BASE" if v == BASE.get(param_name) else ""
        if isinstance(cagr, str):
            print("    %s = %-6s: ERROR" % (param_name, v))
        else:
            print("    %-6s -> CAGR=%6.2f%%  Sharpe=%6.3f  ExCAGR=%6.2f%%  MaxDD=%6.2f%%%s" % (
                v, cagr, sh, ex, mdd, marker))
    # Stability: std of sharpe across perturbations
    sharpes = [r[2] for r in results if isinstance(r[2], float)]
    if sharpes:
        print("    [Stability] Sharpe range: %.3f ~ %.3f  std=%.3f" % (
            min(sharpes), max(sharpes), np.std(sharpes)))
    print()


# ====================================================================
# 2. TURNOVER & FRICTION ANALYSIS
# ====================================================================
print("=" * 80)
print("  2. TURNOVER & FRICTION ANALYSIS")
print("=" * 80)

perf_base, result_base = run_full(BASE)
cost_log = result_base.get("cost_log", [])
holdings_log = result_base.get("holdings_log", [])

total_cost = sum(c["cost"] for c in cost_log)
n_rebalances = len(holdings_log)
n_trading_days = len(result_base["portfolio_returns"])
n_years = n_trading_days / 252

# Calculate turnover from holdings log
total_turnover = 0
for i in range(1, len(holdings_log)):
    old_h = holdings_log[i-1]["holdings"]
    new_h = holdings_log[i]["holdings"]
    all_codes_h = set(old_h) | set(new_h)
    turnover = sum(abs(new_h.get(c, 0) - old_h.get(c, 0)) for c in all_codes_h) / 2
    total_turnover += turnover

ann_turnover = total_turnover / n_years if n_years > 0 else 0
ann_cost = total_cost / n_years if n_years > 0 else 0

# Per-regime rebalance count
regime_counts = {}
for h in holdings_log:
    r = h.get("regime", "UNKNOWN")
    regime_counts[r] = regime_counts.get(r, 0) + 1

print("  Total rebalances:     %d (over %.1f years)" % (n_rebalances, n_years))
print("  Annualized rebalances: %.1f" % (n_rebalances / n_years if n_years > 0 else 0))
print("  Regime distribution:   %s" % regime_counts)
print("  Total turnover:       %.2f" % total_turnover)
print("  Annualized turnover:  %.2f (%.0f%%)" % (ann_turnover, ann_turnover * 100))
print("  Transaction cost rate: %.2f%%" % (TRANSACTION_COST * 100))
print("  Total friction cost:  %.4f (%.2f%%)" % (total_cost, total_cost * 100))
print("  Annualized friction:  %.4f (%.2f%%/yr)" % (ann_cost, ann_cost * 100))
print()

# ====================================================================
# 3. ROLLING WINDOW ANALYSIS
# ====================================================================
print("=" * 80)
print("  3. ROLLING 12-MONTH SHARPE & EXCESS")
print("=" * 80)

returns = result_base["portfolio_returns"]
bench = benchmark_returns.reindex(returns.index).fillna(0)

# Monthly returns
monthly_strat = returns.resample("ME").apply(lambda x: (1+x).prod()-1)
monthly_bench = bench.resample("ME").apply(lambda x: (1+x).prod()-1)
monthly_excess = monthly_strat - monthly_bench

# Rolling 12-month
for yr in range(2022, 2026):
    for half in [("H1", "01-01", "06-30"), ("H2", "07-01", "12-31")]:
        label = "%d %s" % (yr, half[0])
        start = "%d-%s" % (yr, half[1])
        end = "%d-%s" % (yr, half[2])
        mask = (monthly_strat.index >= start) & (monthly_strat.index <= end)
        s = monthly_strat[mask]
        b = monthly_bench[mask]
        e = monthly_excess[mask]
        if len(s) < 3:
            continue
        ret_cum = float((1+s).prod()-1)
        bench_cum = float((1+b).prod()-1)
        excess_cum = ret_cum - bench_cum
        win_months = int((e > 0).sum())
        total_months = len(e)
        print("  %s: Strat=%+6.2f%%  Bench=%+6.2f%%  Excess=%+6.2f%%  ExWin=%d/%d" % (
            label, ret_cum*100, bench_cum*100, excess_cum*100, win_months, total_months))

print()

# ====================================================================
# 4. MAX DRAWDOWN DURATION
# ====================================================================
print("=" * 80)
print("  4. MAX DRAWDOWN DURATION ANALYSIS")
print("=" * 80)

pv = (1 + returns).cumprod()
running_max = pv.cummax()
dd = pv / running_max - 1

# Find drawdown periods
in_drawdown = dd < 0
dd_starts = []
dd_ends = []
was_in_dd = False
for i, (date, is_dd) in enumerate(in_drawdown.items()):
    if is_dd and not was_in_dd:
        dd_starts.append(date)
    elif not is_dd and was_in_dd:
        dd_ends.append(date)
    was_in_dd = is_dd
if was_in_dd:
    dd_ends.append(in_drawdown.index[-1])

# Find longest and deepest drawdown
if dd_starts:
    durations = [(e - s).days for s, e in zip(dd_starts, dd_ends)]
    depths = [float(dd.loc[s:e].min()) for s, e in zip(dd_starts, dd_ends)]

    longest_idx = np.argmax(durations)
    deepest_idx = np.argmin(depths)

    print("  Total drawdown episodes: %d" % len(dd_starts))
    print("  Longest drawdown:")
    print("    Period:   %s ~ %s (%d days)" % (
        dd_starts[longest_idx].date(), dd_ends[longest_idx].date(), durations[longest_idx]))
    print("    Depth:    %.2f%%" % (depths[longest_idx] * 100))
    print("  Deepest drawdown:")
    print("    Period:   %s ~ %s (%d days)" % (
        dd_starts[deepest_idx].date(), dd_ends[deepest_idx].date(), durations[deepest_idx]))
    print("    Depth:    %.2f%%" % (depths[deepest_idx] * 100))

    # Top 5 drawdowns by depth
    sorted_dd = sorted(zip(depths, durations, dd_starts, dd_ends))
    print("  Top 5 drawdowns by depth:")
    for depth, dur, s, e in sorted_dd[:5]:
        print("    %.2f%% over %d days (%s ~ %s)" % (depth*100, dur, s.date(), e.date()))

print()

# ====================================================================
# 5. RETURN DISTRIBUTION
# ====================================================================
print("=" * 80)
print("  5. RETURN DISTRIBUTION")
print("=" * 80)

from scipy import stats as sp_stats

daily_ret = returns.dropna().values
n = len(daily_ret)
mean_d = np.mean(daily_ret)
std_d = np.std(daily_ret)
skew = float(sp_stats.skew(daily_ret))
kurt = float(sp_stats.kurtosis(daily_ret))
jb_stat, jb_pval = sp_stats.jarque_bera(daily_ret)

print("  Daily returns (n=%d):" % n)
print("    Mean:       %.4f%%" % (mean_d * 100))
print("    Std:        %.4f%%" % (std_d * 100))
print("    Skewness:   %.3f %s" % (skew, "(negative=left tail risk)" if skew < 0 else "(positive=right skew)"))
print("    Kurtosis:   %.3f %s" % (kurt, "(>0 = fat tails)" if kurt > 0 else ""))
print("    Jarque-Bera: stat=%.2f, p=%.4f %s" % (jb_stat, jb_pval, "(non-normal)" if jb_pval < 0.05 else "(normal)"))

# Tail risk
pct1 = np.percentile(daily_ret, 1)
pct5 = np.percentile(daily_ret, 5)
cvar5 = np.mean(daily_ret[daily_ret <= pct5])
print("    VaR(1%%):    %.2f%%  (worst 1%% of days)" % (pct1 * 100))
print("    VaR(5%%):    %.2f%%  (worst 5%% of days)" % (pct5 * 100))
print("    CVaR(5%%):   %.2f%%  (avg of worst 5%%)" % (cvar5 * 100))
print()

# ====================================================================
# 6. STATISTICAL SIGNIFICANCE
# ====================================================================
print("=" * 80)
print("  6. STATISTICAL SIGNIFICANCE")
print("=" * 80)

# Sharpe significance: t-stat = Sharpe * sqrt(n/252)
sharpe = perf_base.get("sharpe", 0)
t_stat = sharpe * math.sqrt(n / 252)
# degrees of freedom = n - 1
p_value = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n-1))

print("  Sharpe ratio:  %.3f" % sharpe)
print("  t-statistic:   %.3f" % t_stat)
print("  p-value:       %.4f" % p_value)
if p_value < 0.05:
    print("  --> Statistically significant at 5%% level")
elif p_value < 0.10:
    print("  --> Marginally significant at 10%% level")
else:
    print("  --> NOT statistically significant")
print()

# Excess return significance
excess = returns - bench
excess_mean = excess.mean()
excess_std = excess.std()
excess_t = (excess_mean / excess_std) * math.sqrt(n) if excess_std > 0 else 0
excess_p = 2 * (1 - sp_stats.t.cdf(abs(excess_t), df=n-1))

print("  Excess return t-test:")
print("  Daily excess mean:  %.4f%%" % (excess_mean * 100))
print("  t-statistic:        %.3f" % excess_t)
print("  p-value:            %.4f" % excess_p)
if excess_p < 0.05:
    print("  --> Excess return is significant at 5%% level")
elif excess_p < 0.10:
    print("  --> Marginally significant at 10%% level")
else:
    print("  --> NOT statistically significant")
print()

# ====================================================================
# 7. FINAL VERDICT
# ====================================================================
print("=" * 80)
print("  7. INSTITUTIONAL VERDICT")
print("=" * 80)

issues = []
if sharpe < 0.5:
    issues.append("Sharpe below 0.5 threshold")
if p_value > 0.05:
    issues.append("Sharpe not statistically significant (p=%.3f)" % p_value)
if excess_p > 0.05:
    issues.append("Excess return not statistically significant (p=%.3f)" % excess_p)
if ann_turnover > 10:
    issues.append("Very high annualized turnover (%.1fx)" % ann_turnover)
if skew < -0.5:
    issues.append("Negative skew (%.2f) = left tail risk" % skew)
if kurt > 3:
    issues.append("Fat tails (kurtosis=%.2f)" % kurt)

# Param stability check
sharpe_values = []
for param_name, values in perturbations[:3]:  # Top 3 critical params
    for v in values:
        params = {**BASE, param_name: v}
        perf, _ = run_full(params)
        sh = perf.get("sharpe", -99)
        if sh > -99:
            sharpe_values.append(sh)

sharpe_std = np.std(sharpe_values)
if sharpe_std > 0.3:
    issues.append("High parameter sensitivity (Sharpe std=%.3f)" % sharpe_std)

strengths = []
if perf_base.get("excess_cagr", 0) > 10:
    strengths.append("Strong alpha (ExCAGR=%.1f%%)" % perf_base.get("excess_cagr"))
if perf_base.get("information_ratio", 0) > 0.5:
    strengths.append("High IR (%.3f)" % perf_base.get("information_ratio"))
if abs(perf_base.get("max_drawdown", -100)) < abs(perf_base.get("benchmark_max_dd", -100)):
    strengths.append("MaxDD better than benchmark")

print("  Strengths:")
for s in strengths:
    print("    [+] %s" % s)
print("  Issues:")
for issue in issues:
    print("    [-] %s" % issue)

if len(issues) == 0:
    grade = "A+"
elif len(issues) <= 2:
    grade = "A"
elif len(issues) <= 4:
    grade = "B"
else:
    grade = "C"

print()
print("  INSTITUTIONAL GRADE: %s" % grade)
print("=" * 80)
