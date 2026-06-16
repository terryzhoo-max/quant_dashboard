"""
AlphaCore · 统一缓存服务 (恢复自 __pycache__ 字节码逆向)
==========================================================
单例模式缓存管理器: Redis 优先 → 内存 fallback
- 连接 Redis 成功 → 分布式缓存 (支持 TTL / 多 Worker 共享)
- Redis 不可用 → 自动降级为 threading-safe 内存字典

原始文件 cache_service.py 源码丢失，
于 2026-04-22 通过 cpython-312.pyc 字节码完整逆向恢复。
"""

import copy
import json
import os
import logging
import threading
import time as _time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import redis
from datetime import datetime

_logger = logging.getLogger("ac.cache")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))


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
        self._memory_cache = OrderedDict()  # key → (value, expire_at|None), LRU 顺序
        self._mem_maxsize = 512       # P1-6: 内存缓存容量上限 (LRU 驱逐, 200→512 适配 25+ SWR 键)
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

    def _mem_get(self, key, default=None):
        """内存缓存读取 (带 TTL 惰性淘汰 + LRU 提升), 调用方须已持有 _memory_lock"""
        entry = self._memory_cache.get(key)
        if entry is None:
            return default
        value, expire_at = entry
        if expire_at is not None and _time.time() > expire_at:
            del self._memory_cache[key]
            return default
        # LRU: move_to_end O(1)
        self._memory_cache.move_to_end(key)
        return value

    def _mem_set(self, key, value, ttl_seconds=None):
        """内存缓存写入 (带 LRU 驱逐), 调用方须已持有 _memory_lock"""
        expire_at = (_time.time() + ttl_seconds) if ttl_seconds else None
        if key in self._memory_cache:
            self._memory_cache.move_to_end(key)  # O(1) LRU 提升
        self._memory_cache[key] = (value, expire_at)
        # LRU 驱逐: OrderedDict 头部是最久未访问的
        while len(self._memory_cache) > self._mem_maxsize:
            self._memory_cache.popitem(last=False)  # O(1) 驱逐最旧

    def get_json(self, key: str, default=None):
        """获取 JSON 反序列化后的缓存值

        内存模式下返回 deepcopy, 防止调用方修改返回值污染缓存。
        Redis 模式下 json.loads 天然产生新对象, 无需额外拷贝。
        """
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
                    result = self._mem_get(key, default)
                    return copy.deepcopy(result) if result is not default else default

        with self._memory_lock:
            result = self._mem_get(key, default)
            return copy.deepcopy(result) if result is not default else default

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
                    self._mem_set(key, value, ttl_seconds)
                return True  # P0-2 Fix: 防止继续执行到下方的重复内存写入

        with self._memory_lock:
            self._mem_set(key, value, ttl_seconds)
        return True

    def delete(self, key: str):
        """删除缓存键"""
        if self.use_redis:
            try:
                self.redis_client.delete(key)
                return True
            except Exception as e:
                # R5: Redis 异常时 fallback 到内存 + 日志
                _logger.debug("Redis delete(%s) 异常: %s", key, e)

        with self._memory_lock:
            self._memory_cache.pop(key, None)
        return True

    def touch(self, key: str, ttl_seconds: int = None) -> bool:
        """续期缓存 TTL 而不修改值 (O(1), 无数据拷贝)。

        用途: 盘后 reactor tick 周期性续期，防止缓存过期导致页面
        降级为 Fallback 假数据。

        Args:
            key: 缓存键
            ttl_seconds: 新的 TTL (秒), None 表示永不过期

        Returns:
            True 如果键存在且续期成功, 否则 False
        """
        if self.use_redis:
            try:
                if ttl_seconds:
                    return bool(self.redis_client.expire(key, ttl_seconds))
                return bool(self.redis_client.persist(key))
            except Exception as e:
                _logger.debug("Redis touch(%s) 异常: %s", key, e)

        with self._memory_lock:
            entry = self._memory_cache.get(key)
            if entry is not None:
                value, _ = entry
                expire_at = (_time.time() + ttl_seconds) if ttl_seconds else None
                self._memory_cache[key] = (value, expire_at)
                self._memory_cache.move_to_end(key)
                return True
        return False

    def stats(self) -> dict:
        """V25.0: 缓存统计信息 (运维可观测性)"""
        if self.use_redis:
            try:
                info = self.redis_client.info(section="keyspace")
                db_info = info.get(f"db{REDIS_DB}", {})
                total = db_info.get("keys", 0) if isinstance(db_info, dict) else 0
                return {"backend": "redis", "total_keys": total, "expired_pending": 0}
            except Exception:
                pass
        with self._memory_lock:
            now = _time.time()
            total = len(self._memory_cache)
            expired = sum(1 for _, (_, exp) in self._memory_cache.items() if exp and now > exp)
        return {
            "backend": "redis" if self.use_redis else "memory",
            "total_keys": total,
            "expired_pending": expired,
        }


