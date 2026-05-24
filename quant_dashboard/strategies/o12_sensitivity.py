"""
V3.3 O12 参数敏感性分析
=======================
测试 O12_PENALTY_MAX × O12_K 的 4×4 组合，评估:
- IS Alpha / MDD 改善
- OOS Sharpe / Calmar 稳定性
- 熊市仓位变化

基线 (当前): PENALTY=-8, K=0.10
"""
import sys, os
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
sys.path.insert(0, os.path.dirname(_dir))
os.chdir(_dir)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import time
import pandas as pd
import numpy as np
import erp_params
from erp_backtest_data import prepare_erp_backtest_data
from backtest_engine import AlphaBacktester
from erp_position_backtest import compute_composite_series, run_position_backtest

t0 = time.time()
print("=" * 80)
print("  V3.3 O12 参数敏感性分析")
print("=" * 80)

# 数据
macro_df = prepare_erp_backtest_data("20150101", "20251231")
bt = AlphaBacktester(initial_cash=1000000.0)
df_full = bt.fetch_tushare_data("510300.SH", "20180101", "20251231")
df_is = df_full[df_full.index < "2024-01-01"]
df_oos = df_full[df_full.index >= "2024-01-01"]

# 基线 (V3.2 = O12 off)
print("\n📊 基线 (O12 OFF):")
orig_enabled = erp_params.O12_ENABLED
erp_params.O12_ENABLED = False
scores_is_base = compute_composite_series(macro_df, df_is.index)
scores_oos_base = compute_composite_series(macro_df, df_oos.index)
r_is_base = run_position_backtest(df_is, scores_is_base)
r_oos_base = run_position_backtest(df_oos, scores_oos_base)
erp_params.O12_ENABLED = True

mi_base = r_is_base["metrics"]
mo_base = r_oos_base["metrics"]
print(f"  IS:  Alpha={mi_base['alpha']*100:+.2f}%  Sharpe={mi_base['sharpe_ratio']:.3f}  "
      f"MDD={mi_base['max_drawdown']*100:.1f}%  调仓={mi_base['total_trades']}  仓位={mi_base['avg_position']*100:.0f}%")
print(f"  OOS: Alpha={mo_base['alpha']*100:+.2f}%  Sharpe={mo_base['sharpe_ratio']:.3f}  "
      f"MDD={mo_base['max_drawdown']*100:.1f}%  调仓={mo_base['total_trades']}  仓位={mo_base['avg_position']*100:.0f}%")

# 参数网格
PENALTY_VALUES = [-6, -8, -10, -12]
K_VALUES = [0.08, 0.10, 0.15, 0.20]

results = []

print(f"\n📊 O12 参数网格: {len(PENALTY_VALUES)}×{len(K_VALUES)} = {len(PENALTY_VALUES)*len(K_VALUES)} 组合")
print(f"{'Penalty':>8s} {'K':>6s} | {'IS_Alpha':>8s} {'IS_Shp':>7s} {'IS_MDD':>7s} {'IS_Tr':>5s} "
      f"{'IS_Pos':>6s} | {'OOS_Shp':>7s} {'OOS_MDD':>8s} {'OOS_Cal':>7s} {'OOS_Tr':>6s} {'OOS_Pos':>7s} | {'ΔAlpha':>7s} {'ΔMDD':>6s}")
print("-" * 120)

