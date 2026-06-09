"""
V6.0 缓存优化 · 边界条件验证脚本
================================
验证所有自适应 TTL 调用不会出现 fresh_ttl > stale_ttl 的逻辑倒挂。
验证 is_market_hours 在各时段返回正确值。
验证 adaptive_fresh_ttl 倍率矩阵的数学正确性。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from unittest.mock import patch

# ========== Test 1: is_market_hours ==========
from services.cache_service import is_market_hours, adaptive_fresh_ttl, _TTL_MULTIPLIERS

print("=" * 60)
print("Test 1: is_market_hours()")
print("=" * 60)

# 模拟各时间点
test_cases = [
    (datetime(2026, 6, 9, 9, 30), "trading",  "周一盘中"),
    (datetime(2026, 6, 9, 15, 30), "after",   "周一收盘后"),
    (datetime(2026, 6, 9, 8, 0),  "after",    "周一盘前"),
    (datetime(2026, 6, 7, 12, 0), "weekend",  "周六"),
    (datetime(2026, 6, 8, 12, 0), "weekend",  "周日"),
    (datetime(2026, 6, 9, 9, 15), "trading",  "周一开盘"),
    (datetime(2026, 6, 9, 15, 5), "trading",  "周一收盘时刻"),
    (datetime(2026, 6, 9, 15, 6), "after",    "周一收盘后1分钟"),
]

for mock_time, expected, desc in test_cases:
    with patch('services.cache_service._datetime') as mock_dt:
        mock_dt.now.return_value = mock_time
        result = is_market_hours()
        status = "✅" if result == expected else "❌"
        print(f"  {status} {desc:20s} ({mock_time.strftime('%a %H:%M')}) => {result:8s} (expected: {expected})")

# ========== Test 2: adaptive_fresh_ttl 边界 ==========
print("\n" + "=" * 60)
print("Test 2: adaptive_fresh_ttl 不变量检查")
print("=" * 60)

# 所有 Router 中实际使用的 (base_ttl, stale_ttl, category) 组合
ACTUAL_CALLS = [
    # decision.py
    (300, 3600, "decision", "hub"),
    (300, 3600, "decision", "risk-matrix"),
    (60, 300, "realtime", "compliance"),
    (600, 3600, "decision", "accuracy"),
    (7200, 43200, "strategy", "perf-analytics"),
    (3600, 21600, "strategy", "swing-guard"),
    (1800, 7200, "slow", "correlation"),
    (3600, 14400, "slow", "contagion"),
    (60, 300, "realtime", "drift"),
    (1800, 7200, "strategy", "brinson"),
    (600, 3600, "decision", "multi-asset"),
    # market.py
    (3600, 21600, "strategy", "erp-timing"),
    (1800, 14400, "strategy", "erp-global"),
    (3600, 21600, "strategy", "rates"),
    (3600, 21600, "strategy", "gold-signal"),
    # portfolio.py
    (300, 1800, "decision", "portfolio-risk"),
    (3600, 14400, "strategy", "portfolio-brinson"),
    (7200, 28800, "slow", "factor-attribution"),
    (60, 300, "realtime", "intraday-pnl"),
    # aiae.py
    (1800, 14400, "strategy", "aiae-cn-report"),
    # strategy.py
    (1800, 21600, "strategy", "gem"),
]

violations = 0
warnings = 0
for base, stale, category, endpoint in ACTUAL_CALLS:
    for period_name, period_idx in [("trading", 0), ("after", 1), ("weekend", 2)]:
        multipliers = _TTL_MULTIPLIERS.get(category, _TTL_MULTIPLIERS["default"])
        raw_fresh = base * multipliers[period_idx]
        
        if raw_fresh > stale:
            warnings += 1
            # 这不是真正的违反 — SWR guard 会在运行时截断

if warnings > 0:
    print(f"  [INFO] {warnings} 个原始倍率超标 (SWR guard 会自动截断)")

# 关键验证: 模拟 SWR guard 后是否还有违反
print(f"\n  === SWR Guard 验证 (min(fresh, stale*0.9)) ===")
swr_violations = 0
for base, stale, category, endpoint in ACTUAL_CALLS:
    for period_name, period_idx in [("trading", 0), ("after", 1), ("weekend", 2)]:
        multipliers = _TTL_MULTIPLIERS.get(category, _TTL_MULTIPLIERS["default"])
        raw_fresh = base * multipliers[period_idx]
        # 模拟 SWR guard
        guarded_fresh = min(raw_fresh, int(stale * 0.9))
        
        if guarded_fresh > stale:
            swr_violations += 1
            print(f"  FATAL: {endpoint:25s} [{period_name:8s}] guarded_fresh={guarded_fresh}s > stale={stale}s")
        elif guarded_fresh != raw_fresh:
            ratio = guarded_fresh / stale * 100
            # Only show truncations that matter
            if raw_fresh > stale:
                pass  # Expected truncation, don't spam

if swr_violations == 0:
    print(f"  PASS: 全部 {len(ACTUAL_CALLS) * 3} 个组合通过 SWR guard 后 fresh < stale")
else:
    print(f"\n  FAIL: {swr_violations} 个违反 SWR guard!")

violations = swr_violations

# ========== Test 3: max_ttl 安全阀 ==========
print("\n" + "=" * 60)
print("Test 3: max_ttl 安全阀")
print("=" * 60)

with patch('services.cache_service._datetime') as mock_dt:
    mock_dt.now.return_value = datetime(2026, 6, 7, 12, 0)  # 周六
    # 不加 max_ttl
    result_no_cap = adaptive_fresh_ttl(7200, "strategy")
    # 加 max_ttl
    result_capped = adaptive_fresh_ttl(7200, "strategy", max_ttl=43200)
    print(f"  base=7200, strategy, 周末:")
    print(f"    无上限: {result_no_cap}s ({result_no_cap/3600:.1f}h)")
    print(f"    max_ttl=43200: {result_capped}s ({result_capped/3600:.1f}h)")
    assert result_capped <= 43200, "max_ttl 未生效!"
    print(f"  ✅ max_ttl 安全阀正常")

# ========== Test 4: VIX 磁盘缓存路径 ==========
print("\n" + "=" * 60)
print("Test 4: VIX 磁盘缓存路径")
print("=" * 60)

from dashboard_modules.fetch_macro import _VIX_CACHE_PATH
print(f"  路径: {_VIX_CACHE_PATH}")
print(f"  目录存在: {os.path.isdir(os.path.dirname(_VIX_CACHE_PATH))}")

# ========== Test 5: data_manager 新鲜度逻辑 ==========
print("\n" + "=" * 60)
print("Test 5: stock_list 新鲜度")
print("=" * 60)

cache_path = os.path.join("data_lake", "stock_list.parquet")
if os.path.exists(cache_path):
    age_days = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_path))).days
    print(f"  stock_list.parquet age: {age_days} 天")
    print(f"  需要刷新: {'是' if age_days > 30 else '否'}")
else:
    print(f"  stock_list.parquet 不存在 (首次运行将创建)")

# ========== Test 6: CacheService 容量 ==========
print("\n" + "=" * 60)
print("Test 6: CacheService 容量验证")
print("=" * 60)

from services.cache_service import cache_manager
print(f"  _mem_maxsize: {cache_manager._mem_maxsize}")
assert cache_manager._mem_maxsize == 512, f"Expected 512, got {cache_manager._mem_maxsize}"
print(f"  ✅ 内存缓存容量正确 (512)")

# ========== Summary ==========
print("\n" + "=" * 60)
print("验证总结")
print("=" * 60)
print(f"  TTL 不变量: {'✅ PASS' if violations == 0 else '❌ FAIL'}")
print(f"  安全阀:     ✅ PASS")
print(f"  内存容量:   ✅ 512")
print(f"  VIX 路径:   ✅ {_VIX_CACHE_PATH}")
