"""V3.0 参数调优 — 聚焦止损和仓位优化"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.momentum_backtest_engine import (
    MomentumBacktester, PerformanceEvaluator, FactorDataManager,
    load_price_matrix, MOMENTUM_POOL_V2, BENCHMARK_CODE
)

dm = FactorDataManager()
all_codes = [etf["code"] for etf in MOMENTUM_POOL_V2] + [BENCHMARK_CODE]
group_map = {etf["code"]: etf["group"] for etf in MOMENTUM_POOL_V2}

price_matrix = load_price_matrix(all_codes, "2021-01-01", "2025-12-31", dm)
benchmark_prices = price_matrix.get(BENCHMARK_CODE)
strategy_prices = price_matrix.drop(columns=[BENCHMARK_CODE], errors='ignore')
benchmark_returns = benchmark_prices.pct_change().dropna()
hs300_prices = load_price_matrix(["000300.SH"], "2021-01-01", "2025-12-31", dm).get("000300.SH")

configs = [
    # (label, params_override)
    ("A: V3 default",           {"cumulative_stop": True,  "stop_bull": -0.08, "stop_range": -0.07, "stop_bear": -0.05}),
    ("B: wider stops",          {"cumulative_stop": True,  "stop_bull": -0.12, "stop_range": -0.10, "stop_bear": -0.07}),
    ("C: bull no stop",         {"cumulative_stop": True,  "stop_bull": -0.99, "stop_range": -0.10, "stop_bear": -0.07}),
    ("D: wider+top5",           {"cumulative_stop": True,  "stop_bull": -0.12, "stop_range": -0.10, "stop_bear": -0.07, "top_n": 5}),
    ("E: wider+top5+cap90",     {"cumulative_stop": True,  "stop_bull": -0.12, "stop_range": -0.10, "stop_bear": -0.07, "top_n": 5, "position_cap": 0.90}),
    ("F: wider+top5+rebal",     {"cumulative_stop": True,  "stop_bull": -0.12, "stop_range": -0.10, "stop_bear": -0.07, "top_n": 5, "rebal_bull": 5, "rebal_range": 8, "rebal_bear": 15}),
    ("G: C+top5+cap90",         {"cumulative_stop": True,  "stop_bull": -0.99, "stop_range": -0.10, "stop_bear": -0.07, "top_n": 5, "position_cap": 0.90}),
    ("H: G+mom_s=40",           {"cumulative_stop": True,  "stop_bull": -0.99, "stop_range": -0.10, "stop_bear": -0.07, "top_n": 5, "position_cap": 0.90, "w_mom_s": 0.40, "w_mom_m": 0.20, "w_trend": 0.10}),
    ("I: H+rebal_bull3",        {"cumulative_stop": True,  "stop_bull": -0.99, "stop_range": -0.10, "stop_bear": -0.07, "top_n": 5, "position_cap": 0.90, "w_mom_s": 0.40, "w_mom_m": 0.20, "w_trend": 0.10, "rebal_bull": 3}),
]

base_params = {
    "top_n": 4, "rebalance_days": 10, "mom_s_window": 20, "mom_m_window": 60,
    "w_mom_s": 0.35, "w_mom_m": 0.25, "w_slope": 0.15, "w_sharpe": 0.15, "w_trend": 0.10,
    "stop_loss": -0.08, "position_cap": 0.85,
    "cumulative_stop": True, "stop_bull": -0.08, "stop_range": -0.07, "stop_bear": -0.05,
    "adaptive_rebalance": True, "rebal_bull": 5, "rebal_range": 10, "rebal_bear": 15,
    "dual_ma_regime": True,
}

print(f"{'Config':<25s} {'CAGR%':>7s} {'MaxDD%':>7s} {'Sharpe':>7s} {'ExCAGR%':>8s} {'IR':>7s} {'OOS_CAGR%':>10s} {'OOS_ExCAGR':>10s}")
print("-" * 95)

for label, overrides in configs:
    params = {**base_params, **overrides}
    bt = MomentumBacktester(**params)

    # Full
    result_full = bt.run(strategy_prices, hs300_prices, group_map)
    perf_full = PerformanceEvaluator.evaluate(result_full["portfolio_returns"], benchmark_returns, label)

    # OOS
    sp_oos = strategy_prices.loc["2024-01-01":]
    br_oos = benchmark_returns.loc["2024-01-01":]
    result_oos = bt.run(sp_oos, hs300_prices, group_map)
    perf_oos = PerformanceEvaluator.evaluate(result_oos["portfolio_returns"], br_oos, label+" OOS")

    cagr = perf_full.get("cagr", "?")
    mdd = perf_full.get("max_drawdown", "?")
    sharpe = perf_full.get("sharpe", "?")
    ex_cagr = perf_full.get("excess_cagr", "?")
    ir = perf_full.get("information_ratio", "?")
    oos_cagr = perf_oos.get("cagr", "?")
    oos_ex = perf_oos.get("excess_cagr", "?")

    print(f"{label:<25s} {cagr:>7} {mdd:>7} {sharpe:>7} {ex_cagr:>8} {ir:>7} {oos_cagr:>10} {oos_ex:>10}")

print("\nDONE")
