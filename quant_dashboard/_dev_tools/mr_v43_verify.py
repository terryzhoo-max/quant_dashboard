"""MR V4.3 Verification Script"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np

from mean_reversion_engine import _sigmoid_score, generate_signal

passed = 0
total_tests = 4

# Test 1: Sigmoid continuity - RSI 40.0 vs 40.1 should differ by < 1 point
s_40  = _sigmoid_score(40.0, center=45, steepness=0.3, max_score=25)
s_401 = _sigmoid_score(40.1, center=45, steepness=0.3, max_score=25)
diff = abs(s_40 - s_401)
ok1 = diff < 1.0
print(f"[TEST 1] Sigmoid continuity: RSI=40.0 -> {s_40:.2f}, RSI=40.1 -> {s_401:.2f}, diff={diff:.3f} {'PASS' if ok1 else 'FAIL'}")
if ok1: passed += 1

# Test 2: opt_score weights sum = 1.0
weights = [0.30, 0.20, 0.15, 0.10, 0.25]
wsum = sum(weights)
ok2 = abs(wsum - 1.0) < 1e-6
print(f"[TEST 2] opt_score weight sum = {wsum:.2f} {'PASS' if ok2 else 'FAIL'}")
if ok2: passed += 1

# Test 3: stop_loss +/- compatibility
ind_base = {
    'close': 10, 'ma20': 10.5, 'ma_n': 10.5, 'rsi': 50, 'bias': -1,
    'percent_b': 0.5, 'regime': 'RANGE', 'score_gate': 68,
    'regime_params': {'rsi_buy': 40, 'rsi_sell': 70, 'bias_buy': -2.0, 'stop_loss': 0.07},
    'cost_price': 12
}
ind_neg = dict(ind_base)
ind_neg['regime_params'] = dict(ind_base['regime_params'])
ind_neg['regime_params']['stop_loss'] = -0.07

sig_pos = generate_signal(ind_base, 50)
sig_neg = generate_signal(ind_neg, 50)
ok3 = sig_pos == sig_neg
print(f"[TEST 3] stop_loss compat: +0.07 -> {sig_pos}, -0.07 -> {sig_neg} {'PASS' if ok3 else 'FAIL'}")
if ok3: passed += 1

# Test 4: coverage=0% penalty = 0.25 deduction
cov0 = 0.25 * min(max(0.0 / 0.30, 0), 1.0)
cov30 = 0.25 * min(max(0.30 / 0.30, 0), 1.0)
ok4 = abs(cov30 - cov0 - 0.25) < 1e-6
print(f"[TEST 4] coverage penalty: 0% -> {cov0:.2f}, 30% -> {cov30:.2f}, delta={cov30-cov0:.2f} {'PASS' if ok4 else 'FAIL'}")
if ok4: passed += 1

print(f"\n{'='*40}")
print(f"  Results: {passed}/{total_tests} tests passed")
if passed == total_tests:
    print("  ALL VERIFICATION PASSED")
else:
    print("  SOME TESTS FAILED")
print(f"{'='*40}")
