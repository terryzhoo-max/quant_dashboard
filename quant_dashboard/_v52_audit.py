"""V5.2 Parameter Consistency Audit"""
import sys; sys.path.insert(0, '.')

print('=== V5.2 PARAMETER CONSISTENCY AUDIT ===')
print()

# 1. AIAE Params
from engines.aiae_params import (
    V5_ENABLED, V5_REGIME_THRESHOLDS, V5_REGIME_HYSTERESIS,
    V5_REGIME_SMOOTH_BUFFER, V5_POSITION_MATRIX, VERSION,
    REGIME_THRESHOLDS, REGIME_SMOOTH_BUFFER
)
print('[1] aiae_params.py')
print(f'  VERSION: {VERSION}')
print(f'  V5_ENABLED: {V5_ENABLED}')
print(f'  V5_THRESHOLDS: {V5_REGIME_THRESHOLDS}')
print(f'  V5_HYSTERESIS: {V5_REGIME_HYSTERESIS}')
print(f'  V5_SMOOTH_BUFFER: {V5_REGIME_SMOOTH_BUFFER}')
gaps = [round(V5_REGIME_THRESHOLDS[i+1]-V5_REGIME_THRESHOLDS[i],1) for i in range(3)]
min_gap = min(gaps)
print(f'  Gaps: {gaps}, min={min_gap}')
print(f'  Buffer < min_gap/2: {V5_REGIME_SMOOTH_BUFFER} < {min_gap/2} = {V5_REGIME_SMOOTH_BUFFER < min_gap/2}')
assert V5_REGIME_SMOOTH_BUFFER < min_gap / 2, 'BUFFER CONSTRAINT VIOLATED'
print(f'  V3_THRESHOLDS (legacy): {REGIME_THRESHOLDS}')
print()

# 2. Config
from config import POSITION_CONFIG, MR_SCORE_GATE, MR_STOP_LOSS
print('[2] config.py')
print(f'  MR_SCORE_GATE: {MR_SCORE_GATE}')
print(f'  MR_STOP_LOSS: {MR_STOP_LOSS}')
tc = POSITION_CONFIG["total_cap"]
sl = POSITION_CONFIG["single_limit"]
print(f'  total_cap: {tc}%')
print(f'  single_limit: {sl}%')
print()

# 3. params_api
from routers.params_api import get_strategy_config
import asyncio
result = asyncio.run(get_strategy_config())
print('[3] params_api /strategy-config')
print(f'  version: {result["version"]}')
print(f'  aiae.v5_enabled: {result["aiae"]["v5_enabled"]}')
thresholds_from_api = result['aiae'].get('thresholds')
print(f'  aiae.thresholds: {thresholds_from_api}')
assert thresholds_from_api == V5_REGIME_THRESHOLDS, f'THRESHOLD MISMATCH: API={thresholds_from_api} vs params={V5_REGIME_THRESHOLDS}'
print(f'  aiae.thresholds MATCHES aiae_params: OK')
print(f'  mr.score_gate: {result["mr"]["score_gate"]}')
assert result['mr']['score_gate'] == MR_SCORE_GATE, 'MR_SCORE_GATE MISMATCH'
print(f'  mr.score_gate MATCHES config: OK')
print()

# 4. Tushare limiter
from services.tushare_limiter import tushare_limiter
stats = tushare_limiter.stats
print('[4] tushare_limiter')
print(f'  interval_ms: {stats["interval_ms"]}ms')
print(f'  total_calls: {stats["total_calls"]}')
print()

# 5. V5 Position Matrix
print('[5] V5 Position Matrix')
for tier, positions in V5_POSITION_MATRIX.items():
    assert len(positions) == 5, f'{tier} has {len(positions)} positions'
    assert all(0 <= p <= 100 for p in positions), f'{tier} invalid positions'
    assert positions == sorted(positions, reverse=True), f'{tier} not monotonic'
    print(f'  {tier}: {positions} (monotonic: OK)')
print()

# 6. Regime classification cross-check
from engines.aiae_engine import get_aiae_engine
engine = get_aiae_engine()
test_values = [21.0, 22.0, 23.0, 24.0, 25.5, 27.0, 28.0, 29.0, 30.0]
print('[6] Regime Classification (cold start, V5)')
for v in test_values:
    r = engine.classify_regime(0, None, aiae_simple=v)
    print(f'  AIAE_simple={v:5.1f}% -> R{r}')
# Verify key thresholds
r_21 = engine.classify_regime(0, None, aiae_simple=21.0)
r_23 = engine.classify_regime(0, None, aiae_simple=23.0)
r_25 = engine.classify_regime(0, None, aiae_simple=25.5)
r_28 = engine.classify_regime(0, None, aiae_simple=28.0)
r_30 = engine.classify_regime(0, None, aiae_simple=30.0)
assert r_21 == 1, f'21% should be R1, got R{r_21}'
assert r_23 == 2, f'23% should be R2, got R{r_23}'
assert r_25 == 3, f'25.5% should be R3, got R{r_25}'
assert r_28 == 4, f'28% should be R4, got R{r_28}'
assert r_30 == 5, f'30% should be R5, got R{r_30}'
print('  Boundary classification: ALL CORRECT')
print()

# 7. Hysteresis behavior
print('[7] Hysteresis Behavior')
# From R3, need to exceed 27.0+0.5=27.5 to go to R4
r_from_r3_at_27_3 = engine.classify_regime(0, 3, aiae_simple=27.3)
r_from_r3_at_27_6 = engine.classify_regime(0, 3, aiae_simple=27.6)
print(f'  From R3: AIAE=27.3% -> R{r_from_r3_at_27_3} (should stay R3, H=+0.5)')
print(f'  From R3: AIAE=27.6% -> R{r_from_r3_at_27_6} (should transition to R4)')
assert r_from_r3_at_27_3 == 3, f'Hysteresis failed: 27.3 from R3 should stay R3'
assert r_from_r3_at_27_6 == 4, f'Hysteresis failed: 27.6 from R3 should go R4'

# From R4, need to drop below 27.0-0.5=26.5 to go back to R3
r_from_r4_at_26_7 = engine.classify_regime(0, 4, aiae_simple=26.7)
r_from_r4_at_26_4 = engine.classify_regime(0, 4, aiae_simple=26.4)
print(f'  From R4: AIAE=26.7% -> R{r_from_r4_at_26_7} (should stay R4, H=-0.5)')
print(f'  From R4: AIAE=26.4% -> R{r_from_r4_at_26_4} (should transition to R3)')
assert r_from_r4_at_26_7 == 4, f'Hysteresis failed: 26.7 from R4 should stay R4'
assert r_from_r4_at_26_4 == 3, f'Hysteresis failed: 26.4 from R4 should go R3'
print('  Hysteresis direction-aware logic: CORRECT')
print()

print('=== ALL 7 CONSISTENCY CHECKS PASSED ===')
