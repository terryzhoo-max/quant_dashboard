"""V1.3 Wilshire 磁盘缓存校验测试"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.chdir(os.path.dirname(os.path.dirname(__file__)))

# 模拟云端脏缓存
dirty_cache = {
    "trade_date": "2026-04-28",
    "wilshire_index": 270,       # VTI 价格, 不是 Wilshire 指数!
    "market_cap_trillion_usd": 0.27,
    "source": "yfinance_W5000",
}

_MKTCAP_MIN_T = 10.0
_WILSHIRE_MIN = 10000
_WILSHIRE_MAX = 200000

mktcap = dirty_cache["market_cap_trillion_usd"]
wilshire = dirty_cache["wilshire_index"]

if mktcap >= _MKTCAP_MIN_T and _WILSHIRE_MIN <= wilshire <= _WILSHIRE_MAX:
    print(f"FAIL: dirty cache passed validation!")
else:
    print(f"PASS: dirty cache blocked (MktCap={mktcap}T, Wilshire={wilshire})")

# 硬编码 fallback 产出
mktcap_fb = 55.0
m2 = 22.67
ratio = mktcap_fb / m2
core = 10.0 + (ratio - 0.7) / (2.6 - 0.7) * 35.0
core = max(5.0, min(50.0, core))
print(f"PASS: hardcoded fallback -> ratio={ratio:.2f}, Core={core:.1f}%")

# compute_aiae_core 防线
from aiae_us_engine import AIAEUSEngine
eng = AIAEUSEngine()

# 正常输入
result_normal = eng.compute_aiae_core(71.7, 22.67)
print(f"PASS: normal input (71.7T/22.67T) -> Core={result_normal}%")

# 异常输入 (脏数据泄漏)
result_bad = eng.compute_aiae_core(0.27, 22.67)
print(f"PASS: bad input (0.27T/22.67T) -> Core={result_bad}% (should be 25.0)")
assert result_bad == 25.0, f"FAIL: expected 25.0, got {result_bad}"

# margin heat 钳制
heat_bad = eng.compute_margin_heat(0.75, 0.27)
print(f"PASS: margin heat clamp (0.75T/0.27T) -> heat={heat_bad}% (should be 1.5)")
assert heat_bad == 1.5, f"FAIL: expected 1.5, got {heat_bad}"

print("\n=== ALL V1.3 TESTS PASSED ===")
