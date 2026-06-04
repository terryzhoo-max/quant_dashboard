"""
Global guard for FRED API calls.

FRED is shared by several engines. Local retries in each engine are not enough:
when startup warmups run concurrently they can still create a request burst.
This module provides one process-wide rate limit and a short circuit breaker.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Dict, TypeVar

from services.logger import get_logger


T = TypeVar("T")

logger = get_logger("fred_guard")


class FredGuardError(RuntimeError):
    """Base class for FRED guard failures."""


class FredCircuitOpenError(FredGuardError):
    """Raised when FRED calls are temporarily blocked after rate limiting."""


class FredRateLimitError(FredGuardError):
    """Raised when the wrapped FRED call failed due to rate limiting."""


def should_retry_fred_error(exc: Exception) -> bool:
    """Return False for FRED guard failures that already opened the circuit."""
    return not isinstance(exc, (FredCircuitOpenError, FredRateLimitError))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class FredGuard:
    def __init__(
        self,
        min_interval_seconds: float = 1.25,
        cooldown_seconds: float = 300.0,
        time_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self._time = time_fn
        self._sleep = sleep_fn
        self._lock = threading.Lock()
        self._last_call_at = 0.0
        self._blocked_until = 0.0
        self._last_error = ""
        self._last_series = ""
        self._total_calls = 0
        self._rate_limited_count = 0

    def call(self, series_id: str, fn: Callable[[], T]) -> T:
        # Phase 1: 持锁检查速率状态 + 等待间隔
        with self._lock:
            now = self._time()
            if now < self._blocked_until:
                remaining = round(self._blocked_until - now, 1)
                raise FredCircuitOpenError(
                    f"FRED circuit open for {remaining}s after rate limit"
                )

            wait_for = self.min_interval_seconds - (now - self._last_call_at)
            if wait_for > 0:
                self._sleep(wait_for)

            self._last_call_at = self._time()
            self._last_series = series_id
            self._total_calls += 1

        # Phase 2: 释放锁后执行网络请求 (P0-2: 消除全局串行瓶颈)
        try:
            return fn()
        except Exception as exc:
            with self._lock:
                if self._is_rate_limit_error(exc):
                    self._rate_limited_count += 1
                    self._blocked_until = self._time() + self.cooldown_seconds
                    self._last_error = str(exc)
                    logger.warning(
                        "FRED rate limited on %s; circuit open for %.0fs",
                        series_id,
                        self.cooldown_seconds,
                    )
                    raise FredRateLimitError(str(exc)) from exc
                self._last_error = str(exc)
            raise

    def get_status(self) -> Dict[str, object]:
        now = self._time()
        state = "open" if now < self._blocked_until else "closed"
        return {
            "state": state,
            "blocked_for_sec": round(max(0.0, self._blocked_until - now), 1),
            "min_interval_sec": self.min_interval_seconds,
            "cooldown_sec": self.cooldown_seconds,
            "last_series": self._last_series,
            "last_error": self._last_error,
            "total_calls": self._total_calls,
            "rate_limited_count": self._rate_limited_count,
        }

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "too many requests" in msg
            or "rate limit" in msg
            or "exceeded rate" in msg
            or "status code: 429" in msg
            or "response code: 429" in msg
        )


fred_guard = FredGuard(
    min_interval_seconds=_env_float("FRED_MIN_INTERVAL_SECONDS", 3.0),
    cooldown_seconds=_env_float("FRED_RATE_LIMIT_COOLDOWN_SECONDS", 600.0),
)


def fred_get_series(series_id: str, fetch_fn: Callable[[], T]) -> T:
    return fred_guard.call(series_id, fetch_fn)


def get_fred_guard_status() -> Dict[str, object]:
    return fred_guard.get_status()
