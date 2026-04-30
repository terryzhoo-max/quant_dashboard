import tushare as ts
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from config import TUSHARE_TOKEN

class SwingDataFetcher:
    """
    7大ETF生产级波段数据获取器
    """
    def __init__(self):
        self.pro = ts.pro_api(TUSHARE_TOKEN)
        
        # 标的映射：字典 key 是引擎里定义的 asset_id
        self.a_share_etfs = {
            'CSI300': '510300.SH',  # 沪深300ETF
            'CSI500': '510500.SH',  # 中证500ETF
            'STAR50': '588090.SH',  # 科创50ETF
            'SP500':  '513500.SH',  # 标普500ETF (博时)
            'NASDAQ': '513100.SH',  # 纳指100ETF (国泰)
            'NIKKEI': '513520.SH',  # 日经225ETF (华夏)
            'HSTECH': '513180.SH',  # 恒生科技ETF (华夏)
        }

    def fetch_etf_daily(self, asset_id: str, days: int = 120) -> pd.DataFrame:
        """获取ETF日线复权数据"""
        if asset_id not in self.a_share_etfs:
            raise ValueError(f"Unknown asset_id: {asset_id}")
            
        ts_code = self.a_share_etfs[asset_id]
        
        # 计算起止日期
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
        
        # 从 Tushare 获取场内基金日线行情
        try:
            df = self.pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df.empty:
                print(f"⚠️ [DataFetcher] Tushare 返回 {ts_code} 数据为空！")
                return pd.DataFrame()
                
            # 排序并重命名
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df = df.sort_values('trade_date').reset_index(drop=True)
            
            # 为了对接 swing_strategy_engine.py，返回包含 'close' 的 df
            # 注意：真实的量化生产环境需要取复权因子，但针对波段跟踪，
            # 若ETF近期无分红，直接用收盘价近似即可。严谨做法应该用 adj_factor，这里暂时简写。
            return df[['trade_date', 'close']]
            
        except Exception as e:
            print(f"❌ [DataFetcher] 抓取 {ts_code} 失败: {e}")
            return pd.DataFrame()

    def get_qdii_premium(self, asset_id: str) -> float:
        """
        实时估算 QDII 溢价率 (生产级难点)
        由于免费 API 很难拿到盘中实时 IOPV，我们用近似法或暂时返回 0。
        在真实生产中，可以去爬取集思录(JSL)的数据。
        这里为了跑通主流程，我们做一个 Mock 或接入特定 API。
        """
        # 预留给真实的集思录爬虫或收费接口
        # Mocking for now: 
        if asset_id == 'NASDAQ':
            # 假设纳指目前有 2% 溢价
            return 0.02
        elif asset_id == 'NIKKEI':
            # 假设日经目前有 1% 溢价
            return 0.01
        return 0.0

# 测试数据流是否打通
if __name__ == "__main__":
    fetcher = SwingDataFetcher()
    print(">>> 测试拉取 沪深300 ETF 数据...")
    df_300 = fetcher.fetch_etf_daily('CSI300')
    if not df_300.empty:
        print(df_300.tail())
        
    print("\n>>> 测试拉取 纳指100 ETF 数据...")
    df_ndx = fetcher.fetch_etf_daily('NASDAQ')
    if not df_ndx.empty:
        print(df_ndx.tail())
        
    print("\n>>> 纳指 QDII 溢价率估算:", fetcher.get_qdii_premium('NASDAQ'))
