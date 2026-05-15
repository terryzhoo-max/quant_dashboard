"""
AlphaCore P3-A · 引擎级断路器 (Circuit Breaker)
=================================================
当引擎连续异常时, 自动熔断并返回降级响应, 避免 500 错误传播到前端。

状态机:
  CLOSED  → (连续 N 次失败) → OPEN
  OPEN    → (等待 half_open_after 秒) → HALF_OPEN
  HALF_OPEN → (成功) → CLOSED
  HALF_OPEN → (失败) → OPEN

使用方式:
  breaker = CircuitBreaker("decision_hub", failure_threshold=3, half_open_after=300)
  result = breaker.call(lambda: expensive_engine_call(), fallback=cached_data)
"""

import time
import threading
from enum import Enum
from typing import Any, Callable, Optional
from services.logger import get_logger

logger = get_logger("ac.breaker")


class BreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """引擎级断路器"""

    def __init__(self, name: str,
                 failure_threshold: int = 3,
                 half_open_after: int = 300,
                 success_threshold: int = 2):
        """
        Args:
            name: 引擎名称 (用于日志)
            failure_threshold: 连续失败 N 次后熔断
            half_open_after: 熔断后等待多少秒尝试恢复
            success_threshold: HALF_OPEN 状态下连续成功 N 次后恢复
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.half_open_after = half_open_after
        self.success_threshold = success_threshold

        self._state = BreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> BreakerState:
        with self._lock:
            if self._state == BreakerState.OPEN:
                # 检查是否可以进入 HALF_OPEN
                if time.time() - self._last_failure_time >= self.half_open_after:
                    self._state = BreakerState.HALF_OPEN
                    self._success_count = 0
                    logger.info("[Breaker:%s] OPEN → HALF_OPEN (尝试恢复)", self.name)
            return self._state

    def call(self, fn: Callable, fallback: Any = None,
             fallback_fn: Callable = None) -> Any:
        """
        执行引擎调用, 带断路器保护。

        Args:
            fn: 主函数
            fallback: 静态降级数据 (优先)
            fallback_fn: 降级函数 (当 fallback 为 None 时使用)

        Returns:
            fn() 的结果, 或降级数据
        """
        current_state = self.state

        if current_state == BreakerState.OPEN:
            logger.warning("[Breaker:%s] 熔断中, 返回降级数据", self.name)
            return self._get_fallback(fallback, fallback_fn)

        try:
            result = fn()
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(str(e))
            if fallback is not None or fallback_fn is not None:
                return self._get_fallback(fallback, fallback_fn)
            raise

    def _on_success(self):
        with self._lock:
            if self._state == BreakerState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = BreakerState.CLOSED
                    self._failure_count = 0
                    logger.info("[Breaker:%s] HALF_OPEN → CLOSED (恢复正常)", self.name)
            else:
                self._failure_count = 0

    def _on_failure(self, error: str):
        with self._lock:
            self._failure_count += 1
            self._last_error = error
            self._last_failure_time = time.time()

            if self._state == BreakerState.HALF_OPEN:
                self._state = BreakerState.OPEN
                logger.warning("[Breaker:%s] HALF_OPEN → OPEN (恢复失败: %s)", self.name, error)
            elif self._failure_count >= self.failure_threshold:
                self._state = BreakerState.OPEN
                logger.error("[Breaker:%s] CLOSED → OPEN (连续 %d 次失败: %s)",
                           self.name, self._failure_count, error)

    def _get_fallback(self, fallback: Any, fallback_fn: Callable = None) -> Any:
        if fallback is not None:
            return fallback
        if fallback_fn is not None:
            try:
                return fallback_fn()
            except Exception as e:
                logger.error("[Breaker:%s] 降级函数也失败: %s", self.name, e)
        return {"status": "degraded", "error": self._last_error,
                "breaker": self.name, "message": "引擎暂时不可用, 使用降级数据"}

    def reset(self):
        """手动重置 (运维用)"""
        with self._lock:
            self._state = BreakerState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            logger.info("[Breaker:%s] 手动重置 → CLOSED", self.name)

    def get_status(self) -> dict:
        """状态查询"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "last_error": self._last_error,
            "failure_threshold": self.failure_threshold,
            "half_open_after": self.half_open_after,
        }


# ═══════════════════════════════════════════════════
#  预创建的断路器实例 (供各 Router 使用)
# ═══════════════════════════════════════════════════

decision_hub_breaker = CircuitBreaker("decision_hub", failure_threshold=3, half_open_after=300)
correlation_breaker = CircuitBreaker("correlation", failure_threshold=3, half_open_after=600)
brinson_breaker = CircuitBreaker("brinson", failure_threshold=3, half_open_after=600)
optimizer_breaker = CircuitBreaker("optimizer", failure_threshold=3, half_open_after=600)


def get_all_breaker_status() -> list:
    """查询所有断路器状态"""
    return [
        decision_hub_breaker.get_status(),
        correlation_breaker.get_status(),
        brinson_breaker.get_status(),
        optimizer_breaker.get_status(),
    ]
