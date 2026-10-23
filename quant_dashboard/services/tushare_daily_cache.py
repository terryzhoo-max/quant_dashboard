"""
AlphaCore · Tushare 日频截面聚合缓存
=====================================
2026-10-23 新增 (启动提速 + 口径统一)

问题: 每次启动都要重新拉取 20+ 个交易日的全市场 daily_basic (每次 5000+ 行,
本机到 Tushare 单次约 10s), 以及逐日 margin, 且按"自然日"循环会把周末/节假日
也请求一遍. HF_PROXY 单项就耗时 ~4 分钟, 市场温度又重复拉一次 daily_basic。

做法:
  1. 交易日历: 读 data_lake/trading_calendar.json (仅含交易日), 不再请求非交易日
  2. 按日持久化聚合值: 历史交易日的数据发布后不再变化, 拉一次永久复用
     (只缓存"有数据"的日子; 当日未发布时返回空, 不写缓存, 下次再试)
  3. 缺失日期并行补齐 (受全局 tushare_limiter 限频保护)

缓存文件: data_lake/xs_daily_aggregates.json
  {"turnover": {"20261023": {"turnover_rate": 2.57, "turnover_rate_f": 4.19, "n": 5380}},
   "margin":   {"20261022": {"rzye_yi": 24269.1}}}
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from services.logger import get_logger

logger = get_logger("ac.xs_cache")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, "data_lake")
_CACHE_FILE = os.path.join(_DATA, "xs_daily_aggregates.json")
_CAL_FILE = os.path.join(_DATA, "trading_calendar.json")
_lock = threading.RLock()
_MAX_WORKERS = 4


# ───────────────────────── 交易日历 ─────────────────────────

def recent_trade_dates(n: int, end: Optional[str] = None) -> List[str]:
    """返回 <= end (默认今天) 的最近 n 个交易日, 新→旧 (YYYYMMDD)."""
    end = end or datetime.now().strftime("%Y%m%d")
    dates: List[str] = []
    try:
        with open(_CAL_FILE, "r", encoding="utf-8") as f:
            cal = sorted({str(d) for d in json.load(f)}, reverse=True)
        dates = [d for d in cal if d <= end][:n]
    except Exception:
        dates = []
    if len(dates) < n:  # 日历缺失/过期 → 退化为工作日 (仍跳过周末)
        dt = datetime.strptime(end, "%Y%m%d")
        dates = []
        while len(dates) < n:
            if dt.weekday() < 5:
                dates.append(dt.strftime("%Y%m%d"))
            dt -= timedelta(days=1)
    return dates


# ───────────────────────── 持久化 ─────────────────────────

def _load() -> Dict[str, Dict[str, dict]]:
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(data: Dict[str, Dict[str, dict]]) -> None:
    os.makedirs(_DATA, exist_ok=True)
    tmp = _CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, _CACHE_FILE)


def _get_series(kind: str, dates: List[str], fetch_one: Callable[[str], Optional[dict]]) -> Dict[str, dict]:
    """通用: 读缓存 → 并行补齐缺失日期 → 回写. 返回 {date: record} (只含有数据的日期)."""
    with _lock:
        store = _load()
        bucket = store.setdefault(kind, {})
        missing = [d for d in dates if d not in bucket]
    if missing:
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(missing)), thread_name_prefix=f"xs-{kind}") as pool:
            results = list(pool.map(lambda d: (d, _safe(fetch_one, d)), missing))
        fetched = {d: r for d, r in results if r}
        if fetched:
            with _lock:
                store = _load()
                store.setdefault(kind, {}).update(fetched)
                # 只保留最近 400 个交易日, 防止无限增长
                keep = sorted(store[kind])[-400:]
                store[kind] = {k: store[kind][k] for k in keep}
                _save(store)
                bucket = store[kind]
        logger.info("截面缓存[%s]: 命中 %d/%d, 新拉取 %d 天 (其中有数据 %d 天)",
                    kind, len(dates) - len(missing), len(dates), len(missing), len(fetched))
    return {d: bucket[d] for d in dates if d in bucket}


def _safe(fn, d):
    try:
        return fn(d)
    except Exception as e:
        logger.warning("截面拉取失败 %s: %s", d, e)
        return None


# ───────────────────────── 具体指标 ─────────────────────────

def get_turnover_medians(pro, dates: List[str]) -> Dict[str, dict]:
    """全市场换手率中位数 (turnover_rate 与 turnover_rate_f 一次取齐, 两个模块共用)."""
    def _one(d):
        df = pro.daily_basic(trade_date=d, fields="ts_code,turnover_rate,turnover_rate_f")
        # 防部分发布: 全市场应 >4000 只, 不足视为未发布完, 不缓存
        if df is None or len(df) < 4000:
            return None
        return {
            "turnover_rate": float(df["turnover_rate"].dropna().median()),
            "turnover_rate_f": float(df["turnover_rate_f"].dropna().median()),
            "n": int(len(df)),
        }
    return _get_series("turnover", dates, _one)


def get_margin_totals(pro, dates: List[str]) -> Dict[str, dict]:
    """沪深融资余额合计 (亿元)."""
    def _one(d):
        df = pro.margin(trade_date=d)
        if df is None or df.empty or "rzye" not in df.columns:
            return None
        # 防部分发布: 需同时包含沪、深两市, 否则当日合计偏小且会被永久缓存
        if "exchange_id" in df.columns and not {"SSE", "SZSE"} <= set(df["exchange_id"]):
            return None
        return {"rzye_yi": float(df["rzye"].sum()) / 1e8}
    return _get_series("margin", dates, _one)
