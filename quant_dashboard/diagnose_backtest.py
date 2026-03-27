"""诊断数据问题"""
import pandas as pd
import numpy as np
import sys
sys.stdout.reconfigure(encoding='utf-8')

# 检查价格数据
df_510300 = pd.read_parquet('data_lake/daily_prices/510300.SH.parquet')
df_515100 = pd.read_parquet('data_lake/daily_prices/515100.SH.parquet')

print("=== 510300 沪深300ETF 价格样本 ===")
print(df_510300[['trade_date','close']].tail(10).to_string())
print(f"\n价格范围: {df_510300['close'].min():.2f} ~ {df_510300['close'].max():.2f}")

print("\n=== 515100 红利低波ETF 价格样本 ===")
print(df_515100[['trade_date','close']].tail(10).to_string())
print(f"\n价格范围: {df_515100['close'].min():.2f} ~ {df_515100['close'].max():.2f}")

# 计算实际涨幅
from dividend_backtest_engine import load_prices
print("\n=== BEAR期（2022-01-04~2022-10-31）基准走势 ===")
p = load_prices(['510300.SH'], '2022-01-04', '2022-10-31')
bm = p['510300.SH']
bm_ret = (bm.iloc[-1] / bm.iloc[0] - 1) * 100
print(f"沪深300ETF区间收益: {bm_ret:.1f}%")
print(f"数据点数: {len(bm)}")

print("\n=== BULL期（2024-09-01~2024-12-31）基准走势 ===")
p2 = load_prices(['510300.SH'], '2024-09-01', '2024-12-31')
bm2 = p2['510300.SH']
bm_ret2 = (bm2.iloc[-1] / bm2.iloc[0] - 1) * 100
print(f"沪深300ETF区间收益: {bm_ret2:.1f}%")

# 检查annualization问题
print("\n=== _metrics计算验证 ===")
n_bear = len(bm)
ann_factor = 252/n_bear
print(f"BEAR期: {n_bear}天, 年化因子={ann_factor:.3f}")
total_ret = bm.iloc[-1]/bm.iloc[0] - 1
ann_ret = total_ret**ann_factor - 1
print(f"基准总收益={total_ret*100:.1f}%, 年化={ann_ret*100:.1f}%")
