"""
AlphaCore · 跨市场风险传染矩阵 (Contagion Matrix)
===================================================
从 decision_engine.py 拆分: 四大市场 120 日收益率相关性

O1 Refactor: 独立子模块
"""

import os
import numpy as np
import pandas as pd
from services.logger import get_logger

logger = get_logger("ac.decision.contagion")


# 四大市场索引: parquet 文件 → 标签
_CONTAGION_INDICES = [
    {"key": "cn", "ts_code": "510300.SH", "label": "A股", "flag": "🇨🇳",
     "file": "data_lake/daily_prices/510300.SH.parquet"},
    {"key": "us", "ts_code": "513500.SH", "label": "美股", "flag": "🇺🇸",
     "file": "data_lake/daily_prices/513500.SH.parquet"},
    {"key": "hk", "ts_code": "HSI", "label": "港股", "flag": "🇭🇰",
     "file": "data_lake/erp_hk_hsi_history.parquet", "col": "close"},
    {"key": "jp", "ts_code": "N225", "label": "日股", "flag": "🇯🇵",
     "file": "data_lake/erp_jp_nikkei.parquet", "col": "close"},
    # 数据源确认:
    #   CN: 沪深300ETF (Tushare → daily_prices/510300.SH.parquet)
    #   US: 标普500ETF (Tushare → daily_prices/513500.SH.parquet)
    #   HK: 恒生指数 (erp_hk_engine._fetch_hsi_history → erp_hk_hsi_history.parquet, col=close)
    #   JP: 日经225  (erp_jp_engine._fetch_nikkei_history → erp_jp_nikkei.parquet, col=close)
    # 均为引擎原生缓存, 零新增 API 调用.
]


def compute_contagion_matrix(window_days: int = 120) -> dict:
    """
    计算四大市场日收益率 Pearson 相关性矩阵。

    数据源: data_lake/daily_prices/ 中的 parquet 文件 (零 API 调用)
    方法:
      1. 读取四个 ETF 的日线收盘价
      2. 计算日收益率 (close.pct_change)
      3. 对齐交易日 (取四市场交集)
      4. 计算 {window_days} 日滚动 Pearson 矩阵
      5. 返回矩阵 + 传染力解读

    返回:
    {
        "markets": [{key, label, flag}],
        "correlation_matrix": [[1.0, 0.35, 0.62, 0.28], ...],
        "window_days": 120,
        "common_days": 245,
        "contagion_risk": "medium"/"high"/"low",
        "contagion_note": str,
        "high_pairs": [{a, b, corr, level}],
    }
    """

    # ── 1. 读取 ETF/指数日线 ──
    returns = {}
    for idx in _CONTAGION_INDICES:
        fpath = idx["file"]
        if not os.path.exists(fpath):
            continue
        try:
            df = pd.read_parquet(fpath)
            if df.empty:
                continue

            # 确定价格列名 (默认 "close", 可覆盖为 "index_value" 等)
            price_col = idx.get("col", "close")
            if price_col not in df.columns:
                continue

            # 确保有日期列
            if "trade_date" in df.columns:
                df["trade_date"] = pd.to_datetime(df["trade_date"])
                df = df.set_index("trade_date")
            elif df.index.name != "trade_date" and not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            # 日收益率
            r = df[price_col].pct_change().dropna()
            # 过滤异常值 (>50% 单日波动)
            r = r[(r > -0.5) & (r < 0.5)]
            if len(r) >= 30:
                returns[idx["key"]] = r
        except Exception as e:
            logger.debug("传染矩阵: 读取 %s 失败: %s", fpath, e)

    if len(returns) < 2:
        return {
            "status": "insufficient_data",
            "markets": [],
            "correlation_matrix": [],
            "window_days": window_days,
            "common_days": 0,
            "contagion_risk": "unknown",
            "contagion_note": "数据不足，需至少两个市场的日线数据",
            "high_pairs": [],
        }

    # ── 2. 对齐日期 ──
    ret_df = pd.DataFrame(returns)
    ret_df = ret_df.dropna()  # 仅保留所有市场都有数据的交易日
    common_days = len(ret_df)
    if common_days < window_days:
        # 数据不够窗口大小, 用全部数据
        effective_window = common_days
    else:
        effective_window = window_days

    # 取最近 effective_window 天
    ret_tail = ret_df.tail(effective_window)

    # ── 3. 计算 Pearson 相关性 ──
    corr_matrix_raw = ret_tail.corr().values
    market_keys = list(ret_df.columns)
    market_count = len(market_keys)

    # 构建输出矩阵 (按原始 _CONTAGION_INDICES 顺序)
    ordered_keys = [idx["key"] for idx in _CONTAGION_INDICES if idx["key"] in market_keys]
    corr_map = {}
    for i, ki in enumerate(market_keys):
        for j, kj in enumerate(market_keys):
            corr_map[(ki, kj)] = round(float(corr_matrix_raw[i][j]), 3)

    matrix = []
    for ki in ordered_keys:
        row = []
        for kj in ordered_keys:
            row.append(corr_map.get((ki, kj), 0.0))
        matrix.append(row)

    # ── 4. 高相关对检测 (|ρ| > 0.5) ──
    high_pairs = []
    for i, ki in enumerate(ordered_keys):
        for j, kj in enumerate(ordered_keys):
            if i >= j:
                continue
            corr = corr_map.get((ki, kj), 0)
            if abs(corr) > 0.5:
                level = "extreme" if abs(corr) > 0.8 else ("high" if abs(corr) > 0.65 else "moderate")
                label_i = next((idx["label"] for idx in _CONTAGION_INDICES if idx["key"] == ki), ki)
                label_j = next((idx["label"] for idx in _CONTAGION_INDICES if idx["key"] == kj), kj)
                high_pairs.append({
                    "a": label_i, "b": label_j,
                    "corr": corr,
                    "level": level,
                    "direction": "同涨同跌" if corr > 0 else "对冲",
                })

    # ── 5. 传染风险评估 ──
    avg_corr = np.mean([abs(corr) for (ki, kj), corr in corr_map.items() if ki != kj]) if len(corr_map) > 1 else 0
    if avg_corr > 0.7:
        contagion_risk = "high"
        contagion_note = f"🔴 市场高度联动 (平均 |ρ|={avg_corr:.2f})，单一风险事件可能引发跨市场共振。建议降低单一市场集中度。"
    elif avg_corr > 0.4:
        contagion_risk = "medium"
        contagion_note = f"🟡 市场温和联动 (平均 |ρ|={avg_corr:.2f})，存在区域性分散价值。选择低相关市场可有效降低组合波动。"
    else:
        contagion_risk = "low"
        contagion_note = f"🟢 市场相对独立 (平均 |ρ|={avg_corr:.2f})，全球分散化效果显著。当前是跨市场配置的理想窗口。"

    # ── 6. 市场信息 ──
    markets_info = []
    for idx in _CONTAGION_INDICES:
        if idx["key"] in ordered_keys:
            markets_info.append({
                "key": idx["key"],
                "label": idx["label"],
                "flag": idx["flag"],
                "ts_code": idx["ts_code"],
            })

    return {
        "markets": markets_info,
        "correlation_matrix": matrix,
        "window_days": effective_window,
        "common_days": common_days,
        "contagion_risk": contagion_risk,
        "contagion_note": contagion_note,
        "high_pairs": high_pairs,
    }
