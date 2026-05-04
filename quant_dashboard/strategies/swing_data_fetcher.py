import tushare as ts
import pandas as pd
import os
import time
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import TUSHARE_TOKEN

_logger = logging.getLogger("ac.swing_fetcher")

# 磁盘缓存目录
_DISK_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache", "swing")
os.makedirs(_DISK_CACHE_DIR, exist_ok=True)

# 磁盘缓存有效期 (秒) — 4 小时
_DISK_CACHE_TTL = 4 * 3600


class SwingDataFetcher:
    """
    7大ETF生产级波段数据获取器
    V2.0: 并行拉取 + Parquet 磁盘缓存兜底
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
        """获取单只ETF日线数据 (含磁盘缓存兜底)"""
        return self._fetch_single_with_disk_cache(asset_id, days)

    def fetch_all_etfs(self, days: int = 120) -> dict:
        """
        并行拉取全部 ETF 日线数据
        V2.0: ThreadPoolExecutor 并行, max_workers=4 (Tushare 频率限制)
        """
        results = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self._fetch_single_with_disk_cache, aid, days): aid
                for aid in self.a_share_etfs
            }
            for future in as_completed(futures):
                aid = futures[future]
                try:
                    results[aid] = future.result()
                except Exception as e:
                    _logger.warning(f"并行拉取 {aid} 失败: {e}")
                    results[aid] = pd.DataFrame()
        return results

    def _fetch_single_with_disk_cache(self, asset_id: str, days: int = 120) -> pd.DataFrame:
        """单资产拉取: Tushare → 磁盘缓存 fallback"""
        if asset_id not in self.a_share_etfs:
            raise ValueError(f"Unknown asset_id: {asset_id}")
        
        cache_path = os.path.join(_DISK_CACHE_DIR, f"{asset_id}.parquet")
        
        # 先尝试 Tushare 拉取
        ts_code = self.a_share_etfs[asset_id]
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
        
        try:
            df = self.pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                df['trade_date'] = pd.to_datetime(df['trade_date'])
                df = df.sort_values('trade_date').reset_index(drop=True)
                df = df[['trade_date', 'close']]
                
                # 写入磁盘缓存 (原子写入)
                try:
                    tmp_path = cache_path + ".tmp"
                    df.to_parquet(tmp_path, index=False)
                    os.replace(tmp_path, cache_path)
                except Exception as we:
                    _logger.warning(f"磁盘缓存写入失败 {asset_id}: {we}")
                
                return df
            else:
                _logger.warning(f"Tushare 返回 {ts_code} 数据为空, 尝试磁盘缓存")
        except Exception as e:
            _logger.warning(f"Tushare 拉取 {ts_code} 失败: {e}, 尝试磁盘缓存")
        
        # Fallback: 磁盘缓存
        return self._read_disk_cache(asset_id, cache_path)

    def _read_disk_cache(self, asset_id: str, cache_path: str) -> pd.DataFrame:
        """读取磁盘缓存 (Parquet), 不检查 TTL — 有数据比没数据好"""
        if os.path.exists(cache_path):
            try:
                df = pd.read_parquet(cache_path)
                age_h = (time.time() - os.path.getmtime(cache_path)) / 3600
                _logger.info(f"磁盘缓存命中 {asset_id} (age={age_h:.1f}h, rows={len(df)})")
                return df
            except Exception as e:
                _logger.error(f"磁盘缓存读取失败 {asset_id}: {e}")
        
        _logger.error(f"无可用数据: {asset_id} (Tushare 失败 + 无磁盘缓存)")
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
    print(">>> 并行拉取全部 7 大 ETF...")
    t0 = time.time()
    all_data = fetcher.fetch_all_etfs()
    elapsed = time.time() - t0
    for aid, df in all_data.items():
        print(f"  {aid}: {len(df)} rows")
    print(f"\n总耗时: {elapsed:.1f}s (并行)")