for penalty in PENALTY_VALUES:
    for k in K_VALUES:
        # 设置参数
        erp_params.O12_PENALTY_MAX = penalty
        erp_params.O12_K = k
        erp_params.O12_ENABLED = True

        # 回测
        scores_is = compute_composite_series(macro_df, df_is.index)
        scores_oos = compute_composite_series(macro_df, df_oos.index)
        r_is = run_position_backtest(df_is, scores_is)
        r_oos = run_position_backtest(df_oos, scores_oos)

        mi = r_is["metrics"]
        mo = r_oos["metrics"]

        d_alpha = mi["alpha"] - mi_base["alpha"]
        d_mdd = mi["max_drawdown"] - mi_base["max_drawdown"]  # 负值变小 = 改善

        mark = ""
        if penalty == -8 and k == 0.10:
            mark = " ← 当前"

        print(f"  {penalty:>6d} {k:>6.2f} | {mi['alpha']*100:>+7.2f}% {mi['sharpe_ratio']:>7.3f} "
              f"{mi['max_drawdown']*100:>6.1f}% {mi['total_trades']:>5d} {mi['avg_position']*100:>5.0f}% | "
              f"{mo['sharpe_ratio']:>7.3f} {mo['max_drawdown']*100:>7.1f}% {mo['calmar_ratio']:>7.3f} "
              f"{mo['total_trades']:>5d} {mo['avg_position']*100:>6.0f}% | "
              f"{d_alpha*100:>+6.2f}% {d_mdd*100:>+5.1f}%{mark}")

        results.append({
            "penalty": penalty, "k": k,
            "is_alpha": mi["alpha"], "is_sharpe": mi["sharpe_ratio"],
            "is_mdd": mi["max_drawdown"], "is_trades": mi["total_trades"],
            "is_pos": mi["avg_position"],
            "oos_sharpe": mo["sharpe_ratio"], "oos_mdd": mo["max_drawdown"],
            "oos_calmar": mo["calmar_ratio"], "oos_trades": mo["total_trades"],
            "oos_pos": mo["avg_position"],
            "d_alpha": d_alpha, "d_mdd": d_mdd,
        })

# 恢复原始参数
erp_params.O12_PENALTY_MAX = -8
erp_params.O12_K = 0.10
erp_params.O12_ENABLED = orig_enabled

# 排名
print("\n" + "=" * 80)
print("  综合排名 (IS Alpha↑ + OOS Sharpe↑ + IS MDD↑ 三维)")
print("=" * 80)

df = pd.DataFrame(results)
# 标准化后加权: IS Alpha 0.3, OOS Sharpe 0.4, IS MDD改善 0.3
for col in ["is_alpha", "oos_sharpe", "is_mdd"]:
    mn, mx = df[col].min(), df[col].max()
    if mx > mn:
        df[f"{col}_norm"] = (df[col] - mn) / (mx - mn)
    else:
        df[f"{col}_norm"] = 0.5

# MDD 越小 (越负) 越差, 所以 norm 已经正确 (更高=更好)
df["composite"] = (df["is_alpha_norm"] * 0.3 +
                   df["oos_sharpe_norm"] * 0.4 +
                   df["is_mdd_norm"] * 0.3)
df = df.sort_values("composite", ascending=False)

print(f"\n{'Rank':>4s} {'Penalty':>8s} {'K':>6s} {'IS_Alpha':>9s} {'OOS_Shp':>8s} {'IS_MDD':>8s} {'Score':>6s}")
print("-" * 55)
for i, (_, row) in enumerate(df.head(5).iterrows()):
    mark = " ★" if row["penalty"] == -8 and row["k"] == 0.10 else ""
    print(f"  {i+1:>2d}. {row['penalty']:>6.0f} {row['k']:>6.2f} "
          f"{row['is_alpha']*100:>+8.2f}% {row['oos_sharpe']:>8.3f} "
          f"{row['is_mdd']*100:>7.1f}% {row['composite']:>6.3f}{mark}")

best = df.iloc[0]
print(f"\n  🏆 最优: Penalty={best['penalty']:.0f}, K={best['k']:.2f}")
print(f"     IS Alpha={best['is_alpha']*100:+.2f}% | OOS Sharpe={best['oos_sharpe']:.3f} | IS MDD={best['is_mdd']*100:.1f}%")

# 与当前对比
current = df[(df["penalty"] == -8) & (df["k"] == 0.10)]
if not current.empty:
    c = current.iloc[0]
    rank = df.index.get_loc(current.index[0]) + 1
    print(f"\n  当前 (Penalty=-8, K=0.10): 排名 {rank}/{len(df)}")
    if rank <= 3:
        print(f"  → 当前参数已在 Top 3, 无需调整")
    else:
        print(f"  → 建议切换到最优参数")

print(f"\n  ⏱️ 总耗时: {time.time()-t0:.0f}s")
print("=" * 80)
