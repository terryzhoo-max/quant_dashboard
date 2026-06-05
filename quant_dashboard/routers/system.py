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
    """EngineCache 统一监控面板 — 展示所有引擎缓存实例的键数、年龄、命中情况"""
    stats = _collect_cache_stats()
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        **stats,
    }


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
