"""V1.3 三引擎防线验证"""
import sys, os
sys.path.insert(0, '.')
os.chdir(os.path.dirname(os.path.dirname(__file__)))

print("=" * 60)
print("  V1.3 Defense-in-Depth Test: US + JP + HK")
print("=" * 60)

# ============ US ENGINE ============
print("\n--- US Engine ---")
from aiae_us_engine import AIAEUSEngine
us = AIAEUSEngine()
# Bad input
assert us.compute_aiae_core(0.27, 22.67) == 25.0, "US: bad mktcap should return 25%"
print("  PASS: compute_aiae_core(0.27T, 22.67T) = 25.0%")
assert us.compute_margin_heat(0.75, 0.27) == 1.5, "US: bad margin heat should clamp"
print("  PASS: margin_heat(0.75T, 0.27T) = 1.5%")
# Normal input
core_ok = us.compute_aiae_core(71.7, 22.67)
assert core_ok > 5.0, f"US: normal core should be >5, got {core_ok}"
print(f"  PASS: compute_aiae_core(71.7T, 22.67T) = {core_ok}%")

# ============ JP ENGINE ============
print("\n--- JP Engine ---")
from aiae_jp_engine import AIAEJPEngine
jp = AIAEJPEngine()
# Bad input: MktCap=0
result = jp.compute_aiae_core(0, 1250)
assert result == 17.0, f"JP: zero mktcap should return 17%, got {result}"
print(f"  PASS: compute_aiae_core(0T, 1250T) = {result}%")
# Bad input: MktCap=50 (<100T)
result = jp.compute_aiae_core(50, 1250)
assert result == 17.0, f"JP: low mktcap should return 17%, got {result}"
print(f"  PASS: compute_aiae_core(50T, 1250T) = {result}%")
# Bad margin heat
result = jp.compute_margin_heat(10, 50)
assert result == 0.5, f"JP: extreme margin heat should clamp to 0.5%, got {result}"
print(f"  PASS: margin_heat(10T, 50T) = {result}%")
# Normal input
core_ok = jp.compute_aiae_core(870, 1250)
assert core_ok > 5.0, f"JP: normal core should be >5, got {core_ok}"
print(f"  PASS: compute_aiae_core(870T, 1250T) = {core_ok}%")
# Normal margin
mh = jp.compute_margin_heat(2.0, 870)
assert mh < 3.0, f"JP: normal margin should be <3, got {mh}"
print(f"  PASS: margin_heat(2.0T, 870T) = {mh}%")

# ============ HK ENGINE ============
print("\n--- HK Engine ---")
from aiae_hk_engine import AIAEHKEngine
hk = AIAEHKEngine()
# Bad input: MktCap=0
result = hk.compute_aiae_core(0, 43.4)
assert result == 15.0, f"HK: zero mktcap should return 15%, got {result}"
print(f"  PASS: compute_aiae_core(0T, 43.4T) = {result}%")
# Bad input: MktCap=0.5 (<1T)
result = hk.compute_aiae_core(0.5, 43.4)
assert result == 15.0, f"HK: low mktcap should return 15%, got {result}"
print(f"  PASS: compute_aiae_core(0.5T, 43.4T) = {result}%")
# Bad ratio
result = hk.compute_aiae_core(1.0, 1000)
assert result == 15.0, f"HK: tiny ratio should return 15%, got {result}"
print(f"  PASS: compute_aiae_core(1.0T, 1000T) = {result}%")
# Bad SB heat
result = hk.compute_southbound_heat(5000, 0.1)
assert result == 1.5, f"HK: extreme SB heat should clamp to 1.5%, got {result}"
print(f"  PASS: sb_heat(5000, 0.1T) = {result}%")
# Normal input
core_ok = hk.compute_aiae_core(4.3, 43.4)
assert core_ok > 4.0, f"HK: normal core should be >4, got {core_ok}"
print(f"  PASS: compute_aiae_core(4.3T, 43.4T) = {core_ok}%")

print("\n" + "=" * 60)
print("  ALL V1.3 TESTS PASSED - US + JP + HK")
print("=" * 60)
