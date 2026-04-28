"""集成测试: HK + JP 引擎自检 (自动数据源)"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, proj_root)
os.chdir(proj_root)

print("=" * 60)
print("  集成测试: AIAE 自动数据源")
print("=" * 60)

# ===== JP Engine =====
print("\n[1/2] JP AIAE Engine...")
try:
    from aiae_jp_engine import get_jp_aiae_engine
    jp = get_jp_aiae_engine()
    r = jp.generate_report()
    c = r.get("current", {})
    m = r.get("raw_data", {}).get("margin", {})
    f = r.get("raw_data", {}).get("foreign", {})
    print(f"  Status: {r.get('status')}")
    print(f"  AIAE: {c.get('aiae_v1')}% | Regime: {c.get('regime')}")
    print(f"  Margin source: {m.get('source', '?')} | {m.get('margin_buying_trillion_jpy', '?')}兆円")
    print(f"  Foreign source: {f.get('source', '?')} | net={f.get('net_buy_billion_jpy', '?')}億円")
    print(f"  ✅ JP OK")
except Exception as e:
    print(f"  ❌ JP FAILED: {e}")
    import traceback; traceback.print_exc()

# ===== HK Engine =====
print("\n[2/2] HK AIAE Engine...")
try:
    from aiae_hk_engine import get_hk_aiae_engine
    hk = get_hk_aiae_engine()
    r = hk.generate_report()
    c = r.get("current", {})
    print(f"  Status: {r.get('status')}")
    print(f"  AIAE: {c.get('aiae_v1')}% | Regime: {c.get('regime')}")
    sb = c.get("southbound_flow", {})
    ah = c.get("ah_premium", {})
    print(f"  Southbound source: {sb.get('source', '?')}")
    print(f"    Weekly: {sb.get('weekly_net_buy_billion_rmb', '?')}亿 | 12M: {sb.get('cumulative_12m_billion_rmb', '?')}亿")
    print(f"  AH Premium source: {ah.get('source', '?')}")
    print(f"    Index: {ah.get('index_value', '?')} | {ah.get('interpretation', '')}")
    print(f"  ✅ HK OK")
except Exception as e:
    print(f"  ❌ HK FAILED: {e}")
    import traceback; traceback.print_exc()

print("\n" + "=" * 60)
print("  集成测试完成")
print("=" * 60)
