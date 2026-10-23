"""
AlphaCore · 市场宽度 (沪深300 站上 250 日均线占比) 增量面板
============================================================
2026-10-23 新增, 替代 market_temp.get_market_breadth 的逐股 pro_bar 实现.

原实现的两个问题:
  1. 慢: 每次启动对 50 只股票逐只串行调用 ts.pro_bar(qfq, 400天), 每只 ~16s,
     单项耗时 ~13.5 分钟, 是"服务完全启动要 10~20 分钟"的最大来源.
  2. 样本偏差: 只取 index_weight 返回顺序的前 50 只 (非随机, 偏向特定代码段/权重),
     且 30 天窗口内若跨调仓日会混入新旧成分股.

新实现:
  - 样本 = 最新一期沪深300 全部成分股 (无抽样偏差)
  - 价格 = 后复权 hfq = close × adj_factor (与 qfq 只差常数倍, close>MA250 判定完全等价,
    且历史值不随新除权而改变, 适合增量追加)
  - 首次: 逐股拉取 400 天 (并行, 受全局限频保护) → 一次性成本
  - 之后: 每个新交易日只需 2 次截面调用 (daily + adj_factor, trade_date=当日)
  - 面板持久化 data_lake/breadth_hfq_panel.parquet
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd

from services.logger import get_logger
from services.tushare_daily_cache import recent_trade_dates

logger = get_logger("ac.breadth")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, "data_lake")
PANEL_FILE = os.path.join(_DATA, "breadth_hfq_panel.parquet")
CONS_FILE = os.path.join(_DATA, "hs300_constituents.json")
MA_WINDOW = 250
KEEP_DAYS = 320
INCREMENTAL_MAX_GAP = 10
_WORKERS = 6


def _retry(fn, *a, tries=3, **kw):
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
            logger.debug("breadth retry %s: %s", getattr(fn, "__name__", "api"), e)


# ───────────────────────── 成分股 ─────────────────────────

def get_constituents(pro, date_str: str, max_age_days: int = 7) -> List[str]:
    try:
        with open(CONS_FILE, "r", encoding="utf-8") as f:
            c = json.load(f)
        if time.time() - c.get("fetched_ts", 0) < max_age_days * 86400 and len(c.get("codes", [])) >= 250:
            return c["codes"]
    except Exception:
        pass
    start = (datetime.strptime(date_str, "%Y%m%d") - timedelta(days=40)).strftime("%Y%m%d")
    df = _retry(pro.index_weight, index_code="399300.SZ", start_date=start, end_date=date_str)
    if df is None or df.empty:
        raise RuntimeError("沪深300成分股数据缺失")
    latest = df["trade_date"].max()
    codes = sorted(df.loc[df["trade_date"] == latest, "con_code"].unique().tolist())
    os.makedirs(_DATA, exist_ok=True)
    with open(CONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"as_of": str(latest), "codes": codes, "fetched_ts": time.time()}, f)
    return codes


# ───────────────────────── 面板读写 ─────────────────────────

def _load_panel() -> pd.DataFrame:
    try:
        p = pd.read_parquet(PANEL_FILE)
        p["trade_date"] = p["trade_date"].astype(str)
        return p
    except Exception:
        return pd.DataFrame(columns=["trade_date", "ts_code", "hfq"])


def _save_panel(p: pd.DataFrame) -> None:
    os.makedirs(_DATA, exist_ok=True)
    tmp = PANEL_FILE + ".tmp"
    p.to_parquet(tmp, index=False)
    os.replace(tmp, PANEL_FILE)


def _fetch_stock_history(pro, code: str, start: str, end: str) -> Optional[pd.DataFrame]:
    px = _retry(pro.daily, ts_code=code, start_date=start, end_date=end, fields="trade_date,close")
    af = _retry(pro.adj_factor, ts_code=code, start_date=start, end_date=end, fields="trade_date,adj_factor")
    if px is None or px.empty or af is None or af.empty:
        return None
    m = px.merge(af, on="trade_date", how="inner")
    m["hfq"] = m["close"].astype(float) * m["adj_factor"].astype(float)
    m["ts_code"] = code
    return m[["trade_date", "ts_code", "hfq"]]


def _fetch_cross_section(pro, d: str, codes: set) -> Optional[pd.DataFrame]:
    px = _retry(pro.daily, trade_date=d, fields="ts_code,close")
    af = _retry(pro.adj_factor, trade_date=d, fields="ts_code,adj_factor")
    if px is None or len(px) < 3000 or af is None or len(af) < 3000:
        return None  # 未发布或不完整 → 不写入
    m = px[px["ts_code"].isin(codes)].merge(af, on="ts_code", how="inner")
    m["hfq"] = m["close"].astype(float) * m["adj_factor"].astype(float)
    m["trade_date"] = d
    return m[["trade_date", "ts_code", "hfq"]]


# ───────────────────────── 主入口 ─────────────────────────

def compute_breadth(pro, date_str: str) -> Tuple[Optional[float], int, dict]:
    """返回 (宽度%, 有效样本数, 诊断信息). 失败返回 (None, 0, info)."""
    t0 = time.time()
    codes = get_constituents(pro, date_str)
    code_set = set(codes)
    panel = _load_panel()
    have = set(panel["ts_code"].unique()) if not panel.empty else set()

    recent = sorted(recent_trade_dates(INCREMENTAL_MAX_GAP + 5, end=date_str))
    panel_last = panel["trade_date"].max() if not panel.empty else None
    gap_dates = [d for d in recent if panel_last is None or d > panel_last]

    # 需逐股全量拉取: 新成分股 / 面板为空 / 断档过长
    full_codes = [c for c in codes if c not in have]
    if panel_last is not None and len(gap_dates) > INCREMENTAL_MAX_GAP:
        full_codes = codes
        gap_dates = []

    frames = [panel] if not panel.empty else []
    if full_codes:
        start = (datetime.strptime(date_str, "%Y%m%d") - timedelta(days=420)).strftime("%Y%m%d")
        logger.info("宽度面板: 逐股补齐 %d 只 (首次构建为一次性成本, 之后每日仅 2 次截面调用)", len(full_codes))
        with ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="breadth") as pool:
            res = list(pool.map(lambda c: _safe_hist(pro, c, start, date_str), full_codes))
        frames += [r for r in res if r is not None]
        if len(full_codes) == len(codes):
            gap_dates = []  # 全量已覆盖到 date_str, 无需截面补齐

    for d in gap_dates:
        xs = _fetch_cross_section(pro, d, code_set)
        if xs is None:
            break  # 当日尚未发布, 之后的日期也不会有
        frames.append(xs)

    if frames:
        panel = pd.concat(frames, ignore_index=True)
        panel["trade_date"] = panel["trade_date"].astype(str)
        panel = panel.drop_duplicates(["ts_code", "trade_date"], keep="last")
        keep_dates = sorted(panel["trade_date"].unique())[-KEEP_DAYS:]
        panel = panel[panel["trade_date"].isin(keep_dates)]
        if full_codes or gap_dates:
            try:
                _save_panel(panel)
            except Exception as e:  # 持久化失败不影响本次结果
                logger.warning("宽度面板保存失败: %s", e)

    sub = panel[panel["ts_code"].isin(code_set)].sort_values(["ts_code", "trade_date"])
    above = valid = 0
    for _, g in sub.groupby("ts_code"):
        s = g["hfq"].astype(float)
        if len(s) >= MA_WINDOW:
            valid += 1
            if s.iloc[-1] > s.iloc[-MA_WINDOW:].mean():
                above += 1
    info = {
        "constituents": len(codes),
        "valid": valid,
        "panel_last": sub["trade_date"].max() if not sub.empty else None,
        "full_fetched": len(full_codes),
        "seconds": round(time.time() - t0, 1),
    }
    if valid < 10:
        return None, valid, info
    return round(above / valid * 100, 1), valid, info


def _safe_hist(pro, code, start, end):
    try:
        return _fetch_stock_history(pro, code, start, end)
    except Exception as e:
        logger.warning("宽度面板: %s 拉取失败: %s", code, e)
        return None
