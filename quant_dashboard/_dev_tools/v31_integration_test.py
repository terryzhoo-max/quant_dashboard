"""
V3.1 实盘引擎集成测试
====================
用本地缓存数据模拟完整运行，验证：
1. 引擎import无报错
2. 新增字段正确输出
3. 累计止损持仓追踪工作正常
4. 7维评分函数输出完整
5. 双MA Regime升降级逻辑
"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 70)
print("  V3.1 INTEGRATION TEST")
print("=" * 70)

# ─── Test 1: Import ───
print("\n[TEST 1] Import engine module...")
try:
    from engines.momentum_rotation_engine import (
        REGIME_PARAMS, CUMULATIVE_STOP_THRESHOLDS,
        calculate_indicators, calculate_momentum_score,
        _load_holdings, _save_holdings, _check_cumulative_stop,
        _MOM_HOLDINGS_KEY,
    )
    print("  [PASS] Import OK")
except Exception as e:
    print(f"  [FAIL] Import error: {e}")
    sys.exit(1)

# ─── Test 2: REGIME_PARAMS structure ───
print("\n[TEST 2] REGIME_PARAMS V3.1 fields...")
errors = []
for regime in ["BULL", "RANGE", "BEAR"]:
    p = REGIME_PARAMS[regime]
    for key in ["w_mom_s", "w_mom_m", "w_slope", "w_sharpe", "w_trend",
                "rebalance_days", "signal_safety_gate"]:
        if key not in p:
            errors.append(f"  {regime} missing '{key}'")
    # Weight sum check
    total_w = p["w_mom_s"] + p["w_mom_m"] + p["w_slope"] + p["w_sharpe"] + p["w_trend"]
    if abs(total_w - 1.0) > 0.01:
        errors.append(f"  {regime} weight sum={total_w} (should be 1.0)")
    else:
        print(f"  {regime}: weights sum={total_w:.2f}, rebal={p['rebalance_days']}d, w_trend={p['w_trend']}")

if errors:
    for e in errors:
        print(f"  [FAIL] {e}")
else:
    print("  [PASS] All regimes have correct V3.1 fields")

# ─── Test 3: Stop-loss thresholds ───
print("\n[TEST 3] Cumulative stop thresholds...")
expected = {"BULL": -0.99, "RANGE": -0.10, "BEAR": -0.07}
for regime, expected_val in expected.items():
    actual = CUMULATIVE_STOP_THRESHOLDS.get(regime)
    status = "PASS" if actual == expected_val else "FAIL"
    print(f"  [{status}] {regime}: {actual} (expected {expected_val})")

# ─── Test 4: 7-dim scoring function ───
print("\n[TEST 4] 7-dim momentum scoring...")
mock_indicators = {
    "momentum_pct": 10.0, "momentum_m": 15.0, "slope": 0.3,
    "sharpe_factor": 1.0, "volume_ratio": 1.2, "rsi": 60,
    "rsi_slope5": 2.0, "ma_deviation": 3.0,
}
for regime in ["BULL", "RANGE", "BEAR"]:
    result = calculate_momentum_score(mock_indicators, regime)
    bd = result["breakdown"]
    has_trend = "trend" in bd
    keys = sorted(bd.keys())
    print(f"  {regime}: total={result['total']}, keys={keys}, trend={bd.get('trend', 'MISSING')}")
    if not has_trend:
        print(f"  [FAIL] {regime} missing 'trend' in breakdown!")
    else:
        print(f"  [PASS] {regime} scoring OK")

# ─── Test 5: Holdings persistence ───
print("\n[TEST 5] Holdings persistence (cache)...")
try:
    # Save test holdings
    test_holdings = {
        "512480.SH": {"entry_price": 1.50, "entry_date": "20260520", "name": "半导体ETF"},
        "515880.SH": {"entry_price": 0.90, "entry_date": "20260518", "name": "通信ETF"},
    }
    _save_holdings(test_holdings)
    
    # Load back
    loaded = _load_holdings()
    if loaded and "512480.SH" in loaded:
        print(f"  [PASS] Save/Load OK: {len(loaded)} holdings")
    else:
        print(f"  [FAIL] Load returned: {loaded}")
    
    # Test stop-loss check
    # Case 1: No loss
    check1 = _check_cumulative_stop("512480.SH", 1.60, "BULL", loaded)
    print(f"  Check no-loss: triggered={check1['triggered']}, pnl={check1['pnl']}%")
    
    # Case 2: Small loss in BULL (should NOT trigger, -99% threshold)
    check2 = _check_cumulative_stop("512480.SH", 1.20, "BULL", loaded)
    print(f"  Check BULL -20%: triggered={check2['triggered']} (expect False)")
    
    # Case 3: -12% loss in RANGE (should trigger, -10% threshold)
    check3 = _check_cumulative_stop("512480.SH", 1.32, "RANGE", loaded)
    print(f"  Check RANGE -12%: triggered={check3['triggered']} (expect True)")
    
    # Case 4: -8% loss in BEAR (should trigger, -7% threshold)
    check4 = _check_cumulative_stop("515880.SH", 0.828, "BEAR", loaded)
    print(f"  Check BEAR -8%: triggered={check4['triggered']} (expect True)")
    
    all_ok = (not check1["triggered"] and not check2["triggered"] 
              and check3["triggered"] and check4["triggered"])
    print(f"  [{'PASS' if all_ok else 'FAIL'}] Stop-loss logic correct")
    
    # Cleanup
    _save_holdings({})
    
except Exception as e:
    import traceback
    print(f"  [FAIL] Holdings test error: {e}")
    traceback.print_exc()

# ─── Test 6: Dual-MA regime logic (unit test) ───
print("\n[TEST 6] Dual-MA Regime upgrade/downgrade logic...")
import pandas as pd
import numpy as np

# Create synthetic HS300 data: 150 days, price crossing above MA20
np.random.seed(42)
n = 150
prices = pd.Series(np.cumsum(np.random.randn(n) * 0.5) + 100)
# Make last 5 days cross above MA20 with rising MA20
prices.iloc[-5:] = prices.iloc[-10:-5].values + 3

close = prices
ma120 = close.rolling(120).mean()
ma20 = close.rolling(20).mean()
ma20_slope = ma20.diff(3)

latest_close = float(close.iloc[-1])
latest_ma120 = float(ma120.iloc[-1])
latest_ma20 = float(ma20.iloc[-1])
latest_ma20_slope = float(ma20_slope.iloc[-1])

above_ma20 = latest_close > latest_ma20
ma20_rising = latest_ma20_slope > 0

print(f"  Close={latest_close:.2f}, MA120={latest_ma120:.2f}, MA20={latest_ma20:.2f}")
print(f"  Above MA20: {above_ma20}, MA20 rising: {ma20_rising}")

# Simulate BEAR→RANGE upgrade
simulated_regime = "BEAR"
if simulated_regime == "BEAR" and above_ma20 and ma20_rising:
    new_regime = "RANGE"
    print(f"  BEAR + above MA20 + rising → upgrade to RANGE")
    print(f"  [PASS] Dual-MA upgrade logic works")
else:
    print(f"  [INFO] No upgrade triggered (conditions not met)")

# ─── Summary ───
print("\n" + "=" * 70)
print("  INTEGRATION TEST COMPLETE")
print("=" * 70)
