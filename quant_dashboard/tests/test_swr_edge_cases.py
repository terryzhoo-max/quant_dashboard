import time
import pytest
import threading
from concurrent.futures import ThreadPoolExecutor
from services.cache_service import stale_while_revalidate, cache_manager
from dashboard_modules.fetch_macro import fetch_cny_for_dashboard, _save_cny_disk, _load_cny_disk


def test_swr_non_dict_type_safety():
    """测试 1: 非 dict 类型数据缓存类型安全 (不应崩溃)"""
    cache_key = "swr_test_list_key"
    cache_manager.delete(cache_key)

    # 1. 首次 Miss 同步计算
    compute_count = 0
    def compute_list():
        nonlocal compute_count
        compute_count += 1
        return [1, 2, 3]

    res = stale_while_revalidate(cache_key, compute_list, fresh_ttl=2, stale_ttl=10)
    assert res == [1, 2, 3]
    assert compute_count == 1

    # 2. 命中 Fresh 时段 (Tier 1)
    res2 = stale_while_revalidate(cache_key, compute_list, fresh_ttl=2, stale_ttl=10)
    assert res2 == [1, 2, 3]
    assert compute_count == 1  # 无额外计算

    # 3. 模拟 Stale 时段 (手动把 timestamp 调回去)
    cached = cache_manager.get_json(cache_key)
    cached["timestamp"] = time.time() - 5  # 过了 fresh_ttl，没过 stale_ttl
    cache_manager.set_json(cache_key, cached)

    # 命中 Stale 时段 (Tier 2)，应直接返回旧值，并在后台异步计算
    res3 = stale_while_revalidate(cache_key, compute_list, fresh_ttl=2, stale_ttl=10)
    assert res3 == [1, 2, 3]
    
    # 稍等一会让后台异步计算完成
    time.sleep(0.5)
    assert compute_count == 2


def test_swr_single_flight_stampede():
    """测试 2: SWR Single Flight 同步防击穿 (并发 Hard miss 时只计算一次)"""
    cache_key = "swr_test_single_flight"
    cache_manager.delete(cache_key)

    compute_count = 0
    compute_lock = threading.Lock()

    def slow_compute():
        nonlocal compute_count
        with compute_lock:
            compute_count += 1
        time.sleep(0.5)  # 模拟较慢的计算
        return {"data": "ok"}

    # 并发 5 个线程请求
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(stale_while_revalidate, cache_key, slow_compute, 5, 20)
            for _ in range(5)
        ]
        results = [f.result() for f in futures]

    # 所有线程都应该得到正确的数据
    for r in results:
        assert r["data"] == "ok"
        assert r["_cache"]["cached"] in (True, False)

    # 虽然有 5 个并发请求，但在 Single Flight 锁保护下，`slow_compute` 应该只被调用了 1 次
    assert compute_count == 1


def test_swr_stale_on_error():
    """测试 3: Stale-on-Error 柔性降级 (Hard miss 异常时返回过期缓存)"""
    cache_key = "swr_test_stale_on_error"
    cache_manager.delete(cache_key)

    # 1. 写入一份初始数据
    payload = {"timestamp": time.time() - 30000, "data": {"strategy": "MA_Cross"}}  # 30000s 前，早已过期
    cache_manager.set_json(cache_key, payload)

    # 2. 运行 stale_while_revalidate 且 compute_fn 抛出异常
    def fail_compute():
        raise RuntimeError("Tushare API rate limit exceeded")

    res = stale_while_revalidate(cache_key, fail_compute, fresh_ttl=60, stale_ttl=120)

    # 验证是否没有崩溃，并且成功返回了过期的旧数据，同时被打上了降级标记
    assert res["strategy"] == "MA_Cross"
    assert res["_cache"]["cached"] is True
    assert res["_cache"]["stale"] is True
    assert res["_cache"]["degraded"] is True
    assert "Tushare API rate limit" in res["_cache"]["error"]


def test_cny_disk_cache_behavior():
    """测试 4: CNY 离岸人民币汇率磁盘降级缓存功能"""
    # 模拟写入和读取
    test_rate = 7.2458
    _save_cny_disk(test_rate)

    # 检查是否成功从磁盘加载
    loaded = _load_cny_disk(max_age_hours=24)
    assert loaded == test_rate

    # 测试 fetch_cny_for_dashboard，我们可以用 mock 模拟网络失败
    # 在非周末时，fetch_cny_for_dashboard 会优先发起请求。
    # 我们可以通过 mock 故意让 CNBC 请求失败，看它是否能自动回滚到磁盘上的 7.2458
    import requests
    original_get = requests.get

    def mock_get(url, **kwargs):
        raise requests.exceptions.RequestException("CNBC Down")

    import dashboard_modules.fetch_macro as fm
    fm.requests.get = mock_get

    try:
        cny = fetch_cny_for_dashboard()
        assert cny == test_rate  # 应该读取磁盘缓存值
    finally:
        fm.requests.get = original_get
