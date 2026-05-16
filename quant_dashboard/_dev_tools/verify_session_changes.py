"""
本次会话全部变更的综合验证脚本
=============================================
1. D3 曲线 ±10bps 缓冲带 (rates_strategy_engine.py)
2. 黄金因子驱动动态配置 (rates_strategy_engine.py)
3. AIAE 图表月度历史合并 (aiae_engine.py)
4. warmup_pipeline region_names 修复
"""

import sys, os
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r"d:\FIONA\google AI\quant_dashboard\quant_dashboard")
os.chdir(r"d:\FIONA\google AI\quant_dashboard\quant_dashboard")

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} — {detail}")

print("=" * 60)
print("  AlphaCore 本次会话变更 — 综合验证")
print("=" * 60)

# ============================================================
# TEST 1: D3 曲线 ±10bps 缓冲带
# ============================================================
print("\n📊 TEST 1: D3 曲线 ±10bps 缓冲带")
print("-" * 40)

from engines.rates_strategy_engine import RatesStrategyEngine
engine = RatesStrategyEngine()

# 模拟不同 spread_bps 值, 直接测试评分逻辑
import pandas as pd
from datetime import datetime, timedelta

# 构造最小 mock 数据
dates = pd.date_range(end=datetime.now(), periods=250, freq='B')
df_10y = pd.DataFrame({"trade_date": dates, "yield_10y": [4.3]*250})
df_2y_base = pd.DataFrame({"trade_date": dates, "yield_2y": [4.3]*250})

def test_d3_spread(spread_pct, expected_min, expected_max):
    """构造特定 spread 的数据并测试 D3 评分"""
    y2_val = 4.3 - spread_pct  # spread = 10y - 2y
    df_2y = pd.DataFrame({"trade_date": dates, "yield_2y": [y2_val]*250})
    score, info, desc = engine._score_d3_curve_shape(df_10y=df_10y, df_2y=df_2y)
    return score, info.get("regime", "")

# 缓冲带外: < -10bps → 60 (mild_inversion)
score, regime = test_d3_spread(spread_pct=-0.15, expected_min=59, expected_max=61)
check("spread=-15bps → mild_inversion (60分)", 
      abs(score - 60) < 1 and regime == "mild_inversion",
      f"got score={score}, regime={regime}")

# 缓冲带内: -5bps → 应在57-58之间 (线性插值)
score, regime = test_d3_spread(spread_pct=-0.05, expected_min=56, expected_max=59)
check("spread=-5bps → 缓冲带内 (~57.5分)", 
      56 <= score <= 59,
      f"got score={score}")

# 缓冲带中心: 0bps → 应为55
score, regime = test_d3_spread(spread_pct=0.0, expected_min=54, expected_max=56)
check("spread=0bps → 缓冲带中心 (55分)", 
      54 <= score <= 56,
      f"got score={score}")

# 缓冲带内: +5bps → 应在52-53之间
score, regime = test_d3_spread(spread_pct=0.05, expected_min=51, expected_max=54)
check("spread=+5bps → 缓冲带内 (~52.5分)", 
      51 <= score <= 54,
      f"got score={score}")

# 缓冲带外: +15bps → 50 (flat)
score, regime = test_d3_spread(spread_pct=0.15, expected_min=49, expected_max=51)
check("spread=+15bps → flat (50分)", 
      abs(score - 50) < 1 and regime == "flat",
      f"got score={score}, regime={regime}")

# 关键: -2bps vs +2bps 差值应 < 3分 (旧版差10分!)
score_neg2, _ = test_d3_spread(spread_pct=-0.02, expected_min=55, expected_max=57)
score_pos2, _ = test_d3_spread(spread_pct=0.02, expected_min=53, expected_max=55)
delta = abs(score_neg2 - score_pos2)
check(f"±2bps 跳变幅度: {delta:.1f}分 (应<3, 旧版=10)", 
      delta < 3,
      f"delta={delta}")


# ============================================================
# TEST 2: 黄金因子驱动动态配置
# ============================================================
print("\n🥇 TEST 2: 黄金因子驱动动态配置")
print("-" * 40)

# Case A: 正常环境 (real_yield > 0, BEI < 2.5) → 黄金保持10%
dims_normal = {
    "real_yield": {"real_info": {"current": 1.95, "breakeven": 2.2}},
}
sig_normal = engine._compute_signal(55.0, dims=dims_normal)
check("正常环境: 黄金=10% (无增配)", 
      sig_normal["gold_pct"] == 10 and sig_normal["gold_boost"] == 0,
      f"got gold={sig_normal['gold_pct']}%, boost={sig_normal.get('gold_boost')}")

# Case B: 负利率 → 黄金+5%
dims_neg_real = {
    "real_yield": {"real_info": {"current": -0.5, "breakeven": 2.0}},
}
sig_neg = engine._compute_signal(55.0, dims=dims_neg_real)
check("负利率: 黄金=15% (+5%)", 
      sig_neg["gold_pct"] == 15 and sig_neg["gold_boost"] == 5,
      f"got gold={sig_neg['gold_pct']}%, boost={sig_neg.get('gold_boost')}")

