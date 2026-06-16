"""AlphaCore 共享缓存容器 — 跨模块状态管理"""
from datetime import datetime


def get_cache_ttl() -> int:
    """智能缓存 TTL：盘中5分钟 / 盘后18小时 / 周末72小时

    核心原则: 盘后数据已冻结，TTL 必须覆盖到下一个预热窗口 (08:30/15:35)。
    缓存不应在无刷新机制时自行过期，否则页面降级为 Fallback 假数据，
    导致信号方向误导 (e.g. 真实 Regime=4/Cap=44% 显示为 Regime=3/Cap=65%)。
    """
    now = datetime.now()
    weekday = now.weekday()
    if weekday >= 5:
        return 259200   # 72h: 覆盖整个周末到 Monday 08:30
    hour = now.hour
    if 9 <= hour < 15:  # A股盘中 09:00-14:59 (15:00 已收盘)
        return 300
    # 盘后: TTL 覆盖到下一个预热窗口
    if weekday == 4 and hour >= 15:
        return 259200   # Friday 15:00+ → Monday 08:30 (≈65.5h)
    return 64800        # Mon-Thu 盘后: 18h → 次日 morning_warmup (08:30)


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
