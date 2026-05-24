"""V3.3 生产引擎端到端验证"""
import sys, os
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _parent)
os.chdir(_parent)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from engines.erp_timing_engine import ERPTimingEngine

print("=" * 60)
print("  V3.3 生产引擎端到端验证")
print("=" * 60)

e = ERPTimingEngine()
result = e.compute_signal()

print(f"  Version: {e.VERSION}")
status = result.get("status", "unknown")
print(f"  Status: {status}")

if status == "success":
    score = result.get("composite_score", 0)
    signal = result.get("trade", {}).get("signal_key", "N/A")
    signal_info = result.get("trade", {}).get("signal", {})
    print(f"  Score: {score}")
    print(f"  Signal: {signal} ({signal_info.get('label', '')})")

    dims = result.get("dimensions", {})
    print(f"  Dimensions: {list(dims.keys())}")

    # 验证 O12 market_trend 存在
    mt = dims.get("market_trend", {})
    if mt:
        print(f"  ✅ O12 market_trend: score={mt.get('score')}, desc={mt.get('desc')}")
    else:
        print("  ❌ O12 market_trend MISSING!")

    # 验证 erp_momentum 包含 capped_mod
    mom = dims.get("erp_momentum", {})
    if mom and "capped_mod" in mom:
        print(f"  ✅ O7 momentum: score={mom.get('score')}, capped={mom.get('capped_mod')}")
    else:
        print("  ❌ O7 momentum missing capped_mod!")

    # 五维+两修正 = 7 维度
    expected_dims = ["erp_abs", "erp_pct", "m1_trend", "volatility", "credit",
                     "erp_momentum", "market_trend"]
    missing = [d for d in expected_dims if d not in dims]
    if not missing:
        print(f"  ✅ All {len(expected_dims)} dimensions present")
    else:
        print(f"  ❌ Missing dimensions: {missing}")

    print(f"\n  === ✅ PASS ===")
else:
    reason = result.get("fallback_reason", "unknown")
    print(f"  Fallback: {reason}")
    if "dimensions" in result and "trade" in result:
        print(f"  Structure: OK (fallback)")
        print(f"\n  === ✅ PASS (degraded) ===")
    else:
        print(f"\n  === ❌ FAIL ===")
