"""
AlphaCore · ERP回测数据预处理模块
==================================
将 PE-TTM(日频) + 10Y国债(日频) + M1/M2(月频) 合并为日频宽表。

核心防线:
  1. M1/M2 月频→日频前向填充
  2. M1 发布延迟模拟 (滞后1个月，防止未来函数)
  3. 所有 NaN 采用 ffill + bfill，确保无空值

数据源: Tushare Pro (复用 erp_timing_engine.py 的缓存逻辑)
"""

import pandas as pd
import numpy as np
import tushare as ts
import time
import os
from datetime import datetime, timedelta

TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)


def _fetch_pe_ttm(start_date: str, end_date: str, index_code: str = "000300.SH") -> pd.DataFrame:
    """
    获取指数 PE-TTM 日频数据 (带 parquet 增量缓存)
    返回: DataFrame[trade_date, pe_ttm, turnover_rate]
    """
    cache_file = os.path.join(CACHE_DIR, "erp_pe_ttm.parquet")
    existing = None

    if os.path.exists(cache_file):
        existing = pd.read_parquet(cache_file)
        existing['trade_date'] = pd.to_datetime(existing['trade_date'])

    # 拉取数据
    df = pro.index_dailybasic(
        ts_code=index_code, start_date=start_date, end_date=end_date,
        fields="ts_code,trade_date,pe,pe_ttm,pb,turnover_rate"
    )
    if df is not None and not df.empty:
        df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        if existing is not None:
            df = pd.concat([existing, df]).drop_duplicates(subset='trade_date', keep='last')
        df = df.sort_values('trade_date').reset_index(drop=True)
        df.to_parquet(cache_file)
        print(f"[ERP Data] PE-TTM: {len(df)} rows cached")
    elif existing is not None:
        df = existing
    else:
        raise ValueError("PE-TTM 数据拉取失败")

    return df[['trade_date', 'pe_ttm', 'turnover_rate']].sort_values('trade_date').reset_index(drop=True)


def _fetch_yield_10y(start_date: str, end_date: str, bond_code: str = "1001.CB") -> pd.DataFrame:
    """
    获取10Y国债收益率日频数据 (分批拉取 + parquet 缓存)
    返回: DataFrame[trade_date, yield_10y]
    """
    cache_file = os.path.join(CACHE_DIR, "erp_yield_10y.parquet")
    existing = None

    if os.path.exists(cache_file):
        existing = pd.read_parquet(cache_file)
        existing['trade_date'] = pd.to_datetime(existing['trade_date'])

    start_dt = datetime.strptime(start_date, "%Y%m%d")
    end_dt = datetime.strptime(end_date, "%Y%m%d")

    # 检查是否需要增量拉取
    need_fetch = True
    if existing is not None and not existing.empty:
        cached_max = existing['trade_date'].max()
        if cached_max >= end_dt:
            need_fetch = False
        else:
            start_dt = cached_max - timedelta(days=1)

    all_dfs = []
    if need_fetch:
        chunk_start = start_dt
        while chunk_start < end_dt:
            chunk_end = min(chunk_start + timedelta(days=180), end_dt)
            s_str = chunk_start.strftime("%Y%m%d")
            e_str = chunk_end.strftime("%Y%m%d")
            try:
                chunk = pro.yc_cb(ts_code=bond_code, curve_type='0',
                                  start_date=s_str, end_date=e_str)
                if chunk is not None and not chunk.empty:
                    chunk_10y = chunk[chunk['curve_term'] == 10.0].copy()
                    if not chunk_10y.empty:
                        all_dfs.append(chunk_10y)
            except Exception as e:
                print(f"[ERP Data] yield batch {s_str}-{e_str}: {e}")
            chunk_start = chunk_end + timedelta(days=1)
            time.sleep(3.5)  # Tushare 限流

    if all_dfs:
        new_df = pd.concat(all_dfs, ignore_index=True)
        new_df['trade_date'] = pd.to_datetime(new_df['trade_date'], format='%Y%m%d')
        new_df = new_df.rename(columns={'yield': 'yield_10y'})
        new_df = new_df[['trade_date', 'yield_10y']]
        if existing is not None:
            df = pd.concat([existing, new_df]).drop_duplicates(subset='trade_date', keep='last')
        else:
            df = new_df
        df = df.sort_values('trade_date').reset_index(drop=True)
        df.to_parquet(cache_file)
        print(f"[ERP Data] 10Y Yield: {len(df)} rows cached")
    elif existing is not None:
        df = existing
    else:
        raise ValueError("国债收益率数据拉取失败")

    return df[['trade_date', 'yield_10y']].sort_values('trade_date').reset_index(drop=True)


def _fetch_m1_m2(months: int = 120) -> pd.DataFrame:
    """
    获取M1/M2同比月频数据
    返回: DataFrame[month, m1_yoy, m2_yoy]
    """
    end_m = datetime.now().strftime("%Y%m")
    start_m = (datetime.now() - timedelta(days=months * 31)).strftime("%Y%m")

    df = pro.cn_m(start_m=start_m, end_m=end_m, fields="month,m1,m1_yoy,m2,m2_yoy")
    if df is None or df.empty:
        raise ValueError("M1/M2 数据拉取失败")

    df = df.sort_values('month').reset_index(drop=True)
    df['m1_yoy'] = pd.to_numeric(df['m1_yoy'], errors='coerce')
    df['m2_yoy'] = pd.to_numeric(df['m2_yoy'], errors='coerce')
    print(f"[ERP Data] M1/M2: {len(df)} months")
    return df[['month', 'm1_yoy', 'm2_yoy']]


