import pandas as pd

codes = ['515100.SH', '510880.SH', '159545.SZ', '512890.SH',
         '515080.SH', '513530.SH', '513950.SH', '159201.SZ', '510300.SH']
for c in codes:
    try:
        df = pd.read_parquet(f'data_lake/daily_prices/{c}.parquet')
        print(f'{c}: {df["trade_date"].min()} ~ {df["trade_date"].max()}, {len(df)} rows')
    except Exception as e:
        print(f'{c}: ERROR - {e}')
