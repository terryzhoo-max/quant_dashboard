"""Quick smoke test for JOINT_WEIGHTS dual-dimension lookup"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from aiae_engine import AIAEEngine, JOINT_WEIGHTS, AIAE_RUN_ALL_WEIGHTS

e = AIAEEngine()

# Test all 3 tiers for regime III
w1, t1 = e.get_run_all_weights(3, 60)
w2, t2 = e.get_run_all_weights(3, 45)
w3, t3 = e.get_run_all_weights(3, 35)
w4, t4 = e.get_run_all_weights(3, None)

print(f"ERP=60(bull):     tier={t1} mr={w1['mr']} div={w1['div']} mom={w1['mom']}")
print(f"ERP=45(neutral):  tier={t2} mr={w2['mr']} div={w2['div']} mom={w2['mom']}")
print(f"ERP=35(bear):     tier={t3} mr={w3['mr']} div={w3['div']} mom={w3['mom']}")
print(f"ERP=None(fallback):tier={t4} mr={w4['mr']} div={w4['div']} mom={w4['mom']}")
print()

# Verify backward compatibility
compat = AIAE_RUN_ALL_WEIGHTS[3] == JOINT_WEIGHTS[3]["neutral"]
print(f"Backward compatibility: {'OK' if compat else 'FAIL'}")

# Verify all 15 cells sum to 1.0
errors = []
for r in JOINT_WEIGHTS:
    for t, w in JOINT_WEIGHTS[r].items():
        s = sum(w.values())
        if abs(s - 1.0) > 0.001:
            errors.append(f"R{r}/{t}: {s:.2f}")
print(f"Weight sum check: {'ALL 15 = 1.0 OK' if not errors else 'ERRORS: ' + ', '.join(errors)}")

# Extremes test
w_panic_bull, _ = e.get_run_all_weights(1, 80)  # Most aggressive
w_eupho_bear, _ = e.get_run_all_weights(5, 20)  # Most defensive
print(f"\nExtremes:")
print(f"  Panic+Bull:   MR={w_panic_bull['mr']} MOM={w_panic_bull['mom']} (aggressive)")
print(f"  Euphoria+Bear: DIV={w_eupho_bear['div']} AIAE={w_eupho_bear['aiae_etf']} (defensive)")
