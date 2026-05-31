"""
AlphaCore H1 回测: AIAE V5 阈值重设计验证
==========================================
目的: 用 2014-2026 历史数据对比两套阈值方案的换挡行为差异

方案A (现状):  thresholds=[22.8, 24.0, 26.5, 28.3], hysteresis=0.5
方案B (建议):  thresholds=[22.0, 24.0, 27.0, 29.0], hysteresis=0.3
方案C (保守):  thresholds=[22.0, 24.0, 27.0, 29.0], hysteresis=0.5

评估指标:
  1. 换挡频次 (越少越稳定)
  2. 各档位有效持续月数分布
  3. Ⅱ档有效占比 (当前方案A的 Ⅱ档几乎不存在)
  4. 仓位路径对比 (结合ERP的实际矩阵仓位)
  5. 极端市场识别能力 (2015股灾/2018贸易战/2020疫情/2022调整)

数据源: data_lake/aiae_true_history.parquet (月频, 含 aiae_simple + erp_tier)
"""

import pandas as pd
import numpy as np
import os
import json
from datetime import datetime

# ── 数据加载 ──
DATA_PATH = "data_lake/aiae_true_history.parquet"

def load_data():
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"回测数据不存在: {DATA_PATH}")
    df = pd.read_parquet(DATA_PATH)
    df = df.sort_values("month").reset_index(drop=True)
    print(f"[回测] 加载 {len(df)} 条月度数据: {df['month'].iloc[0]} → {df['month'].iloc[-1]}")
    print(f"[回测] aiae_simple 范围: [{df['aiae_simple'].min():.2f}%, {df['aiae_simple'].max():.2f}%]")
    print(f"[回测] aiae_simple 均值: {df['aiae_simple'].mean():.2f}%, 中位数: {df['aiae_simple'].median():.2f}%")
    return df


# ── 阈值方案定义 ──
SCENARIOS = {
    "A_current": {
        "label": "方案A (现状)",
        "thresholds": [22.8, 24.0, 26.5, 28.3],
        "hysteresis": 0.5,
    },
    "B_proposed": {
        "label": "方案B (建议: 拉宽+收窄迟滞)",
        "thresholds": [22.0, 24.0, 27.0, 29.0],
        "hysteresis": 0.3,
    },
    "C_conservative": {
        "label": "方案C (仅拉宽, 保持迟滞0.5)",
        "thresholds": [22.0, 24.0, 27.0, 29.0],
        "hysteresis": 0.5,
    },
}

# V5 仓位矩阵 (与 aiae_params.py 一致)
V5_POSITION_MATRIX = {
    "erp_gt6":  [80, 75, 65, 40, 15],
    "erp_4_6":  [75, 70, 60, 35, 10],
    "erp_2_4":  [70, 60, 50, 25,  5],
    "erp_lt2":  [60, 50, 35, 15,  0],
}


# ── 核心: 带迟滞的 Regime 分类 (复现 aiae_engine.py 逻辑) ──
def classify_regime_with_hysteresis(value, thresholds, hysteresis, prev_regime=None):
    """方向感知的迟滞分类 (与 aiae_engine.py classify_regime 完全一致)"""
    t = thresholds
    H = hysteresis

    if prev_regime is None:
        for i, th in enumerate(t):
            if value < th:
                return i + 1
        return 5

    effective = []
    for i, th in enumerate(t):
        lower_regime = i + 1
        upper_regime = i + 2
        if prev_regime <= lower_regime:
            effective.append(th + H)   # 上行: 需超过更多才升档
        elif prev_regime >= upper_regime:
            effective.append(th - H)   # 下行: 需跌破更多才降档
        else:
            effective.append(th)

    for i, th in enumerate(effective):
        if value < th:
            return i + 1
    return 5


def get_position(regime, erp_tier):
    """从仓位矩阵获取建议仓位"""
    tier_key = erp_tier if erp_tier in V5_POSITION_MATRIX else "erp_2_4"
    positions = V5_POSITION_MATRIX[tier_key]
    return positions[regime - 1]


