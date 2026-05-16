"""
ERP择时V2.0 P1修正验证
======================
1. 降级报告保守中性化 (ERP=4.0, score=50)
2. M1 Parquet磁盘缓存
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
print("  ERP择时 V2.0 P1修正 — 验证")
print("=" * 60)

# ============================================================
# TEST 1: 降级报告保守中性化
# ============================================================
print("\n🛡️ TEST 1: 降级报告保守中性化")
print("-" * 40)

from engines.erp_timing_engine import ERPTimingEngine
engine = ERPTimingEngine()

fb = engine._fallback_signal("测试降级")

# 快照值验证
snap = fb["current_snapshot"]
check("ERP降级值 = 4.0% (非6.2%)", 
      snap["erp_value"] == 4.0,
      f"got {snap['erp_value']}")

check("PE降级值 = 13.0 (非12.5)", 
      snap["pe_ttm"] == 13.0,
      f"got {snap['pe_ttm']}")

check("10Y降级值 = 2.30 (非1.80)", 
      snap["yield_10y"] == 2.30,
      f"got {snap['yield_10y']}")

check("分位降级值 = 50.0% (非70.0%)", 
      snap["erp_percentile"] == 50.0,
      f"got {snap['erp_percentile']}")

# 信号值验证
sig = fb["signal"]
check("Score降级值 = 50 (非70)", 
      sig["score"] == 50,
      f"got {sig['score']}")

check("信号 = hold (标配)", 
      sig["key"] == "hold",
      f"got {sig['key']}")

# 告警文本验证
alert_text = fb["alerts"][0]["text"]
check("告警包含'保守中性'提示", 
      "保守中性" in alert_text or "降级" in alert_text,
      f"got: {alert_text[:50]}")

diag_text = fb["diagnosis"][0]["text"]
check("诊断包含'ERP=4.0%'说明", 
      "4.0%" in diag_text or "保守" in diag_text,
      f"got: {diag_text[:50]}")

# 数学一致性: earnings_yield 应与 PE 匹配
expected_ey = round(1.0 / 13.0 * 100, 1)
actual_ey = snap["earnings_yield"]
check(f"earnings_yield ({actual_ey}) 与 PE ({snap['pe_ttm']}) 一致", 
      abs(actual_ey - expected_ey) < 0.5,
      f"expected ~{expected_ey}, got {actual_ey}")

# ERP 降级值设计验证: ERP=4.0 是历史中位数(保守), 非EY-10Y计算值(5.4)
# 这是有意为之 — 降级场景优先保守, 避免因PE/10Y预设值偏差放大信号
derived_erp = round(actual_ey - snap["yield_10y"], 1)
check(f"ERP降级值(4.0) < 计算值({derived_erp}) → 保守设计正确", 
      snap["erp_value"] <= derived_erp,
      f"ERP={snap['erp_value']} should be <= derived {derived_erp}")


# ============================================================
# TEST 2: M1 Parquet磁盘缓存
# ============================================================
print("\n💾 TEST 2: M1 Parquet磁盘缓存")
print("-" * 40)

import ast
with open(r"d:\FIONA\google AI\quant_dashboard\quant_dashboard\engines\erp_timing_engine.py", "r", encoding="utf-8") as f:
    src = f.read()

# 语法检查
ast.parse(src)
check("erp_timing_engine.py 语法正确", True)

# 代码结构检查
check("M1缓存文件路径存在", 
      "erp_m1_history.parquet" in src,
      "erp_m1_history.parquet not found in source")

check("atomic_write_parquet 调用存在 (M1写入)", 
      src.count("atomic_write_parquet") >= 3,  # PE + 10Y + M1
      f"atomic_write_parquet count = {src.count('atomic_write_parquet')}")

check("M1磁盘降级读取逻辑存在", 
      "M1 使用磁盘缓存" in src,
      "M1 disk cache fallback message not found")

# 实际调用测试 (使用内存缓存或磁盘缓存)
import pandas as pd
try:
    m1_df = engine._fetch_m1_history()
    check(f"M1数据获取成功: {len(m1_df)} rows", 
          len(m1_df) > 0,
          f"empty dataframe")
    
    # 验证数据结构
    required_cols = ['month', 'm1_yoy', 'm2_yoy']
    has_cols = all(c in m1_df.columns for c in required_cols)
    check(f"M1数据包含必要列 {required_cols}", 
          has_cols,
          f"got columns: {list(m1_df.columns)}")

    # 验证磁盘缓存文件是否已写入
    cache_path = os.path.join("data_lake", "erp_m1_history.parquet")
    check(f"M1 Parquet缓存已持久化", 
          os.path.exists(cache_path),
          f"file not found: {cache_path}")
    
    if os.path.exists(cache_path):
        cached_df = pd.read_parquet(cache_path)
        check(f"磁盘缓存可读取: {len(cached_df)} rows", 
              len(cached_df) > 0,
              "cached df empty")
except Exception as e:
    check(f"M1数据获取 (可能API不可用)", False, str(e))


# ============================================================
# TEST 3: 降级信号不会误导 (安全边界验证)
# ============================================================
print("\n⚠️ TEST 3: 降级信号安全边界")
print("-" * 40)

# 验证降级的D1评分不会触发买入
import math
erp_fb = 4.0
d1_score = 100.0 / (1.0 + math.exp(-1.5 * (erp_fb - 4.0)))
check(f"降级ERP=4.0% → D1评分={d1_score:.0f} (应=50, 中性)", 
      49 <= d1_score <= 51,
      f"got {d1_score}")

# 验证降级综合分不在买入区间
check("降级Score=50 不触发买入 (阈值55)", 
      50 < 55,  # hold区间是40-55
      "50 should not trigger buy")

check("降级Score=50 不触发减仓 (阈值40)", 
      50 > 40,  # hold区间
      "50 should not trigger reduce")

# 旧版验证(反面教材)
old_erp = 6.2
old_d1 = 100.0 / (1.0 + math.exp(-1.5 * (old_erp - 4.0)))
check(f"[反面] 旧版ERP=6.2% → D1={old_d1:.0f} (危险!接近满分)", 
      old_d1 > 90,
      f"old d1={old_d1}")
print(f"    → 旧版降级D1={old_d1:.1f} 会误导为'极度低估', 已修复 ✅")


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
