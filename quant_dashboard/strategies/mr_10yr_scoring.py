"""
均值回归 V4.2 · 机构级策略评分计算
"""
import json, sys, os
import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except Exception: pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

RESULT_FILE = os.path.join(os.path.dirname(__file__), "mr_10yr_results.json")

with open(RESULT_FILE, "r", encoding="utf-8") as f:
    r = json.load(f)

overall = r["overall"]
yearly = r["yearly"]
regime_perf = r["regime_perf"]
eq = np.array(r["equity_values"])
bm = np.array(r["bm_values"])
ret = np.diff(eq) / eq[:-1]
bm_ret_arr = np.diff(bm) / bm[:-1]

print("=" * 60)
print("  机构级多维度策略评分 · 均值回归 V4.2")
print("=" * 60)

# ─── 1. 绝对收益 ───
print("\n[1] 绝对收益")
print(f"  年化收益率: {overall['ann_ret']:+.2f}%")
print(f"  累计收益率: {overall['total_ret']:+.2f}%")

# ─── 2. 相对收益 ───
print("\n[2] 相对收益 (vs 沪深300ETF)")
print(f"  年化 Alpha: {overall['alpha']:+.2f}%")
total_alpha = overall['total_ret'] - overall['total_bm']
print(f"  累计 Alpha: {total_alpha:+.2f}%")

# ─── 3. 风险调整收益 ───
print("\n[3] 风险调整收益")
print(f"  Sharpe Ratio:  {overall['sharpe']:.3f}")
print(f"  Calmar Ratio:  {overall['calmar']:.3f}")
print(f"  IR:            {overall['ir']:.3f}")

# Sortino
down_ret = ret[ret < 0]
downside_vol = np.sqrt(252) * np.std(down_ret) if len(down_ret) > 0 else 1
sortino = (np.mean(ret) * 252 - 0.025) / downside_vol
print(f"  Sortino Ratio: {sortino:.3f}")

# ─── 4. 风险控制 ───
print("\n[4] 风险控制")
print(f"  最大回撤: {overall['max_dd']:.2f}%")
print(f"  年化波动率: {overall['ann_vol']:.2f}%")

# Underwater analysis
peak = np.maximum.accumulate(eq)
underwater = (eq - peak) / peak * 100
pct_underwater = (underwater < -1).sum() / len(underwater) * 100
avg_underwater = underwater.mean()
print(f"  平均水下深度: {avg_underwater:.2f}%")
print(f"  水下时间占比(>1%): {pct_underwater:.1f}%")

# Max consecutive DD days
max_dd_days = 0
cur_dd_days = 0
for u in underwater:
    if u < -0.5:
        cur_dd_days += 1
        max_dd_days = max(max_dd_days, cur_dd_days)
    else:
        cur_dd_days = 0
print(f"  最长连续回撤天数: {max_dd_days}")

# Tail ratio
p95 = np.percentile(ret, 95)
p5 = abs(np.percentile(ret, 5))
tail_ratio = p95 / p5 if p5 > 0 else 0
print(f"  尾部比率 (P95/|P5|): {tail_ratio:.3f}")

# ─── 5. 一致性 ───
print("\n[5] 一致性 / 稳定性")
print(f"  周胜率: {overall['win_rate']:.1f}%")

# Positive alpha years
yearly_alphas = [d["alpha"] for y, d in sorted(yearly.items())]
pos_alpha_years = sum(1 for a in yearly_alphas if a > 0)
total_years = len(yearly_alphas)
print(f"  正Alpha年份: {pos_alpha_years}/{total_years} ({pos_alpha_years/total_years*100:.0f}%)")

# Max consecutive losing
max_consec_loss = 0
cur_loss = 0
for a in yearly_alphas:
    if a < 0:
        cur_loss += 1
        max_consec_loss = max(max_consec_loss, cur_loss)
    else:
        cur_loss = 0
print(f"  最长连续跑输年数: {max_consec_loss}")

# Rolling 1yr beat rate
if len(eq) > 252:
    strat_1yr = [(eq[i] / eq[i - 252] - 1) * 100 for i in range(252, len(eq))]
    bm_1yr = [(bm[i] / bm[i - 252] - 1) * 100 for i in range(252, len(bm))]
    beat_count = sum(1 for s, b in zip(strat_1yr, bm_1yr) if s > b)
    total = len(strat_1yr)
    beat_rate = beat_count / total * 100
    print(f"  滚动1年跑赢概率: {beat_count}/{total} = {beat_rate:.1f}%")
    print(f"  滚动1年策略: min={min(strat_1yr):.2f}% max={max(strat_1yr):.2f}% avg={np.mean(strat_1yr):.2f}%")
else:
    beat_rate = 0

