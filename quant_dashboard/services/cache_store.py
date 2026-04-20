"""AlphaCore 共享缓存容器 — 跨模块状态管理"""
import threading
from datetime import datetime


# 海外 AIAE 全局缓存 (V1.1: L1 API结果级缓存)
_AIAE_GLOBAL_LOCK = threading.Lock()
AIAE_GLOBAL_CACHE = {
    "last_update": None,
    "report_data": None
}


def get_cache_ttl() -> int:
    """智能缓存 TTL：盘中5分钟 / 盘后1小时 / 周末24小时"""
    now = datetime.now()
    weekday = now.weekday()
    if weekday >= 5:
        return 86400
    hour = now.hour
    if 9 <= hour <= 15:
        return 300
    return 3600


def get_global_aiae_ttl() -> int:
    """海外 AIAE TTL: 盘中15分钟 / 盘后6小时 / 周末24小时"""
    now = datetime.now()
    weekday = now.weekday()
    if weekday >= 5:
        return 86400
    hour = now.hour
    if 9 <= hour <= 15:
        return 900
    if 21 <= hour or hour <= 5:
        return 1800
    return 21600
