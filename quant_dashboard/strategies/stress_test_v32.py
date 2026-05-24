"""
V3.2 压力测试 — 极端行情分段分析
=================================
将 IS+OOS 全区间按 A 股关键行情分段, 评估策略在不同市场环境下的表现。

分段:
  2018 (贸易战熊市)       → 策略应降仓防御
  2019-2020H1 (慢牛+疫情) → 策略应维持仓位
  2020H2-2021 (结构牛)    → 策略应偏多
  2022 (二次探底)          → 策略应降仓防御
  2023 (震荡磨底)          → 策略应逐步加仓
  2024-2025 (反弹)         → 策略应维持中高仓位
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
from erp_position_backtest import compute_composite_series, run_position_backtest
import erp_params

t0 = time.time()
print("=" * 70)
print("  V3.2 压力测试 — 极端行情分段分析")
print("=" * 70)

# 数据
macro_df = prepare_erp_backtest_data("20150101", "20251231")
bt = AlphaBacktester(initial_cash=1000000.0)
df_full = bt.fetch_tushare_data("510300.SH", "20180101", "20251231")

# 行情分段
REGIMES = [
    ("2018 贸易战熊市",   "20180101", "20181231", "bear",   "降仓防御"),
    ("2019 慢牛启动",     "20190101", "20191231", "bull",   "维持/加仓"),
    ("2020 疫情冲击+修复", "20200101", "20201231", "mixed",  "先守后攻"),
    ("2021 结构分化",     "20210101", "20211231", "mixed",  "维持中仓"),
    ("2022 系统性回撤",   "20220101", "20221231", "bear",   "降仓防御"),
    ("2023 震荡磨底",     "20230101", "20231231", "bottom", "逐步加仓"),
    ("2024 反弹行情",     "20240101", "20241231", "bull",   "加仓"),
    ("2025 延续",         "20250101", "20251231", "mixed",  "维持"),
]

results = []

print(f"\n{'行情':<20s} {'基准%':>7s} {'策略%':>7s} {'Alpha%':>7s} "
      f"{'Sharpe':>7s} {'MDD%':>7s} {'仓位%':>6s} {'调仓':>4s} "
      f"{'预期':>10s} {'评价':>6s}")
print("-" * 100)

for name, start, end, regime, expected in REGIMES:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    df_seg = df_full[(df_full.index >= start_ts) & (df_full.index <= end_ts)].copy()

    if len(df_seg) < 20:
        print(f"  {name:<20s} 数据不足 ({len(df_seg)} 天), 跳过")
        continue

    scores = compute_composite_series(macro_df, df_seg.index)
    result = run_position_backtest(df_seg, scores)
    m = result["metrics"]

    # 评价
    avg_pos = m["avg_position"]
    alpha = m["alpha"]
    mdd = m["max_drawdown"]

    if regime == "bear":
        # 熊市: 低仓位 + 小回撤 = 好
        if avg_pos < 0.50 and mdd > -0.20:
            verdict = "✅ 达标"
        elif avg_pos < 0.60:
            verdict = "⚠️ 偏高"
        else:
            verdict = "❌ 失败"
    elif regime == "bull":
        # 牛市: 高仓位 = 好 (alpha 为负可接受)
        if avg_pos > 0.55:
            verdict = "✅ 达标"
        elif avg_pos > 0.40:
            verdict = "⚠️ 偏低"
        else:
            verdict = "❌ 失败"
    elif regime == "bottom":
        # 磨底: 逐步加仓, alpha > 0 = 好
        if alpha > -0.03:
            verdict = "✅ 达标"
        else:
            verdict = "⚠️ 保守"
    else:
        # mixed: 有节奏即可
        if mdd > -0.25:
            verdict = "✅ 达标"
        else:
            verdict = "⚠️ 回撤"

    print(f"  {name:<20s} {m['bench_ann_return']*100:>6.1f}% {m['annualized_return']*100:>6.1f}% "
          f"{alpha*100:>6.1f}% {m['sharpe_ratio']:>7.3f} {mdd*100:>6.1f}% "
          f"{avg_pos*100:>5.0f}% {m['total_trades']:>4d} "
          f"{expected:>10s} {verdict:>6s}")

    results.append({
        "name": name, "regime": regime, "expected": expected,
        "verdict": verdict,
        "bench_ann": m["bench_ann_return"],
        "ann_return": m["annualized_return"],
        "alpha": alpha, "sharpe": m["sharpe_ratio"],
        "mdd": mdd, "avg_pos": avg_pos, "trades": m["total_trades"],
        "score_mean": float(scores.mean()),
        "score_std": float(scores.std()),
    })

# 汇总
print("\n" + "=" * 70)
print("  汇总")
print("=" * 70)

pass_count = sum(1 for r in results if "✅" in r["verdict"])
warn_count = sum(1 for r in results if "⚠️" in r["verdict"])
fail_count = sum(1 for r in results if "❌" in r["verdict"])
total = len(results)

print(f"\n  ✅ 达标: {pass_count}/{total}")
print(f"  ⚠️ 警告: {warn_count}/{total}")
print(f"  ❌ 失败: {fail_count}/{total}")

# 熊市防御能力
bear_results = [r for r in results if r["regime"] == "bear"]
if bear_results:
    avg_bear_mdd = np.mean([r["mdd"] for r in bear_results])
    avg_bear_pos = np.mean([r["avg_pos"] for r in bear_results])
    print(f"\n  熊市防御: 平均仓位 {avg_bear_pos*100:.0f}%, 平均 MDD {avg_bear_mdd*100:.1f}%")

# 牛市参与能力
bull_results = [r for r in results if r["regime"] == "bull"]
if bull_results:
    avg_bull_pos = np.mean([r["avg_pos"] for r in bull_results])
    avg_bull_alpha = np.mean([r["alpha"] for r in bull_results])
    print(f"  牛市参与: 平均仓位 {avg_bull_pos*100:.0f}%, 平均 Alpha {avg_bull_alpha*100:.1f}%")

# Score 分布特征
print(f"\n  Score 特征 (按行情):")
for r in results:
    print(f"    {r['name']:<20s} Mean={r['score_mean']:>5.1f} Std={r['score_std']:>5.1f} Pos={r['avg_pos']*100:>4.0f}%")

print(f"\n  ⏱️ 总耗时: {time.time()-t0:.0f}s")
print("=" * 70)