# Return per unit risk
ret_per_risk = overall['ann_ret'] / abs(overall['max_dd']) if abs(overall['max_dd']) > 0.01 else 0
print(f"  收益/风险比: {ret_per_risk:.3f}")

# ─── 6. 容量与流动性 ───
print("\n[6] 容量与实操性")
print(f"  持仓覆盖率: {overall['coverage']:.1f}%")
print(f"  标的类型: ETF（高流动性）")
print(f"  单边费率假设: 0.10%")
# Turnover estimation
w_changes = np.abs(np.diff(ret > 0))
avg_daily_turnover = w_changes.mean()
ann_turnover = avg_daily_turnover * 252
print(f"  信号切换频率: ~{w_changes.sum():.0f} 次/10年")

# ─── 7. Regime 适应性 ───
print("\n[7] Regime 适应性")
for regime_name in ["BULL", "RANGE", "BEAR", "CRASH"]:
    if regime_name in regime_perf:
        d = regime_perf[regime_name]
        print(f"  {regime_name:6s}: {d['days']:4d}天 策略{d['cum_ret']:+8.2f}% 基准{d['cum_bm']:+9.2f}% Alpha{d['cum_alpha']:+9.2f}%")

# ─── 8. 鲁棒性 ───
print("\n[8] 鲁棒性")
# First half vs second half
mid = len(eq) // 2
first_half_ret = (eq[mid] / eq[0] - 1) * 100
second_half_ret = (eq[-1] / eq[mid] - 1) * 100
bm_first = (bm[mid] / bm[0] - 1) * 100
bm_second = (bm[-1] / bm[mid] - 1) * 100
print(f"  前半段(2016-2021): 策略{first_half_ret:+.2f}% 基准{bm_first:+.2f}%")
print(f"  后半段(2021-2026): 策略{second_half_ret:+.2f}% 基准{bm_second:+.2f}%")

# Yearly alpha volatility
alpha_vol = np.std(yearly_alphas)
alpha_mean = np.mean(yearly_alphas)
print(f"  年度Alpha均值: {alpha_mean:+.2f}%")
print(f"  年度Alpha波动: {alpha_vol:.2f}%")
alpha_ir = alpha_mean / alpha_vol if alpha_vol > 0.01 else 0
print(f"  Alpha信息比: {alpha_ir:.3f}")

# ═══════════════════════════════════════════════════════════
#  机构级综合评分
# ═══════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("  📊 机构级综合评分卡")
print("=" * 60)

scores = {}

# D1: 绝对收益能力 (0-10)
# 年化 < 0% = 0-2, 0-5% = 3-5, 5-10% = 6-7, 10-15% = 8, >15% = 9-10
ann = overall['ann_ret']
if ann < -5: d1 = 0
elif ann < 0: d1 = 1
elif ann < 3: d1 = 3
elif ann < 6: d1 = 5
elif ann < 10: d1 = 7
elif ann < 15: d1 = 8
else: d1 = 9
scores["绝对收益能力"] = d1

# D2: 超额收益 Alpha (0-10)
alpha = overall['alpha']
if alpha < -10: d2 = 0
elif alpha < -5: d2 = 1
elif alpha < -2: d2 = 2
elif alpha < 0: d2 = 3
elif alpha < 3: d2 = 5
elif alpha < 6: d2 = 7
elif alpha < 10: d2 = 8
else: d2 = 10
scores["超额收益Alpha"] = d2

# D3: Sharpe Ratio (0-10)
sh = overall['sharpe']
if sh < -0.5: d3 = 0
elif sh < 0: d3 = 1
elif sh < 0.3: d3 = 3
elif sh < 0.5: d3 = 4
elif sh < 0.8: d3 = 6
elif sh < 1.0: d3 = 7
elif sh < 1.5: d3 = 8
elif sh < 2.0: d3 = 9
else: d3 = 10
scores["风险调整收益(Sharpe)"] = d3

# D4: 最大回撤控制 (0-10)
dd = abs(overall['max_dd'])
if dd < 5: d4 = 10
elif dd < 10: d4 = 8
elif dd < 15: d4 = 7
elif dd < 20: d4 = 6
elif dd < 25: d4 = 5
elif dd < 30: d4 = 4
elif dd < 40: d4 = 3
else: d4 = 1
scores["最大回撤控制"] = d4

# D5: 收益一致性 (0-10)
# Based on positive alpha years ratio and rolling beat rate
consistency = (pos_alpha_years / total_years) * 0.5 + (beat_rate / 100) * 0.5
if consistency > 0.7: d5 = 9
elif consistency > 0.6: d5 = 7
elif consistency > 0.5: d5 = 5
elif consistency > 0.4: d5 = 4
elif consistency > 0.3: d5 = 3
elif consistency > 0.2: d5 = 2
else: d5 = 1
scores["收益一致性"] = d5

