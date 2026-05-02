"""
AlphaCore V18.1 · 绩效分析引擎 (Phase L — 多基准)
====================================================
零外部依赖 — 仅用 numpy/pandas 手写核心绩效指标。
替代 QuantStats 的 3 个核心可视化: 月度热力图 / 回撤瀑布 / 滚动 Sharpe

数据源: 沪深300 / 科创50 / 创业板50 日线 via Tushare
"""

import logging
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

from services.cache_service import cache_manager

logger = logging.getLogger("alphacore.perf_analytics")

# 缓存 key
_CACHE_KEY = "perf_analytics_7bm"  # V19.2: 7 benchmarks (换 key 清旧缓存)
_CACHE_TTL = 3600 * 4  # 4 小时

# ── 多基准配置 (V19.2: 扩展至7标的, 与波段守卫一致) ──
BENCHMARKS = [
    {"key": "hs300",  "ts_code": "000300.SH", "name": "沪深300",    "api": "index"},
    {"key": "kc50",   "ts_code": "000688.SH", "name": "科创50",     "api": "index"},
    {"key": "cy50",   "ts_code": "399673.SZ", "name": "创业板50",   "api": "index"},
    {"key": "sp500",  "ts_code": "513500.SH", "name": "标普500ETF",  "api": "fund"},
    {"key": "nasdaq", "ts_code": "513100.SH", "name": "纳指100ETF",  "api": "fund"},
    {"key": "nikkei", "ts_code": "513520.SH", "name": "日经225ETF",  "api": "fund"},
    {"key": "hstech", "ts_code": "513180.SH", "name": "恒生科技ETF", "api": "fund"},
]


def _fetch_index_returns(ts_code: str, days: int = 500, api: str = "index") -> Optional[pd.Series]:
    """从 Tushare 获取指数/基金日收益率序列 (V19.2: 支持 index_daily + fund_daily)"""
    try:
        import tushare as ts
        pro = ts.pro_api()
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")
        if api == "fund":
            df = pro.fund_daily(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
            )
        else:
            df = pro.index_daily(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
                fields="trade_date,close"
            )
        if df is None or df.empty:
            logger.warning("Tushare %s (%s) 数据为空", ts_code, api)
            return None
        df = df.sort_values("trade_date")
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date")
        returns = df["close"].pct_change().dropna()
        return returns.tail(days)
    except Exception as e:
        logger.warning("获取 %s (%s) 日线失败: %s", ts_code, api, e)
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


def _compute_single_benchmark(bm: dict) -> tuple:
    """计算单个基准的完整绩效数据, 供线程池并行调用"""
    key = bm["key"]
    returns = _fetch_index_returns(bm["ts_code"], days=500, api=bm.get("api", "index"))
    if returns is None or len(returns) < 60:
        logger.warning("[PerfAnalytics] %s (%s) 数据不足, 跳过", bm["name"], bm["ts_code"])
        return key, None

    data = {
        "name": bm["name"],
        "ts_code": bm["ts_code"],
        "metrics": _basic_metrics(returns),
        "monthly_heatmap": _monthly_heatmap(returns),
        "drawdown": _drawdown_series(returns),
        "rolling_sharpe": _rolling_sharpe(returns, window=60),
    }
    logger.info("[PerfAnalytics] %s 计算完成: 年化%.1f%% Sharpe=%.2f",
                bm["name"], data["metrics"]["annual_return"], data["metrics"]["sharpe_ratio"])
    return key, data


def compute_performance_analytics() -> dict:
    """
    主入口: 计算多基准绩效分析数据
    先检查缓存, 缓存未命中时从 Tushare 并行获取数据并计算
    """
    # 尝试缓存 (只接受有 benchmarks 数据的缓存)
    cached = cache_manager.get_json(_CACHE_KEY)
    if cached and cached.get("benchmarks"):
        return cached

    # 顺序获取 7 个基准 (Tushare 有限流, 并行会被拒绝)
    benchmarks = {}
    for i, bm in enumerate(BENCHMARKS):
        if i > 0:
            time.sleep(0.35)  # Tushare 限流间隔 (7标的需更保守)
        key, data = _compute_single_benchmark(bm)
        if data is not None:
            benchmarks[key] = data

    # 向后兼容: 顶层字段取 hs300 的数据
    hs300 = benchmarks.get("hs300", {})

    result = {
        "benchmarks": benchmarks,
        "default": "hs300",
        # 向后兼容字段 (沪深300)
        "benchmark": "沪深300 (000300.SH)",
        "metrics": hs300.get("metrics", {}),
        "monthly_heatmap": hs300.get("monthly_heatmap", []),
        "drawdown": hs300.get("drawdown", {"series": [], "max_drawdown": 0, "max_drawdown_duration": 0}),
        "rolling_sharpe": hs300.get("rolling_sharpe", []),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # 只有 benchmarks 非空时才缓存 (防止失败结果污染缓存)
    if benchmarks:
        cache_manager.set_json(_CACHE_KEY, result, ttl_seconds=_CACHE_TTL)
    return result

