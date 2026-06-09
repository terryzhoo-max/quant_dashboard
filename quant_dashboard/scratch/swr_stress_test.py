import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from services.cache_service import stale_while_revalidate, cache_manager

def run_swr_concurrency_stress():
    print("=" * 60)
    print("SWR 统一缓存 - 机构级并发压力测试 (50并发)")
    print("=" * 60)
    
    cache_key = "swr_stress_test_key"
    cache_manager.delete(cache_key)
    
    compute_count = 0
    compute_lock = threading.Lock()
    
    def slow_heavy_compute():
        nonlocal compute_count
        with compute_lock:
            compute_count += 1
        # 模拟 0.2s 的高载/网路延迟计算
        time.sleep(0.2)
        return {"value": random.randint(100, 999), "timestamp": time.time()}

    # ────────────────────────────────────────────────────────
    # 场景 1: 50并发 Hard miss 同步防击穿测试
    # ────────────────────────────────────────────────────────
    print("场景 1: 50路并发 Hard miss 请求开始...")
    t_start = time.time()
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [
            executor.submit(stale_while_revalidate, cache_key, slow_heavy_compute, fresh_ttl=2, stale_ttl=10)
            for _ in range(50)
        ]
        results = [f.result() for f in as_completed(futures)]
        
    t_elapsed = time.time() - t_start
    print(f"  -> 50路并发请求全部完成。总耗时: {t_elapsed:.4f}s")
    print(f"  -> 实际计算执行次数: {compute_count} 次 (预期: 1次)")
    
    # 验证 Single Flight 防击穿效果
    assert compute_count == 1, f"击穿防线！实际计算执行了 {compute_count} 次"
    # 验证并发总耗时是否远小于串行等待 (50 * 0.2s = 10s)，应接近 0.2s 的单次阻塞
    assert t_elapsed < 1.0, f"并发等待开销过大: {t_elapsed:.4f}s"
    print("  ✅ 场景 1 校验通过: Single Flight 成功拦截了 49 个无效重复穿透计算")
    
    # ────────────────────────────────────────────────────────
    # 场景 2: 50并发 Fresh 内存高速命中测试
    # ────────────────────────────────────────────────────────
    print("\n场景 2: 50路并发 Fresh 状态高速请求开始...")
    t_start = time.time()
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [
            executor.submit(stale_while_revalidate, cache_key, slow_heavy_compute, fresh_ttl=2, stale_ttl=10)
            for _ in range(50)
        ]
        results_fresh = [f.result() for f in as_completed(futures)]
        
    t_elapsed_fresh = time.time() - t_start
    print(f"  -> 50路请求在 Fresh 时段全部完成。总耗时: {t_elapsed_fresh:.4f}s")
    print(f"  -> 实际计算执行次数: {compute_count} 次 (预期: 保持1次不变)")
    
    assert compute_count == 1, "Fresh 缓存时段发生了不应有的重算"
    assert t_elapsed_fresh < 0.05, f"Fresh 时段缓存读取过慢: {t_elapsed_fresh:.4f}s"
    print("  ✅ 场景 2 校验通过: Fresh 时段实现微秒级本地零延迟直接命中")

    # ────────────────────────────────────────────────────────
    # 场景 3: 模拟外部接口断线时的 50并发 Stale-on-Error 柔性降级测试
    # ────────────────────────────────────────────────────────
    print("\n场景 3: 模拟 50并发 API 断网 + 触发 Stale-on-Error 柔性降级...")
    
    # 手动让缓存过期 (变成过期缓存)
    cached = cache_manager.get_json(cache_key)
    cached["timestamp"] = time.time() - 30000  # 30000s 前
    cache_manager.set_json(cache_key, cached)
    
    # 模拟高比例故障接口
    def broken_api_compute():
        raise RuntimeError("Tushare Pro / FRED API timeout connection refused")
        
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [
            executor.submit(stale_while_revalidate, cache_key, broken_api_compute, fresh_ttl=2, stale_ttl=10)
            for _ in range(50)
        ]
        results_degraded = [f.result() for f in as_completed(futures)]
        
    t_elapsed_degraded = time.time() - t_start
    print(f"  -> 50路请求在 API 故障时全部返回完毕。总耗时: {t_elapsed_degraded:.4f}s")
    
    # 统计返回结果
    success_fallbacks = 0
    errors = 0
    for res in results_degraded:
        if isinstance(res, dict) and "_cache" in res and res["_cache"].get("degraded") is True:
            success_fallbacks += 1
        else:
            errors += 1
            
    print(f"  -> 成功返回降级历史缓存数: {success_fallbacks} (预期: 50)")
    print(f"  -> 最终向客户端抛出异常数: {errors} (预期: 0)")
    
    assert success_fallbacks == 50, f"部分请求未能成功回退到旧缓存: 成功 {success_fallbacks}, 失败 {errors}"
    print("  ✅ 场景 3 校验通过: Stale-on-Error 完美接管故障，50个客户端无一报错白屏")
    
    print("\n" + "=" * 60)
    print("总结: 缓存锁防击穿、零等待Fresh、高可用Stale-on-Error全部达到机构生产级指标！")
    print("=" * 60)

if __name__ == "__main__":
    run_swr_concurrency_stress()
