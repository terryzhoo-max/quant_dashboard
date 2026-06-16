"""
AlphaCore · 中债国债收益率统一数据层 V1.0
==========================================
数据源: AKShare bond_china_yield (底层为中国债券信息网 CCDC)
替代:   Tushare yc_cb (需付费权限 yc_cb)

降级策略:
  Tier 0: AKShare 中债 (免费, 权威, 日频完整历史)
  Tier 1: Tushare yc_cb (如权限恢复自动启用)
  Tier 2: 磁盘缓存 (data_lake/chinabond_yield_10y.parquet)

消费者:
  - engines/erp_timing_engine.py  → get_yield_10y_history()
  - engines/erp_hk_engine.py      → get_yield_10y_latest()
  - strategies/erp_backtest_data.py → get_yield_10y_history()
"""

import os
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger("ac.chinabond")

# ── 配置 ──
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_lake")
_CACHE_FILE = os.path.join(_CACHE_DIR, "chinabond_yield_10y.parquet")
_LEGACY_CACHE_FILE = os.path.join(_CACHE_DIR, "erp_yield_10y.parquet")

# 内存缓存 (线程安全)
_mem_lock = threading.Lock()
_mem_cache: Optional[pd.DataFrame] = None
_mem_ts: float = 0
_MEM_TTL = 1800  # 30 分钟内存 TTL


