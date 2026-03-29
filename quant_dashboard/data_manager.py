import pandas as pd
import tushare as ts
import os
import time
from datetime import datetime, timedelta
from typing import List, Optional

# ====== 配置区 ======
TUSHARE_TOKEN = "5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6"
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

    def sync_financial_indicators(self, ts_codes: List[str], start_year: int = 2018):
        """
        同步财务指标 (PIT 数据)
        由于 Tushare 单次调用限制，需按年度或季度分批拉取
        """
        current_year = datetime.now().year
        
        for code in ts_codes:
            file_path = os.path.join(FINA_INDICATOR_DIR, f"{code}.parquet")
            
            # 如果本地已有，检查是否需要增量更新（此处简化为存在即跳过，实际生产建议按 ann_date 增量）
            if os.path.exists(file_path):
                print(f"[DataManager] 跳过已存在数据: {code}")
                continue

            print(f"[DataManager] 正在拉取 {code} 的 PIT 财务数据...")
            all_indicators = []
            
            # 循环拉取各年数据
            for year in range(start_year, current_year + 1):
                try:
                    # 获取该年度的核心财务指标 (包含 ann_date 关键日期)
                    # 字段说明：ann_date 公告日期, end_date 报告期, roe, netprofit_margin 等
                    df = pro.fina_indicator(ts_code=code, start_date=f"{year}0101", end_date=f"{year}1231")
                    if df is not None and not df.empty:
                        all_indicators.append(df)
                    time.sleep(0.5) # 控制频率 (120次/分钟)
                except Exception as e:
                    print(f"  [ERROR] {code} {year}年获取失败: {e}")
                    break
            
            if all_indicators:
                full_df = pd.concat(all_indicators).drop_duplicates().sort_values("ann_date")
                full_df.to_parquet(file_path)
                print(f"  [SUCCESS] {code} 同步完成 ({len(full_df)} 条记录)")

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
                        combined_df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['trade_date']).sort_values("trade_date")
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

if __name__ == "__main__":
    manager = FactorDataManager()
    
    # 演示：同步前10只股票作为测试
    stocks = manager.get_all_stocks()
    test_codes = stocks["ts_code"].head(10).tolist()
    
    print(f"开始测试同步 {len(test_codes)} 只标的的财务数据...")
    manager.sync_financial_indicators(test_codes)
