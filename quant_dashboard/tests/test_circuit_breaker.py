"""
AlphaCore P3-A · 断路器单元测试
==================================
"""

import pytest
import time
from unittest.mock import patch

from services.circuit_breaker import (
    CircuitBreaker,
    BreakerState,
    get_all_breaker_status,
)


# ═══════════════════════════════════════════════════
#  基本状态机
# ═══════════════════════════════════════════════════

class TestBreakerStateMachine:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        assert cb.state == BreakerState.CLOSED

    def test_success_keeps_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        result = cb.call(lambda: "ok")
        assert result == "ok"
        assert cb.state == BreakerState.CLOSED
        assert cb._failure_count == 0

    def test_single_failure_stays_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        result = cb.call(lambda: (_ for _ in ()).throw(ValueError("err")),
                        fallback="fallback_data")
        assert result == "fallback_data"
        assert cb.state == BreakerState.CLOSED
        assert cb._failure_count == 1

    def test_threshold_failures_opens(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        for _ in range(3):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")),
                   fallback="fb")
        assert cb.state == BreakerState.OPEN

    def test_open_returns_fallback_immediately(self):
        cb = CircuitBreaker("test", failure_threshold=2, half_open_after=9999)
        # Trip the breaker
        for _ in range(2):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")), fallback="fb")

        call_count = 0
        def counter():
            nonlocal call_count
            call_count += 1
            return "real_data"

        result = cb.call(counter, fallback="cached")
        assert result == "cached"
        assert call_count == 0  # fn was NOT called

    def test_half_open_transition(self):
        cb = CircuitBreaker("test", failure_threshold=2, half_open_after=0)
        # Trip
        for _ in range(2):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()), fallback="fb")
        assert cb._state == BreakerState.OPEN  # internal state is OPEN

        # With half_open_after=0, reading .state immediately transitions
        time.sleep(0.01)
        assert cb.state == BreakerState.HALF_OPEN

    def test_half_open_success_closes(self):
        cb = CircuitBreaker("test", failure_threshold=2,
                           half_open_after=0, success_threshold=2)
        # Trip
        for _ in range(2):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()), fallback="fb")
        time.sleep(0.01)
        assert cb.state == BreakerState.HALF_OPEN

        # 2 successes → CLOSED
        cb.call(lambda: "ok")
        assert cb.state == BreakerState.HALF_OPEN  # need 2
        cb.call(lambda: "ok")
        assert cb.state == BreakerState.CLOSED

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker("test", failure_threshold=2,
                           half_open_after=0, success_threshold=2)
        # Trip
        for _ in range(2):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()), fallback="fb")
        time.sleep(0.01)
        assert cb.state == BreakerState.HALF_OPEN

        # Fail in HALF_OPEN → back to OPEN
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError()), fallback="fb")
        assert cb._state == BreakerState.OPEN


# ═══════════════════════════════════════════════════
#  Fallback 机制
# ═══════════════════════════════════════════════════

class TestFallback:
    def test_static_fallback(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        result = cb.call(lambda: (_ for _ in ()).throw(ValueError()),
                        fallback={"status": "cached"})
        assert result == {"status": "cached"}

    def test_fallback_fn(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        result = cb.call(
            lambda: (_ for _ in ()).throw(ValueError()),
            fallback_fn=lambda: {"status": "computed_fallback"}
        )
        assert result == {"status": "computed_fallback"}

    def test_no_fallback_raises(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))

    def test_static_fallback_priority_over_fn(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        result = cb.call(
            lambda: (_ for _ in ()).throw(ValueError()),
            fallback="static",
            fallback_fn=lambda: "dynamic"
        )
        assert result == "static"

    def test_degraded_response_when_both_fail(self):
        """fallback_fn 也失败 → 返回降级元数据"""
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.call(lambda: (_ for _ in ()).throw(ValueError("original")),
               fallback_fn=lambda: (_ for _ in ()).throw(RuntimeError("fb_fail")))
        # 第二次调用 (open state)
        cb._state = BreakerState.OPEN
        cb._last_failure_time = time.time() + 9999  # keep open
        result = cb.call(
            lambda: "should_not_run",
            fallback_fn=lambda: (_ for _ in ()).throw(RuntimeError("fb_fail"))
        )
        assert result["status"] == "degraded"


# ═══════════════════════════════════════════════════
#  Reset & Status
# ═══════════════════════════════════════════════════

class TestResetAndStatus:
    def test_reset(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        for _ in range(2):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError()), fallback="fb")
        assert cb.state == BreakerState.OPEN

        cb.reset()
        assert cb.state == BreakerState.CLOSED
        assert cb._failure_count == 0

    def test_get_status(self):
        cb = CircuitBreaker("my_engine", failure_threshold=5)
        status = cb.get_status()
        assert status["name"] == "my_engine"
        assert status["state"] == "closed"
        assert status["failure_threshold"] == 5

    def test_last_error_recorded(self):
        cb = CircuitBreaker("test", failure_threshold=5)
        cb.call(lambda: (_ for _ in ()).throw(ValueError("specific_error")),
               fallback="fb")
        assert "specific_error" in cb._last_error


# ═══════════════════════════════════════════════════
#  全局实例
# ═══════════════════════════════════════════════════

class TestGlobalInstances:
    def test_get_all_status(self):
        statuses = get_all_breaker_status()
        assert len(statuses) == 4
        names = {s["name"] for s in statuses}
        assert "decision_hub" in names
        assert "optimizer" in names

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=5)
        cb.call(lambda: (_ for _ in ()).throw(ValueError()), fallback="fb")
        cb.call(lambda: (_ for _ in ()).throw(ValueError()), fallback="fb")
        assert cb._failure_count == 2
        cb.call(lambda: "ok")
        assert cb._failure_count == 0
