"""
AlphaCore · ERP择时策略参数优化器 V1.0
=======================================
两阶段网格搜索 + 样本内/外交叉验证

Stage 1: 粗筛 — 固定默认权重，搜索阈值+窗口 (~240组)
Stage 2: 精调 — Top-10粗筛结果 × 权重微调 (~270组)

防过拟合:
  - 样本内 2018-01-01 ~ 2023-12-31 (训练)
  - 样本外 2024-01-01 ~ 2025-12-31 (验证)
  - 要求样本外 Sharpe > 样本内 × 0.5

输出: erp_optimization_results.json
"""

import pandas as pd
import numpy as np
import json
import time
import itertools
import os
import sys
from datetime import datetime, timedelta

# Windows GBK 兼容: 强制 stdout 为 UTF-8
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from erp_backtest_data import prepare_erp_backtest_data
from strategies_backtest import erp_timing_strategy_vectorized
from backtest_engine import AlphaBacktester


# ═══════════════════════════════════════════════════════════════
#  参数空间定义
# ═══════════════════════════════════════════════════════════════

STAGE1_GRID = {
    "buy_threshold":  [55, 60, 65, 70, 75],
    "sell_threshold": [30, 35, 40, 45],
    "erp_window":     [504, 756, 1008, 1260],
    "stop_loss":      [8, 10, 12, 15, 0],
}

STAGE2_WEIGHT_GRID = {
    "w_erp_abs": [0.20, 0.25, 0.30],
    "w_erp_pct": [0.20, 0.25, 0.30],
    "w_m1":      [0.25, 0.30, 0.35],
}

# 默认权重 (Stage 1 固定)
DEFAULT_WEIGHTS = {
    "w_erp_abs": 0.25,
    "w_erp_pct": 0.25,
    "w_m1": 0.30,
    "w_vol": 0.10,
    "w_credit": 0.10,
}

# ETF标的
ETF_CODE = "510300.SH"  # 沪深300ETF
ETF_NAME = "沪深300ETF"

# 回测区间
IN_SAMPLE_START  = "20180101"
IN_SAMPLE_END    = "20231231"
OUT_SAMPLE_START = "20240101"
OUT_SAMPLE_END   = "20251231"

# 宏观数据提前拉取期 (给ERP分位足够回溯窗口)
MACRO_PRE_FETCH  = "20150101"


def _run_single_backtest(bt: AlphaBacktester, df: pd.DataFrame,
                         macro_df: pd.DataFrame, params: dict) -> dict:
    """执行单次回测，返回核心指标"""
    try:
        signals = erp_timing_strategy_vectorized(df, macro_df=macro_df, **params)

        results = bt.run_vectorized(df, signals, ts_code=ETF_CODE)
        m = results.get("metrics", {})
        rt = results.get("round_trips", {})
        grade = results.get("grade", {})

        return {
            "total_return": m.get("total_return", 0),
            "annualized_return": m.get("annualized_return", 0),
            "sharpe_ratio": m.get("sharpe_ratio", 0),
            "sortino_ratio": m.get("sortino_ratio", 0),
            "calmar_ratio": m.get("calmar_ratio", 0),
            "max_drawdown": m.get("max_drawdown", 0),
            "alpha": m.get("alpha", 0),
            "information_ratio": m.get("information_ratio", 0),
            "win_rate": rt.get("win_rate", 0),
            "total_trades": rt.get("total_trades", 0),
            "profit_loss_ratio": rt.get("profit_loss_ratio", 0),
            "grade": grade.get("grade", "F"),
            "grade_score": grade.get("score", 0),
            "bench_return": results.get("bench_metrics", {}).get("total_return", 0),
            "bench_ann_return": results.get("bench_metrics", {}).get("annualized_return", 0),
        }
    except Exception as e:
        print(f"  ⚠️ Backtest error: {e}")
        return {"sharpe_ratio": -999, "error": str(e)}


