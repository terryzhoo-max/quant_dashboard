"""
rebal_bear 敏感性根因分析
为什么 rebal_bear=20 比 15 和 22 好这么多？
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from strategies.momentum_backtest_engine import (
    MomentumBacktester, PerformanceEvaluator, FactorDataManager,
    load_price_matrix, MOMENTUM_POOL_V2, BENCHMARK_CODE
)

dm = FactorDataManager()
all_codes = [etf["code"] for etf in MOMENTUM_POOL_V2] + [BENCHMARK_CODE]
group_map = {etf["code"]: etf["group"] for etf in MOMENTUM_POOL_V2}
price_matrix = load_price_matrix(all_codes, "2021-01-01", "2025-12-31", dm)
benchmark_prices = price_matrix.get(BENCHMARK_CODE)
strategy_prices = price_matrix.drop(columns=[BENCHMARK_CODE], errors="ignore")
benchmark_returns = benchmark_prices.pct_change().dropna()
hs300_prices = load_price_matrix(["000300.SH"], "2021-01-01", "2025-12-31", dm).get("000300.SH")

BASE = dict(
    top_n=5, rebalance_days=10, mom_s_window=20, mom_m_window=60,
    w_mom_s=0.40, w_mom_m=0.20, w_slope=0.15, w_sharpe=0.15, w_trend=0.10,
    stop_loss=-0.08, position_cap=0.90,
    cumulative_stop=True, stop_bull=-0.99, stop_range=-0.10, stop_bear=-0.07,
    adaptive_rebalance=True, rebal_bull=3, rebal_range=10, rebal_bear=20,
    dual_ma_regime=True,
)

print("=" * 80)
print("  PART 1: rebal_bear fine-grid (every integer 12-30)")
print("=" * 80)

for rb in range(12, 31):
    params = {**BASE, "rebal_bear": rb}
    bt = MomentumBacktester(**params)
    result = bt.run(strategy_prices, hs300_prices, group_map)
    perf = PerformanceEvaluator.evaluate(result["portfolio_returns"], benchmark_returns, "test")
    cagr = perf.get("cagr", -99)
    sh = perf.get("sharpe", -99)
    ex = perf.get("excess_cagr", -99)
    mdd = perf.get("max_drawdown", -99)
    marker = " <== BASE" if rb == 20 else ""
    print("  rebal_bear=%2d  CAGR=%6.2f%%  Sharpe=%6.3f  ExCAGR=%6.2f%%  MaxDD=%6.2f%%%s" % (
        rb, cagr, sh, ex, mdd, marker))

# Part 2: Test if combining rebal_bear with a range improves stability
# Use average of results across 18-22 as a "band" approach
print()
print("=" * 80)
print("  PART 2: Stabilization strategy — use MEDIAN of multiple rebal_bear runs")
print("=" * 80)
print("  (Not modifiable in engine, but shows what 'true' Sharpe is across the band)")

for band in [(15,25), (17,23), (18,22), (19,21)]:
    sharpes = []
    cagrs = []
    for rb in range(band[0], band[1]+1):
        params = {**BASE, "rebal_bear": rb}
        bt = MomentumBacktester(**params)
        result = bt.run(strategy_prices, hs300_prices, group_map)
        perf = PerformanceEvaluator.evaluate(result["portfolio_returns"], benchmark_returns, "test")
        sharpes.append(perf.get("sharpe", 0))
        cagrs.append(perf.get("cagr", 0))
    print("  Band [%d-%d]: Median Sharpe=%.3f  Mean CAGR=%.2f%%  Min Sharpe=%.3f" % (
        band[0], band[1], np.median(sharpes), np.mean(cagrs), min(sharpes)))

# Part 3: Alternative stabilization — fixed rebal_bear=20 but random noise on rebal timing
# Simulates real-world execution uncertainty
print()
print("=" * 80)
print("  PART 3: Monte Carlo — perturb ALL key params simultaneously (50 runs)")
print("=" * 80)

rng = np.random.RandomState(42)
mc_sharpes = []
mc_cagrs = []
mc_exs = []

for trial in range(50):
    params = {
        **BASE,
        "rebal_bear": rng.choice([18, 19, 20, 21, 22]),
        "rebal_bull": rng.choice([2, 3, 4, 5]),
        "rebal_range": rng.choice([8, 9, 10, 11, 12]),
        "top_n": rng.choice([4, 5, 6]),
        "stop_bear": rng.choice([-0.06, -0.07, -0.08]),
        "w_mom_s": rng.choice([0.35, 0.40, 0.45]),
    }
    bt = MomentumBacktester(**params)
    result = bt.run(strategy_prices, hs300_prices, group_map)
    perf = PerformanceEvaluator.evaluate(result["portfolio_returns"], benchmark_returns, "mc")
    sh = perf.get("sharpe", -99)
    cagr = perf.get("cagr", -99)
    ex = perf.get("excess_cagr", -99)
    if sh > -99:
        mc_sharpes.append(sh)
        mc_cagrs.append(cagr)
        mc_exs.append(ex)

print("  50 Monte Carlo runs (random params within reasonable band):")
print("  Sharpe:    Median=%.3f  Mean=%.3f  Min=%.3f  Max=%.3f  Std=%.3f" % (
    np.median(mc_sharpes), np.mean(mc_sharpes), min(mc_sharpes), max(mc_sharpes), np.std(mc_sharpes)))
print("  CAGR:      Median=%.2f%%  Mean=%.2f%%  Min=%.2f%%  Max=%.2f%%" % (
    np.median(mc_cagrs), np.mean(mc_cagrs), min(mc_cagrs), max(mc_cagrs)))
print("  ExCAGR:    Median=%.2f%%  Mean=%.2f%%  Min=%.2f%%  Max=%.2f%%" % (
    np.median(mc_exs), np.mean(mc_exs), min(mc_exs), max(mc_exs)))
print("  Pct Sharpe>0:  %.0f%%" % (100 * sum(1 for s in mc_sharpes if s > 0) / len(mc_sharpes)))
print("  Pct ExCAGR>0:  %.0f%%" % (100 * sum(1 for e in mc_exs if e > 0) / len(mc_exs)))
print("  Pct Sharpe>0.3: %.0f%%" % (100 * sum(1 for s in mc_sharpes if s > 0.3) / len(mc_sharpes)))

print()
print("=" * 80)
print("  VERDICT")
print("=" * 80)