# ── 回测主逻辑 ──
def run_backtest(df, scenario_key, scenario):
    thresholds = scenario["thresholds"]
    hysteresis = scenario["hysteresis"]

    regimes = []
    positions = []
    transitions = []
    prev_regime = None

    for idx, row in df.iterrows():
        aiae_simple = row["aiae_simple"]
        erp_tier = row.get("erp_tier", "erp_2_4")
        if pd.isna(erp_tier) or erp_tier == "":
            erp_tier = "erp_2_4"

        regime = classify_regime_with_hysteresis(
            aiae_simple, thresholds, hysteresis, prev_regime
        )

        pos = get_position(regime, erp_tier)

        if prev_regime is not None and regime != prev_regime:
            transitions.append({
                "month": row["month"],
                "from": prev_regime,
                "to": regime,
                "aiae_simple": round(aiae_simple, 2),
                "direction": "up" if regime > prev_regime else "down",
            })

        regimes.append(regime)
        positions.append(pos)
        prev_regime = regime

    df_result = df[["month", "aiae_simple"]].copy()
    df_result["regime"] = regimes
    df_result["position"] = positions

    return df_result, transitions


def analyze_results(df_result, transitions, scenario):
    """分析单个方案的回测结果"""
    label = scenario["label"]
    thresholds = scenario["thresholds"]

    # 1. 基础统计
    total_months = len(df_result)
    total_transitions = len(transitions)
    transition_rate = round(total_transitions / max(total_months - 1, 1) * 100, 1)

    # 2. 各档位分布
    regime_dist = df_result["regime"].value_counts().sort_index()
    regime_pct = (regime_dist / total_months * 100).round(1)

    # 3. 各档位连续持续月数
    runs = []
    current_regime = df_result["regime"].iloc[0]
    current_run = 1
    for i in range(1, len(df_result)):
        if df_result["regime"].iloc[i] == current_regime:
            current_run += 1
        else:
            runs.append({"regime": current_regime, "duration": current_run})
            current_regime = df_result["regime"].iloc[i]
            current_run = 1
    runs.append({"regime": current_regime, "duration": current_run})

    avg_duration = {}
    for r in range(1, 6):
        r_runs = [x["duration"] for x in runs if x["regime"] == r]
        if r_runs:
            avg_duration[r] = round(np.mean(r_runs), 1)
        else:
            avg_duration[r] = 0

    # 4. 阈值间距
    gaps = [round(thresholds[i+1] - thresholds[i], 1) for i in range(len(thresholds)-1)]
    min_gap = min(gaps)

    # 5. 仓位统计
    avg_pos = round(df_result["position"].mean(), 1)
    pos_std = round(df_result["position"].std(), 1)

    # 6. 极端市场识别
    key_periods = {
        "2015-06": "股灾",
        "2015-07": "股灾续",
        "2018-10": "贸易战底",
        "2020-03": "疫情冲击",
        "2022-04": "调整底",
        "2024-09": "政策底",
    }
    extreme_check = {}
    for month, event in key_periods.items():
        match = df_result[df_result["month"] == month]
        if not match.empty:
            extreme_check[event] = {
                "month": month,
                "aiae_simple": round(float(match["aiae_simple"].iloc[0]), 2),
                "regime": int(match["regime"].iloc[0]),
                "position": int(match["position"].iloc[0]),
            }

    return {
        "label": label,
        "thresholds": thresholds,
        "hysteresis": scenario["hysteresis"],
        "total_months": total_months,
        "total_transitions": total_transitions,
        "transition_rate_pct": transition_rate,
        "regime_distribution": {f"R{k}": f"{v}%" for k, v in regime_pct.items()},
        "regime_months": {f"R{k}": int(v) for k, v in regime_dist.items()},
        "avg_duration_months": {f"R{k}": v for k, v in avg_duration.items()},
        "threshold_gaps": gaps,
        "min_gap": min_gap,
        "avg_position": avg_pos,
        "position_std": pos_std,
        "extreme_events": extreme_check,
        "transitions": transitions,
    }


