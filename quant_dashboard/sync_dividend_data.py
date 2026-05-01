"""
Step 1: 同步8只红利ETF + 沪深300ETF基准历史数据
起始日期：2022-01-01（统一基准线）
"""
import tushare as ts
import pandas as pd
import os
import time

from config import TUSHARE_TOKEN
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

DAILY_PRICE_DIR = "data_lake/daily_prices"
os.makedirs(DAILY_PRICE_DIR, exist_ok=True)

DIVIDEND_POOL = [
    ('515100.SH', 'FD'),  # 中证红利低波100ETF
    ('510880.SH', 'FD'),  # 红利ETF
    ('159545.SZ', 'FD'),  # 恒生红利低波ETF
    ('512890.SH', 'FD'),  # 红利低波ETF
    ('515080.SH', 'FD'),  # 央企红利ETF
    ('513530.SH', 'FD'),  # 港股通红利ETF
    ('513950.SH', 'FD'),  # 恒生红利ETF
    ('159201.SZ', 'FD'),  # 自由现金流ETF
    ('510300.SH', 'FD'),  # 沪深300ETF（基准）
]

START_DATE = "20220101"
END_DATE   = "20260327"

for code, asset in DIVIDEND_POOL:
    fpath = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
    
    # 增量逻辑
    start_sync = START_DATE
    existing = None
    if os.path.exists(fpath):
        existing = pd.read_parquet(fpath)
        if not existing.empty:
            last = str(existing['trade_date'].max())
            from datetime import datetime, timedelta
            last_dt = datetime.strptime(last[:8], "%Y%m%d")
            start_sync = (last_dt + timedelta(days=1)).strftime("%Y%m%d")
    
    if start_sync.replace("-","") >= END_DATE:
        print(f"[SKIP] {code} 数据已最新")
        continue
    
    print(f"[SYNC] {code} 拉取 {start_sync} -> {END_DATE}...")
    try:
        df = ts.pro_bar(ts_code=code, asset=asset, adj='qfq',
                        start_date=start_sync, end_date=END_DATE)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date').reset_index(drop=True)
            if existing is not None:
                dfs = [d for d in [existing, df] if d is not None and not d.empty]
                df = pd.concat(dfs).drop_duplicates('trade_date').sort_values('trade_date').reset_index(drop=True)
            df.to_parquet(fpath)
            # 验证数量
            rows = len(df)
            print(f"  [OK] {code}: {rows} 行, {df.trade_date.min()} - {df.trade_date.max()}")
        else:
            print(f"  [WARN] {code}: 无数据返回")
        time.sleep(0.3)
    except Exception as e:
        print(f"  [ERROR] {code}: {e}")

print("\n=== 数据同步完成 ===")
# 最终验证
print("\n标的池数据摘要:")
for code, _ in DIVIDEND_POOL:
    fpath = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
    if os.path.exists(fpath):
        df = pd.read_parquet(fpath)
        # 只看2022年后的
        df_2022 = df[df['trade_date'] >= '20220101']
        print(f"  {code}: 2022起 {len(df_2022)} 条, 最新 {df['trade_date'].max()}")
    else:
        print(f"  {code}: 文件不存在")
