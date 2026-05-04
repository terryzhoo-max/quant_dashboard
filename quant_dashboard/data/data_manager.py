import pandas as pd
import tushare as ts
import os
import time
from datetime import datetime, timedelta
from typing import List, Optional

import config  # 导入config以触发Tushare全局连接修复(Monkey Patch)

# ====== 配置区 ======
TUSHARE_TOKEN = config.TUSHARE_TOKEN
DATA_DIR = "data_lake"
FINA_INDICATOR_DIR = os.path.join(DATA_DIR, "financials")
DAILY_PRICE_DIR = os.path.join(DATA_DIR, "daily_prices")

# 初始化 Tushare
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

class FactorDataManager:
    def __init__(self):
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        if not os.path.exists(FINA_INDICATOR_DIR):
            os.makedirs(FINA_INDICATOR_DIR)
        if not os.path.exists(DAILY_PRICE_DIR):
            os.makedirs(DAILY_PRICE_DIR)

    def get_all_stocks(self) -> pd.DataFrame:
        """获取全市场 A 股列表"""
        cache_path = os.path.join(DATA_DIR, "stock_list.parquet")
        if os.path.exists(cache_path):
            print(f"[DataManager] 加载本地股票列表缓存...")
            return pd.read_parquet(cache_path)
        
        print(f"[DataManager] 正在从 Tushare 获取全市场股票列表...")
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,list_date')
        df.to_parquet(cache_path)
        return df

    def sync_financial_indicators(self, ts_codes: List[str], start_year: int = 2018, force: bool = False):
        """
        V5.0: 同步财务指标 (PIT 数据) — 支持增量更新
        force=True 时强制全量刷新, 否则增量拉取最近1年数据
        """
        current_year = datetime.now().year
        
        for code in ts_codes:
            file_path = os.path.join(FINA_INDICATOR_DIR, f"{code}.parquet")
            existing_df = None
            
            if os.path.exists(file_path) and not force:
                existing_df = pd.read_parquet(file_path)
                if not existing_df.empty and 'ann_date' in existing_df.columns:
                    last_ann = str(existing_df['ann_date'].max())
                    last_year = int(last_ann[:4]) if len(last_ann) >= 4 else start_year
                    # 增量: 只拉取最后公告年份至今的数据
                    start_year = max(start_year, last_year)

            print(f"[DataManager] 正在{'增量' if existing_df is not None else '全量'}拉取 {code} 的 PIT 财务数据 ({start_year}-{current_year})...")
            all_indicators = []
            
            for year in range(start_year, current_year + 1):
                try:
                    df = pro.fina_indicator(ts_code=code, start_date=f"{year}0101", end_date=f"{year}1231")
                    if df is not None and not df.empty:
                        all_indicators.append(df)
                    time.sleep(0.5)
                except Exception as e:
                    print(f"  [ERROR] {code} {year}年获取失败: {e}")
                    break
            
            if all_indicators:
                new_df = pd.concat([d for d in all_indicators if not d.empty and not d.isna().all(axis=None)])
                if existing_df is not None:
                    dfs = [d for d in [existing_df, new_df] if not d.empty and not d.isna().all(axis=None)]
                    full_df = pd.concat(dfs).drop_duplicates(
                        subset=['ts_code', 'ann_date', 'end_date']
                    ).sort_values('ann_date')
                else:
                    full_df = new_df.drop_duplicates().sort_values('ann_date')
                full_df.to_parquet(file_path)
                print(f"  [SUCCESS] {code} 同步完成 ({len(full_df)} 条记录)")
            elif existing_df is not None:
                print(f"  [INFO] {code} 无新增财务数据")

    def get_factor_payload(self, ts_code: str, factor_names: List[str]) -> pd.DataFrame:
        """
        获取指定因子的 PIT 时间序列
        """
        file_path = os.path.join(FINA_INDICATOR_DIR, f"{ts_code}.parquet")
        if not os.path.exists(file_path):
            return pd.DataFrame()
        
        df = pd.read_parquet(file_path)
        # 仅保留 ann_date, end_date 和需要的因子字段
        cols = ["ts_code", "ann_date", "end_date"] + factor_names
        available_cols = [c for c in cols if c in df.columns]
        return df[available_cols]

    def sync_daily_prices(self, ts_codes: List[str], start_date: str = "20180101", end_date: Optional[str] = None, asset: str = 'E'):
        """同步日线行情 (含复权因子)"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
            
        for code in ts_codes:
            file_path = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
            
            # 增量逻辑
            start_sync_date = start_date
            existing_df = None
            if os.path.exists(file_path):
                existing_df = pd.read_parquet(file_path)
                if not existing_df.empty:
                    last_date = existing_df['trade_date'].max()
                    # 如果 last_date 是 YYYYMMDD 字符串，转为 datetime 再加一天
                    last_dt = datetime.strptime(str(last_date), "%Y%m%d")
                    start_sync_date = (last_dt + timedelta(days=1)).strftime("%Y%m%d")
            
            if start_sync_date > end_date:
                print(f"[DataManager] {code} 数据已是最新 ({start_sync_date} > {end_date})")
                continue
                
            print(f"[DataManager] 正在增量拉取 {code} 行情 ({start_sync_date} -> {end_date})...")
            try:
                new_df = ts.pro_bar(ts_code=code, asset=asset, adj='qfq', start_date=start_sync_date, end_date=end_date)
                if new_df is not None and not new_df.empty:
                    new_df = new_df.sort_values("trade_date")
                    if existing_df is not None:
                        dfs = [d for d in [existing_df, new_df] if not d.empty and not d.isna().all(axis=None)]
                        combined_df = pd.concat(dfs).drop_duplicates(subset=['trade_date']).sort_values("trade_date")
                    else:
                        combined_df = new_df
                    combined_df.to_parquet(file_path)
                    print(f"  [SUCCESS] {code} 增量更新完成")
                else:
                    print(f"  [INFO] {code} 无新数据")
                time.sleep(0.2)
            except Exception as e:
                print(f"  [ERROR] {code} 行情获取失败: {e}")

    def get_last_sync_date(self, ts_codes: List[str]) -> str:
        """获取这些股票里最晚的一个交易日期"""
        dates = []
        for code in ts_codes:
            file_path = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
            if os.path.exists(file_path):
                df = pd.read_parquet(file_path)
                if not df.empty:
                    dates.append(str(df['trade_date'].max()))
        return max(dates) if dates else "N/A"

    def get_price_payload(self, ts_code: str) -> pd.DataFrame:
        """读取行情数据并计算未来收益率"""
        file_path = os.path.join(DAILY_PRICE_DIR, f"{ts_code}.parquet")
        if not os.path.exists(file_path):
            return pd.DataFrame()
        
        df = pd.read_parquet(file_path)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.sort_values('trade_date')
        
        # 计算未来 5 日收益率 (用于 IC 计算)
        df['next_5d_ret'] = df['close'].shift(-5) / df['close'] - 1
        # V2.0: 返回 amount 列供资金热度引擎使用
        cols = ['trade_date', 'close', 'next_5d_ret']
        if 'amount' in df.columns:
            cols.append('amount')
        if 'vol' in df.columns:
            cols.append('vol')
        return df[[c for c in cols if c in df.columns]]

    def check_data_freshness(self, ts_codes: List[str]) -> dict:
        """
        V5.0: 检查因子数据新鲜度
        返回: {daily_latest: str, fina_latest: str, is_stale: bool, stale_days: int}
        """
        today = datetime.now().strftime("%Y%m%d")
        daily_dates = []
        fina_dates = []

        for code in ts_codes[:5]:  # 只检查前5只，提速
            # 日线数据
            dp = os.path.join(DAILY_PRICE_DIR, f"{code}.parquet")
            if os.path.exists(dp):
                df = pd.read_parquet(dp)
                if not df.empty:
                    daily_dates.append(str(df['trade_date'].max()))
            # 财务数据
            fp = os.path.join(FINA_INDICATOR_DIR, f"{code}.parquet")
            if os.path.exists(fp):
                df = pd.read_parquet(fp)
                if not df.empty and 'ann_date' in df.columns:
                    fina_dates.append(str(df['ann_date'].max()))

        daily_latest = max(daily_dates) if daily_dates else 'N/A'
        fina_latest = max(fina_dates) if fina_dates else 'N/A'

        # 判断是否过期: 日线数据超过1个自然日(周末+3)
        stale_days = 0
        is_stale = True
        if daily_latest != 'N/A':
            try:
                last_dt = datetime.strptime(str(daily_latest)[:8], "%Y%m%d")
                delta = (datetime.now() - last_dt).days
                stale_days = delta
                # 考虑周末: 周五收盘后到周一算3天, 不算过期
                is_stale = delta > 3 if datetime.now().weekday() == 0 else delta > 1
            except:
                pass

        return {
            'daily_latest': daily_latest,
            'fina_latest': fina_latest,
            'is_stale': is_stale,
            'stale_days': stale_days,
            'checked_at': datetime.now().strftime("%Y-%m-%d %H:%M")
        }

    def smart_sync(self, ts_codes: List[str], force: bool = False):
        """
        V5.0: 智能同步 — 仅当数据过期时拉取
        返回: sync_result dict
        """
        freshness = self.check_data_freshness(ts_codes)
        if not freshness['is_stale'] and not force:
            print(f"[SmartSync] 数据新鲜 (最新日线: {freshness['daily_latest']}), 跳过同步")
            return {'synced': False, 'freshness': freshness}

        print(f"[SmartSync] 数据过期 {freshness['stale_days']} 天, 开始同步...")
        # 同步日线行情
        self.sync_daily_prices(ts_codes)
        # 同步财务指标 (增量)
        self.sync_financial_indicators(ts_codes)
        # 重新检查
        new_freshness = self.check_data_freshness(ts_codes)
        print(f"[SmartSync] 同步完成, 最新日线: {new_freshness['daily_latest']}")
        return {'synced': True, 'freshness': new_freshness}


if __name__ == "__main__":
    manager = FactorDataManager()
    
    # 演示：同步前10只股票作为测试
    stocks = manager.get_all_stocks()
    test_codes = stocks["ts_code"].head(10).tolist()
    
    print(f"开始测试同步 {len(test_codes)} 只标的的财务数据...")
    manager.sync_financial_indicators(test_codes)