# 模块级单例 — main.py 中 `from services.cache_service import cache_manager`
cache_manager = CacheService()


# ═══════════════════════════════════════════════════
#  V6.0: 分时段自适应 TTL (收盘后辅助决策优化)
# ═══════════════════════════════════════════════════

from datetime import datetime as _datetime

# TTL 放大倍数矩阵 (盘中=1x, 收盘后=Nx, 周末=Mx)
# 注意: 周末倍率不宜过大, 否则 base_ttl × M 可能超过 stale_ttl 导致逻辑倒挂
_TTL_MULTIPLIERS = {
    #                盘中   收盘后  周末/节假日
    "realtime":   (1,     6,      12),    # 合规/漂移/盘中PnL: 盘中高频, 收盘后大幅放宽
    "decision":   (1,     4,      8),     # 决策中枢/风险矩阵: 收盘后仍需可访问但无需频繁刷新
    "strategy":   (1,     4,      12),    # 策略信号: 收盘后到次日不会变 (12× 不超过 stale)
    "slow":       (1,     2,      6),     # 相关性/传染/归因: 本身就是低频计算
    "default":    (1,     3,      8),     # 兜底
}


def is_market_hours() -> str:
    """
    判断当前所处的市场时段:
    - "trading"   : A股盘中 (工作日 09:15-15:05)
    - "after"     : 收盘后 (工作日 15:05-次日09:15)
    - "weekend"   : 周末/节假日
    """
    now = _datetime.now()
    weekday = now.weekday()  # 0=Mon, 6=Sun
    if weekday >= 5:
        return "weekend"
    hour, minute = now.hour, now.minute
    t = hour * 60 + minute
    if 555 <= t <= 905:  # 09:15 ~ 15:05
        return "trading"
    return "after"


def adaptive_fresh_ttl(base_ttl: int, category: str = "default", max_ttl: int = None) -> int:
    """
    根据市场时段动态调整 SWR fresh_ttl:
    - 盘中: 原始值 (高频刷新)
    - 收盘后: base_ttl × N (数据不再变化, 减少无意义重算)
    - 周末: base_ttl × M (最大化缓存命中)

    安全约束: 返回值不会超过 max_ttl (防止 fresh > stale 倒挂)

    Args:
        base_ttl: 盘中基准 TTL (秒)
        category: 端点分类 (realtime/decision/strategy/slow)
        max_ttl: 上限 (秒), 不传则不封顶

    Returns:
        调整后的 fresh_ttl (秒)
    """
    period = is_market_hours()
    multipliers = _TTL_MULTIPLIERS.get(category, _TTL_MULTIPLIERS["default"])
    idx = {"trading": 0, "after": 1, "weekend": 2}.get(period, 0)
    result = base_ttl * multipliers[idx]
    if max_ttl is not None:
        result = min(result, max_ttl)
    return result


# ═══════════════════════════════════════════════════
#  V2.0: Stale-While-Revalidate 通用中间件
# ═══════════════════════════════════════════════════



