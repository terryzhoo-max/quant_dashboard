"""
AlphaCore · 引擎级缓存基座
===========================
从 aiae_engine / erp_timing_engine 提取的公共缓存机制。

特性:
  - TTL (Time-To-Live) 自动过期
  - SWR (Stale-While-Revalidate) 后台刷新
  - 线程安全 (threading.Lock)
  - 受控线程池 (不使用无界裸线程)

使用方式:
    from services.engine_cache import EngineCache

    _cache = EngineCache("erp")

    def _fetch_pe():
        return pro.index_dailybasic(...)

    # 30 分钟 TTL，过期返回旧数据 + 后台刷新
    data = _cache.get("pe_ttm_history", ttl_seconds=1800, fetcher=_fetch_pe)
"""

import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("alphacore.engine_cache")


class EngineCache:
    """线程安全 TTL 缓存 (SWR 模式)

    替代各引擎中重复的 _cache + _cache_lock + _bg_executor + _refresh_cache + _cached
    基础设施代码 (~30 行/引擎 × 12 引擎 = ~360 行重复)。
    """

    def __init__(self, name: str = "default", max_workers: int = 3):
        """
        Args:
            name: 缓存实例名称 (用于日志标识)
            max_workers: 后台刷新线程池大小
        """
        self._cache: dict = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=f"ec_{name}"
        )
        self._name = name
        # V26.1: 自动注册到系统监控
        try:
            from routers.system import register_engine_cache
            register_engine_cache(name, self)
        except ImportError:
            pass  # 独立运行/测试时无 router

    def get(self, key: str, ttl_seconds: int, fetcher):
        """线程安全 TTL 缓存读取 (支持 SWR)

        - 未过期: 直接返回缓存数据
        - 已过期: 返回旧数据 + 后台异步刷新
        - 无数据: 同步阻塞获取

        Args:
            key: 缓存键
            ttl_seconds: 缓存有效期 (秒)
            fetcher: 无参数的数据获取函数
        """
        now = time.time()
        with self._lock:
            if key in self._cache:
                ts_cached, data = self._cache[key]
                if now - ts_cached < ttl_seconds:
                    return data
                else:
                    # SWR: 返回旧数据 + 后台刷新
                    try:
                        self._executor.submit(self._refresh, key, fetcher)
                    except RuntimeError:
                        pass  # shutdown 阶段
                    return data

        # 无缓存: 同步获取 (冷启动/重启后)
        return self._refresh(key, fetcher)

    def _refresh(self, key: str, fetcher):
        """执行数据获取并写入缓存 (失败时返回旧数据)"""
        try:
            data = fetcher()
            with self._lock:
                self._cache[key] = (time.time(), data)
            return data
        except Exception as e:
            logger.warning("[%s] 缓存刷新失败 (%s): %s", self._name, key, e)
            with self._lock:
                if key in self._cache:
                    return self._cache[key][1]
            raise

    def invalidate(self, key: str = None):
        """清除缓存

        Args:
            key: 指定键名清除，None 清除所有
        """
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    def invalidate_prefix(self, prefix: str):
        """清除指定前缀的所有缓存键"""
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._cache[k]

    def stats(self) -> dict:
        """返回缓存统计信息"""
        with self._lock:
            now = time.time()
            entries = {}
            for k, (ts, _) in self._cache.items():
                entries[k] = {"age_seconds": int(now - ts)}
            return {
                "name": self._name,
                "total_keys": len(self._cache),
                "entries": entries,
            }
