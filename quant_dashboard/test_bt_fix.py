import sys
sys.path.insert(0, '.')
from data_manager import FactorDataManager
from momentum_backtest_engine import MOMENTUM_POOL_V2, BENCHMARK_CODE

dm = FactorDataManager()
codes = [e['code'] for e in MOMENTUM_POOL_V2] + [BENCHMARK_CODE, '000300.SH']
present = []
missing = []
for code in codes:
    try:
        df = dm.get_price_payload(code)
        if df is None or df.empty:
            missing.append(code)
        else:
            present.append((code, len(df)))
    except Exception as ex:
        missing.append(code)

print('Present:', len(present))
for c, n in present:
    print(' ', c, n)
print('Missing:', len(missing))
for c in missing:
    print(' ', c)
