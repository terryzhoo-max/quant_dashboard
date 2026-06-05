"""
AlphaCore · 统一重试装饰器
===========================
从 6 个引擎中提取的公共重试工具。
支持两种历史 API 签名 + 可选的错误过滤器 (FRED Guard)。

使用方式:
    from services.retry import retry_with_backoff

    # 标准用法 (替代 ERP/AIAE HK/JP/US 变体)
    @retry_with_backoff(max_retries=3, base_delay=2.0)
    def fetch_data(): ...

    # MR 引擎旧签名兼容
    @retry_with_backoff(retries=3, backoff_in_seconds=1)
    def fetch_data(): ...

    # 带 FRED 错误过滤 (替代 AIAE HK/JP/US 变体)
    from services.fred_guard import should_retry_fred_error
    @retry_with_backoff(max_retries=3, base_delay=2.0, error_filter=should_retry_fred_error)
    def fetch_fred(): ...
"""

import time
import logging
from functools import wraps
from typing import Callable, Optional

logger = logging.getLogger("alphacore.retry")


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 2.0,
    *,
    retries: int = None,
    backoff_in_seconds: float = None,
    error_filter: Optional[Callable[[Exception], bool]] = None,
):
    """指数退避重试装饰器 (统一 6 处历史实现)

    Args:
        max_retries: 最大重试次数 (默认 3)
        base_delay: 初始延迟秒数 (默认 2.0, 每次 ×2)
        retries: MR 引擎旧签名兼容 (优先于 max_retries)
        backoff_in_seconds: MR 引擎旧签名兼容 (优先于 base_delay)
        error_filter: 可选的错误过滤器。
                      接受异常实例，返回 True 表示应该重试。
                      返回 False 表示应该立即 raise (不重试)。
                      None 表示所有异常都重试。
    """
    _retries = retries if retries is not None else max_retries
    _delay = backoff_in_seconds if backoff_in_seconds is not None else base_delay

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = _delay
            for i in range(_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # 错误过滤: 某些错误不应重试 (如 FRED 熔断)
                    if error_filter is not None and not error_filter(e):
                        raise
                    if i == _retries - 1:
                        raise
                    logger.warning(
                        "Retry %s [%d/%d]: %s. Wait %.1fs",
                        func.__name__, i + 1, _retries, e, delay
                    )
                    time.sleep(delay)
                    delay *= 2
            return None
        return wrapper
    return decorator
