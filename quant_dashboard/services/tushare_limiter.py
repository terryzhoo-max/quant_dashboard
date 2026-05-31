"""
AlphaCore · Tushare 全局限频器 V5.2
====================================
所有引擎共享的请求令牌桶，防止并发超限。

Tushare Pro 限制:
  - 积分 2000+: ~200 次/分钟
  - 积分 5000+: ~500 次/分钟

设计:
  - 令牌桶 + 信号量双层控制
  - 在 config.py monkey patch 中自动接入，零侵入
  - 线程安全 (ThreadPoolExecutor 兼容)
"""

import threading
import time
import logging

logger = logging.getLogger("tushare_limiter")


class TushareLimiter:
    """线程安全的令牌桶限频器"""

    def __init__(self, max_per_minute: int = 150, max_concurrent: int = 8):
        """
        Args:
            max_per_minute: 每分钟最大请求数 (保守值, 留20%余量)
            max_concurrent: 最大并发请求数
        """
        self._interval = 60.0 / max_per_minute  # ~0.4s per request
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._semaphore = threading.Semaphore(max_concurrent)
        self._total_calls = 0
        self._throttled_calls = 0

    def acquire(self, caller: str = ""):
        """获取一个请求令牌，必要时阻塞等待"""
        self._semaphore.acquire()
        try:
            with self._lock:
                now = time.monotonic()
                wait = self._interval - (now - self._last_call)
                if wait > 0:
                    self._throttled_calls += 1
                    time.sleep(wait)
                self._last_call = time.monotonic()
                self._total_calls += 1
        finally:
            self._semaphore.release()

    @property
    def stats(self) -> dict:
        """限频器统计信息"""
        return {
            "total_calls": self._total_calls,
            "throttled_calls": self._throttled_calls,
            "throttle_rate": round(self._throttled_calls / max(self._total_calls, 1) * 100, 1),
            "interval_ms": round(self._interval * 1000, 1),
        }


# ── 全局单例 ──
tushare_limiter = TushareLimiter(max_per_minute=150, max_concurrent=8)
