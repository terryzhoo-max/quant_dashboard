"""V3.0 第二轮调优 — 基于Config I的精细调整"""
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

# Base = Config I (best from round 1)
base_I = {
    "top_n": 5, "rebalance_days": 10, "mom_s_window": 20, "mom_m_window": 60,
    "w_mom_s": 0.40, "w_mom_m": 0.20, "w_slope": 0.15, "w_sharpe": 0.15, "w_trend": 0.10,
    "stop_loss": -0.08, "position_cap": 0.90,
    "cumulative_stop": True, "stop_bull": -0.99, "stop_range": -0.10, "stop_bear": -0.07,
    "adaptive_rebalance": True, "rebal_bull": 3, "rebal_range": 10, "rebal_bear": 15,
    "dual_ma_regime": True,
}

configs = [
    ("I: baseline",              {}),
    ("J: top4",                  {"top_n": 4}),
    ("K: cap95",                 {"position_cap": 0.95}),
    ("L: rebal_range=8",         {"rebal_range": 8}),
    ("M: rebal_bear=20",         {"rebal_bear": 20}),
    ("N: stop_bear=-0.05",       {"stop_bear": -0.05}),
    ("O: J+K",                   {"top_n": 4, "position_cap": 0.95}),
    ("P: J+K+L",                 {"top_n": 4, "position_cap": 0.95, "rebal_range": 8}),
    ("Q: J+K+L+M",              {"top_n": 4, "position_cap": 0.95, "rebal_range": 8, "rebal_bear": 20}),
    ("R: J+K+L+N",              {"top_n": 4, "position_cap": 0.95, "rebal_range": 8, "stop_bear": -0.05}),
    ("S: mom_s=45+trend5",       {"w_mom_s": 0.45, "w_mom_m": 0.15, "w_trend": 0.05}),
    ("T: S+J+K+L",              {"w_mom_s": 0.45, "w_mom_m": 0.15, "w_trend": 0.05, "top_n": 4, "position_cap": 0.95, "rebal_range": 8}),
    ("U: mom_s=50+no_trend",     {"w_mom_s": 0.50, "w_mom_m": 0.15, "w_trend": 0.0, "w_slope": 0.20}),
    ("V: U+J+K+L",              {"w_mom_s": 0.50, "w_mom_m": 0.15, "w_trend": 0.0, "w_slope": 0.20, "top_n": 4, "position_cap": 0.95, "rebal_range": 8}),
]

print(f"{'Config':<25s} {'CAGR%':>7s} {'MaxDD%':>7s} {'Sharpe':>7s} {'ExCAGR%':>8s} {'IR':>7s} {'OOS_sh':>7s} {'OOS_ex':>7s} {'WR%':>5s}")
print("-" * 100)

best_label = ""
best_score = -999

for label, overrides in configs:
    params = {**base_I, **overrides}
    bt = MomentumBacktester(**params)

    result_full = bt.run(strategy_prices, hs300_prices, group_map)
    perf_full = PerformanceEvaluator.evaluate(result_full["portfolio_returns"], benchmark_returns, label)

    sp_oos = strategy_prices.loc["2024-01-01":]
    br_oos = benchmark_returns.loc["2024-01-01":]
    result_oos = bt.run(sp_oos, hs300_prices, group_map)
    perf_oos = PerformanceEvaluator.evaluate(result_oos["portfolio_returns"], br_oos, label+" OOS")

    cagr = perf_full.get("cagr", -99)
    mdd = perf_full.get("max_drawdown", -99)
    sharpe = perf_full.get("sharpe", -99)
    ex_cagr = perf_full.get("excess_cagr", -99)
    ir = perf_full.get("information_ratio", -99)
    oos_sh = perf_oos.get("sharpe", -99)
    oos_ex = perf_oos.get("excess_cagr", -99)
    wr = perf_full.get("monthly_win_rate", 0)

    # composite score: sharpe*25 + excess_cagr*30 + ir*20 + oos_sharpe*15 + oos_excess*10
    score = 0.25 * min(max(sharpe, -2), 3) + 0.30 * min(max(ex_cagr/10, -2), 3) + 0.20 * min(max(ir, -2), 2) + 0.15 * min(max(oos_sh, -2), 3) + 0.10 * min(max(oos_ex/10, -2), 3)
    if score > best_score:
        best_score = score
        best_label = label

    marker = " ***" if label == best_label else ""
    print(f"{label:<25s} {cagr:>7} {mdd:>7} {sharpe:>7} {ex_cagr:>8} {ir:>7} {oos_sh:>7} {oos_ex:>7} {wr:>5}{marker}")

print(f"\nBEST: {best_label} (score={best_score:.4f})")
