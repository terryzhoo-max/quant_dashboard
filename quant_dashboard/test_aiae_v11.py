"""海外AIAE V1.1 端到端测试"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

SEP = "=" * 60
PASS = 0
FAIL = 0

def test_engine(name, engine_cls):
    global PASS, FAIL
    print(f"\n{SEP}")
    print(f"TEST: {name}")
    print(SEP)
    try:
        engine = engine_cls()
        t0 = time.time()
        report = engine.generate_report()
        elapsed = time.time() - t0

        status = report.get("status", "unknown")
        c = report.get("current", {})
        p = report.get("position", {})
        cv = report.get("cross_validation", {})
        signals = report.get("signals", [])
        chart = report.get("chart", {})

        print(f"  Status:      {status} ({'fallback' if status == 'fallback' else 'live'})")
        print(f"  Time:        {elapsed:.1f}s")
        print(f"  AIAE Core:   {c.get('aiae_core', 'N/A')}%")
        
        # Engine-specific factors
        if "margin_heat" in c:
            print(f"  Margin Heat: {c.get('margin_heat', 'N/A')}%")
        if "aaii_sentiment" in c:
            sp = c.get("aaii_sentiment", {})
            print(f"  AAII:        Bull={sp.get('bull_pct','?')}% Bear={sp.get('bear_pct','?')}% Spread={sp.get('spread','?')}")
        if "foreign_flow" in c:
            ff = c.get("foreign_flow", {})
            print(f"  Foreign:     net={ff.get('net_buy_billion_jpy','?')} billion JPY")
        if "southbound_heat" in c:
            print(f"  SB Heat:     {c.get('southbound_heat', 'N/A')}%")
        if "ah_premium" in c:
            ah = c.get("ah_premium", {})
            if isinstance(ah, dict):
                print(f"  AH Premium:  {ah.get('index_value', 'N/A')}")
            else:
                print(f"  AH Premium:  {ah}")

        v1 = c.get("aiae_v1", 0)
        regime = c.get("regime", 0)
        ri = c.get("regime_info", {})
        print(f"  -----------")
        print(f"  AIAE V1:     {v1}%")
        print(f"  Regime:      {regime} ({ri.get('cn', '?')})")
        print(f"  Range:       {ri.get('range', '?')}")
        print(f"  Position:    {p.get('matrix_position', 'N/A')}%")
        print(f"  ERP Level:   {p.get('erp_level', 'N/A')} (ERP={p.get('erp_value', 'N/A')}%)")
        print(f"  CV Verdict:  {cv.get('verdict', 'N/A')} ({cv.get('confidence_stars', '')})")
        print(f"  Signals:     {len(signals)}")
        if signals:
            for s in signals[:3]:
                print(f"    - {s.get('text', '')[:60]}")
        print(f"  Chart pts:   {len(chart.get('dates', []))}")

        # Sanity checks
        errors = []
        if v1 <= 0 or v1 > 50:
            errors.append(f"AIAE V1 out of range: {v1}")
        if regime < 1 or regime > 5:
            errors.append(f"Regime out of range: {regime}")
        if not ri.get("cn"):
            errors.append("Missing regime_info.cn")
        pos = p.get("matrix_position", 0)
        if pos < 0 or pos > 100:
            errors.append(f"Position out of range: {pos}")
        if len(signals) == 0:
            errors.append("No signals generated")

        if errors:
            print(f"\n  SANITY CHECK FAILED:")
            for e in errors:
                print(f"    ❌ {e}")
            FAIL += 1
        else:
            print(f"\n  ✅ ALL CHECKS PASSED")
            PASS += 1

    except Exception as e:
        print(f"  ❌ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        FAIL += 1


# ===== Run Tests =====
print("\n🧪 AIAE V1.1 Engine Test Suite\n")

# US
from aiae_us_engine import AIAEUSEngine
test_engine("🇺🇸 US AIAE Engine", AIAEUSEngine)

# JP
from aiae_jp_engine import AIAEJPEngine
test_engine("🇯🇵 JP AIAE Engine", AIAEJPEngine)

# HK
from aiae_hk_engine import AIAEHKEngine
test_engine("🇭🇰 HK AIAE Engine", AIAEHKEngine)

# Summary
print(f"\n{SEP}")
print(f"SUMMARY: {PASS} passed, {FAIL} failed")
print(SEP)
if FAIL == 0:
    print("🎉 ALL ENGINES OPERATIONAL")
else:
    print("⚠️  SOME ENGINES HAVE ISSUES")
