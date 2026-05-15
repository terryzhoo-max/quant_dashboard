"""
AlphaCore P3-B · 自适应实时轮询器
===================================
盘中 30s / 盘后 5min / 周末暂停

关键特性:
  - 交易时段自动识别 (A股 09:30-15:00, 含夜盘 VIX 21:30-04:00)
  - VIX 跳变即时触发 (|Δ| > 5% → 强制刷新全链路)
  - 断路器保护 (连续失败自动降频)
  - APScheduler 无缝集成 (替换固定 120s 的 hot_data job)
"""

import time
import threading
from datetime import datetime
from typing import Callable, Optional

from services.logger import get_logger
from services.cache_service import cache_manager

logger = get_logger("ac.poller")


# ═══════════════════════════════════════════════════
#  交易时段判定
# ═══════════════════════════════════════════════════

class MarketSession:
    """市场交易时段识别器"""

    @staticmethod
    def is_a_share_session(dt: datetime = None) -> bool:
        """A 股盘中: 周一至周五 09:25 - 15:05"""
        dt = dt or datetime.now()
        if dt.weekday() >= 5:
            return False
        t = dt.hour * 60 + dt.minute
        return 565 <= t <= 905  # 09:25 - 15:05

    @staticmethod
    def is_us_session(dt: datetime = None) -> bool:
        """美股盘中 (北京时间): 21:30 - 04:00 次日 (夏令) / 22:30 - 05:00 (冬令)"""
        dt = dt or datetime.now()
        if dt.weekday() >= 5:  # 简化: 周末不开盘
            return False
        h = dt.hour
        return h >= 21 or h < 5

    @staticmethod
    def is_any_session(dt: datetime = None) -> bool:
        dt = dt or datetime.now()
        return MarketSession.is_a_share_session(dt) or MarketSession.is_us_session(dt)

    @staticmethod
    def get_polling_interval(dt: datetime = None) -> int:
        """
        自适应轮询间隔:
          A股盘中:   30s
          美股盘中:  60s (VIX 更新频率较低)
          盘后:      300s (5min)
          周末:      900s (15min)
        """
        dt = dt or datetime.now()
        if dt.weekday() >= 5:
            return 900
        if MarketSession.is_a_share_session(dt):
            return 30
        if MarketSession.is_us_session(dt):
            return 60
        return 300


# ═══════════════════════════════════════════════════
#  VIX 跳变检测器
# ═══════════════════════════════════════════════════

class VIXJumpDetector:
    """VIX 跳变检测: |Δ| > threshold → 触发紧急刷新"""

    def __init__(self, threshold_pct: float = 5.0, cooldown_seconds: int = 60):
        self.threshold_pct = threshold_pct
        self.cooldown_seconds = cooldown_seconds
        self._last_vix: Optional[float] = None
        self._last_trigger_time: float = 0

    def check(self, current_vix: float) -> bool:
        """返回 True 表示检测到跳变"""
        if current_vix is None or current_vix <= 0:
            return False

        now = time.time()
        if now - self._last_trigger_time < self.cooldown_seconds:
            return False  # 冷却中

        if self._last_vix is not None and self._last_vix > 0:
            change_pct = abs(current_vix - self._last_vix) / self._last_vix * 100
            if change_pct >= self.threshold_pct:
                logger.warning(
                    "[VIX Jump] %.2f → %.2f (%.1f%%), 触发紧急刷新",
                    self._last_vix, current_vix, change_pct
                )
                self._last_trigger_time = now
                self._last_vix = current_vix
                return True

        self._last_vix = current_vix
        return False

    def get_status(self) -> dict:
        return {
            "last_vix": self._last_vix,
            "threshold_pct": self.threshold_pct,
            "cooldown_seconds": self.cooldown_seconds,
            "in_cooldown": time.time() - self._last_trigger_time < self.cooldown_seconds,
        }


# ═══════════════════════════════════════════════════
#  自适应轮询器
# ═══════════════════════════════════════════════════