def _expand_monthly_to_daily(m_df: pd.DataFrame, daily_dates: pd.DatetimeIndex,
                              publish_delay_months: int = 1) -> pd.DataFrame:
    """
    将月频 M1/M2 数据展开为日频 (核心防未来函数逻辑)

    关键设计:
      - M1数据通常在次月中旬发布 (例如2月M1在3月15日左右公布)
      - 为保守防止未来函数，我们做整月延迟:
        即 2024-01 的M1数据，从 2024-03-01 起才可用
      - publish_delay_months=1: 延迟1个月 (实际约45天)

    方法: 将月份+delay_months 转为日期，然后 merge_asof 到交易日
    """
    m_df = m_df.copy()

    # month 格式: "202401" → 转为 datetime
    m_df['month_dt'] = pd.to_datetime(m_df['month'], format='%Y%m')

    # 发布延迟: 数据在 (month + delay_months) 的1号才可用
    m_df['available_date'] = m_df['month_dt'] + pd.DateOffset(months=publish_delay_months + 1)

    # 构建日频 DataFrame
    daily_df = pd.DataFrame({'trade_date': daily_dates})
    daily_df = daily_df.sort_values('trade_date').reset_index(drop=True)

    # merge_asof: 对每个交易日，找最近的已发布M1数据
    m_df = m_df.sort_values('available_date')
    result = pd.merge_asof(
        daily_df,
        m_df[['available_date', 'm1_yoy', 'm2_yoy']],
        left_on='trade_date',
        right_on='available_date',
        direction='backward'
    )

    result['scissor'] = result['m1_yoy'] - result['m2_yoy']
    return result[['trade_date', 'm1_yoy', 'm2_yoy', 'scissor']]


def prepare_erp_backtest_data(start_date: str = "20170101",
                               end_date: str = None,
                               index_code: str = "000300.SH") -> pd.DataFrame:
    """
    核心函数: 构建ERP回测日频宽表

    返回 DataFrame 列:
      - trade_date: 交易日期
      - pe_ttm: PE-TTM
      - yield_10y: 10Y国债收益率 (%)
      - earnings_yield: 盈利收益率 (1/PE × 100, %)
      - erp: 股权风险溢价 (earnings_yield - yield_10y, %)
      - m1_yoy: M1同比 (%, 已延迟)
      - m2_yoy: M2同比 (%, 已延迟)
      - scissor: M1-M2 剪刀差 (%)
      - pe_vol: PE滚动标准差 (60日)

    注意:
      - start_date 建议提前1年 (如回测2018开始，传入20170101)
        以确保ERP分位和PE波动率有足够回溯期
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    print(f"[ERP Backtest Data] 构建日频宽表: {start_date} → {end_date}")

    # 1. 拉取PE-TTM (日频)
    pe_df = _fetch_pe_ttm(start_date, end_date, index_code)

    # 2. 拉取10Y国债 (日频)
    yield_df = _fetch_yield_10y(start_date, end_date)

    # 3. 合并 PE + Yield
    merged = pd.merge(pe_df, yield_df, on='trade_date', how='left')
    merged = merged.sort_values('trade_date')
    merged['yield_10y'] = merged['yield_10y'].ffill().bfill()
    merged = merged.dropna(subset=['pe_ttm', 'yield_10y'])
    merged = merged[merged['pe_ttm'] > 0].copy()

    # 4. 计算 ERP
    merged['earnings_yield'] = 1.0 / merged['pe_ttm'] * 100
    merged['erp'] = merged['earnings_yield'] - merged['yield_10y']

    # 5. PE波动率 (60日)
    merged['pe_vol'] = merged['pe_ttm'].rolling(60, min_periods=20).std()

    # 6. 拉取并展开 M1/M2 (月频→日频, 带发布延迟)
    m1_df = _fetch_m1_m2(months=120)
    m1_daily = _expand_monthly_to_daily(m1_df, merged['trade_date'])

    # 7. 合并宏观数据
    merged = pd.merge(merged, m1_daily, on='trade_date', how='left')
    merged['m1_yoy'] = merged['m1_yoy'].ffill().bfill()
    merged['m2_yoy'] = merged['m2_yoy'].ffill().bfill()
    merged['scissor'] = merged['scissor'].ffill().bfill()

    # 8. 填充所有剩余NaN
    merged = merged.ffill().bfill()

    print(f"[ERP Backtest Data] 宽表构建完成: {len(merged)} 行, "
          f"{merged['trade_date'].min().strftime('%Y-%m-%d')} → "
          f"{merged['trade_date'].max().strftime('%Y-%m-%d')}")

    return merged.reset_index(drop=True)


# ===== CLI Self-Test =====
if __name__ == "__main__":
    print("=" * 60)
    print("ERP Backtest Data Pipeline — Self-Test")
    print("=" * 60)

    df = prepare_erp_backtest_data("20170101")
    print(f"\n✅ 宽表形状: {df.shape}")
    print(f"列: {list(df.columns)}")
    print(f"\n最新5行:")
    print(df.tail())
    print(f"\n统计:")
    print(df[['erp', 'm1_yoy', 'scissor', 'pe_vol']].describe())
    null_count = df.isnull().sum().sum()
    print(f"\n空值总数: {null_count} {'✅' if null_count == 0 else '❌'}")