# 防止并发重复刷新的标志位 (P1-3: 改为 dict 存时间戳, 防僵死线程)
_swr_refreshing: dict[str, float] = {}  # key → start_time
_swr_refresh_lock = threading.Lock()
_SWR_REFRESH_TIMEOUT = 300  # 5 分钟超时自动清除
# P1-7: 受控线程池替代无界裸线程 (上限 4 路并发刷新)
_swr_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="swr")


# ── V7.0: 同步防击穿锁 (Single Flight Lock) ──
# P1-2 修复: 使用 _SWR_LOCK_MAX 上限 + LRU 清理，防止锁对象无限增长
_swr_compute_locks: dict[str, threading.RLock] = {}
_swr_compute_locks_lock = threading.Lock()
_SWR_LOCK_MAX = 128  # 最多缓存 128 个键的锁


def _get_key_lock(cache_key: str) -> threading.RLock:
    """获取专属缓存键的重入锁 (P1-2: 带容量上限防泄漏)"""
    with _swr_compute_locks_lock:
        if cache_key in _swr_compute_locks:
            return _swr_compute_locks[cache_key]
        # 容量保护: 超限时清除最早的一半
        if len(_swr_compute_locks) >= _SWR_LOCK_MAX:
            keys_to_remove = list(_swr_compute_locks.keys())[:_SWR_LOCK_MAX // 2]
            for k in keys_to_remove:
                _swr_compute_locks.pop(k, None)
        lock = threading.RLock()
        _swr_compute_locks[cache_key] = lock
        return lock


def stale_while_revalidate(cache_key: str, compute_fn, fresh_ttl=3600, stale_ttl=21600):
    """
    三级缓存通用中间件 (全路由复用):
    
    - Fresh  (age < fresh_ttl):  直接返回
    - Stale  (fresh_ttl < age < stale_ttl): 返回旧数据 + 后台静默刷新
    - Miss   (age > stale_ttl 或无缓存): 同步计算
    
    V6.0 不变量守卫: fresh_ttl 不会超过 stale_ttl 的 90%,
    防止 adaptive_fresh_ttl 放大后导致 fresh > stale 逻辑倒挂。
    
    V7.0 生产级打磨:
      - 强类型保护: data 不为 dict 时直接返回，不再强行写入 _cache 触发 TypeError
      - 深拷贝防御: 统一使用 copy.deepcopy 拷贝缓存对象，防止调用方修改子字典污染内存缓存
      - 同步防击穿: Hard miss 时基于 Single Flight Lock 重入排队，带 Double Check 逻辑
      - 柔性容灾降级: 同步计算失败时，若存在过期缓存，触发 Stale-On-Error 优雅返回
    
    Args:
        cache_key: 缓存键名 (建议前缀 swr_)
        compute_fn: 无参数计算函数, 返回 dict
        fresh_ttl: 新鲜数据有效期 (秒), 默认 1h
        stale_ttl: 过时数据最大容忍期 (秒), 默认 6h
    
    Returns:
        dict: 计算结果 + 缓存元数据 (cached, stale, age_seconds)
    """
    # V6.0: 不变量守卫 — fresh 不得超过 stale 的 90%
    fresh_ttl = min(fresh_ttl, int(stale_ttl * 0.9))

    cached = cache_manager.get_json(cache_key)
    
    if cached and "timestamp" in cached:
        age = _time.time() - cached["timestamp"]
        
        # Tier 1: Fresh — 直接返回 (深拷贝防污染, 类型安全保护)
        if age < fresh_ttl:
            if isinstance(cached["data"], dict):
                result = copy.deepcopy(cached["data"])
                result["_cache"] = {"cached": True, "stale": False, "age_seconds": int(age)}
                return result
            return copy.deepcopy(cached["data"])
        
        # Tier 2: Stale — 返回旧数据 + 后台刷新 (深拷贝防污染, 类型安全保护)
        if age < stale_ttl:
            _trigger_bg_refresh(cache_key, compute_fn)
            if isinstance(cached["data"], dict):
                result = copy.deepcopy(cached["data"])
                result["_cache"] = {"cached": True, "stale": True, "age_seconds": int(age)}
                return result
            return copy.deepcopy(cached["data"])
    
    # Tier 3: Hard miss — 同步计算 (加锁防止多线程并发计算导致 Tushare 击穿/限频)
    key_lock = _get_key_lock(cache_key)
    with key_lock:
        # Double Check: 获取锁后再次检查缓存，防并发排队时已被前一线程刷新为 Fresh
        cached = cache_manager.get_json(cache_key)
        if cached and "timestamp" in cached:
            age = _time.time() - cached["timestamp"]
            if age < fresh_ttl:
                if isinstance(cached["data"], dict):
                    result = copy.deepcopy(cached["data"])
                    result["_cache"] = {"cached": True, "stale": False, "age_seconds": int(age)}
                    return result
                return copy.deepcopy(cached["data"])

        try:
            return _swr_compute_sync(cache_key, compute_fn)
        except Exception as e:
            # Stale-On-Error 柔性容灾降级:
            # 计算失败时，如果缓存中有旧数据（哪怕已经超出 stale_ttl 过期），优先返回旧数据并打上降级标记
            if cached and "timestamp" in cached:
                age = _time.time() - cached["timestamp"]
                _logger.warning("SWR 刷新失败, 触发 Stale-On-Error 柔性降级返回过期缓存: %s (age=%ds), 错误: %s", 
                               cache_key, int(age), e)
                if isinstance(cached["data"], dict):
                    result = copy.deepcopy(cached["data"])
                    result["_cache"] = {
                        "cached": True,
                        "stale": True,
                        "age_seconds": int(age),
                        "degraded": True,
                        "error": str(e)
                    }
                    return result
                return copy.deepcopy(cached["data"])
            
            # 彻底无缓存可用，降级返回错误响应
            _logger.error("SWR 同步计算失败且无旧缓存可用 %s: %s", cache_key, e)
            return {"status": "error", "error": str(e)}


def _trigger_bg_refresh(cache_key: str, compute_fn):
    """后台静默刷新 (带防雷锁 + P1-3 超时保护)"""
    now = _time.time()
    with _swr_refresh_lock:
        if cache_key in _swr_refreshing:
            started = _swr_refreshing[cache_key]
            if now - started < _SWR_REFRESH_TIMEOUT:
                return  # 已有刷新线程在跑且未超时
            # 超时: 清除僵死标记, 允许重新刷新
            _logger.warning("SWR 刷新超时清除: %s (已挂 %.0fs)", cache_key, now - started)
        _swr_refreshing[cache_key] = now
    
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
                _swr_refreshing.pop(cache_key, None)
    
    try:
        _swr_pool.submit(_do_refresh)
    except RuntimeError:
        _logger.debug("SWR pool shutdown, skip refresh for %s", cache_key)


def _swr_compute_sync(cache_key: str, compute_fn):
    """同步计算并写入缓存 (V7.0: 异常不吞掉，抛出供柔性降级捕捉)"""
    try:
        result = compute_fn()
        payload = {"timestamp": _time.time(), "data": result}
        cache_manager.set_json(cache_key, payload)
        if isinstance(result, dict):
            ret = copy.deepcopy(result)
            ret["_cache"] = {"cached": False, "stale": False, "age_seconds": 0}
            return ret
        return copy.deepcopy(result)
    except Exception as e:
        _logger.error(f"SWR 同步计算执行出错 {cache_key}: {e}")
        import traceback
        _logger.debug("Traceback", exc_info=True)
        raise e


def swr_clear(cache_key: str):
    """清除 SWR 缓存 (供 /refresh 端点调用)"""
    cache_manager.delete(cache_key)
    _logger.info(f"SWR 缓存已清除: {cache_key}")

