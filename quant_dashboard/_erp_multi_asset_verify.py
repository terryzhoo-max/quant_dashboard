"""
ERP择时策略 — 多标的验证 (最优参数)
沪深300ETF / 中证500ETF / 红利ETF
"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
from erp_backtest_data import prepare_erp_backtest_data
from strategies_backtest import erp_timing_strategy_vectorized
from backtest_engine import AlphaBacktester

# 最优参数 (来自优化器 Top-1)
BEST_PARAMS = {
    "buy_threshold": 55,
    "sell_threshold": 40,
    "erp_window": 1008,
    "stop_loss": 0,
    "w_erp_abs": 0.20,
    "w_erp_pct": 0.30,
    "w_m1": 0.35,
    "w_vol": 0.08,
    "w_credit": 0.07,
}

# 回测标的
TARGETS = [
    {"code": "510300.SH", "name": "沪深300ETF"},
    {"code": "510500.SH", "name": "中证500ETF"},
    {"code": "510880.SH", "name": "红利ETF"},
    {"code": "510900.SH", "name": "H股ETF"},
    {"code": "513180.SH", "name": "恒生科技ETF"},
]

IS_START, IS_END = "20180101", "20231231"
OOS_START, OOS_END = "20240101", "20251231"

def run_one(bt, macro_df, df, label):
    signals = erp_timing_strategy_vectorized(df, macro_df=macro_df, **BEST_PARAMS)
    res = bt.run_vectorized(df, signals, ts_code=label)
    m = res["metrics"]
    bm = res["bench_metrics"]
    rt = res["round_trips"]
    g = res["grade"]
    return {
        "ann_ret": m["annualized_return"] * 100,
        "bench_ann": bm["annualized_return"] * 100,
        "alpha": m["alpha"] * 100,
        "sharpe": m["sharpe_ratio"],
        "sortino": m["sortino_ratio"],
        "mdd": m["max_drawdown"] * 100,
        "calmar": m["calmar_ratio"],
        "trades": rt["total_trades"],
        "winrate": rt["win_rate"],
        "plr": rt["profit_loss_ratio"],
        "grade": g["grade"],
        "score": g["score"],
    }

print("=" * 90)
print("  ERP择时策略 — 多标的交叉验证 (最优参数)")
print("=" * 90)

# 1. 加载宏观数据
print("\n[1/3] 加载宏观日频宽表...")
macro_df = prepare_erp_backtest_data("20150101", OOS_END)

bt = AlphaBacktester(initial_cash=1000000.0)

all_results = {}

for target in TARGETS:
    code, name = target["code"], target["name"]
    print(f"\n{'─'*90}")
    print(f"  {name} ({code})")
    print(f"{'─'*90}")

    # 拉取数据
    df_full = bt.fetch_tushare_data(code, IS_START, OOS_END)
    if df_full.empty:
        print(f"  ❌ 数据拉取失败: {code}")
        continue

    is_end_ts = pd.Timestamp("20231231")
    oos_start_ts = pd.Timestamp("20240101")
    df_in = df_full[df_full.index <= is_end_ts].copy()
    df_out = df_full[df_full.index >= oos_start_ts].copy()

    print(f"  样本内: {len(df_in)} 天 | 样本外: {len(df_out)} 天")

    # 样本内
    res_in = run_one(bt, macro_df, df_in, code)
    # 样本外
    res_out = run_one(bt, macro_df, df_out, code)

    all_results[name] = {"in": res_in, "out": res_out}

    print(f"\n  {'指标':<16} {'样本内':>10} {'样本外':>10}")
    print(f"  {'-'*38}")
    print(f"  {'策略年化':<14} {res_in['ann_ret']:>9.2f}% {res_out['ann_ret']:>9.2f}%")
    print(f"  {'基准年化':<14} {res_in['bench_ann']:>9.2f}% {res_out['bench_ann']:>9.2f}%")
    print(f"  {'Alpha':<14} {res_in['alpha']:>9.2f}% {res_out['alpha']:>9.2f}%")
    print(f"  {'Sharpe':<14} {res_in['sharpe']:>10.3f} {res_out['sharpe']:>10.3f}")
    print(f"  {'Sortino':<14} {res_in['sortino']:>10.3f} {res_out['sortino']:>10.3f}")
    print(f"  {'MDD':<14} {res_in['mdd']:>9.2f}% {res_out['mdd']:>9.2f}%")
    print(f"  {'Calmar':<14} {res_in['calmar']:>10.3f} {res_out['calmar']:>10.3f}")
    print(f"  {'交易次数':<14} {res_in['trades']:>10d} {res_out['trades']:>10d}")
    print(f"  {'胜率':<14} {res_in['winrate']:>9.1f}% {res_out['winrate']:>9.1f}%")
    print(f"  {'盈亏比':<14} {res_in['plr']:>10.2f} {res_out['plr']:>10.2f}")
    print(f"  {'评级':<14} {res_in['grade']:>10} {res_out['grade']:>10}")

    beat_in = res_in["ann_ret"] > res_in["bench_ann"]
    beat_out = res_out["alpha"] > 0
    print(f"\n  {'✅' if beat_in else '❌'} 样本内跑赢基准  {'✅' if beat_out else '❌'} 样本外正Alpha")

# 汇总表
print("\n" + "=" * 90)
print("  ═══ 全标的汇总对比 ═══")
print("=" * 90)
print(f"\n  {'标的':<12} {'IS年化':>8} {'IS Alpha':>9} {'IS Sharpe':>10} "
      f"{'OOS年化':>9} {'OOS Alpha':>10} {'OOS Sharpe':>11} {'OOS MDD':>8} {'OOS评级':>7}")
print(f"  {'-'*88}")
for name, r in all_results.items():
    ri, ro = r["in"], r["out"]
    print(f"  {name:<10} {ri['ann_ret']:>7.2f}% {ri['alpha']:>8.2f}% {ri['sharpe']:>10.3f} "
          f"{ro['ann_ret']:>8.2f}% {ro['alpha']:>9.2f}% {ro['sharpe']:>11.3f} "
          f"{ro['mdd']:>7.2f}% {ro['grade']:>7}")

# 判定
all_beat = all(r["out"]["alpha"] > 0 for r in all_results.values())
print(f"\n  {'✅ 全部标的在样本外均产生正Alpha!' if all_beat else '⚠️ 部分标的在样本外未能产生正Alpha'}")
print("=" * 90)
