"""V3.0 vs V2.0 对比验证脚本"""
import sys, os
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

def run_and_eval(bt, label, start=None, end=None):
    sp = strategy_prices
    br = benchmark_returns
    if start:
        sp = sp.loc[start:]
        br = br.loc[start:]
    if end:
        sp = sp.loc[:end]
        br = br.loc[:end]
    result = bt.run(sp, hs300_prices, group_map)
    perf = PerformanceEvaluator.evaluate(result["portfolio_returns"], br, label)
    return perf

# ========== V2.0 Baseline ==========
bt_v2 = MomentumBacktester(
    top_n=4, rebalance_days=10, mom_s_window=20, mom_m_window=60,
    w_mom_s=0.40, w_mom_m=0.30, w_slope=0.15, w_sharpe=0.15,
    w_trend=0.0,  # V2无趋势因子
    stop_loss=-0.08, position_cap=0.85,
    cumulative_stop=False,   # V2: 单日止损
    adaptive_rebalance=False,  # V2: 固定调仓
    dual_ma_regime=False,      # V2: 单MA120
)

# ========== V3.0 Optimized ==========
bt_v3 = MomentumBacktester(
    top_n=4, rebalance_days=10, mom_s_window=20, mom_m_window=60,
    w_mom_s=0.35, w_mom_m=0.25, w_slope=0.15, w_sharpe=0.15,
    w_trend=0.10,              # V3: 趋势因子
    stop_loss=-0.08, position_cap=0.85,
    cumulative_stop=True,      # V3: 累计浮亏止损
    stop_bull=-0.08, stop_range=-0.07, stop_bear=-0.05,
    adaptive_rebalance=True,   # V3: 自适应调仓
    rebal_bull=5, rebal_range=10, rebal_bear=15,
    dual_ma_regime=True,       # V3: 双均线Regime
)

def print_perf(label, p):
    if "error" in p:
        print(f"  [{label}] ERROR: {p['error']}")
        return
    print(f"  [{label}]")
    print(f"    CAGR: {p.get('cagr','?')}%  |  MaxDD: {p.get('max_drawdown','?')}%  |  Sharpe: {p.get('sharpe','?')}")
    print(f"    BenchCAGR: {p.get('benchmark_cagr','?')}%  |  ExcessCAGR: {p.get('excess_cagr','?')}%  |  IR: {p.get('information_ratio','?')}")
    print(f"    Calmar: {p.get('calmar','?')}  |  WinRate: {p.get('monthly_win_rate','?')}%  |  ExWinRate: {p.get('excess_win_rate','?')}%")

print("=" * 80)
print("  V2.0 vs V3.0 对比验证")
print("=" * 80)

# Full period
print("\n--- FULL 2021-2025 ---")
p_v2_full = run_and_eval(bt_v2, "V2.0 Full")
p_v3_full = run_and_eval(bt_v3, "V3.0 Full")
print_perf("V2.0", p_v2_full)
print_perf("V3.0", p_v3_full)

# In-sample
print("\n--- IN-SAMPLE 2021-2023 ---")
p_v2_is = run_and_eval(bt_v2, "V2.0 IS", end="2023-12-31")
p_v3_is = run_and_eval(bt_v3, "V3.0 IS", end="2023-12-31")
print_perf("V2.0", p_v2_is)
print_perf("V3.0", p_v3_is)

# Out-of-sample
print("\n--- OUT-OF-SAMPLE 2024-2025 ---")
p_v2_oos = run_and_eval(bt_v2, "V2.0 OOS", start="2024-01-01")
p_v3_oos = run_and_eval(bt_v3, "V3.0 OOS", start="2024-01-01")
print_perf("V2.0", p_v2_oos)
print_perf("V3.0", p_v3_oos)

# Summary table
print("\n" + "=" * 80)
print("  IMPROVEMENT SUMMARY")
print("=" * 80)
metrics = ["cagr", "max_drawdown", "sharpe", "excess_cagr", "information_ratio", "monthly_win_rate"]
labels = ["CAGR%", "MaxDD%", "Sharpe", "ExcessCAGR%", "IR", "WinRate%"]
for m, l in zip(metrics, labels):
    v2 = p_v2_full.get(m, "?")
    v3 = p_v3_full.get(m, "?")
    if isinstance(v2, (int, float)) and isinstance(v3, (int, float)):
        delta = v3 - v2
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        print(f"  {l:12s}  V2.0={v2:>8}  V3.0={v3:>8}  {arrow} {delta:+.2f}")
    else:
        print(f"  {l:12s}  V2.0={v2}  V3.0={v3}")

# A-rating check
print("\n" + "=" * 80)
print("  A-RATING CHECK")
print("=" * 80)
checks = {
    "Sharpe >= 0.5": p_v3_full.get("sharpe", 0) >= 0.5,
    "Excess CAGR >= 5%": p_v3_full.get("excess_cagr", 0) >= 5.0,
    "MaxDD better than bench": abs(p_v3_full.get("max_drawdown", -100)) < abs(p_v3_full.get("benchmark_max_dd", -100)),
    "IR >= 0.4": p_v3_full.get("information_ratio", 0) >= 0.4,
    "OOS Sharpe >= 0.3": p_v3_oos.get("sharpe", 0) >= 0.3,
    "OOS still beats bench": p_v3_oos.get("excess_cagr", 0) > 0,
    "Win Rate >= 55%": p_v3_full.get("monthly_win_rate", 0) >= 55.0,
}
passed = 0
for check, ok in checks.items():
    icon = "✓" if ok else "✗"
    print(f"  [{icon}] {check}")
    if ok:
        passed += 1
grade = "A" if passed >= 6 else "B" if passed >= 4 else "C" if passed >= 2 else "D"
print(f"\n  GRADE: {grade} ({passed}/{len(checks)} passed)")
print("=" * 80)
