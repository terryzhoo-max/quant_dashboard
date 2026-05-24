"""
V3.2 仓位管理优化 — Score 分布分析 + 参数敏感性测试
"""
import sys, os
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
sys.path.insert(0, os.path.dirname(_dir))
os.chdir(_dir)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import time, json
import pandas as pd
import numpy as np
from erp_backtest_data import prepare_erp_backtest_data
from backtest_engine import AlphaBacktester
from erp_position_backtest import compute_composite_series, run_position_backtest, _score_to_position
import erp_params

t0 = time.time()
print("=" * 70)
print("  V3.2 仓位优化 — Score 分布 + 参数敏感性")
print("=" * 70)

# 数据
macro_df = prepare_erp_backtest_data("20150101", "20251231")
bt = AlphaBacktester(initial_cash=1000000.0)
df_full = bt.fetch_tushare_data("510300.SH", "20180101", "20251231")

is_end = pd.Timestamp("20231231")
os_start = pd.Timestamp("20240101")
df_in = df_full[df_full.index <= is_end].copy()
df_out = df_full[df_full.index >= os_start].copy()

# ═══════════════════════════════════════════════════════════════
#  1. Score 分布分析
# ═══════════════════════════════════════════════════════════════

print("\n📊 Score 分布分析")
print("-" * 50)

for label, df_p in [("IS", df_in), ("OOS", df_out)]:
    scores = compute_composite_series(macro_df, df_p.index)
    print(f"\n  {label} ({len(scores)} 天):")
    print(f"    Mean:   {scores.mean():.1f}")
    print(f"    Median: {scores.median():.1f}")
    print(f"    Std:    {scores.std():.1f}")
    print(f"    Min:    {scores.min():.1f}")
    print(f"    Max:    {scores.max():.1f}")

    # 各信号级别分布
    T = erp_params.SIGNAL_THRESHOLDS
    bins = [0, T["underweight"], T["reduce"], T["hold"], T["buy"], T["strong_buy"], 100]
    labels_b = ["cash(<25)", "underweight(25-40)", "reduce(40-55)", "hold(55-70)", "buy(70-80)", "strong_buy(80+)"]
    cats = pd.cut(scores, bins=bins, labels=labels_b, right=False)
    dist = cats.value_counts().sort_index()
    total = len(scores)
    for name, count in dist.items():
        pct = count / total * 100
        bar = "█" * int(pct / 2)
        print(f"    {name:>22s}: {count:>4d} ({pct:>5.1f}%) {bar}")

    # 55 附近的精细分布 (关键区域)
    near_55 = ((scores >= 50) & (scores < 60)).sum()
    near_70 = ((scores >= 65) & (scores < 75)).sum()
    print(f"    Score 50-60 (hold边界):  {near_55:>4d} ({near_55/total*100:.1f}%)")
    print(f"    Score 65-75 (buy边界):   {near_70:>4d} ({near_70/total*100:.1f}%)")

# ═══════════════════════════════════════════════════════════════
#  2. 参数敏感性测试 — 仓位映射 + 调仓阈值
# ═══════════════════════════════════════════════════════════════

print("\n\n" + "=" * 70)
print("  参数敏感性测试")
print("=" * 70)

# 测试矩阵
POSITION_MAPS = {
    "保守(当前)":  {80: 0.90, 70: 0.70, 55: 0.60, 40: 0.40, 25: 0.20, 0: 0.05},
    "适度偏多":    {80: 0.90, 70: 0.75, 55: 0.65, 40: 0.45, 25: 0.25, 0: 0.05},
    "积极":       {80: 0.95, 70: 0.80, 55: 0.70, 40: 0.50, 25: 0.30, 0: 0.10},
}
REBALANCE_THRESHOLDS = [0.05, 0.08, 0.10]

results_grid = []

