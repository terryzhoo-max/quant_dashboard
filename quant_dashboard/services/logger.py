"""
AlphaCore · 统一日志模块
========================
替代散落各处的 print() 调用，提供:
  - 结构化 JSON 日志 (生产环境)
  - 彩色 console 日志 (开发环境)
  - 统一的日志器命名空间 (ac.xxx)
  - @log_execution_time 装饰器

用法:
    from services.logger import get_logger
    logger = get_logger("warmup")
    logger.info("ERP 预热完成", extra={"erp": 4.5, "status": "success"})
"""

import logging
import time
import functools
import os
import json
from datetime import datetime


# ─── 日志级别: 环境变量控制 ───
LOG_LEVEL = os.getenv("AC_LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("AC_LOG_FORMAT", "console")  # "console" | "json"


class JsonFormatter(logging.Formatter):
    """生产级 JSON 日志格式 (适配 ELK/Loki)"""
    def format(self, record):
        log_entry = {
            "ts": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        # 附加 extra 字段
        for key in record.__dict__:
            if key not in logging.LogRecord(
                "", 0, "", 0, "", (), None
            ).__dict__ and key not in ("message", "asctime"):
                log_entry[key] = record.__dict__[key]
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """开发友好的彩色 console 格式"""
    COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[41m",  # red bg
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        prefix = f"{color}[{ts}] [{record.levelname[0]}] [{record.name}]{self.RESET}"
        msg = record.getMessage()
        if record.exc_info and record.exc_info[0]:
            msg += "\n" + self.formatException(record.exc_info)
        return f"{prefix} {msg}"


def _setup_handler():
    """创建统一的 StreamHandler (避免重复添加)"""
    handler = logging.StreamHandler()
    if LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())
    return handler


# 全局 handler 单例
_handler = _setup_handler()


def get_logger(name: str) -> logging.Logger:
    """获取命名日志器 (统一 ac.xxx 命名空间)

    Args:
        name: 模块简称，如 "warmup", "cache", "reactor", "erp"

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(f"ac.{name}")
    if not logger.handlers:
        logger.addHandler(_handler)
        logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        logger.propagate = False
    return logger


def log_execution_time(logger_name: str = "perf"):
    """装饰器: 记录函数执行耗时

    用法:
        @log_execution_time("erp")
        def generate_report():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(logger_name)
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = time.perf_counter() - start
                logger.info(f"{func.__name__} 完成 ({elapsed:.2f}s)")
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start
                logger.error(f"{func.__name__} 失败 ({elapsed:.2f}s): {e}")
                raise
        return wrapper
    return decorator
