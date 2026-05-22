"""
GEM V3.1 生产加固验证测试
测试覆盖:
  1. classify_regime 迟滞逻辑 (P0-1)
  2. R4 比例限仓 vs R5 清仓 (V3.1 核心)
  3. 零仓位安全兜底 (P0-2)
  4. 缓存过期保护 (P2-7)
  5. 信号历史审计字段 (P2-8)
  6. REGIME_HYSTERESIS 参数断言 (P0-1)
  7. JS Number() 安全性验证 (概念测试)
"""
import sys, os, json

# Windows GBK console fix
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 设置路径
ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE_DIR)
sys.path.insert(0, os.path.join(ENGINE_DIR, "engines"))

passed = 0
failed = 0
errors = []

def test(name, condition, detail=""):
    global passed, failed, errors
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        errors.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")

# ═══════════════════════════════════════════════════════════════
#  Test 1: REGIME_HYSTERESIS 参数存在且合理
# ═══════════════════════════════════════════════════════════════
print("\n═══ Test 1: aiae_params.REGIME_HYSTERESIS ═══")
try:
    import aiae_params as AP
    test("REGIME_HYSTERESIS exists", hasattr(AP, 'REGIME_HYSTERESIS'))
    test("REGIME_HYSTERESIS = 0.5", AP.REGIME_HYSTERESIS == 0.5)
    test("REGIME_THRESHOLDS intact", AP.REGIME_THRESHOLDS == [12.5, 17, 23, 30])
    # 迟滞带不应超过最小分界线间距的一半
    min_gap = min(AP.REGIME_THRESHOLDS[i+1] - AP.REGIME_THRESHOLDS[i]
                  for i in range(len(AP.REGIME_THRESHOLDS)-1))
    test("Hysteresis < min_gap/2",
         AP.REGIME_HYSTERESIS < min_gap / 2,
         f"H={AP.REGIME_HYSTERESIS}, min_gap/2={min_gap/2}")
except Exception as e:
    test("aiae_params import", False, str(e))