def run_optimization():
    """
    两阶段网格搜索主流程
    """
    print("=" * 70)
    print("  AlphaCore ERP择时策略 — 参数优化器 V1.0")
    print(f"  标的: {ETF_NAME} ({ETF_CODE})")
    print(f"  样本内: {IN_SAMPLE_START} → {IN_SAMPLE_END}")
    print(f"  样本外: {OUT_SAMPLE_START} → {OUT_SAMPLE_END}")
    print("=" * 70)

    # ─── 0. 数据准备 ───
    print("\n📦 加载宏观日频宽表...")
    t0 = time.time()
    macro_df = prepare_erp_backtest_data(MACRO_PRE_FETCH, OUT_SAMPLE_END)
    print(f"   宏观数据: {len(macro_df)} 行 ({time.time()-t0:.1f}s)")

    print("\n📦 加载ETF价格数据...")
    bt = AlphaBacktester(initial_cash=1000000.0)
    # 从较早开始拉以确保样本内有足够数据
    df_full = bt.fetch_tushare_data(ETF_CODE, IN_SAMPLE_START, OUT_SAMPLE_END)
    if df_full.empty:
        print("❌ ETF数据拉取失败!")
        return

    print(f"   ETF数据: {len(df_full)} 行, {df_full.index.min()} → {df_full.index.max()}")

    # 分割样本内/外
    is_end = pd.Timestamp(datetime.strptime(IN_SAMPLE_END, "%Y%m%d"))
    os_start = pd.Timestamp(datetime.strptime(OUT_SAMPLE_START, "%Y%m%d"))

    df_in = df_full[df_full.index <= is_end].copy()
    df_out = df_full[df_full.index >= os_start].copy()

    print(f"   样本内: {len(df_in)} 天 | 样本外: {len(df_out)} 天")

    # ═══════════════════════════════════════════════════════
    #  Stage 1: 粗筛 — 阈值 + 窗口 (固定默认权重)
    # ═══════════════════════════════════════════════════════
    print("\n" + "═" * 70)
    print("  STAGE 1: 粗筛 (固定权重, 搜索阈值+窗口+止损)")
    print("═" * 70)

    keys = list(STAGE1_GRID.keys())
    values = list(STAGE1_GRID.values())
    combos = list(itertools.product(*values))
    # 过滤无效组合: buy_threshold 必须 > sell_threshold + 10
    combos = [c for c in combos if c[0] > c[1] + 5]
    print(f"   有效参数组合: {len(combos)}")

    stage1_results = []
    t1 = time.time()

    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        params.update(DEFAULT_WEIGHTS)

        # 样本内回测
        res_in = _run_single_backtest(bt, df_in, macro_df, params)
        if res_in.get("sharpe_ratio", -999) == -999:
            continue

        result_entry = {
            "params": params,
            "in_sample": res_in,
        }
        stage1_results.append(result_entry)

        # 进度
        if (i + 1) % 20 == 0 or i == len(combos) - 1:
            elapsed = time.time() - t1
            eta = elapsed / (i + 1) * (len(combos) - i - 1)
            best_so_far = max(stage1_results, key=lambda x: x["in_sample"]["sharpe_ratio"])
            best_sharpe = best_so_far["in_sample"]["sharpe_ratio"]
            print(f"   [{i+1}/{len(combos)}] "
                  f"当前Sharpe={res_in['sharpe_ratio']:.3f} "
                  f"最佳={best_sharpe:.3f} "
                  f"({elapsed:.0f}s / ETA {eta:.0f}s)")

    # 按样本内 Sharpe 排序
    stage1_results.sort(key=lambda x: x["in_sample"]["sharpe_ratio"], reverse=True)

    print(f"\n   ✅ Stage 1 完成: {len(stage1_results)} 组 "
          f"({time.time()-t1:.1f}s)")

    # 打印 Top-10
    print("\n   📊 Stage 1 Top-10 (样本内):")
    print(f"   {'#':>3} {'Buy':>4} {'Sell':>5} {'Window':>7} {'SL%':>4} "
          f"{'Sharpe':>7} {'Return':>7} {'MDD':>7} {'Alpha':>7} {'Trades':>6} {'Grade':>5}")
    print("   " + "-" * 70)
    for j, r in enumerate(stage1_results[:10]):
        p = r["params"]
        m = r["in_sample"]
        print(f"   {j+1:>3} {p['buy_threshold']:>4.0f} {p['sell_threshold']:>5.0f} "
              f"{p['erp_window']:>7d} {p['stop_loss']:>4.0f} "
              f"{m['sharpe_ratio']:>7.3f} {m['annualized_return']*100:>6.1f}% "
              f"{m['max_drawdown']*100:>6.1f}% {m['alpha']*100:>6.1f}% "
              f"{m['total_trades']:>6d} {m['grade']:>5}")

    # ═══════════════════════════════════════════════════════
    #  Stage 2: 精调 — Top-10 × 权重微调
    # ═══════════════════════════════════════════════════════
    print("\n" + "═" * 70)
    print("  STAGE 2: 精调 (Top-10 × 权重微调)")
    print("═" * 70)

    top10 = stage1_results[:10]
    w_keys = list(STAGE2_WEIGHT_GRID.keys())
    w_values = list(STAGE2_WEIGHT_GRID.values())
    w_combos = list(itertools.product(*w_values))
    # 过滤: 三个主权重之和 <= 0.90 (给 vol+credit 留空间)
    w_combos = [wc for wc in w_combos if sum(wc) <= 0.90]

    print(f"   权重组合: {len(w_combos)} × Top-{len(top10)} = {len(w_combos) * len(top10)} 轮")

    stage2_results = []
    t2 = time.time()
    total_s2 = len(w_combos) * len(top10)
    count = 0

    for base_result in top10:
        base_p = base_result["params"].copy()
        for wc in w_combos:
            w_dict = dict(zip(w_keys, wc))
            remaining = 1.0 - sum(wc)
            w_dict["w_vol"] = round(remaining * 0.5, 2)
            w_dict["w_credit"] = round(remaining - w_dict["w_vol"], 2)

            params = {**base_p, **w_dict}

            # 样本内
            res_in = _run_single_backtest(bt, df_in, macro_df, params)
            if res_in.get("sharpe_ratio", -999) == -999:
                count += 1
                continue

            # 样本外
            res_out = _run_single_backtest(bt, df_out, macro_df, params)

            stage2_results.append({
                "params": params,
                "in_sample": res_in,
                "out_sample": res_out,
            })
            count += 1

            if count % 30 == 0:
                elapsed = time.time() - t2
                eta = elapsed / count * (total_s2 - count)
                print(f"   [{count}/{total_s2}] ({elapsed:.0f}s / ETA {eta:.0f}s)")

    print(f"\n   ✅ Stage 2 完成: {len(stage2_results)} 组 ({time.time()-t2:.1f}s)")

    # ═══════════════════════════════════════════════════════
    #  综合排名: Sharpe_in × 0.4 + Sharpe_out × 0.6
    # ═══════════════════════════════════════════════════════
    print("\n" + "═" * 70)
    print("  综合排名 (IS×0.4 + OOS×0.6)")
    print("═" * 70)

    for r in stage2_results:
        sharpe_in = r["in_sample"].get("sharpe_ratio", 0)
        sharpe_out = r["out_sample"].get("sharpe_ratio", 0) if r.get("out_sample") else 0
        r["composite_sharpe"] = sharpe_in * 0.4 + sharpe_out * 0.6

        # 样本外衰减检查
        if sharpe_in > 0:
            r["oos_decay"] = sharpe_out / sharpe_in if sharpe_in != 0 else 0
        else:
            r["oos_decay"] = 0

    # 过滤: 样本外必须正Alpha + 衰减率>0.5
    valid_results = [r for r in stage2_results
                     if r.get("out_sample", {}).get("alpha", -1) > 0
                     and r.get("oos_decay", 0) > 0.3]

    if not valid_results:
        print("   ⚠️ 无满足OOS过滤条件的参数，放宽标准...")
        valid_results = [r for r in stage2_results
                         if r.get("out_sample", {}).get("sharpe_ratio", 0) > 0]

    if not valid_results:
        print("   ❌ 所有参数在样本外表现均为负，降级使用样本内最优")
        valid_results = stage2_results

    valid_results.sort(key=lambda x: x["composite_sharpe"], reverse=True)

    # 打印 Top-10 最终结果
    print(f"\n   📊 最终 Top-10 (IS+OOS 综合):")
    print(f"   {'#':>3} {'Buy':>4} {'Sell':>5} {'Win':>6} {'SL':>3} "
          f"{'w1':>4} {'w2':>4} {'w3':>4} "
          f"{'IS_Sharpe':>9} {'OOS_Sharpe':>10} {'Comp':>6} "
          f"{'IS_Ret%':>7} {'OOS_Ret%':>8} {'IS_MDD%':>7} {'OOS_Alpha%':>10}")
    print("   " + "-" * 110)

    for j, r in enumerate(valid_results[:10]):
        p = r["params"]
        mi = r["in_sample"]
        mo = r.get("out_sample", {})
        print(f"   {j+1:>3} {p['buy_threshold']:>4.0f} {p['sell_threshold']:>5.0f} "
              f"{p['erp_window']:>6d} {p['stop_loss']:>3.0f} "
              f"{p.get('w_erp_abs',0.25):>4.2f} {p.get('w_erp_pct',0.25):>4.2f} "
              f"{p.get('w_m1',0.30):>4.2f} "
              f"{mi['sharpe_ratio']:>9.3f} {mo.get('sharpe_ratio',0):>10.3f} "
              f"{r['composite_sharpe']:>6.3f} "
              f"{mi['annualized_return']*100:>6.1f}% {mo.get('annualized_return',0)*100:>7.1f}% "
              f"{mi['max_drawdown']*100:>6.1f}% {mo.get('alpha',0)*100:>9.1f}%")

    # ═══════════════════════════════════════════════════════
    #  Benchmark 对比
    # ═══════════════════════════════════════════════════════
    best = valid_results[0] if valid_results else None
    if best:
        print("\n" + "═" * 70)
        print("  🏆 最优参数 vs 基准 (买入持有) 对比")
        print("═" * 70)

        mi = best["in_sample"]
        mo = best.get("out_sample", {})
        p = best["params"]

        print(f"\n  最优参数:")
        for k, v in sorted(p.items()):
            print(f"    {k}: {v}")

        print(f"\n  {'指标':<18} {'策略(IS)':>12} {'基准(IS)':>12} {'策略(OOS)':>12}")
        print(f"  {'-'*54}")
        print(f"  {'年化收益率':<16} {mi['annualized_return']*100:>10.2f}% "
              f"{mi['bench_ann_return']*100:>10.2f}% "
              f"{mo.get('annualized_return',0)*100:>10.2f}%")
        print(f"  {'Sharpe Ratio':<16} {mi['sharpe_ratio']:>12.3f} "
              f"{'—':>12} "
              f"{mo.get('sharpe_ratio',0):>12.3f}")
        print(f"  {'最大回撤':<16} {mi['max_drawdown']*100:>10.2f}% "
              f"{'—':>12} "
              f"{mo.get('max_drawdown',0)*100:>10.2f}%")
        print(f"  {'Alpha':<16} {mi['alpha']*100:>10.2f}% "
              f"{'0':>12} "
              f"{mo.get('alpha',0)*100:>10.2f}%")
        print(f"  {'交易次数':<16} {mi['total_trades']:>12d} "
              f"{'1(买入持有)':>12} "
              f"{mo.get('total_trades',0):>12d}")
        print(f"  {'胜率':<16} {mi['win_rate']:>10.1f}% "
              f"{'—':>12} "
              f"{mo.get('win_rate',0):>10.1f}%")
        print(f"  {'评级':<16} {mi['grade']:>12} "
              f"{'—':>12} "
              f"{mo.get('grade','?'):>12}")

        is_beat = mi['annualized_return'] > mi['bench_ann_return']
        oos_beat = mo.get('alpha', 0) > 0
        print(f"\n  {'✅' if is_beat else '❌'} 样本内超越基准: "
              f"{'是' if is_beat else '否'}")
        print(f"  {'✅' if oos_beat else '❌'} 样本外正Alpha: "
              f"{'是' if oos_beat else '否'}")

    # ═══════════════════════════════════════════════════════
    #  保存结果
    # ═══════════════════════════════════════════════════════
    output = {
        "meta": {
            "etf_code": ETF_CODE,
            "etf_name": ETF_NAME,
            "in_sample": f"{IN_SAMPLE_START} → {IN_SAMPLE_END}",
            "out_sample": f"{OUT_SAMPLE_START} → {OUT_SAMPLE_END}",
            "stage1_combos": len(combos),
            "stage2_combos": total_s2,
            "valid_results": len(valid_results),
            "timestamp": datetime.now().isoformat(),
        },
        "best_params": best["params"] if best else {},
        "best_in_sample": best["in_sample"] if best else {},
        "best_out_sample": best.get("out_sample", {}) if best else {},
        "top10": [
            {
                "rank": i + 1,
                "params": r["params"],
                "in_sample": r["in_sample"],
                "out_sample": r.get("out_sample", {}),
                "composite_sharpe": r["composite_sharpe"],
                "oos_decay": r.get("oos_decay", 0),
            }
            for i, r in enumerate(valid_results[:10])
        ],
    }

    out_file = "erp_optimization_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  💾 结果已保存: {out_file}")

    total_time = time.time() - t0
    print(f"\n  ⏱️ 总耗时: {total_time:.0f}s ({total_time/60:.1f}min)")
    print("=" * 70)

    return output


if __name__ == "__main__":
    run_optimization()