def format_report(results):
    """生成可读报告"""
    lines = []
    lines.append("=" * 80)
    lines.append("  AlphaCore H1: AIAE V5 Threshold Backtest Report")
    lines.append(f"  Generated: {datetime.now().isoformat()}")
    lines.append("=" * 80)

    for key, r in results.items():
        lines.append("")
        lines.append(f"--- {r['label']} ---")
        lines.append(f"  Thresholds: {r['thresholds']}  Hysteresis: {r['hysteresis']}")
        lines.append(f"  Gaps: {r['threshold_gaps']}  Min gap: {r['min_gap']}pt")
        lines.append(f"  Data: {r['total_months']} months")
        lines.append("")
        lines.append(f"  [Switching]")
        lines.append(f"    Total transitions: {r['total_transitions']}")
        lines.append(f"    Transition rate: {r['transition_rate_pct']}% (per month)")
        lines.append("")
        lines.append(f"  [Regime Distribution]")
        for regime, pct in r['regime_distribution'].items():
            months = r['regime_months'].get(regime, 0)
            avg_dur = r['avg_duration_months'].get(regime, 0)
            lines.append(f"    {regime}: {pct:>6s} ({months:>3d} months, avg run: {avg_dur:.1f} months)")
        lines.append("")
        lines.append(f"  [Position]")
        lines.append(f"    Average: {r['avg_position']}%  StdDev: {r['position_std']}%")
        lines.append("")
        lines.append(f"  [Extreme Events]")
        for event, data in r['extreme_events'].items():
            lines.append(f"    {event} ({data['month']}): AIAE_简={data['aiae_simple']}% -> R{data['regime']} -> {data['position']}%")

    # Comparison summary
    lines.append("")
    lines.append("=" * 80)
    lines.append("  COMPARISON SUMMARY")
    lines.append("=" * 80)
    keys = list(results.keys())
    lines.append(f"  {'Metric':<30s} | " + " | ".join(f"{results[k]['label'][:20]:>20s}" for k in keys))
    lines.append("  " + "-" * (32 + 23 * len(keys)))

    metrics = [
        ("Transitions", "total_transitions"),
        ("Transition rate", "transition_rate_pct"),
        ("Min gap (pt)", "min_gap"),
        ("Avg position (%)", "avg_position"),
        ("Position StdDev", "position_std"),
    ]
    for name, key in metrics:
        vals = [str(results[k][key]) for k in keys]
        lines.append(f"  {name:<30s} | " + " | ".join(f"{v:>20s}" for v in vals))

    # R2 comparison (the key problem)
    lines.append("")
    lines.append("  [R2 (Ⅱ档) Focus - the core issue]")
    for k in keys:
        r2_months = results[k]['regime_months'].get('R2', 0)
        r2_pct = results[k]['regime_distribution'].get('R2', '0%')
        r2_dur = results[k]['avg_duration_months'].get('R2', 0)
        lines.append(f"    {results[k]['label'][:30]:30s}: {r2_months:>3d} months ({r2_pct:>5s}), avg run: {r2_dur:.1f} months")

    return "\n".join(lines)


# ── MAIN ──
if __name__ == "__main__":
    df = load_data()

    results = {}
    for key, scenario in SCENARIOS.items():
        print(f"\n[回测] Running: {scenario['label']}...")
        df_result, transitions = run_backtest(df, key, scenario)
        analysis = analyze_results(df_result, transitions, scenario)
        results[key] = analysis
        print(f"  Transitions: {analysis['total_transitions']}, R2 months: {analysis['regime_months'].get('R2', 0)}")

    report = format_report(results)
    print("\n" + report)

    # Save report
    report_path = os.path.join("data_lake", "h1_backtest_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n[回测] Report saved to: {report_path}")

    # Save JSON for further analysis
    json_path = os.path.join("data_lake", "h1_backtest_results.json")
    # Clean transitions for JSON serialization
    for key in results:
        results[key]["transitions"] = results[key]["transitions"][:50]  # Keep first 50 for review
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"[回测] JSON saved to: {json_path}")
