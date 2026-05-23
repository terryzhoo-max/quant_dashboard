"""V10.0 Signal Consensus Integration Tests (Post-Polish)"""
import sys
sys.path.insert(0, '.')

from dashboard_modules.assemble_response import (
    _compute_signal_consensus, _compute_signal_strength, _compute_weighted_consensus
)

def test_macro_anchor_governance():
    """AIAE neutral should cap label at '偏空/偏多' even with extreme score"""
    # Score <= -30 but AIAE R3 (neutral) → should NOT be '强势看空'
    s = _compute_signal_strength(
        {'signal_count': {'buy': 0, 'sell': 0}},
        {'buy_count': 3, 'avg_momentum': 5.61},
        {'trend_up_count': 0},
        -2.0,  # extreme ERP bearish
        3      # AIAE NEUTRAL
    )
    c = _compute_weighted_consensus(s)
    assert c['label'] == '偏空共振', f"AIAE neutral + score<=-30 should cap at '偏空共振', got '{c['label']}'"
    assert c['direction'] == 'bear'
    print(f"  PASS: AIAE neutral caps label → {c['label']} (score={c['score']})")

def test_macro_confirms_strong():
    """AIAE non-neutral allows '强势' labels"""
    # Score <= -30 and AIAE R4 (bearish) → should be '强势看空'
    s = _compute_signal_strength(
        {'signal_count': {'buy': 0, 'sell': 5}},
        {'buy_count': 0, 'avg_momentum': -3},
        {'trend_up_count': 0},
        -2.0,
        4  # AIAE bearish
    )
    c = _compute_weighted_consensus(s)
    assert c['label'] == '强势看空', f"AIAE R4 + extreme bear should be '强势看空', got '{c['label']}'"
    print(f"  PASS: AIAE R4 confirms → {c['label']} (score={c['score']})")

def test_bull_macro_governance():
    """AIAE neutral should cap bull label too"""
    s = _compute_signal_strength(
        {'signal_count': {'buy': 10, 'sell': 0}},
        {'buy_count': 5, 'avg_momentum': 12},
        {'trend_up_count': 8},
        2.0,
        3  # AIAE NEUTRAL
    )
    c = _compute_weighted_consensus(s)
    assert c['label'] == '偏多共振', f"AIAE neutral + score>=30 should cap at '偏多共振', got '{c['label']}'"
    print(f"  PASS: Bull capped → {c['label']} (score={c['score']})")

def test_consensus_string_format():
    """Consensus string should use score format, not X/5 format"""
    result = _compute_signal_consensus(
        {'signal_count': {'buy': 0, 'sell': 0}},
        {'buy_count': 3, 'avg_momentum': 5.61},
        {'trend_up_count': 0},
        -1.0, 3
    )
    consensus_str = result[2]
    assert '/' not in consensus_str, f"V10 consensus should not use X/5 format: '{consensus_str}'"
    assert any(c.isdigit() for c in consensus_str), f"Should contain score number: '{consensus_str}'"
    print(f"  PASS: Consensus string = '{consensus_str}'")

def test_all_previous():
    """Regression: previous tests still pass"""
    from dashboard_modules.assemble_response import _compute_signal_strength as cs, _compute_weighted_consensus as wc
    
    # Degraded
    s = cs({}, None, None, None, None)
    c = wc(s)
    assert c['label'] == '中性均衡', f"Degraded: {c['label']}"
    
    # Extreme bull with AIAE R1
    s = cs({'signal_count':{'buy':15,'sell':0}},{'buy_count':3,'avg_momentum':12},{'trend_up_count':8},2.0,1)
    c = wc(s)
    assert c['label'] == '强势共振', f"Extreme bull R1: {c['label']}"
    
    # Direction sanity
    s_r1 = cs({}, {}, {}, 0, 1)
    assert s_r1['aiae'] == 1.0
    s_r5 = cs({}, {}, {}, 0, 5)
    assert s_r5['aiae'] == -1.0
    
    print(f"  PASS: All regression tests passed")

if __name__ == '__main__':
    tests = [
        ("Macro anchor governance (bear)", test_macro_anchor_governance),
        ("Macro confirms strong", test_macro_confirms_strong),
        ("Macro anchor governance (bull)", test_bull_macro_governance),
        ("Consensus string format", test_consensus_string_format),
        ("Regression tests", test_all_previous),
    ]
    passed = 0
    for name, fn in tests:
        try:
            print(f"\n[{name}]")
            fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
    
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{len(tests)} passed")
    if passed == len(tests):
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        exit(1)