# Case C: 负利率 + 高通胀 → 黄金+10% → cap at 20%
dims_extreme = {
    "real_yield": {"real_info": {"current": -1.0, "breakeven": 3.0}},
}
sig_extreme = engine._compute_signal(55.0, dims=dims_extreme)
check("负利率+高通胀: 黄金=20% (硬上限)", 
      sig_extreme["gold_pct"] == 20 and sig_extreme["gold_boost"] == 10,
      f"got gold={sig_extreme['gold_pct']}%, boost={sig_extreme.get('gold_boost')}")

# Case D: 股债扣减验证 — 总和应仍=100%
total = sig_extreme["stock_pct"] + sig_extreme["bond_pct"] + sig_extreme["gold_pct"]
check(f"极端环境总配比: {total}% (应=100%)", 
      total == 100,
      f"stock={sig_extreme['stock_pct']}, bond={sig_extreme['bond_pct']}, gold={sig_extreme['gold_pct']}")

# Case E: 无dims时退化为10% (向后兼容)
sig_no_dims = engine._compute_signal(55.0)
check("无dims: 黄金=10% (向后兼容)", 
      sig_no_dims["gold_pct"] == 10,
      f"got gold={sig_no_dims['gold_pct']}%")

# Case F: position 文本正确
check("position文本含动态数值", 
      f"金{sig_extreme['gold_pct']}%" in sig_extreme["position"],
      f"got position='{sig_extreme['position']}'")


# ============================================================
# TEST 3: AIAE 图表月度历史合并
# ============================================================
print("\n📈 TEST 3: AIAE 图表月度历史合并")
print("-" * 40)

from engines.aiae_engine import AIAEEngine
aiae_engine = AIAEEngine()

chart = aiae_engine.get_chart_data(live_aiae=24.75)

check("图表数据非空", 
      len(chart["dates"]) > 0 and len(chart["values"]) > 0,
      f"dates={len(chart['dates'])}, values={len(chart['values'])}")

check("dates/values/labels 长度一致", 
      len(chart["dates"]) == len(chart["values"]) == len(chart["labels"]),
      f"dates={len(chart['dates'])}, values={len(chart['values'])}, labels={len(chart['labels'])}")

check("日期已排序", 
      chart["dates"] == sorted(chart["dates"]),
      f"first={chart['dates'][0]}, last={chart['dates'][-1]}")

check("包含实时点 (末尾)", 
      chart["labels"][-1] == "当前状态(实时)" and chart["values"][-1] == 24.8,
      f"last_label={chart['labels'][-1]}, last_val={chart['values'][-1]}")

check("stats.mean 动态计算 (非硬编码18.5)", 
      chart["stats"]["mean"] != 18.5 or len(chart["values"]) <= 9,
      f"mean={chart['stats']['mean']}, points={chart['stats'].get('data_points')}")

check("stats.data_points 存在", 
      "data_points" in chart["stats"],
      f"stats keys={list(chart['stats'].keys())}")

# 静态历史节点保留
has_998 = any("998" in (l or "") for l in chart["labels"])
check("保留历史标注 (998点)", has_998, "998点标签未找到")

has_6124 = any("6124" in (l or "") for l in chart["labels"])
check("保留历史标注 (6124点)", has_6124, "6124点标签未找到")

# 五档区间线
check("bands 包含4条分界线", 
      len(chart["bands"]) == 4,
      f"got {len(chart['bands'])} bands")


# ============================================================
# TEST 4: warmup_pipeline region_names 修复
# ============================================================
print("\n🔧 TEST 4: warmup_pipeline region_names 修复")
print("-" * 40)

import ast
with open(r"d:\FIONA\google AI\quant_dashboard\quant_dashboard\services\warmup_pipeline.py", "r", encoding="utf-8") as f:
    src = f.read()

ast.parse(src)
check("warmup_pipeline.py 语法正确", True)

check("region_names 已定义", 
      "region_names" in src and "'cn': 'A股'" in src,
      "region_names dict not found")


# ============================================================
# TEST 5: 金色增配前端标注
# ============================================================
print("\n🎨 TEST 5: 前端gold_boost标注")
print("-" * 40)

with open(r"d:\FIONA\google AI\quant_dashboard\quant_dashboard\static\js\treasury.js", "r", encoding="utf-8") as f:
    js_src = f.read()

check("treasury.js: gold_boost 逻辑存在", 
      "gold_boost" in js_src and "↑+" in js_src,
      "gold_boost display logic not found")


# ============================================================
# 汇总
# ============================================================
print("\n" + "=" * 60)
total = passed + failed
if failed == 0:
    print(f"  🎉 ALL {total} TESTS PASSED")
else:
    print(f"  ⚠️  {passed}/{total} passed, {failed} FAILED")
print("=" * 60)
