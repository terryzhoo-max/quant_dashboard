"""
AlphaCore V26.1 基础设施测试
==============================
覆盖:
  1. EngineCache — TTL / SWR / invalidate / stats / 自动注册
  2. aiae_normalizer — 边界映射 / 全局仓位 / 区域阈值
  3. locks — 单例一致性
"""

import time
import threading
import pytest


# ═══════════════════════════════════════════
#  EngineCache 测试
# ═══════════════════════════════════════════

class TestEngineCache:
    """EngineCache 核心功能测试"""

    def _make_cache(self, name="test"):
        from services.engine_cache import EngineCache
        return EngineCache(name, max_workers=1)

    def test_get_cold_start(self):
        """冷启动: 无缓存时同步获取"""
        cache = self._make_cache("cold")
        result = cache.get("key1", 60, lambda: {"value": 42})
        assert result == {"value": 42}

    def test_get_cache_hit(self):
        """缓存命中: TTL 内返回缓存数据, 不调用 fetcher"""
        cache = self._make_cache("hit")
        call_count = [0]

        def fetcher():
            call_count[0] += 1
            return "data"

        # 首次调用
        result1 = cache.get("k", 60, fetcher)
        assert result1 == "data"
        assert call_count[0] == 1

        # 二次调用应走缓存
        result2 = cache.get("k", 60, fetcher)
        assert result2 == "data"
        assert call_count[0] == 1  # fetcher 不应被再次调用

    def test_get_swr_returns_stale_data(self):
        """SWR: TTL 过期后立即返回旧数据"""
        cache = self._make_cache("swr")
        cache.get("k", 0.01, lambda: "old_data")  # TTL=10ms
        time.sleep(0.05)  # 等待过期

        result = cache.get("k", 0.01, lambda: "new_data")
        # SWR 语义: 应立即返回旧数据
        assert result == "old_data"

    def test_get_fetcher_failure_returns_stale(self):
        """Fetcher 失败时返回旧缓存数据 (降级)"""
        cache = self._make_cache("fail")
        cache.get("k", 60, lambda: "cached")

        # 直接调用 _refresh 模拟失败
        def bad_fetcher():
            raise RuntimeError("API down")

        # SWR 后台刷新失败应返回旧值
        result = cache._refresh("k", bad_fetcher)
        assert result == "cached"

    def test_get_fetcher_failure_no_cache_raises(self):
        """无缓存 + Fetcher 失败 → 抛异常"""
        cache = self._make_cache("no_cache_fail")

        def bad_fetcher():
            raise RuntimeError("total failure")

        with pytest.raises(RuntimeError, match="total failure"):
            cache.get("nonexistent", 60, bad_fetcher)

    def test_invalidate_single_key(self):
        """invalidate(key) 精确删除"""
        cache = self._make_cache("inv_key")
        cache.get("a", 60, lambda: 1)
        cache.get("b", 60, lambda: 2)
        cache.invalidate("a")
        assert cache.stats()["total_keys"] == 1

    def test_invalidate_all(self):
        """invalidate() 清除所有"""
        cache = self._make_cache("inv_all")
        cache.get("a", 60, lambda: 1)
        cache.get("b", 60, lambda: 2)
        cache.invalidate()
        assert cache.stats()["total_keys"] == 0

    def test_invalidate_prefix(self):
        """invalidate_prefix() 按前缀批量删除"""
        cache = self._make_cache("inv_pfx")
        cache.get("aiae_mv", 60, lambda: 1)
        cache.get("aiae_m2", 60, lambda: 2)
        cache.get("erp_pe", 60, lambda: 3)
        cache.invalidate_prefix("aiae_")
        stats = cache.stats()
        assert stats["total_keys"] == 1
        assert "erp_pe" in stats["entries"]

    def test_stats(self):
        """stats() 返回正确结构"""
        cache = self._make_cache("stats")
        cache.get("x", 60, lambda: "val")
        stats = cache.stats()
        assert stats["name"] == "stats"
        assert stats["total_keys"] == 1
        assert "x" in stats["entries"]
        assert "age_seconds" in stats["entries"]["x"]

    def test_thread_safety(self):
        """并发安全: 多线程同时读写不崩溃"""
        cache = self._make_cache("thread_safe")
        errors = []

        def writer(i):
            try:
                cache.get(f"key_{i % 5}", 0.001, lambda: i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread errors: {errors}"


# ═══════════════════════════════════════════
#  aiae_normalizer 测试
# ═══════════════════════════════════════════

class TestAIAENormalizer:
    """跨区域温度归一化测试"""

    def test_threshold_anchors(self):
        """四个阈值应精确映射到 20/40/60/80"""
        from services.aiae_normalizer import normalize_temp, get_region_thresholds
        t = get_region_thresholds()
        for region in ["cn", "us", "jp", "hk"]:
            for i, expected in enumerate([20, 40, 60, 80]):
                actual = normalize_temp(t[region][i], region, t)
                assert abs(actual - expected) < 0.01, (
                    f"{region} threshold[{i}]={t[region][i]} -> {actual}, expected {expected}"
                )

    def test_extreme_low(self):
        """极低值应映射到接近 0"""
        from services.aiae_normalizer import normalize_temp, get_region_thresholds
        t = get_region_thresholds()
        result = normalize_temp(0, "cn", t)
        assert result == 0

    def test_extreme_high(self):
        """极高值应映射到接近 100, 但不超过"""
        from services.aiae_normalizer import normalize_temp, get_region_thresholds
        t = get_region_thresholds()
        result = normalize_temp(99, "cn", t)
        assert result <= 100

    def test_monotonic(self):
        """归一化函数应单调递增"""
        from services.aiae_normalizer import normalize_temp, get_region_thresholds
        t = get_region_thresholds()
        for region in ["cn", "us", "jp", "hk"]:
            prev = -1
            for val in range(0, 50):
                curr = normalize_temp(val, region, t)
                assert curr >= prev, f"{region} not monotonic at {val}: {curr} < {prev}"
                prev = curr

    def test_global_position_tiers(self):
        """全局仓位五档覆盖测试"""
        from services.aiae_normalizer import compute_global_position
        regimes = {"cn": 3, "us": 3, "jp": 3, "hk": 3}

        # 各温度档位
        gp_10 = compute_global_position(10, regimes)
        gp_25 = compute_global_position(25, regimes)
        gp_40 = compute_global_position(40, regimes)
        gp_55 = compute_global_position(55, regimes)
        gp_70 = compute_global_position(70, regimes)
        gp_85 = compute_global_position(85, regimes)

        # equity_pct 应随温度递减
        assert gp_10["equity_pct"] > gp_25["equity_pct"]
        assert gp_25["equity_pct"] > gp_40["equity_pct"]
        assert gp_40["equity_pct"] > gp_55["equity_pct"]
        assert gp_55["equity_pct"] > gp_70["equity_pct"]
        assert gp_70["equity_pct"] > gp_85["equity_pct"]

        # cash + equity = 100
        for gp in [gp_10, gp_25, gp_40, gp_55, gp_70, gp_85]:
            assert gp["cash_pct"] + gp["equity_pct"] == 100

    def test_extreme_warnings(self):
        """Ⅴ级市场应触发极端告警"""
        from services.aiae_normalizer import compute_global_position
        gp = compute_global_position(50, {"cn": 5, "us": 3, "jp": 5, "hk": 2})
        assert "cn" in gp["extreme_warnings"]
        assert "jp" in gp["extreme_warnings"]
        assert "us" not in gp["extreme_warnings"]

    def test_region_names(self):
        """区域名称完整性"""
        from services.aiae_normalizer import REGION_NAMES
        assert set(REGION_NAMES.keys()) == {"cn", "us", "jp", "hk"}


# ═══════════════════════════════════════════
#  locks 单例测试
# ═══════════════════════════════════════════

class TestLocks:
    """全局锁注册表测试"""

    def test_lock_types(self):
        """所有导出的锁应为 threading.Lock"""
        from services.locks import AIAE_GLOBAL_LOCK, STRATEGY_RESULTS_LOCK
        assert isinstance(AIAE_GLOBAL_LOCK, type(threading.Lock()))
        assert isinstance(STRATEGY_RESULTS_LOCK, type(threading.Lock()))

    def test_lock_singleton_aiae_router(self):
        """aiae.py 和 locks.py 使用同一个 AIAE_GLOBAL_LOCK 实例"""
        from services.locks import AIAE_GLOBAL_LOCK
        from routers.aiae import _AIAE_GLOBAL_LOCK
        assert _AIAE_GLOBAL_LOCK is AIAE_GLOBAL_LOCK

    def test_lock_singleton_warmup(self):
        """warmup_pipeline.py 和 locks.py 使用同一个 AIAE_GLOBAL_LOCK 实例"""
        from services.locks import AIAE_GLOBAL_LOCK
        from services.warmup_pipeline import _AIAE_GLOBAL_LOCK
        assert _AIAE_GLOBAL_LOCK is AIAE_GLOBAL_LOCK