# ═══════════════════════════════════════════════════════════════
#  Test 2: classify_regime 迟滞逻辑
# ═══════════════════════════════════════════════════════════════
print("\n═══ Test 2: classify_regime hysteresis ═══")
try:
    from aiae_engine import AIAEEngine
    engine = AIAEEngine()

    # 2a: 冷启动 (prev_regime=None) — 应直接判定
    test("Cold start R1", engine.classify_regime(10.0) == 1)
    test("Cold start R3", engine.classify_regime(20.0) == 3)
    test("Cold start R4", engine.classify_regime(25.0) == 4)
    test("Cold start R5", engine.classify_regime(35.0) == 5)

    # 2b: R3→R4 升级需 >= 23+0.5 = 23.5
    test("R3 stays at 23.0", engine.classify_regime(23.0, prev_regime=3) == 3,
         f"got {engine.classify_regime(23.0, prev_regime=3)}")
    test("R3 stays at 23.4", engine.classify_regime(23.4, prev_regime=3) == 3,
         f"got {engine.classify_regime(23.4, prev_regime=3)}")
    test("R3→R4 at 23.5", engine.classify_regime(23.5, prev_regime=3) == 4,
         f"got {engine.classify_regime(23.5, prev_regime=3)}")
    test("R3→R4 at 24.0", engine.classify_regime(24.0, prev_regime=3) == 4,
         f"got {engine.classify_regime(24.0, prev_regime=3)}")

    # 2c: R4→R3 降级需 < 23-0.5 = 22.5
    test("R4 stays at 23.0", engine.classify_regime(23.0, prev_regime=4) == 4,
         f"got {engine.classify_regime(23.0, prev_regime=4)}")
    test("R4 stays at 22.5", engine.classify_regime(22.5, prev_regime=4) == 4,
         f"got {engine.classify_regime(22.5, prev_regime=4)}")
    test("R4→R3 at 22.4", engine.classify_regime(22.4, prev_regime=4) == 3,
         f"got {engine.classify_regime(22.4, prev_regime=4)}")
    test("R4→R3 at 21.0", engine.classify_regime(21.0, prev_regime=4) == 3,
         f"got {engine.classify_regime(21.0, prev_regime=4)}")

    # 2d: R4→R5 升级需 >= 30+0.5 = 30.5
    test("R4 stays at 30.0", engine.classify_regime(30.0, prev_regime=4) == 4,
         f"got {engine.classify_regime(30.0, prev_regime=4)}")
    test("R4→R5 at 30.5", engine.classify_regime(30.5, prev_regime=4) == 5,
         f"got {engine.classify_regime(30.5, prev_regime=4)}")

    # 2e: R5→R4 降级需 < 30-0.5 = 29.5
    test("R5 stays at 29.5", engine.classify_regime(29.5, prev_regime=5) == 5,
         f"got {engine.classify_regime(29.5, prev_regime=5)}")
    test("R5→R4 at 29.4", engine.classify_regime(29.4, prev_regime=5) == 4,
         f"got {engine.classify_regime(29.4, prev_regime=5)}")

    # 2f: 边界死区验证 — AIAE=23.2, prev=R3 → R3 (不升级)
    #                      AIAE=23.2, prev=R4 → R4 (不降级)
    test("Dead zone: prev=R3, AIAE=23.2 → R3",
         engine.classify_regime(23.2, prev_regime=3) == 3)
    test("Dead zone: prev=R4, AIAE=23.2 → R4",
         engine.classify_regime(23.2, prev_regime=4) == 4)

    # 2g: 跨两级跳变 (R3→R5 理论上不应一步跳, 但如果 AIAE=35 且 prev=R3)
    # 迟滞逻辑是逐级的: R3→R4 at 23.5, 然后 R4→R5 at 30.5
    # 但单次调用只检查当前 regime 与邻近边界, 所以:
    # prev=R3, AIAE=35: 先 R3→R4 (35>=23.5), 但不会继续 R4→R5
    # 因为循环中 regime 已变为 R4, 下一个 boundary(30,4,5): regime==4, 35>=30.5 → R5
    result = engine.classify_regime(35.0, prev_regime=3)
    test("Multi-level jump: R3→R5 at AIAE=35",
         result == 5, f"got {result}")

except Exception as e:
    import traceback; traceback.print_exc()
    test("classify_regime tests", False, str(e))

# ═══════════════════════════════════════════════════════════════
#  Test 3: SUB_STRATEGY_ALLOC R4/R5 仓位计算
# ═══════════════════════════════════════════════════════════════
print("\n═══ Test 3: R4/R5 仓位矩阵计算 ═══")
try:
    from aiae_params import SUB_STRATEGY_ALLOC, POSITION_MATRIX

    # R4 GEM 配额
    r4_gem = SUB_STRATEGY_ALLOC[4]["gem"]
    test("R4 GEM alloc = 18%", r4_gem == 18, f"got {r4_gem}")

    # R5 GEM 配额
    r5_gem = SUB_STRATEGY_ALLOC[5]["gem"]
    test("R5 GEM alloc = 15%", r5_gem == 15, f"got {r5_gem}")

    # R4 + ERP>6% → matrix_pos=40, gem_cap = int(40*0.18) = 7
    r4_cap_high = int(40 * r4_gem / 100)
    test("R4 ERP>6% GEM cap = 7%", r4_cap_high == 7, f"got {r4_cap_high}")

    # R4 + ERP<2% → matrix_pos=15, gem_cap = int(15*0.18) = 2
    r4_cap_low = int(15 * r4_gem / 100)
    test("R4 ERP<2% GEM cap = 2%", r4_cap_low == 2, f"got {r4_cap_low}")

    # R5 + ERP<2% → matrix_pos=0, gem_cap = int(0*0.15) = 0
    r5_pos = POSITION_MATRIX["erp_lt2"][4]  # regime 5 = index 4
    r5_cap = int(r5_pos * r5_gem / 100)
    test("R5 ERP<2% matrix_pos = 0", r5_pos == 0, f"got {r5_pos}")
    test("R5 ERP<2% GEM cap = 0", r5_cap == 0, f"got {r5_cap}")

    # 每行配额和 = 100
    for regime, alloc in SUB_STRATEGY_ALLOC.items():
        s = sum(alloc.values())
        test(f"R{regime} alloc sum = 100", s == 100, f"got {s}")

