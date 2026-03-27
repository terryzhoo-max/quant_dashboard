"""同步动量策略所需的全部 ETF 历史价格数据到本地 data_lake"""
import sys
sys.path.insert(0, '.')
from data_manager import FactorDataManager
from momentum_backtest_engine import MOMENTUM_POOL_V2, BENCHMARK_CODE, run_momentum_backtest

dm = FactorDataManager()

# All codes needed
all_codes = [etf["code"] for etf in MOMENTUM_POOL_V2] + [BENCHMARK_CODE, "000300.SH"]
print(f"Syncing {len(all_codes)} ETF price series from 2021-01-01...")

# ETF/Fund codes need asset='FD'; 000300.SH index needs asset='I'
etf_codes = [etf["code"] for etf in MOMENTUM_POOL_V2] + [BENCHMARK_CODE]
index_codes = ["000300.SH"]

dm.sync_daily_prices(etf_codes, start_date="20210101", asset='FD')
dm.sync_daily_prices(index_codes, start_date="20210101", asset='I')

print("\nSync complete. Checking data...")
present = []
missing = []
for code in all_codes:
    df = dm.get_price_payload(code)
    if df is not None and not df.empty:
        present.append((code, len(df)))
    else:
        missing.append(code)

print(f"Present: {len(present)}")
for c, n in present:
    print(f"  {c}: {n} rows")
print(f"Missing: {len(missing)}")
for c in missing:
    print(f"  {c}")

if len(present) > 5:
    print("\nRunning backtest test...")
    result = run_momentum_backtest('2021-01-01', '2025-12-31')
    print('Status:', result.get('status'))
    if result.get('status') == 'success':
        p = result['performance']
        print(f'  CAGR:         {p.get("cagr")}%')
        print(f'  Excess CAGR:  {p.get("excess_cagr")}%')
        print(f'  Max DD:       {p.get("max_drawdown")}%')
        print(f'  Sharpe:       {p.get("sharpe")}')
        print(f'  IR:           {p.get("information_ratio")}')
        print(f'  Monthly Win:  {p.get("monthly_win_rate")}%')
        print(f'  n_days:       {p.get("n_days")}')
