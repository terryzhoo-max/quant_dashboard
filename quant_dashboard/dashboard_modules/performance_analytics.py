"""
AlphaCore V18.0 · 绩效分析引擎 (Phase L)
==========================================
零外部依赖 — 仅用 numpy/pandas 手写核心绩效指标。
替代 QuantStats 的 3 个核心可视化: 月度热力图 / 回撤瀑布 / 滚动 Sharpe

数据源: 沪深300 (000300.SH) 日线 via Tushare
"""

import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

from services.cache_service import cache_manager

logger = logging.getLogger("alphacore.perf_analytics")

# 缓存 key
_CACHE_KEY = "perf_analytics_300"
_CACHE_TTL = 3600 * 4  # 4 小时


def _fetch_hs300_returns(days: int = 365) -> Optional[pd.Series]:
    """从 Tushare 获取沪深300日收益率序列"""
    try:
        import tushare as ts
        pro = ts.pro_api()
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")
        df = pro.index_daily(
            ts_code="000300.SH",
            start_date=start,
            end_date=end,
            fields="trade_date,close"
        )
        if df is None or df.empty:
            logger.warning("Tushare 沪深300数据为空")
            return None
        df = df.sort_values("trade_date")
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date")
        returns = df["close"].pct_change().dropna()
        return returns.tail(days)
    except Exception as e:
        logger.warning("获取沪深300日线失败: %s", e)
        return None


def _monthly_heatmap(returns: pd.Series) -> list:
    """
    月度收益热力图数据
    返回: [[year, month, return_pct], ...]
    """
    monthly = returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    result = []
    for dt, ret in monthly.items():
        result.append([dt.year, dt.month, round(float(ret) * 100, 2)])
    return result


def _drawdown_series(returns: pd.Series) -> dict:
    """
    回撤序列
    返回: {series: [{date, drawdown}], max_dd, max_dd_duration}
    """
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max

    series = []
    for dt, dd in drawdown.items():
        series.append({
            "date": dt.strftime("%Y-%m-%d"),
            "drawdown": round(float(dd) * 100, 2)
        })

    max_dd = float(drawdown.min())

    # 计算最长回撤持续天数
    in_dd = False
    current_duration = 0
    max_duration = 0
    for dd_val in drawdown.values:
        if dd_val < -0.001:
            in_dd = True
            current_duration += 1
        else:
            if in_dd:
                max_duration = max(max_duration, current_duration)
                current_duration = 0
                in_dd = False
    max_duration = max(max_duration, current_duration)

    return {
        "series": series[-252:],  # 最近一年
        "max_drawdown": round(max_dd * 100, 2),
        "max_drawdown_duration": max_duration,
    }


def _rolling_sharpe(returns: pd.Series, window: int = 60) -> list:
    """
    滚动 Sharpe (年化, 无风险利率 2.5%)
    返回: [{date, sharpe}, ...]
    """
    rf_daily = 0.025 / 252
    excess = returns - rf_daily
    rolling_mean = excess.rolling(window).mean()
    rolling_std = excess.rolling(window).std()
    sharpe = (rolling_mean / rolling_std * np.sqrt(252)).dropna()

    result = []
    for dt, val in sharpe.items():
        if np.isfinite(val):
            result.append({
                "date": dt.strftime("%Y-%m-%d"),
                "sharpe": round(float(val), 2)
            })
    return result


def _basic_metrics(returns: pd.Series) -> dict:
    """基本绩效指标"""
    rf_daily = 0.025 / 252

    total_return = float((1 + returns).prod() - 1)
    n_years = len(returns) / 252
    annual_return = float((1 + total_return) ** (1 / max(n_years, 0.01)) - 1) if n_years > 0 else 0
    annual_vol = float(returns.std() * np.sqrt(252))

    # Sharpe
    excess = returns - rf_daily
    sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0

    # Sortino (仅下行波动率)
    downside = returns[returns < 0]
    downside_std = float(downside.std() * np.sqrt(252)) if len(downside) > 10 else annual_vol
    sortino = float((annual_return - 0.025) / downside_std) if downside_std > 0 else 0

    # Calmar (年化收益 / 最大回撤)
    cum = (1 + returns).cumprod()
    max_dd = float(((cum - cum.cummax()) / cum.cummax()).min())
    calmar = float(annual_return / abs(max_dd)) if abs(max_dd) > 0.001 else 0

    return {
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "annual_volatility": round(annual_vol * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
        "trading_days": len(returns),
    }


def compute_performance_analytics() -> dict:
    """
    主入口: 计算绩效分析数据
    先检查缓存, 缓存未命中时从 Tushare 获取数据并计算
    """
    # 尝试缓存
    cached = cache_manager.get_json(_CACHE_KEY)
    if cached:
        return cached

    returns = _fetch_hs300_returns(days=500)  # ~2 年
    if returns is None or len(returns) < 60:
        return {
            "error": "数据不足",
            "monthly_heatmap": [],
            "drawdown": {"series": [], "max_drawdown": 0, "max_drawdown_duration": 0},
            "rolling_sharpe": [],
            "metrics": {},
        }

    result = {
        "benchmark": "沪深300 (000300.SH)",
        "monthly_heatmap": _monthly_heatmap(returns),
        "drawdown": _drawdown_series(returns),
        "rolling_sharpe": _rolling_sharpe(returns, window=60),
        "metrics": _basic_metrics(returns),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # 写入缓存
    cache_manager.set_json(_CACHE_KEY, result, ttl_seconds=_CACHE_TTL)
    return result
