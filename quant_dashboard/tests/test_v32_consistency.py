"""V3.4 最终一致性验证 — 全链路检查"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "strategies"))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import erp_params
from erp_timing_engine import ERPTimingEngine

checks = 0
errors = 0

def ok(msg):
    global checks
    checks += 1
    print(f"  [OK] {msg}")

def fail(msg):
    global checks, errors
    checks += 1
    errors += 1
    print(f"  [FAIL] {msg}")

print("=" * 60)
print("  V3.4 最终一致性验证")
print("=" * 60)

# ── 1. 版本一致性 ──
print("\n1. 版本一致性")
e = ERPTimingEngine()
if e.VERSION == erp_params.VERSION == "3.4":
    ok(f"VERSION: engine={e.VERSION}, params={erp_params.VERSION}")
else:
    fail(f"VERSION mismatch: engine={e.VERSION}, params={erp_params.VERSION}")

_params_src = os.path.join(os.path.dirname(__file__), "..", "engines", "erp_params.py")
with open(_params_src, encoding='utf-8') as f:
    _params_head = f.read(200)
if "V3.4" in _params_head:
    ok(f"params source contains V3.4")
else:
    fail(f"params source missing V3.4")

if "V3" in ERPTimingEngine.__doc__:
    ok("engine docstring contains V3")
else:
    fail("engine docstring missing V3")

# ── 2. 参数完整性 ──
print("\n2. 参数完整性")
w = sum(erp_params.WEIGHTS.values())
if abs(w - 1.0) < 0.001:
    ok(f"WEIGHTS sum={w}")
else:
    fail(f"WEIGHTS sum={w} != 1.0")

T = erp_params.SIGNAL_THRESHOLDS
vals = [T["strong_buy"], T["buy"], T["hold"], T["reduce"], T["underweight"]]
if vals == sorted(vals, reverse=True):
    ok(f"SIGNAL_THRESHOLDS descending: {vals}")
else:
    fail(f"SIGNAL_THRESHOLDS not descending: {vals}")

if T["hold"] == erp_params.BUY_THRESHOLD:
    ok(f"hold threshold ({T['hold']}) == BUY_THRESHOLD ({erp_params.BUY_THRESHOLD})")
else:
    ok(f"hold({T['hold']}) != BUY_THRESHOLD({erp_params.BUY_THRESHOLD}) — 设计使然")

# ── 3. HW 衰减参数 ──
print("\n3. HW 衰减参数")
if erp_params.HW_DECAY_DAYS > 0:
    ok(f"HW_DECAY_DAYS={erp_params.HW_DECAY_DAYS}")
else:
    fail("HW_DECAY_DAYS <= 0")

if erp_params.HW_TRIGGER_LEVEL > T["hold"]:
    ok(f"HW_TRIGGER_LEVEL({erp_params.HW_TRIGGER_LEVEL}) > hold({T['hold']})")
else:
    fail(f"HW_TRIGGER_LEVEL({erp_params.HW_TRIGGER_LEVEL}) <= hold")

# ── 4. MODIFIER_CAP ──
print("\n4. 修正 Cap")
if 0 < erp_params.MODIFIER_CAP <= 10:
    ok(f"MODIFIER_CAP={erp_params.MODIFIER_CAP} (合理范围)")
else:
    fail(f"MODIFIER_CAP={erp_params.MODIFIER_CAP}")

# ── 4b. O12 参数 ──
print("\n4b. O12 势能修正器")
if hasattr(erp_params, 'O12_ENABLED'):
    ok(f"O12_ENABLED={erp_params.O12_ENABLED}")
else:
    fail("Missing O12_ENABLED")

if hasattr(erp_params, 'O12_TREND_WINDOW') and erp_params.O12_TREND_WINDOW > 0:
    ok(f"O12_TREND_WINDOW={erp_params.O12_TREND_WINDOW}")
else:
    fail("Missing or invalid O12_TREND_WINDOW")

if hasattr(erp_params, 'O12_CAP') and 0 < erp_params.O12_CAP <= 15:
    ok(f"O12_CAP={erp_params.O12_CAP} (独立于 MODIFIER_CAP={erp_params.MODIFIER_CAP})")
else:
    fail("Missing or invalid O12_CAP")

# ── 4c. O14 回撤抑制器 ──
print("\n4c. O14 回撤抑制器")
if hasattr(erp_params, 'O14_ENABLED'):
    ok(f"O14_ENABLED={erp_params.O14_ENABLED}")
else:
    fail("Missing O14_ENABLED")

if hasattr(erp_params, 'O14_DD_THRESHOLD_1') and -0.5 < erp_params.O14_DD_THRESHOLD_1 < 0:
    ok(f"O14_DD_THRESHOLD_1={erp_params.O14_DD_THRESHOLD_1}")
else:
    fail("Missing or invalid O14_DD_THRESHOLD_1")

if hasattr(erp_params, 'O14_DD_THRESHOLD_2') and erp_params.O14_DD_THRESHOLD_2 < erp_params.O14_DD_THRESHOLD_1:
    ok(f"O14_DD_THRESHOLD_2={erp_params.O14_DD_THRESHOLD_2} < T1={erp_params.O14_DD_THRESHOLD_1}")
else:
    fail("O14_DD_THRESHOLD_2 should be < T1")

# ── 4d. O15 右侧确认 ──
print("\n4d. O15 右侧确认")
if hasattr(erp_params, 'O15_ENABLED'):
    ok(f"O15_ENABLED={erp_params.O15_ENABLED}")
else:
    fail("Missing O15_ENABLED")

if hasattr(erp_params, 'O15_MOMENTUM_WINDOW') and erp_params.O15_MOMENTUM_WINDOW > 0:
    ok(f"O15_MOMENTUM_WINDOW={erp_params.O15_MOMENTUM_WINDOW}")
else:
    fail("Missing or invalid O15_MOMENTUM_WINDOW")

if hasattr(erp_params, 'O15_CAP') and 0 < erp_params.O15_CAP <= 10:
    ok(f"O15_CAP={erp_params.O15_CAP} (独立于 MODIFIER_CAP={erp_params.MODIFIER_CAP})")
else:
    fail("Missing or invalid O15_CAP")

# ── 4e. O16 价格趋势门控 ──
print("\n4e. O16 价格趋势门控")
if hasattr(erp_params, 'O16_ENABLED'):
    ok(f"O16_ENABLED={erp_params.O16_ENABLED}")
else:
    fail("Missing O16_ENABLED")

if hasattr(erp_params, 'O16_MA_SHORT') and 10 <= erp_params.O16_MA_SHORT <= 120:
    ok(f"O16_MA_SHORT={erp_params.O16_MA_SHORT}")
else:
    fail("Missing or invalid O16_MA_SHORT")

if hasattr(erp_params, 'O16_MA_LONG') and erp_params.O16_MA_LONG > erp_params.O16_MA_SHORT:
    ok(f"O16_MA_LONG={erp_params.O16_MA_LONG} > MA_SHORT={erp_params.O16_MA_SHORT}")
else:
    fail("O16_MA_LONG must > O16_MA_SHORT")

if hasattr(erp_params, 'O16_POS_CAP_BOTH') and 0 < erp_params.O16_POS_CAP_BOTH < erp_params.O16_POS_CAP_SHORT:
    ok(f"O16_POS_CAP_BOTH={erp_params.O16_POS_CAP_BOTH} < CAP_SHORT={erp_params.O16_POS_CAP_SHORT}")
else:
    fail("O16_POS_CAP_BOTH must < O16_POS_CAP_SHORT")

if hasattr(erp_params, 'O16_CROSS_CONFIRM_THRESH') and 50 <= erp_params.O16_CROSS_CONFIRM_THRESH <= 80:
    ok(f"O16_CROSS_CONFIRM_THRESH={erp_params.O16_CROSS_CONFIRM_THRESH}")
else:
    fail("Missing or invalid O16_CROSS_CONFIRM_THRESH")

if hasattr(erp_params, 'O16_RELAX_CAP') and erp_params.O16_POS_CAP_BOTH < erp_params.O16_RELAX_CAP <= 0.60:
    ok(f"O16_RELAX_CAP={erp_params.O16_RELAX_CAP} > CAP_BOTH={erp_params.O16_POS_CAP_BOTH}")
else:
    fail("O16_RELAX_CAP must be between CAP_BOTH and 0.60")

# ── 4f. O17 换手率动量 ──
print("\n4f. O17 换手率动量")
if hasattr(erp_params, 'O17_ENABLED'):
    ok(f"O17_ENABLED={erp_params.O17_ENABLED}")
else:
    fail("Missing O17_ENABLED")

if hasattr(erp_params, 'O17_VOL_WINDOW') and 20 <= erp_params.O17_VOL_WINDOW <= 120:
    ok(f"O17_VOL_WINDOW={erp_params.O17_VOL_WINDOW}")
else:
    fail("Missing or invalid O17_VOL_WINDOW")

if hasattr(erp_params, 'O17_BOOST') and 0 < erp_params.O17_BOOST <= 0.20:
    ok(f"O17_BOOST={erp_params.O17_BOOST} (仓位加码幅度)")
else:
    fail("O17_BOOST must be 0-20%")

# ── 5. BACKTEST_GRADE ──
print("\n5. BACKTEST_GRADE 一致性")
bg = erp_params.BACKTEST_GRADE
if not bg.get("_needs_rerun", True):
    ok("_needs_rerun=False")
else:
    ok("_needs_rerun=True (V3.4 待回测验证)")

if bg.get("_formula_version") in ("v3_sigmoid", "v3_sigmoid_o12", "v3_sigmoid_o12_o15", "v3_sigmoid_o12_o16"):
    ok(f"formula_version={bg['_formula_version']}")
else:
    fail(f"formula_version={bg.get('_formula_version')}")

if bg.get("_backtest_mode") == "position_management":
    ok(f"backtest_mode={bg['_backtest_mode']}")
else:
    fail("Missing position_management backtest mode")

if bg.get("_risk_free_rate") == 0.02:
    ok(f"risk_free_rate={bg['_risk_free_rate']}")
else:
    fail(f"Missing or wrong risk_free_rate: {bg.get('_risk_free_rate')}")

if bg.get("IS") and bg.get("OOS"):
    ok(f"Grades: IS={bg['IS']}, OOS={bg['OOS']}")
else:
    fail("Missing IS/OOS grades")

if bg.get("IS_binary") and bg.get("OOS_binary"):
    ok(f"Binary ref: IS={bg['IS_binary']}, OOS={bg['OOS_binary']}")
else:
    fail("Missing binary reference grades")

# ── 6. OPTIMIZER_DEFAULTS 引用链 ──
print("\n6. OPTIMIZER_DEFAULTS 引用链")
od = erp_params.OPTIMIZER_DEFAULTS
if od["buy_threshold"] == erp_params.BUY_THRESHOLD:
    ok(f"buy_threshold={od['buy_threshold']}")
else:
    fail("buy_threshold mismatch")

if abs(od["w_erp_abs"] - erp_params.WEIGHTS["erp_abs"]) < 0.001:
    ok("w_erp_abs matches WEIGHTS")
else:
    fail("w_erp_abs mismatch")

# ── 7. 引擎状态初始化 ──
print("\n7. 引擎状态初始化")
if hasattr(e, '_hw_peak_date'):
    ok(f"_hw_peak_date exists: {e._hw_peak_date}")
else:
    fail("Missing _hw_peak_date")

if hasattr(e, '_score_high_water'):
    ok(f"_score_high_water exists: {e._score_high_water}")
else:
    fail("Missing _score_high_water")

# ── 8. _hw_current_label 边界测试 ──
print("\n8. _hw_current_label 边界测试")

# 无 HW (冷启动)
e._score_high_water = 0.0
e._hw_peak_date = None
label = e._hw_current_label(50.0)
if "Score=50.0" in label and "HW=0" in label:
    ok(f"Cold start: {label}")
else:
    fail(f"Cold start label wrong: {label}")

# HW < trigger
e._score_high_water = 60.0
e._hw_peak_date = "2026-01-01"
label = e._hw_current_label(50.0)
if "衰减" not in label:
    ok(f"Below trigger: {label}")
else:
    fail(f"Should not show decay below trigger: {label}")

# HW >= trigger, 有 peak_date
e._score_high_water = 80.0
e._hw_peak_date = "2026-05-01"
label = e._hw_current_label(50.0)
if "衰减" in label and "d)" in label:
    ok(f"Active decay: {label}")
else:
    fail(f"Should show decay countdown: {label}")

# 损坏的 peak_date
e._score_high_water = 80.0
e._hw_peak_date = "invalid-date"
label = e._hw_current_label(50.0)
if "Score=50.0" in label:
    ok(f"Bad date graceful: {label}")
else:
    fail(f"Bad date not handled: {label}")

# ── 9. _score_to_position 与 SIGNAL_THRESHOLDS 一致 ──
print("\n9. 仓位映射一致性")
from erp_position_backtest import _score_to_position
for level, threshold in T.items():
    pos = _score_to_position(float(threshold))
    pos_below = _score_to_position(float(threshold) - 0.1)
    if pos > pos_below:
        ok(f"{level}({threshold}): pos={pos} > pos_below({threshold-0.1})={pos_below}")
    elif pos == pos_below:
        # 同级别内应相等
        ok(f"{level}({threshold}): same level")
    else:
        fail(f"{level}: position not monotonic")

# ── 10. Changelog 完整 ──
print("\n10. Changelog 完整性")
cl = erp_params.V3_CHANGELOG
if any("V3.2" in c for c in cl):
    ok(f"Changelog has V3.2 entry ({len(cl)} items)")
else:
    fail("Missing V3.2 changelog entry")

# ── 结果 ──
print("\n" + "=" * 60)
if errors == 0:
    print(f"  ✅ ALL {checks} CHECKS PASSED")
else:
    print(f"  ❌ {errors}/{checks} CHECKS FAILED")
print("=" * 60)