# D6: Regime 适应性 (0-10)
# BULL alpha + BEAR alpha balance
bull_alpha = regime_perf.get("BULL", {}).get("cum_alpha", 0)
bear_alpha = regime_perf.get("BEAR", {}).get("cum_alpha", 0)
# Good regime adaptability means positive alpha in BOTH
if bull_alpha > 0 and bear_alpha > 0: d6 = 9
elif bull_alpha > -20 and bear_alpha > 0: d6 = 6
elif bear_alpha > 0: d6 = 4  # Only good in bear
elif bull_alpha > 0: d6 = 3  # Only good in bull
else: d6 = 1
# Severe imbalance penalty
if abs(bull_alpha) > 200: d6 = max(0, d6 - 2)
scores["Regime适应性"] = d6

# D7: 实操可行性 (0-10)
# ETF + reasonable turnover + clear rules
d7 = 7  # ETFs are liquid, rules are systematic
if overall['coverage'] < 30:
    d7 -= 1  # Low coverage = hard to stay engaged
scores["实操可行性"] = d7

# D8: 鲁棒性/稳健性 (0-10)
# First half vs second half consistency + alpha IR
if abs(first_half_ret - second_half_ret) < 10:
    d8 = 6
elif abs(first_half_ret - second_half_ret) < 20:
    d8 = 4
else:
    d8 = 2
# Alpha IR adjustment
if alpha_ir > 0.3: d8 = min(10, d8 + 2)
elif alpha_ir > 0: d8 = min(10, d8 + 1)
elif alpha_ir < -0.3: d8 = max(0, d8 - 2)
scores["鲁棒性/稳健性"] = d8

# D9: 尾部风险控制 (0-10)
if tail_ratio > 1.2: d9 = 8
elif tail_ratio > 1.0: d9 = 7
elif tail_ratio > 0.8: d9 = 6
elif tail_ratio > 0.6: d9 = 5
elif tail_ratio > 0.4: d9 = 3
else: d9 = 1
# Crash protection bonus
crash_alpha = regime_perf.get("CRASH", {}).get("cum_alpha", 0)
if crash_alpha > 20: d9 = min(10, d9 + 2)
elif crash_alpha > 0: d9 = min(10, d9 + 1)
scores["尾部风险控制"] = d9

# D10: 策略容量 (0-10)
d10 = 8  # ETF strategy, high capacity
scores["策略容量"] = d10

# ─── 加权总分 ───
weights = {
    "绝对收益能力":        0.15,
    "超额收益Alpha":       0.15,
    "风险调整收益(Sharpe)": 0.15,
    "最大回撤控制":        0.10,
    "收益一致性":          0.12,
    "Regime适应性":        0.10,
    "实操可行性":          0.05,
    "鲁棒性/稳健性":       0.08,
    "尾部风险控制":        0.05,
    "策略容量":            0.05,
}

total_weighted = sum(scores[k] * weights[k] for k in scores)
total_out_of_10 = total_weighted
total_out_of_100 = total_weighted * 10

print(f"\n  {'维度':<22s} {'得分':>4s} {'权重':>6s} {'加权':>6s}")
print(f"  {'-'*42}")
for dim, score in scores.items():
    w = weights[dim]
    ws = score * w
    bar = "█" * score + "░" * (10 - score)
    print(f"  {dim:<20s} {score:>3d}/10 {w*100:>5.0f}% {ws:>5.2f}  {bar}")

print(f"  {'-'*42}")
print(f"  {'综合评分':<20s} {total_out_of_100:>5.1f}/100")

# Grade
if total_out_of_100 >= 85: grade = "A+"
elif total_out_of_100 >= 75: grade = "A"
elif total_out_of_100 >= 65: grade = "B+"
elif total_out_of_100 >= 55: grade = "B"
elif total_out_of_100 >= 45: grade = "C+"
elif total_out_of_100 >= 35: grade = "C"
elif total_out_of_100 >= 25: grade = "D"
else: grade = "F"

print(f"\n  评级: {grade}")

# Institutional verdict
print(f"\n  {'─'*42}")
print(f"  机构评语:")
if total_out_of_100 < 40:
    print(f"  ⛔ 不可独立部署。策略存在结构性缺陷，")
    print(f"     长期跑输基准，风险调整收益为负。")
    print(f"     建议：仅作为多策略组合的子模块，")
    print(f"     配合趋势/动量策略形成互补。")
elif total_out_of_100 < 60:
    print(f"  ⚠️ 有条件部署。在特定市场环境下有效，")
    print(f"     但全周期表现不稳定。需搭配其他策略。")
else:
    print(f"  ✅ 可部署。策略具备稳定的超额收益能力。")

print()
