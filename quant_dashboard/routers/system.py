"""
AlphaCore · 系统健康检查与缓存监控 API
========================================
/api/v1/system/health     GET   全局健康检查
/api/v1/system/cache      GET   EngineCache 统一监控面板
/api/v1/system/cache/flush POST  手动清除指定引擎缓存
"""

import time
from datetime import datetime
from fastapi import APIRouter

from version import VERSION_STRING, VERSION_SHORT

router = APIRouter(prefix="/api/v1/system", tags=["System"])

# ── 收集所有 EngineCache 实例的注册表 ──
_ENGINE_CACHE_REGISTRY: dict = {}


def register_engine_cache(name: str, cache_instance):
    """引擎模块在 import 时自动注册, 供 /cache API 统一查询"""
    _ENGINE_CACHE_REGISTRY[name] = cache_instance


def _collect_cache_stats() -> dict:
    """聚合所有已注册的 EngineCache 实例状态"""
    all_stats = {}
    total_keys = 0
    for name, cache in _ENGINE_CACHE_REGISTRY.items():
        try:
            stats = cache.stats()
            total_keys += stats.get("total_keys", 0)
            all_stats[name] = stats
        except Exception as e:
            all_stats[name] = {"error": str(e)}
    return {"total_instances": len(all_stats), "total_keys": total_keys, "instances": all_stats}


# ═══════════════════════════════════════════
#  Endpoints
# ═══════════════════════════════════════════

@router.get("/health")
async def health_check():
    """全局健康检查 — 轻量级, 用于 Load Balancer / 监控"""
    cache_summary = _collect_cache_stats()
    return {
        "status": "ok",
        "version": VERSION_SHORT,
        "full_version": VERSION_STRING,
        "timestamp": datetime.now().isoformat(),
        "uptime_note": "use /api/v1/system/cache for detailed cache stats",
        "cache_instances": cache_summary["total_instances"],
        "cache_keys": cache_summary["total_keys"],
    }


@router.get("/cache")
async def cache_dashboard():
    """V6.0: 增强缓存监控面板 — 引擎缓存 + SWR 键状态 + 预热进度 + 市场时段"""
    from services.cache_service import cache_manager, is_market_hours
    import time as _t

    stats = _collect_cache_stats()

    # V6.0: CacheService 后端统计
    cache_backend = cache_manager.stats()

    # V6.0: 所有 SWR 缓存键的 age / freshness 状态
    _SWR_KEYS = [
        "swr_decision_hub", "swr_risk_matrix", "swr_compliance", "swr_accuracy",
        "swr_perf_analytics", "swr_swing_guard", "swr_corr_matrix", "swr_contagion_matrix",
        "swr_drift_status", "swr_multi_asset", "swr_erp_timing", "swr_erp_global",
        "swr_rates", "swr_gold_signal", "swr_gem_strategy", "swr_aiae_cn_report",
        "swr_portfolio_risk",
    ]
    swr_status = {}
    now = _t.time()
    for key in _SWR_KEYS:
        cached = cache_manager.get_json(key)
        if cached and isinstance(cached, dict) and "timestamp" in cached:
            age = int(now - cached["timestamp"])
            swr_status[key] = {"age_sec": age, "age_human": _format_age(age), "status": "cached"}
        else:
            swr_status[key] = {"age_sec": None, "status": "miss"}

    # V6.0: 预热进度
    warmup_status = cache_manager.get_json("warmup_status") or {"phase": "unknown"}

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "market_period": is_market_hours(),
        "cache_backend": cache_backend,
        "warmup": warmup_status,
        "swr_keys": swr_status,
        "swr_miss_count": sum(1 for v in swr_status.values() if v["status"] == "miss"),
        "swr_total": len(swr_status),
        **stats,
    }


def _format_age(seconds: int) -> str:
    """格式化缓存年龄为人类可读字符串"""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h{minutes}m"


@router.post("/cache/flush")
async def cache_flush(engine: str = None):
    """手动清除缓存

    Args:
        engine: 引擎名称 (如 "erp", "aiae")。不传则清除所有。
    """
    flushed = []
    if engine:
        if engine in _ENGINE_CACHE_REGISTRY:
            _ENGINE_CACHE_REGISTRY[engine].invalidate()
            flushed.append(engine)
        else:
            return {"status": "error", "message": f"未找到引擎 '{engine}'",
                    "available": list(_ENGINE_CACHE_REGISTRY.keys())}
    else:
        for name, cache in _ENGINE_CACHE_REGISTRY.items():
            cache.invalidate()
            flushed.append(name)

    return {
        "status": "ok",
        "flushed": flushed,
        "message": f"已清除 {len(flushed)} 个缓存实例",
        "timestamp": datetime.now().isoformat(),
    }