for map_name, pos_map in POSITION_MAPS.items():
    for rb_thresh in REBALANCE_THRESHOLDS:
        # 动态替换 _score_to_position
        def make_scorer(pm):
            thresholds = sorted(pm.keys(), reverse=True)
            def _scorer(score):
                for t in thresholds:
                    if score >= t:
                        return pm[t]
                return pm[min(pm.keys())]
            return _scorer

        import erp_position_backtest as epb
        original_fn = epb._score_to_position
        epb._score_to_position = make_scorer(pos_map)

        for label, df_p in [("IS", df_in), ("OOS", df_out)]:
            scores = compute_composite_series(macro_df, df_p.index)
            result = run_position_backtest(df_p, scores,
                                           rebalance_threshold=rb_thresh)
            m = result["metrics"]
            results_grid.append({
                "map": map_name, "rb_thresh": rb_thresh, "period": label,
                "ann_return": m["annualized_return"],
                "alpha": m["alpha"],
                "sharpe": m["sharpe_ratio"],
                "max_dd": m["max_drawdown"],
                "calmar": m["calmar_ratio"],
                "trades": m["total_trades"],
                "avg_pos": m["avg_position"],
                "cost": m["total_cost"],
            })

        epb._score_to_position = original_fn

# 打印结果
print(f"\n{'Map':>12s} {'RB%':>4s} {'Period':>3s} "
      f"{'AnnRet%':>8s} {'Alpha%':>7s} {'Sharpe':>7s} {'MDD%':>7s} "
      f"{'Calmar':>7s} {'Trades':>6s} {'AvgPos%':>7s} {'Cost':>6s}")
print("-" * 90)

for r in results_grid:
    print(f"{r['map']:>12s} {r['rb_thresh']*100:>3.0f}% {r['period']:>3s} "
          f"{r['ann_return']*100:>7.2f}% {r['alpha']*100:>6.2f}% {r['sharpe']:>7.3f} "
          f"{r['max_dd']*100:>6.2f}% {r['calmar']:>7.3f} {r['trades']:>6d} "
          f"{r['avg_pos']*100:>6.1f}% {r['cost']:>6.0f}")

# 综合评分: IS_Alpha × 0.3 + OOS_Sharpe × 0.4 + (1-|OOS_MDD|) × 0.3
print("\n\n  📊 综合排名 (IS_Alpha×0.3 + OOS_Sharpe×0.4 + OOS_MDD控制×0.3)")
print("-" * 70)

combos = {}
for r in results_grid:
    key = (r["map"], r["rb_thresh"])
    if key not in combos:
        combos[key] = {}
    combos[key][r["period"]] = r

rankings = []
for key, periods in combos.items():
    if "IS" in periods and "OOS" in periods:
        is_r = periods["IS"]
        oos_r = periods["OOS"]
        composite = (
            is_r["alpha"] * 100 * 0.3 +
            oos_r["sharpe"] * 0.4 +
            (1 - abs(oos_r["max_dd"])) * 100 * 0.3
        )
        rankings.append({
            "map": key[0], "rb": key[1],
            "composite": composite,
            "is_alpha": is_r["alpha"],
            "oos_sharpe": oos_r["sharpe"],
            "oos_mdd": oos_r["max_dd"],
            "oos_alpha": oos_r["alpha"],
            "oos_avg_pos": oos_r["avg_pos"],
            "is_trades": is_r["trades"],
            "oos_trades": oos_r["trades"],
        })

rankings.sort(key=lambda x: x["composite"], reverse=True)
for i, r in enumerate(rankings):
    marker = " ⭐" if i == 0 else ""
    print(f"  #{i+1} {r['map']:>12s} RB={r['rb']*100:.0f}% "
          f"Comp={r['composite']:.2f} "
          f"IS_α={r['is_alpha']*100:+.1f}% "
          f"OOS_Sharpe={r['oos_sharpe']:.3f} "
          f"OOS_MDD={r['oos_mdd']*100:.1f}% "
          f"OOS_α={r['oos_alpha']*100:+.1f}% "
          f"OOS_Pos={r['oos_avg_pos']*100:.0f}%"
          f"{marker}")

print(f"\n  ⏱️ 总耗时: {time.time()-t0:.0f}s")
print("=" * 70)
