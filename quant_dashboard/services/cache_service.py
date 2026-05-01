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


# ═══════════════════════════════════════════════════
#  V2.0: Stale-While-Revalidate 通用中间件
# ═══════════════════════════════════════════════════

import time as _time

# 防止并发重复刷新的标志位
_swr_refreshing = set()
_swr_refresh_lock = threading.Lock()


def stale_while_revalidate(cache_key: str, compute_fn, fresh_ttl=3600, stale_ttl=21600):
    """
    三级缓存通用中间件 (全路由复用):
    
    - Fresh  (age < fresh_ttl):  直接返回
    - Stale  (fresh_ttl < age < stale_ttl): 返回旧数据 + 后台静默刷新
    - Miss   (age > stale_ttl 或无缓存): 同步计算
    
    Args:
        cache_key: 缓存键名 (建议前缀 swr_)
        compute_fn: 无参数计算函数, 返回 dict
        fresh_ttl: 新鲜数据有效期 (秒), 默认 1h
        stale_ttl: 过时数据最大容忍期 (秒), 默认 6h
    
    Returns:
        dict: 计算结果 + 缓存元数据 (cached, stale, age_seconds)
    """
    cached = cache_manager.get_json(cache_key)
    
    if cached and "timestamp" in cached:
        age = _time.time() - cached["timestamp"]
        
        # Tier 1: Fresh — 直接返回
        if age < fresh_ttl:
            result = cached["data"]
            result["_cache"] = {"cached": True, "stale": False, "age_seconds": int(age)}
            return result
        
        # Tier 2: Stale — 返回旧数据 + 后台刷新
        if age < stale_ttl:
            _trigger_bg_refresh(cache_key, compute_fn)
            result = cached["data"]
            result["_cache"] = {"cached": True, "stale": True, "age_seconds": int(age)}
            return result
    
    # Tier 3: Hard miss — 同步计算
    return _swr_compute_sync(cache_key, compute_fn)


def _trigger_bg_refresh(cache_key: str, compute_fn):
    """后台静默刷新 (带防雷锁)"""
    with _swr_refresh_lock:
        if cache_key in _swr_refreshing:
            return  # 已有刷新线程在跑
        _swr_refreshing.add(cache_key)
    
    def _do_refresh():
        try:
            result = compute_fn()
            payload = {"timestamp": _time.time(), "data": result}
            cache_manager.set_json(cache_key, payload)
            _logger.info(f"SWR 后台刷新完成: {cache_key}")
        except Exception as e:
            _logger.warning(f"SWR 后台刷新失败 {cache_key}: {e}")
        finally:
            with _swr_refresh_lock:
                _swr_refreshing.discard(cache_key)
    
    threading.Thread(target=_do_refresh, daemon=True).start()


def _swr_compute_sync(cache_key: str, compute_fn):
    """同步计算并写入缓存"""
    try:
        result = compute_fn()
        payload = {"timestamp": _time.time(), "data": result}
        cache_manager.set_json(cache_key, payload)
        result["_cache"] = {"cached": False, "stale": False, "age_seconds": 0}
        return result
    except Exception as e:
        _logger.error(f"SWR 同步计算失败 {cache_key}: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": str(e)}


def swr_clear(cache_key: str):
    """清除 SWR 缓存 (供 /refresh 端点调用)"""
    cache_manager.delete(cache_key)
    _logger.info(f"SWR 缓存已清除: {cache_key}")
