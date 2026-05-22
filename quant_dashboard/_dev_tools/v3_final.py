"""V3.0 FINAL A-rating validation"""
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
strategy_prices = price_matrix.drop(columns=[BENCHMARK_CODE], errors="ignore")
benchmark_returns = benchmark_prices.pct_change().dropna()
hs300_prices = load_price_matrix(["000300.SH"], "2021-01-01", "2025-12-31", dm).get("000300.SH")

# FINAL V3.0 Config
params = dict(
    top_n=5, rebalance_days=10, mom_s_window=20, mom_m_window=60,
    w_mom_s=0.40, w_mom_m=0.20, w_slope=0.15, w_sharpe=0.15, w_trend=0.10,
    stop_loss=-0.08, position_cap=0.90,
    cumulative_stop=True, stop_bull=-0.99, stop_range=-0.10, stop_bear=-0.07,
    adaptive_rebalance=True, rebal_bull=3, rebal_range=10, rebal_bear=20,
    dual_ma_regime=True,
)
bt = MomentumBacktester(**params)

def run_eval(sp, br, label):
    result = bt.run(sp, hs300_prices, group_map)
    return PerformanceEvaluator.evaluate(result["portfolio_returns"], br, label)

# Three periods
p_full = run_eval(strategy_prices, benchmark_returns, "FULL")
p_is = run_eval(strategy_prices.loc[:"2023-12-31"], benchmark_returns.loc[:"2023-12-31"], "IS")
p_oos = run_eval(strategy_prices.loc["2024-01-01":], benchmark_returns.loc["2024-01-01":], "OOS")

keys = ["cagr", "max_drawdown", "sharpe", "calmar", "ann_vol", "monthly_win_rate",
        "benchmark_cagr", "benchmark_max_dd", "excess_cagr", "information_ratio", "excess_win_rate"]

print("=" * 70)
print("  V3.0 FINAL PERFORMANCE REPORT")
print("=" * 70)
for label, perf in [("FULL 2021-2025", p_full), ("IN-SAMPLE 2021-2023", p_is), ("OUT-OF-SAMPLE 2024-2025", p_oos)]:
    if "error" in perf:
        print("  [%s] ERROR: %s" % (label, perf["error"]))
        continue
    print("  [%s]" % label)
    for k in keys:
        v = perf.get(k, "N/A")
        print("    %-20s: %s" % (k, v))
    print()

# A-Rating Check
print("=" * 70)
print("  A-RATING VALIDATION")
print("=" * 70)
checks = [
    ("Sharpe >= 0.5",              p_full.get("sharpe", 0) >= 0.5),
    ("Excess CAGR >= 5%",          p_full.get("excess_cagr", 0) >= 5.0),
    ("MaxDD < Bench MaxDD",        abs(p_full.get("max_drawdown", -100)) < abs(p_full.get("benchmark_max_dd", -100))),
    ("IR >= 0.4",                  p_full.get("information_ratio", 0) >= 0.4),
    ("OOS Sharpe >= 0.3",          p_oos.get("sharpe", 0) >= 0.3),
    ("OOS beats benchmark",        p_oos.get("excess_cagr", 0) > 0),
    ("Monthly WinRate >= 45%",     p_full.get("monthly_win_rate", 0) >= 45.0),
]
passed = 0
for name, ok in checks:
    status = "PASS" if ok else "FAIL"
    print("  [%s] %s" % (status, name))
    if ok:
        passed += 1
grade = "A" if passed >= 6 else "B" if passed >= 4 else "C"
print()
print("  GRADE: %s (%d/%d passed)" % (grade, passed, len(checks)))
print("=" * 70)
