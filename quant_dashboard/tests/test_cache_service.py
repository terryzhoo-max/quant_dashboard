"""
AlphaCore · 缓存服务 单元测试
================================
覆盖: CacheService 单例、内存 fallback、get/set/delete
"""
import pytest
from services.cache_service import CacheService, cache_manager


class TestCacheServiceSingleton:
    """单例模式验证"""

    def test_is_singleton(self):
        a = CacheService()
        b = CacheService()
        assert a is b, "CacheService 应为单例"

    def test_module_level_instance(self):
        assert isinstance(cache_manager, CacheService)


class TestCacheOperations:
    """缓存读写操作"""

    def test_set_and_get(self):
        cache_manager.set_json("_test_rw", {"foo": "bar", "num": 42})
        result = cache_manager.get_json("_test_rw")
        assert result == {"foo": "bar", "num": 42}
        cache_manager.delete("_test_rw")

    def test_get_missing_key_returns_default(self):
        result = cache_manager.get_json("_nonexistent_key_xyz", default="fallback")
        assert result == "fallback"

    def test_get_missing_key_returns_none(self):
        result = cache_manager.get_json("_nonexistent_key_abc")
        assert result is None

    def test_delete(self):
        cache_manager.set_json("_test_del", [1, 2, 3])
        cache_manager.delete("_test_del")
        result = cache_manager.get_json("_test_del")
        assert result is None

    def test_overwrite(self):
        cache_manager.set_json("_test_ow", "v1")
        cache_manager.set_json("_test_ow", "v2")
        assert cache_manager.get_json("_test_ow") == "v2"
        cache_manager.delete("_test_ow")

    def test_complex_data(self):
        """支持嵌套的复杂 JSON 数据"""
        data = {
            "strategies": [
                {"name": "MR", "score": 72.5},
                {"name": "DIV", "score": 65.0},
            ],
            "metadata": {"version": "v14.0", "timestamp": "2026-04-22T10:00:00"},
        }
        cache_manager.set_json("_test_complex", data)
        result = cache_manager.get_json("_test_complex")
        assert result["strategies"][0]["score"] == 72.5
        assert result["metadata"]["version"] == "v14.0"
        cache_manager.delete("_test_complex")

    def test_chinese_content(self):
        """支持中文内容"""
        cache_manager.set_json("_test_cn", {"label": "均值回归", "desc": "低买高卖"})
        result = cache_manager.get_json("_test_cn")
        assert result["label"] == "均值回归"
        cache_manager.delete("_test_cn")


class TestCacheFallback:
    """内存 fallback 验证"""

    def test_memory_mode_works(self):
        """当前无 Redis 环境，应处于内存模式且正常工作"""
        # 如果 Redis 可用，这个测试仍然通过
        cache_manager.set_json("_test_fallback", True)
        assert cache_manager.get_json("_test_fallback") is True
        cache_manager.delete("_test_fallback")
