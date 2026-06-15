"""
Global guard for FRED API calls — V2.0 (Production-Grade)

Four-layer optimization stack:
  L1: Disk cache (parquet) — skip API if fresh data on disk
  L2: Inflight dedup       — concurrent requests for same series share one API call
  L3: Rate limiter         — process-wide min_interval + circuit breaker
  L4: Stale fallback       — circuit open → return stale disk cache instead of raising

FRED free tier: 120 requests/minute.
Typical daily need: ~15 unique series × 1 refresh = 15 calls/day.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import Future
from typing import Callable, Dict, Optional, TypeVar

import pandas as pd

from services.logger import get_logger


T = TypeVar("T")

logger = get_logger("fred_guard")


# ═══════════════════════════════════════════════════
#  Exceptions
# ═══════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════
#  L1: Disk Cache Layer
# ═══════════════════════════════════════════════════

_FRED_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data_lake", "fred_cache",
)
os.makedirs(_FRED_CACHE_DIR, exist_ok=True)

# Default disk TTL: 6 hours (FRED macro data updates daily at most)
_DEFAULT_DISK_TTL_HOURS = _env_float("FRED_DISK_TTL_HOURS", 6.0)


def _disk_cache_path(series_id: str) -> str:
    """Safe filename for series cache."""
    safe_id = series_id.replace("/", "_").replace("\\", "_")
    return os.path.join(_FRED_CACHE_DIR, f"{safe_id}.parquet")


def _read_disk_cache(series_id: str, max_age_hours: float) -> Optional[pd.Series]:
    """Read cached series from disk if fresh enough.

    Returns None if cache is missing/stale/corrupt.
    """
    path = _disk_cache_path(series_id)
    if not os.path.exists(path):
        return None
    try:
        age_hours = (time.time() - os.path.getmtime(path)) / 3600.0
        if age_hours > max_age_hours:
            return None
        df = pd.read_parquet(path)
        if df.empty:
            return None
        series = df.iloc[:, 0]
        series.index = df.index
        logger.info("FRED disk cache hit: %s (%.1fh old)", series_id, age_hours)
        return series
    except Exception as e:
        logger.debug("FRED disk cache read failed for %s: %s", series_id, e)
        return None


def _read_stale_disk_cache(series_id: str) -> Optional[pd.Series]:
    """Read disk cache regardless of age (fallback during circuit open)."""
    path = _disk_cache_path(series_id)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path)
        if df.empty:
            return None
        series = df.iloc[:, 0]
        series.index = df.index
        age_hours = (time.time() - os.path.getmtime(path)) / 3600.0
        logger.warning(
            "FRED stale cache fallback: %s (%.1fh old, circuit open)",
            series_id, age_hours,
        )
        return series
    except Exception:
        return None


def _write_disk_cache(series_id: str, data: pd.Series):
    """Write series to disk cache (atomic via tmp file)."""
    path = _disk_cache_path(series_id)
    tmp = path + ".tmp"
    try:
        df = pd.DataFrame({series_id: data})
        df.to_parquet(tmp, engine="pyarrow")
        os.replace(tmp, path)
    except Exception as e:
        logger.debug("FRED disk cache write failed for %s: %s", series_id, e)
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ═══════════════════════════════════════════════════
#  L2: Inflight Deduplication
# ═══════════════════════════════════════════════════

_inflight_lock = threading.Lock()
_inflight: Dict[str, Future] = {}


# ═══════════════════════════════════════════════════
#  L3: Rate Limiter + Circuit Breaker
# ═══════════════════════════════════════════════════

class FredGuard:
    def __init__(
        self,
        min_interval_seconds: float = 1.5,
        cooldown_seconds: float = 120.0,
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
        self._disk_cache_hits = 0

    @property
    def is_circuit_open(self) -> bool:
        return self._time() < self._blocked_until

    def call(self, series_id: str, fn: Callable[[], T]) -> T:
        # Phase 1: 持锁 → 计算等待时间 + 更新时间戳 → 释放锁
        # P1-1 修复: sleep 移到锁外, 消除全局串行瓶颈
        wait_for = 0.0
        with self._lock:
            now = self._time()
            if now < self._blocked_until:
                remaining = round(self._blocked_until - now, 1)
                raise FredCircuitOpenError(
                    f"FRED circuit open for {remaining}s after rate limit"
                )

            wait_for = self.min_interval_seconds - (now - self._last_call_at)
            # 预占时间槽: 即使多线程同时到达, 每个都会拿到不同的等待时间
            self._last_call_at = max(now, self._last_call_at + self.min_interval_seconds)
            self._last_series = series_id
            self._total_calls += 1

        # 锁外 sleep — 不阻塞其他 FRED 调用者
        if wait_for > 0:
            self._sleep(wait_for)

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
            "disk_cache_hits": self._disk_cache_hits,
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


# ═══════════════════════════════════════════════════
#  Global Instance (tuned defaults)
# ═══════════════════════════════════════════════════

fred_guard = FredGuard(
    min_interval_seconds=_env_float("FRED_MIN_INTERVAL_SECONDS", 1.5),
    cooldown_seconds=_env_float("FRED_RATE_LIMIT_COOLDOWN_SECONDS", 120.0),
)


# ═══════════════════════════════════════════════════
#  Public API — L1→L2→L3→L4 四层调用栈
# ═══════════════════════════════════════════════════

def fred_get_series(
    series_id: str,
    fetch_fn: Callable[[], T],
    disk_ttl_hours: Optional[float] = None,
) -> T:
    """Production-grade FRED data accessor.

    Call stack:
      L1: disk cache check (parquet, default 6h TTL)
      L2: inflight dedup (concurrent callers share one API call)
      L3: rate limiter + circuit breaker
      L4: stale disk fallback on failure

    Args:
        series_id: FRED series identifier (e.g. "DGS10")
        fetch_fn: Callable that returns a pd.Series from fredapi
        disk_ttl_hours: Override disk cache TTL (default from env/6h)
    """
    ttl = disk_ttl_hours if disk_ttl_hours is not None else _DEFAULT_DISK_TTL_HOURS

    # ── L1: Disk cache check ──
    cached = _read_disk_cache(series_id, ttl)
    if cached is not None:
        fred_guard._disk_cache_hits += 1
        return cached

    # ── L2: Inflight dedup ──
    # If another thread is already fetching this series, wait for its result
    with _inflight_lock:
        if series_id in _inflight:
            future = _inflight[series_id]
            logger.debug("FRED dedup: joining inflight request for %s", series_id)
        else:
            future = Future()
            _inflight[series_id] = future
            future = None  # Signal: we are the leader

    if future is not None:
        # Follower: wait for leader's result
        try:
            return future.result(timeout=60)
        except Exception:
            # Leader failed; try stale cache
            stale = _read_stale_disk_cache(series_id)
            if stale is not None:
                return stale
            raise

    # ── Leader path: L3 rate limiter + L4 fallback ──
    leader_future = _inflight[series_id]
    try:
        # L3: Rate-limited API call
        result = fred_guard.call(series_id, fetch_fn)

        # Success: write to disk cache + notify followers
        if isinstance(result, pd.Series) and not result.empty:
            _write_disk_cache(series_id, result)

        leader_future.set_result(result)
        return result

    except FredCircuitOpenError:
        # L4: Circuit open → try stale disk cache before raising
        stale = _read_stale_disk_cache(series_id)
        if stale is not None:
            leader_future.set_result(stale)
            return stale
        leader_future.set_exception(
            FredCircuitOpenError("FRED circuit open, no stale cache")
        )
        raise

    except Exception as exc:
        # L4: API error → try stale disk cache
        stale = _read_stale_disk_cache(series_id)
        if stale is not None:
            leader_future.set_result(stale)
            return stale
        leader_future.set_exception(exc)
        raise

    finally:
        # Clean up inflight entry
        with _inflight_lock:
            _inflight.pop(series_id, None)


def get_fred_guard_status() -> Dict[str, object]:
    status = fred_guard.get_status()
    # Add disk cache stats
    cache_files = []
    try:
        for f in os.listdir(_FRED_CACHE_DIR):
            if f.endswith(".parquet"):
                path = os.path.join(_FRED_CACHE_DIR, f)
                age_h = (time.time() - os.path.getmtime(path)) / 3600.0
                cache_files.append({
                    "series": f.replace(".parquet", ""),
                    "age_hours": round(age_h, 1),
                    "fresh": age_h <= _DEFAULT_DISK_TTL_HOURS,
                })
    except OSError:
        pass
    status["disk_cache"] = {
        "dir": _FRED_CACHE_DIR,
        "ttl_hours": _DEFAULT_DISK_TTL_HOURS,
        "files": cache_files,
    }
    return status
