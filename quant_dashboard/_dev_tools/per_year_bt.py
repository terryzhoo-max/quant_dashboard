"""Per-year backtest breakdown for Momentum V3.0 analysis"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.momentum_backtest_engine import run_momentum_backtest

print("=" * 80)
print("  行业动量轮动 V3.0 · 逐年回测绩效")
print("=" * 80)

# Full period
r = run_momentum_backtest("2021-01-01", "2025-12-31")
if r.get("status") == "success" and "performance" in r:
    p = r["performance"]
    print(f"\n[FULL 2021-2025]")
    print(f"  累计收益: {p.get('cum_return')}%")
    print(f"  年化收益(CAGR): {p.get('cagr')}%")
    print(f"  最大回撤: {p.get('max_drawdown')}%")
    print(f"  年化波动: {p.get('ann_vol')}%")
    print(f"  夏普比率: {p.get('sharpe')}")
    print(f"  Calmar: {p.get('calmar')}")
    print(f"  月度胜率: {p.get('monthly_win_rate')}%")
    print(f"  ---基准(沪深300ETF)---")
    print(f"  基准CAGR: {p.get('benchmark_cagr')}%")
    print(f"  基准最大回撤: {p.get('benchmark_max_dd')}%")
    print(f"  ---超额---")
    print(f"  超额累计: {p.get('excess_cum_return')}%")
    print(f"  超额年化: {p.get('excess_cagr')}%")
    print(f"  跟踪误差: {p.get('tracking_error')}%")
    print(f"  信息比率(IR): {p.get('information_ratio')}")
    print(f"  超额月度胜率: {p.get('excess_win_rate')}%")

# Try 2-period split for out-of-sample
print("\n" + "=" * 80)
print("  样本内/外分割验证")
print("=" * 80)

for label, start, end in [
    ("IN-SAMPLE  2021-2023", "2021-01-01", "2023-12-31"),
    ("OUT-SAMPLE 2024-2025", "2024-01-01", "2025-12-31"),
]:
    r = run_momentum_backtest(start, end)
    if r.get("status") == "success" and "performance" in r:
        p = r["performance"]
        cagr = p.get("cagr", "N/A")
        mdd = p.get("max_drawdown", "N/A")
        sharpe = p.get("sharpe", "N/A")
        bench = p.get("benchmark_cagr", "N/A")
        excess = p.get("excess_cagr", "N/A")
        ir = p.get("information_ratio", "N/A")
        wr = p.get("monthly_win_rate", "N/A")
        print(f"\n[{label}]")
        print(f"  CAGR: {cagr}% | MaxDD: {mdd}% | Sharpe: {sharpe}")
        print(f"  Bench CAGR: {bench}% | Excess CAGR: {excess}% | IR: {ir}")
        print(f"  月度胜率: {wr}%")
    else:
        print(f"\n[{label}] 数据不足，跳过")

print("\n" + "=" * 80)
print("  DONE")
print("=" * 80)
