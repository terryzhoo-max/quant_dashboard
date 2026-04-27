"""
AlphaCore · Finnhub 统一数据客户端
===================================
替代 yfinance 的美股 ETF 实时报价层。

覆盖范围 (Finnhub free tier):
  ✅ 美股个股/ETF 实时报价 (/quote)
  ✅ 美股个股基本面指标 (/stock/metric)  — 注意: ETF 无 PE
  ❌ 指数 (^VIX, ^N225, ^HSI) → 由 FRED / CNBC 覆盖
  ❌ 外汇 (USDCNY) → 由 FRED / CNBC 覆盖
  ❌ 亚洲市场 (1306.T, 2800.HK) → 由 FRED / CNBC 覆盖

API 限制: 60次/分钟 (free tier)
"""

import requests
import time
import threading
from typing import Optional, Dict
from datetime import datetime

from config import FINNHUB_API_KEY
from services.logger import get_logger

logger = get_logger("finnhub")
FINNHUB_BASE = "https://finnhub.io/api/v1"

# ===== 简易速率限制器 (60 req/min) =====
_fh_lock = threading.Lock()
_fh_timestamps: list = []
_FH_RATE_LIMIT = 55  # 留 5 次余量

def _rate_limit():
    """简易滑动窗口限流"""
    with _fh_lock:
        now = time.time()
        _fh_timestamps[:] = [t for t in _fh_timestamps if now - t < 60]
        if len(_fh_timestamps) >= _FH_RATE_LIMIT:
            sleep_time = 60 - (now - _fh_timestamps[0]) + 0.1
            if sleep_time > 0:
                time.sleep(sleep_time)
        _fh_timestamps.append(time.time())


def _log(msg: str, level: str = "INFO"):
    if level == "WARN":
        logger.warning(msg)
    elif level == "ERROR":
        logger.error(msg)
    else:
        logger.info(msg)


# ===== 报价接口 =====

def get_quote(symbol: str) -> Optional[Dict]:
    """
    获取美股实时报价。
    返回: {c: 当前价, d: 涨跌, dp: 涨跌%, h: 最高, l: 最低, o: 开盘, pc: 昨收, t: 时间戳}
    仅支持: 美股个股/ETF (SPY, QQQ, SCHD, AAPL 等)
    不支持: 指数(^VIX), 外汇(USDCNY), 亚洲(1306.T, 2800.HK)
    """
    try:
        _rate_limit()
        r = requests.get(
            f"{FINNHUB_BASE}/quote",
            params={"symbol": symbol, "token": FINNHUB_API_KEY},
            timeout=8
        )
        r.raise_for_status()
        data = r.json()
        if data.get("c", 0) > 0:
            _log(f"Quote {symbol}: ${data['c']:.2f} (d={data.get('d',0):+.2f})")
            return data
        _log(f"Quote {symbol}: 无数据 (可能不支持)", "WARN")
        return None
    except Exception as e:
        _log(f"Quote {symbol} 失败: {e}", "WARN")
        return None


def get_price(symbol: str) -> Optional[float]:
    """获取最新价格 (简化接口)"""
    q = get_quote(symbol)
    return q["c"] if q else None


def get_basic_financials(symbol: str) -> Optional[Dict]:
    """
    获取基本面指标 (PE, EPS, 市值等)。
    仅支持个股 (AAPL, MSFT 等)。ETF (SPY) 无 PE 数据。
    返回 metric 字典，常用字段:
      peNormalizedAnnual, peTTM, peBasicExclExtraTTM, epsAnnual, epsTTM,
      marketCapitalization, dividendYieldIndicatedAnnual
    """
    try:
        _rate_limit()
        r = requests.get(
            f"{FINNHUB_BASE}/stock/metric",
            params={"symbol": symbol, "metric": "all", "token": FINNHUB_API_KEY},
            timeout=8
        )
        r.raise_for_status()
        data = r.json()
        metric = data.get("metric", {})
        if metric:
            pe = metric.get("peNormalizedAnnual") or metric.get("peTTM")
            _log(f"Metric {symbol}: PE={pe}")
            return metric
        _log(f"Metric {symbol}: 无数据", "WARN")
        return None
    except Exception as e:
        _log(f"Metric {symbol} 失败: {e}", "WARN")
        return None


def get_pe(symbol: str) -> Optional[float]:
    """获取 PE (TTM, 仅个股有效)"""
    m = get_basic_financials(symbol)
    if m:
        return m.get("peNormalizedAnnual") or m.get("peTTM") or m.get("peBasicExclExtraTTM")
    return None


# ===== 自检 =====
if __name__ == "__main__":
    print("=== Finnhub Client Self-Test ===")
    # US ETF quote
    q = get_quote("SPY")
    print(f"SPY quote: {q}")
    # US stock PE
    pe = get_pe("AAPL")
    print(f"AAPL PE: {pe}")
    # Non-supported (should return None)
    q2 = get_quote("^VIX")
    print(f"^VIX quote (expect None): {q2}")