class AdaptivePoller:
    """
    自适应轮询器: 替代固定间隔的 hot_data_reactor_tick。
    
    使用方式 (在 APScheduler 中):
        poller = AdaptivePoller(
            tick_fn=_hot_data_reactor_tick,
            emergency_fn=_full_refresh_fn,
        )
        scheduler.add_job(poller.tick, IntervalTrigger(seconds=30), id="adaptive_poller")
    """

    def __init__(self, tick_fn: Callable, emergency_fn: Callable = None,
                 vix_threshold: float = 5.0, max_consecutive_errors: int = 5):
        self.tick_fn = tick_fn
        self.emergency_fn = emergency_fn
        self.vix_detector = VIXJumpDetector(threshold_pct=vix_threshold)
        self.session = MarketSession()

        self._consecutive_errors = 0
        self._max_errors = max_consecutive_errors
        self._last_tick_time: float = 0
        self._tick_count: int = 0
        self._skip_count: int = 0
        self._emergency_count: int = 0
        self._lock = threading.Lock()

    def tick(self):
        """APScheduler 调用入口 (固定 30s 间隔, 内部自适应跳过)"""
        now = datetime.now()
        now_ts = time.time()

        # 1. 自适应间隔: 根据市场状态决定是否执行
        interval = self.session.get_polling_interval(now)
        elapsed = now_ts - self._last_tick_time

        if elapsed < interval * 0.8:  # 还没到时间, 跳过
            self._skip_count += 1
            return

        # 2. 错误降频: 连续失败后拉长间隔
        if self._consecutive_errors >= self._max_errors:
            degraded_interval = interval * 3
            if elapsed < degraded_interval:
                logger.debug("[Poller] 错误降频中, 等待 %.0fs", degraded_interval - elapsed)
                return

        # 3. 执行 tick
        try:
            self.tick_fn()
            self._consecutive_errors = 0
            self._tick_count += 1
            self._last_tick_time = now_ts

            # 4. VIX 跳变检测
            vix_val = self._get_current_vix()
            if vix_val and self.vix_detector.check(vix_val):
                self._trigger_emergency()

        except Exception as e:
            self._consecutive_errors += 1
            logger.warning("[Poller] tick 异常 (%d/%d): %s",
                         self._consecutive_errors, self._max_errors, e)

    def _get_current_vix(self) -> Optional[float]:
        """从缓存获取当前 VIX"""
        try:
            data = cache_manager.get_json("dashboard_data")
            if data and isinstance(data, dict):
                mc = data.get("data", {}).get("macro_cards", {})
                vix_card = mc.get("vix", {})
                return vix_card.get("value")
        except Exception:
            pass
        return None

    def _trigger_emergency(self):
        """VIX 跳变紧急刷新"""
        self._emergency_count += 1
        if self.emergency_fn:
            try:
                logger.info("[Poller] VIX 跳变 → 触发紧急全量刷新 (#%d)", self._emergency_count)
                self.emergency_fn()
            except Exception as e:
                logger.error("[Poller] 紧急刷新失败: %s", e)

    def get_status(self) -> dict:
        now = datetime.now()
        return {
            "current_interval": self.session.get_polling_interval(now),
            "session": {
                "a_share": self.session.is_a_share_session(now),
                "us": self.session.is_us_session(now),
            },
            "stats": {
                "tick_count": self._tick_count,
                "skip_count": self._skip_count,
                "emergency_count": self._emergency_count,
                "consecutive_errors": self._consecutive_errors,
            },
            "vix_detector": self.vix_detector.get_status(),
            "last_tick": datetime.fromtimestamp(self._last_tick_time).isoformat()
                         if self._last_tick_time > 0 else None,
        }


# ═══════════════════════════════════════════════════
#  全局实例 (由 main.py lifespan 初始化)
# ═══════════════════════════════════════════════════

_global_poller: Optional[AdaptivePoller] = None


def init_poller(tick_fn: Callable, emergency_fn: Callable = None) -> AdaptivePoller:
    """初始化全局轮询器"""
    global _global_poller
    _global_poller = AdaptivePoller(tick_fn=tick_fn, emergency_fn=emergency_fn)
    logger.info("[Poller] 自适应轮询器已初始化")
    return _global_poller


def get_poller() -> Optional[AdaptivePoller]:
    return _global_poller