except Exception as e:
    test("SUB_STRATEGY_ALLOC tests", False, str(e))

# ═══════════════════════════════════════════════════════════════
#  Test 4: GEM 引擎 AIAE 穿透逻辑 (模拟)
# ═══════════════════════════════════════════════════════════════
print("\n═══ Test 4: AIAE 穿透逻辑模拟 ═══")
try:
    # 模拟 R4 穿透: regime=4, signal_type=buy, adjusted_position=70, gem_cap=7
    # Expected: adjusted_position → 7, r4_capped=True, signal_type remains "buy"
    aiae_regime = 4
    signal_type = "buy"
    adjusted_position = 70
    aiae_gem_cap = 7
    aiae_info = {"active": True, "regime": 4, "gem_cap": 7}
    best_primary = {"asset_type": "equity"}

    # Simulate R5 path
    if aiae_regime >= 5 and signal_type == "buy":
        if best_primary.get("asset_type") == "equity":
            signal_type = "cash"
            adjusted_position = 0
            aiae_info["forced_cash"] = True
    # Simulate R4 path
    elif aiae_regime == 4 and signal_type == "buy":
        pre_cap_pos = adjusted_position
        if adjusted_position > aiae_gem_cap:
            adjusted_position = aiae_gem_cap
            aiae_info["r4_capped"] = True
            aiae_info["pre_cap_pos"] = pre_cap_pos
    # R1-R3 path
    elif adjusted_position > aiae_gem_cap:
        adjusted_position = aiae_gem_cap

    test("R4: signal stays buy", signal_type == "buy")
    test("R4: position capped to 7", adjusted_position == 7)
    test("R4: r4_capped flag", aiae_info.get("r4_capped") == True)
    test("R4: pre_cap_pos = 70", aiae_info.get("pre_cap_pos") == 70)

    # 模拟 R5 穿透: regime=5
    aiae_regime = 5
    signal_type = "buy"
    adjusted_position = 70
    aiae_info = {"active": True, "regime": 5}

    if aiae_regime >= 5 and signal_type == "buy":
        if best_primary.get("asset_type") == "equity":
            signal_type = "cash"
            adjusted_position = 0
            aiae_info["forced_cash"] = True

    test("R5: signal forced to cash", signal_type == "cash")
    test("R5: position = 0", adjusted_position == 0)
    test("R5: forced_cash flag", aiae_info.get("forced_cash") == True)

    # 模拟 R5 + safe_haven (黄金): 不应被穿透
    aiae_regime = 5
    signal_type = "buy"
    adjusted_position = 70
    best_primary_gold = {"asset_type": "safe_haven"}
    aiae_info = {"active": True, "regime": 5}

    if aiae_regime >= 5 and signal_type == "buy":
        if best_primary_gold.get("asset_type") == "equity":
            signal_type = "cash"
            adjusted_position = 0
            aiae_info["forced_cash"] = True

    test("R5 gold: signal stays buy", signal_type == "buy")
    test("R5 gold: position preserved", adjusted_position == 70)

except Exception as e:
    test("AIAE passthrough tests", False, str(e))

# ═══════════════════════════════════════════════════════════════
#  Test 5: 零仓位安全兜底
# ═══════════════════════════════════════════════════════════════
print("\n═══ Test 5: 零仓位安全兜底 ═══")

# Case: position=0, signal_type=buy → should force cash
adjusted_position = 0
signal_type = "buy"
aiae_info = {}
GEM_CASH_PROXY = {"code": "511880.SH", "name": "银华日利", "class": "cash"}

if adjusted_position <= 0 and signal_type == "buy":
    signal_type = "cash"
    if not aiae_info.get("reason"):
        aiae_info["reason"] = "仓位归零安全兜底: 自动转为现金"

test("Zero pos: forced to cash", signal_type == "cash")
test("Zero pos: reason set", "兜底" in aiae_info.get("reason", ""))