def _atomic_write_parquet(df: pd.DataFrame, path: str):
    """原子写入 parquet (先写 tmp 再 rename, 防止半写损坏)"""
    tmp = path + ".tmp"
    df.to_parquet(tmp, index=False)
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def _fetch_from_akshare(start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """Tier 0: 从 AKShare 获取中债国债收益率 (底层为中国债券信息网)

    Args:
        start_date: 开始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD

    Returns:
        DataFrame with columns ['trade_date', 'yield_10y'] or None on failure
    """
    try:
        import akshare as ak
        df = ak.bond_china_yield(start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            logger.warning("AKShare bond_china_yield 返回空数据")
            return None

        # 列: 曲线名称, 日期, 3月, 6月, 1年, 3年, 5年, 7年, 10年, 30年
        col_name = df.columns[0]   # 曲线名称
        col_date = df.columns[1]   # 日期
        col_10y = '10年'

        if col_10y not in df.columns:
            # 列名可能因版本不同而变化, 尝试位置索引 (第9列)
            col_10y = df.columns[8] if len(df.columns) > 8 else None
            if col_10y is None:
                logger.warning("AKShare 返回数据缺少 10 年期列")
                return None

        # 筛选国债曲线
        gov_mask = df[col_name].astype(str).str.contains('国债')
        gov = df[gov_mask].copy()
        if gov.empty:
            logger.warning("AKShare 数据中未找到国债曲线")
            return None

        # 标准化输出格式 (与 Tushare yc_cb 兼容)
        result = pd.DataFrame({
            'trade_date': pd.to_datetime(gov[col_date]),
            'yield_10y': pd.to_numeric(gov[col_10y], errors='coerce'),
        })
        result = result.dropna(subset=['yield_10y'])

        # 数据质量校验 (10Y 国债正常范围 0.5-8.0%)
        valid_mask = result['yield_10y'].between(0.5, 8.0)
        if not valid_mask.all():
            dropped = (~valid_mask).sum()
            logger.warning("AKShare 数据质量过滤: 丢弃 %d 条异常值", dropped)
            result = result[valid_mask]

        result = result.sort_values('trade_date').reset_index(drop=True)
        logger.info(
            "ChinaBond (AKShare): %d rows, latest=%.4f%% (%s)",
            len(result),
            result.iloc[-1]['yield_10y'] if len(result) > 0 else 0,
            result.iloc[-1]['trade_date'].strftime('%Y-%m-%d') if len(result) > 0 else 'N/A',
        )
        return result
    except ImportError:
        logger.warning("akshare 未安装, 跳过中债通道")
        return None
    except Exception as e:
        logger.warning("AKShare bond_china_yield 异常: %s", e)
        return None


def _fetch_from_tushare(start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """Tier 1: Tushare yc_cb (如权限恢复自动可用)"""
    try:
        from config import TUSHARE_TOKEN
        import tushare as ts
        ts.set_token(TUSHARE_TOKEN)
        pro = ts.pro_api()

        df = pro.yc_cb(ts_code='1001.CB', curve_type='0',
                       start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return None

        df_10y = df[df['curve_term'] == 10.0].copy()
        if df_10y.empty:
            return None

        result = pd.DataFrame({
            'trade_date': pd.to_datetime(df_10y['trade_date'], format='%Y%m%d'),
            'yield_10y': df_10y['yield'].values,
        })
        result = result.sort_values('trade_date').reset_index(drop=True)
        logger.info("Tushare yc_cb: %d rows", len(result))
        return result
    except Exception as e:
        msg = str(e)
        if "没有接口" in msg or "访问权限" in msg:
            logger.debug("Tushare yc_cb 权限不足, 跳过")
        else:
            logger.warning("Tushare yc_cb 异常: %s", e)
        return None


def _read_disk_cache() -> Optional[pd.DataFrame]:
    """Tier 2: 磁盘缓存 (新缓存优先, 旧格式兼容)"""
    for path in [_CACHE_FILE, _LEGACY_CACHE_FILE]:
        if os.path.exists(path):
            try:
                df = pd.read_parquet(path)
                df['trade_date'] = pd.to_datetime(df['trade_date'])
                df = df.sort_values('trade_date').reset_index(drop=True)
                age_hours = (time.time() - os.path.getmtime(path)) / 3600
                logger.info("磁盘缓存命中 (%s): %d rows, %.1f h old",
                            os.path.basename(path), len(df), age_hours)
                return df
            except Exception as e:
                logger.warning("磁盘缓存读取失败 (%s): %s", path, e)
    return None


def get_yield_10y_history(years: int = 5) -> pd.DataFrame:
    """获取 10Y 国债收益率历史序列 (日频, 带增量更新和三级降级)

    Args:
        years: 历史年数 (默认 5 年)

    Returns:
        DataFrame with columns ['trade_date', 'yield_10y'], sorted by date

    Raises:
        ValueError: 所有数据源均失败且无磁盘缓存
    """
    global _mem_cache, _mem_ts

    # 内存缓存命中
    with _mem_lock:
        if _mem_cache is not None and (time.time() - _mem_ts) < _MEM_TTL:
            return _mem_cache.copy()

    # 读取磁盘缓存确定增量起点
    existing = _read_disk_cache()
    last_date = None
    if existing is not None and not existing.empty:
        last_date = existing['trade_date'].max()
        # 如果缓存已覆盖到今天, 直接返回
        if last_date.strftime('%Y%m%d') >= datetime.now().strftime('%Y%m%d'):
            with _mem_lock:
                _mem_cache = existing
                _mem_ts = time.time()
            return existing.copy()

    # 计算增量拉取范围
    end_dt = datetime.now()
    if last_date:
        start_dt = last_date - timedelta(days=3)  # 回退3天确保无缝衔接
    else:
        start_dt = end_dt - timedelta(days=years * 365)

    # AKShare 单次查询限制 < 1 年, 分批拉取
    all_new = []
    chunk_start = start_dt
    while chunk_start < end_dt:
        chunk_end = min(chunk_start + timedelta(days=300), end_dt)
        s_str = chunk_start.strftime('%Y%m%d')
        e_str = chunk_end.strftime('%Y%m%d')

        # Tier 0: AKShare 中债
        chunk = _fetch_from_akshare(s_str, e_str)

        # Tier 1: Tushare yc_cb
        if chunk is None:
            chunk = _fetch_from_tushare(s_str, e_str)

        if chunk is not None and not chunk.empty:
            all_new.append(chunk)

        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(0.5)  # 礼貌间隔

    # 合并增量数据
    if all_new:
        new_df = pd.concat(all_new, ignore_index=True)
        new_df['trade_date'] = pd.to_datetime(new_df['trade_date'])

        if existing is not None and not existing.empty:
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset='trade_date', keep='last')
        else:
            combined = new_df

        combined = combined.sort_values('trade_date').reset_index(drop=True)

        # 持久化 (新格式 + 旧格式兼容写入)
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            _atomic_write_parquet(combined, _CACHE_FILE)
            # 同步更新旧格式缓存, 让未改造的代码路径也能受益
            _atomic_write_parquet(combined, _LEGACY_CACHE_FILE)
            logger.info("中债 10Y 缓存已更新: %d rows (latest=%s)",
                        len(combined), combined.iloc[-1]['trade_date'].strftime('%Y-%m-%d'))
        except Exception as e:
            logger.warning("缓存持久化失败 (非致命): %s", e)

        with _mem_lock:
            _mem_cache = combined
            _mem_ts = time.time()
        return combined.copy()

    # Tier 2: 磁盘缓存兜底
    if existing is not None and not existing.empty:
        logger.warning("中债在线数据源均失败, 降级到磁盘缓存 (%d rows)", len(existing))
        with _mem_lock:
            _mem_cache = existing
            _mem_ts = time.time()
        return existing.copy()

    raise ValueError("国债收益率数据: 所有数据源均失败且无磁盘缓存")


def get_yield_10y_latest() -> Tuple[float, str]:
    """获取最新 10Y 国债收益率单点值 (供 erp_hk_engine 使用)

    Returns:
        (yield_value, date_str) e.g. (1.7324, '2026-06-16')

    Raises:
        ValueError: 无法获取数据
    """
    # 快速通道: 只拉最近 30 天
    end_str = datetime.now().strftime('%Y%m%d')
    start_str = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')

    # Tier 0: AKShare
    df = _fetch_from_akshare(start_str, end_str)
    if df is not None and not df.empty:
        latest = df.iloc[-1]
        return float(latest['yield_10y']), latest['trade_date'].strftime('%Y-%m-%d')

    # Tier 1: Tushare
    df = _fetch_from_tushare(start_str, end_str)
    if df is not None and not df.empty:
        latest = df.iloc[-1]
        return float(latest['yield_10y']), latest['trade_date'].strftime('%Y-%m-%d')

    # Tier 2: 磁盘缓存最新值
    cached = _read_disk_cache()
    if cached is not None and not cached.empty:
        latest = cached.iloc[-1]
        return float(latest['yield_10y']), latest['trade_date'].strftime('%Y-%m-%d')

    raise ValueError("CN10Y: 所有数据源均失败")
