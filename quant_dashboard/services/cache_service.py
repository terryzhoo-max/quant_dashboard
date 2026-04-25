"""
AlphaCore · 统一缓存服务 (恢复自 __pycache__ 字节码逆向)
==========================================================
单例模式缓存管理器: Redis 优先 → 内存 fallback
- 连接 Redis 成功 → 分布式缓存 (支持 TTL / 多 Worker 共享)
- Redis 不可用 → 自动降级为 threading-safe 内存字典

原始文件 cache_service.py 源码丢失，
于 2026-04-22 通过 cpython-312.pyc 字节码完整逆向恢复。
"""

import json
import os
import logging
import threading
import redis
from datetime import datetime

_logger = logging.getLogger("ac.cache")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = os.getenv("REDIS_DB", 0)


class CacheService:
    """线程安全的单例缓存管理器"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CacheService, cls).__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        """初始化: 尝试连接 Redis，失败则降级为内存模式"""
        self._memory_cache = {}
        self._memory_lock = threading.Lock()
        self.use_redis = False

        try:
            self.redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
            )
            self.redis_client.ping()
            self.use_redis = True
            _logger.info(f"Redis ({REDIS_HOST}:{REDIS_PORT}) 连接成功 · 分布式缓存")
        except Exception as e:
            _logger.info(f"Redis 连接失败 ({e}) · 降为内存缓存模式")

    def get_json(self, key: str, default=None):
        """获取 JSON 反序列化后的缓存值"""
        if self.use_redis:
            try:
                val = self.redis_client.get(key)
                if val is not None:
                    return json.loads(val)
                return default
            except Exception as e:
                _logger.error(f"Redis GET 失败: {e}")
                # Redis 异常时 fallback 到内存
                with self._memory_lock:
                    return self._memory_cache.get(key, default)

        with self._memory_lock:
            return self._memory_cache.get(key, default)

    def set_json(self, key: str, value, ttl_seconds: int = None):
        """写入序列化 JSON 缓存，可选 TTL"""
        if self.use_redis:
            try:
                val_str = json.dumps(value, ensure_ascii=False)
                if ttl_seconds:
                    self.redis_client.setex(key, ttl_seconds, val_str)
                else:
                    self.redis_client.set(key, val_str)
                return True
            except Exception as e:
                _logger.error(f"Redis SET 失败: {e}")
                # Redis 异常时 fallback 到内存
                with self._memory_lock:
                    self._memory_cache[key] = value

        with self._memory_lock:
            self._memory_cache[key] = value
        return True

    def delete(self, key: str):
        """删除缓存键"""
        if self.use_redis:
            try:
                self.redis_client.delete(key)
                return True
            except Exception:
                # Redis 异常时 fallback 到内存
                with self._memory_lock:
                    self._memory_cache.pop(key, None)

        with self._memory_lock:
            self._memory_cache.pop(key, None)
        return True


# 模块级单例 — main.py 中 `from services.cache_service import cache_manager`
cache_manager = CacheService()
