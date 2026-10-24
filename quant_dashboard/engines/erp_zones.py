"""ERP 估值区间 — 时点一致 (point-in-time) 的五档划分。

与综合评分 D2 维度同一口径: 每个时点只使用其之前 ERP_WINDOW 个交易日
(含当日) 的 ERP 计算滚动分位, 杜绝全样本 μ±σ 带来的后视偏差。

五档 (按 D2 描述带):
    ≥P80 强买 | P60-80 超配 | P40-60 中性 | P20-40 低配 | <P20 危险

两端采用"相对 + 长期中枢"双重确认, 防止滚动窗口漂移造成误判:
  - 4 年窗口整体偏便宜时, 处于长期中枢附近的 ERP 也会跌破 P20 → 只降为低配, 不判危险;
  - 4 年窗口整体偏贵时, 相对 P80 也可能绝对昂贵 → 只升为超配, 不判强买。
  长期中枢 = 截至当日的扩展窗口 ERP 中位数 (同样无后视)。
危险另设绝对下限: ERP < abs_floor 无条件判危险 (对应 D1 "3% 以下偏高估"),
长期泡沫中相对分位与中枢都会下移, 绝对锚是最后一道硬约束。
判定优先级: 危险 > 低配 > 强买 > 超配 > 中性。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ZONE_KEYS = ("strong", "over", "neutral", "under", "danger")
# 全系统统一的估值区间中文标签 (首页标签 / 策略页图表 / 预警文案共用)
ZONE_LABELS = {"strong": "强买区", "over": "超配区", "neutral": "中性区", "under": "低配区", "danger": "危险区"}


def current_zone(erp: pd.Series, window: int = 1008, abs_floor: float = 3.0) -> dict:
    """最新一日的估值区间 (与图表同一算法)。历史不足时 zone=None。"""
    last = compute_erp_pit_bands(erp, window=window, abs_floor=abs_floor).iloc[-1]
    zone = last["zone"] if isinstance(last["zone"], str) else None
    return {"zone": zone, "label": ZONE_LABELS.get(zone),
            "pct": None if pd.isna(last["pct"]) else round(float(last["pct"]), 1)}


def compute_erp_pit_bands(erp: pd.Series, window: int = 1008, abs_floor: float = 3.0,
                          min_periods: int | None = None) -> pd.DataFrame:
    """返回与 erp 同索引的 DataFrame: pct, danger, under, over, strong, zone。

    pct      : 当日 ERP 在滚动窗口中的分位 (与 D2 相同: (window < v).mean()*100)
    danger   : max(P20, abs_floor)           — 低于此线 (且低于中枢) = 危险
    under    : max(P40, danger)              — 低于此线 = 低配
    over     : max(P60, under)               — 高于此线 = 超配
    strong   : max(P80, over)                — 高于此线 (且高于中枢) = 强买
    anchor   : 扩展窗口 ERP 中位数 (长期中枢)
    zone     : 五档之一; 历史不足 min_periods 时为 None (不做判定)
    full_window : 当日之前已满 window 个有效观测 (统计"历史占比"时只用这些点,
                  避免样本前段 252~1007 天的短窗口分位混入, 口径不一致)
    """
    s = pd.to_numeric(erp, errors="coerce").astype(float)
    window = int(window)
    minp = int(min_periods) if min_periods else min(window, 252)
    roll = s.rolling(window, min_periods=minp)
    p20, p40, p60, p80 = (roll.quantile(q) for q in (0.2, 0.4, 0.6, 0.8))
    pct = roll.apply(lambda w: float((w < w[-1]).mean() * 100.0), raw=True)

    danger = p20.clip(lower=abs_floor)
    under = np.maximum(p40, danger)
    over = np.maximum(p60, under)
    strong = np.maximum(p80, over)

    anchor = s.expanding(min_periods=minp).median()

    zone = pd.Series([None] * len(s), index=s.index, dtype=object)
    valid = danger.notna() & anchor.notna() & s.notna()
    zone[valid & (s >= over)] = "over"
    zone[valid & (s >= strong) & (s >= anchor)] = "strong"        # 相对便宜 + 高于长期中枢
    zone[valid & (s < over)] = "neutral"
    zone[valid & (s < under)] = "under"
    zone[valid & (((s < danger) & (s < anchor)) | (s < abs_floor))] = "danger"   # 最高优先级

    full_window = s.rolling(window, min_periods=1).count() >= window

    return pd.DataFrame({"pct": pct, "danger": danger, "under": under, "over": over,
                         "strong": strong, "anchor": anchor, "zone": zone,
                         "full_window": full_window}, index=s.index)


def zone_episodes(zones, dates, key: str, merge_gap: int = 3) -> list[dict]:
    """连续处于某一档的段落; 间隔 ≤ merge_gap 个点的短暂离开视为同一段。"""
    eps, cur, gap = [], None, 0
    for i, z in enumerate(zones):
        if z == key:
            if cur is None:
                cur = {"s": i, "e": i, "n": 0}
            cur["e"], cur["n"], gap = i, cur["n"] + 1, 0
        elif cur is not None:
            gap += 1
            if gap > merge_gap:
                eps.append(cur); cur, gap = None, 0
    if cur is not None:
        eps.append(cur)
    last = len(zones) - 1
    return [{"start": dates[e["s"]], "end": dates[e["e"]], "points": e["n"],
             "ongoing": e["e"] == last} for e in eps]
