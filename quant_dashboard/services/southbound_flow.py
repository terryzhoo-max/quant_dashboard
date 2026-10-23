"""
AlphaCore · 南向资金统一数据源 (Single Source of Truth)
=======================================================
2026-10-23 修复: erp_hk_engine 与 aiae_hk_engine 各自解析 Tushare moneyflow_hsgt,
单位假设互相矛盾 (一个当"亿元", 一个当"百万元" 再 /100), 导致同一天
周净买入分别为 -206.1亿 与 -2.1亿 (相差 100 倍), 12M 累计窗口也不同 (60天 vs 1年)。

本模块统一:
  1. 语义自检: south_money 是 "累计净买入余额" 还是 "当日净买入"
     - 累计序列: 日间变化远小于水平值 (|diff| 中位数 < 水平值 5%) → 先 diff
     - 当日序列: 直接使用
  2. 单位自检: 累计南向净买入(2014至今)量级约 4~7 万亿元
     - 水平值中位数 > 1e6 → 单位为百万元, ÷100 → 亿元
     - 否则单位已是亿元
  3. 窗口统一: 周=最近5个交易日, 月=最近20个, 12M=最近 ~245 个交易日
  4. 输出统一: 亿元 RMB, date=YYYY-MM-DD
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd

from services.logger import get_logger

logger = get_logger("southbound")

TRADING_DAYS_12M = 245


def normalize_southbound_series(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """把 moneyflow_hsgt 原始 DataFrame 转为每日净买入 (亿元) 序列.

    返回列: trade_date, daily_net_yi ; 附带 attrs: semantics, unit_scale
    """
    if df is None or df.empty or "south_money" not in df.columns:
        return None
    df = df.copy()
    df["south_money"] = pd.to_numeric(df["south_money"], errors="coerce")
    df = df.dropna(subset=["south_money"]).sort_values("trade_date").reset_index(drop=True)
    if len(df) < 3:
        return None

    level = float(df["south_money"].abs().median())
    step = float(df["south_money"].diff().abs().median())
    cumulative = level > 0 and step < 0.05 * level

    # 单位: 累计值 > 1e6 必为百万元 (否则意味着 >100 万亿元, 不可能)
    # 当日值: 单日南向极少超过 500 亿元, > 5e3 视为百万元
    if cumulative:
        unit_scale = 0.01 if level > 1e6 else 1.0
    else:
        unit_scale = 0.01 if level > 5e3 else 1.0

    if cumulative:
        daily = df["south_money"].diff() * unit_scale
    else:
        daily = df["south_money"] * unit_scale

    out = pd.DataFrame({"trade_date": df["trade_date"].astype(str), "daily_net_yi": daily})
    out = out.dropna(subset=["daily_net_yi"]).reset_index(drop=True)
    out.attrs["semantics"] = "cumulative" if cumulative else "daily"
    out.attrs["unit_scale"] = unit_scale
    return out


def summarize_southbound(daily: pd.DataFrame) -> Optional[Dict]:
    if daily is None or daily.empty:
        return None
    weekly = float(daily.tail(5)["daily_net_yi"].sum())
    monthly = float(daily.tail(20)["daily_net_yi"].sum())
    cum_12m = float(daily.tail(TRADING_DAYS_12M)["daily_net_yi"].sum())
    d = str(daily["trade_date"].iloc[-1])
    date_iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else d
    return {
        "weekly_net_buy_billion_rmb": round(weekly, 1),
        "monthly_net_buy_billion_rmb": round(monthly, 1),
        "cumulative_12m_billion_rmb": round(cum_12m, 1),
        "direction": "inflow" if weekly > 0 else "outflow",
        "date": date_iso,
        "source": "tushare_auto",
        "unit": "亿元RMB",
        "raw_semantics": daily.attrs.get("semantics"),
        "raw_unit_scale": daily.attrs.get("unit_scale"),
        "data_points": int(len(daily)),
        "window_12m_days": int(min(len(daily), TRADING_DAYS_12M)),
    }


def fetch_southbound_flow(pro=None) -> Optional[Dict]:
    """拉取并汇总南向资金. 失败返回 None (由调用方走缓存/默认值)."""
    try:
        if pro is None:
            import tushare as ts
            try:
                from config import TUSHARE_TOKEN
                ts.set_token(TUSHARE_TOKEN)
            except Exception:
                pass
            pro = ts.pro_api()
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=380)).strftime("%Y%m%d")
        df = pro.moneyflow_hsgt(start_date=start, end_date=end)
        daily = normalize_southbound_series(df)
        result = summarize_southbound(daily)
        if result:
            logger.info(
                "南向资金(统一源): 周=%+.1f亿 月=%+.1f亿 12M=%+.1f亿 (%s, raw=%s×%s)",
                result["weekly_net_buy_billion_rmb"], result["monthly_net_buy_billion_rmb"],
                result["cumulative_12m_billion_rmb"], result["date"],
                result["raw_semantics"], result["raw_unit_scale"],
            )
        return result
    except Exception as e:
        logger.warning("南向资金统一源拉取失败: %s", e)
        return None