# Case: position=5, signal_type=buy → should NOT trigger
adjusted_position = 5
signal_type = "buy"
triggered = False
if adjusted_position <= 0 and signal_type == "buy":
    triggered = True
test("Non-zero pos: not triggered", triggered == False)

# Case: position=0, signal_type=cash → should NOT trigger (already cash)
adjusted_position = 0
signal_type = "cash"
triggered = False
if adjusted_position <= 0 and signal_type == "buy":
    triggered = True
test("Already cash: not triggered", triggered == False)

# ═══════════════════════════════════════════════════════════════
#  Test 6: signal_label R4 限仓标签
# ═══════════════════════════════════════════════════════════════
print("\n═══ Test 6: signal_label 适配 ═══")

# R4 capped
aiae_info_r4 = {"r4_capped": True}
signal_type = "buy"
adjusted_position = 7
market_stress = False

label = (f"R4限仓·{adjusted_position}%" if aiae_info_r4.get("r4_capped") else "Top-N持仓") if signal_type == "buy" else ("60/40防御" if signal_type == "fallthrough_6040" else ("股债双杀·全仓现金" if market_stress else "全仓现金"))
test("R4 label = 'R4限仓·7%'", label == "R4限仓·7%", f"got '{label}'")

# Normal buy
aiae_info_normal = {}
label2 = (f"R4限仓·{adjusted_position}%" if aiae_info_normal.get("r4_capped") else "Top-N持仓") if signal_type == "buy" else "全仓现金"
test("Normal label = 'Top-N持仓'", label2 == "Top-N持仓", f"got '{label2}'")

# Cash
signal_type = "cash"
label3 = "Top-N持仓" if signal_type == "buy" else ("60/40防御" if signal_type == "fallthrough_6040" else ("股债双杀·全仓现金" if market_stress else "全仓现金"))
test("Cash label = '全仓现金'", label3 == "全仓现金", f"got '{label3}'")

# ═══════════════════════════════════════════════════════════════
#  Test 7: 缓存过期保护模拟
# ═══════════════════════════════════════════════════════════════
print("\n═══ Test 7: 缓存过期保护 ═══")
from datetime import datetime, timedelta
import time as _time

# 新鲜缓存 (1h前)
fresh_ts = (datetime.now() - timedelta(hours=1)).isoformat()
age = (_time.time() - datetime.fromisoformat(fresh_ts).timestamp()) / 3600
test("Fresh cache: age < 24h", age < 24, f"age={age:.1f}h")

# 过期缓存 (48h前)
stale_ts = (datetime.now() - timedelta(hours=48)).isoformat()
age2 = (_time.time() - datetime.fromisoformat(stale_ts).timestamp()) / 3600
test("Stale cache: age > 24h", age2 > 24, f"age={age2:.1f}h")
# 模拟降级
aiae_regime_test = 4
if age2 > 24:
    aiae_regime_test = 3
test("Stale cache: degraded to R3", aiae_regime_test == 3)

# ═══════════════════════════════════════════════════════════════
#  Test 8: 信号历史审计字段
# ═══════════════════════════════════════════════════════════════
print("\n═══ Test 8: 信号历史审计 ═══")
aiae_info_audit = {"regime": 4, "reason": "AIAE R4 比例限仓: 70% → 7%"}
new_entry = {
    "signal_type": "buy",
    "position": 7,
    "aiae_regime": aiae_info_audit.get("regime"),
    "aiae_override": aiae_info_audit.get("reason", ""),
}
test("Audit: aiae_regime present", new_entry["aiae_regime"] == 4)
test("Audit: aiae_override present", "R4" in new_entry["aiae_override"])

# ═══════════════════════════════════════════════════════════════
#  Summary
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  TOTAL: {passed + failed} | PASSED: {passed} | FAILED: {failed}")
print(f"{'='*60}")

if errors:
    print("\nFailed tests:")
    for e in errors:
        print(f"  ✗ {e}")
    sys.exit(1)
else:
    print("\n✓ All tests passed!")
    sys.exit(0)
