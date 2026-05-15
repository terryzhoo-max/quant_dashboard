"""
AlphaCore P3-B · 黄金信号引擎 V1.0
=====================================
基于 FRED 数据的黄金择时三维信号系统:

  D1: 实际利率 (TIPS 10Y) — 权重 40%
      实际利率 ↓ → 黄金 ↑ (持有成本下降)
  D2: 美元指数代理 (DXY via FRED Trade Weighted USD) — 权重 30%
      美元走弱 → 黄金 ↑
  D3: 通胀预期 (10Y Breakeven = DGS10 - DFII10) — 权重 30%
      通胀预期 ↑ → 黄金 ↑ (对冲需求)

输出:
  - gold_signal: 综合信号 [-100, 100], 正值看多黄金
  - gold_direction: "bullish" / "neutral" / "bearish"
  - components: 三维子信号明细
  - suggested_allocation: 黄金建议配比 (0-15%)

数据源: FRED API (DFII10 / DTWEXBGS / DGS10)
"""

import numpy as np
import pandas as pd
import os
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict

from services.logger import get_logger

logger = get_logger("ac.gold_signal")

# FRED API
try:
    from config import FRED_API_KEY
except ImportError:
    FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

# ── FRED 初始化 (复用 rates_strategy_engine 模式) ──
_fred_instance = None
_fred_lock = threading.Lock()

def _get_fred():
    global _fred_instance
    if _fred_instance is None:
        with _fred_lock:
            if _fred_instance is None:
                try:
                    from fredapi import Fred
                    _fred_instance = Fred(api_key=FRED_API_KEY)
                except Exception as e:
                    logger.warning("FRED init failed: %s", e)
    return _fred_instance


# ═══════════════════════════════════════════════════
#  FRED 数据获取 (带磁盘缓存兜底)
# ═══════════════════════════════════════════════════

_gold_cache = {}
_gold_cache_lock = threading.Lock()


def _fetch_fred_series(series_id: str, lookback_days: int = 365) -> Optional[pd.Series]:
    """获取 FRED 数据序列, 带内存 + 磁盘双层缓存"""
    now = time.time()
    cache_key = f"gold_{series_id}"
    
    with _gold_cache_lock:
        if cache_key in _gold_cache:
            ts, data = _gold_cache[cache_key]
            if now - ts < 4 * 3600:  # 4h 有效期
                return data
    
    fred = _get_fred()
    data = None
    
    if fred:
        try:
            start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
            data = fred.get_series(series_id, observation_start=start)
            data = data.dropna()
            
            # 写入磁盘缓存
            cache_path = os.path.join(CACHE_DIR, f"{cache_key}.json")
            data.to_json(cache_path, date_format="iso")
            logger.debug("FRED %s: %d 条数据已缓存", series_id, len(data))
        except Exception as e:
            logger.warning("FRED %s 获取失败: %s", series_id, e)
    
    # 兜底: 磁盘缓存
    if data is None:
        cache_path = os.path.join(CACHE_DIR, f"{cache_key}.json")
        if os.path.exists(cache_path):
            try:
                data = pd.read_json(cache_path, typ="series")
                logger.info("FRED %s: 使用磁盘缓存 (%d 条)", series_id, len(data))
            except Exception:
                pass
    
    if data is not None and len(data) > 0:
        with _gold_cache_lock:
            _gold_cache[cache_key] = (now, data)
    
    return data


# ═══════════════════════════════════════════════════
#  三维信号计算
# ═══════════════════════════════════════════════════

def _real_rate_signal(dfii10: pd.Series) -> Dict:
    """
    D1: 实际利率信号
    逻辑: 实际利率越低, 黄金越有吸引力
    映射: [-2, 2] → [100, -100] (线性插值)
    """
    if dfii10 is None or len(dfii10) < 5:
        return {"score": 0, "label": "数据不足", "value": None, "ma20": None}
    
    current = float(dfii10.iloc[-1])
    ma20 = float(dfii10.tail(20).mean()) if len(dfii10) >= 20 else current
    
    # 实际利率 → 信号: 负利率=看多黄金, 正利率=看空
    # 映射: -2% → +100, 0% → 0, +2% → -100
    score = np.clip(-current / 2.0 * 100, -100, 100)
    
    # 趋势加成: 实际利率下降趋势 → 额外加分
    if len(dfii10) >= 20:
        trend = current - ma20
        trend_bonus = np.clip(-trend / 0.5 * 20, -20, 20)
        score = np.clip(score + trend_bonus, -100, 100)
    
    if score > 30:
        label = "实际利率偏低, 利好黄金"
    elif score < -30:
        label = "实际利率偏高, 利空黄金"
    else:
        label = "实际利率中性"
    
    return {
        "score": round(float(score), 1),
        "label": label,
        "value": round(current, 3),
        "ma20": round(ma20, 3),
    }


def _dollar_signal(dtwex: pd.Series) -> Dict:
    """
    D2: 美元强弱信号
    逻辑: 美元走弱 → 黄金走强 (负相关)
    使用 20 日动量: 当前 vs 20 日前
    """
    if dtwex is None or len(dtwex) < 25:
        return {"score": 0, "label": "数据不足", "value": None, "change_20d": None}
    
    current = float(dtwex.iloc[-1])
    prev_20d = float(dtwex.iloc[-21]) if len(dtwex) >= 21 else current
    
    change_pct = (current - prev_20d) / prev_20d * 100 if prev_20d > 0 else 0
    
    # 美元走弱(change<0) → 看多黄金(score>0)
    score = np.clip(-change_pct / 3.0 * 100, -100, 100)
    
    if score > 30:
        label = "美元走弱, 利好黄金"
    elif score < -30:
        label = "美元走强, 利空黄金"
    else:
        label = "美元中性"
    
    return {
        "score": round(float(score), 1),
        "label": label,
        "value": round(current, 2),
        "change_20d": round(change_pct, 2),
    }


def _inflation_signal(dgs10: pd.Series, dfii10: pd.Series) -> Dict:
    """
    D3: 通胀预期信号
    逻辑: Breakeven = 名义利率 - 实际利率 = 隐含通胀预期
    通胀预期 ↑ → 黄金对冲需求 ↑
    """
    if dgs10 is None or dfii10 is None:
        return {"score": 0, "label": "数据不足", "breakeven": None, "ma20": None}
    
    # 对齐日期 (使用 inner join 对齐)
    combined = pd.DataFrame({"dgs10": dgs10, "dfii10": dfii10}).dropna()
    if len(combined) < 10:
        return {"score": 0, "label": "数据不足", "breakeven": None, "ma20": None}
    
    breakeven = combined["dgs10"] - combined["dfii10"]
    current_be = float(breakeven.iloc[-1])
    ma20_be = float(breakeven.tail(20).mean()) if len(breakeven) >= 20 else current_be
    
    # 通胀预期映射: 2.0% → 0, >3.0% → +100, <1.0% → -100
    score = np.clip((current_be - 2.0) / 1.0 * 100, -100, 100)
    
    # 趋势加成
    if len(breakeven) >= 20:
        trend = current_be - ma20_be
        trend_bonus = np.clip(trend / 0.3 * 20, -20, 20)
        score = np.clip(score + trend_bonus, -100, 100)
    
    if score > 30:
        label = "通胀预期升温, 利好黄金"
    elif score < -30:
        label = "通胀预期降温, 利空黄金"
    else:
        label = "通胀预期中性"
    
    return {
        "score": round(float(score), 1),
        "label": label,
        "breakeven": round(current_be, 3),
        "ma20": round(ma20_be, 3),
    }


# ═══════════════════════════════════════════════════
#  综合信号 + 配置建议
# ═══════════════════════════════════════════════════

_WEIGHTS = {"real_rate": 0.40, "dollar": 0.30, "inflation": 0.30}

_ALLOCATION_MAP = [
    # (threshold, allocation_pct, label)
    (60, 15, "强势看多"),
    (30, 10, "温和看多"),
    (-30, 5, "中性配置"),
    (-60, 2, "防御减配"),
    (-100, 0, "回避"),
]


def compute_gold_signal() -> Dict:
    """
    计算黄金综合信号。
    
    Returns:
        {
            "status": "success",
            "gold_signal": float,           # [-100, 100]
            "gold_direction": str,          # bullish/neutral/bearish
            "suggested_allocation": float,  # 0-15%
            "components": {...},
        }
    """
    try:
        # 获取 FRED 数据
        dfii10 = _fetch_fred_series("DFII10", 365)       # 实际利率
        dtwex = _fetch_fred_series("DTWEXBGS", 365)      # 贸易加权美元指数
        dgs10 = _fetch_fred_series("DGS10", 365)         # 10年期名义利率
        
        # 计算三维子信号
        d1 = _real_rate_signal(dfii10)
        d2 = _dollar_signal(dtwex)
        d3 = _inflation_signal(dgs10, dfii10)
        
        # 加权综合
        composite = (
            d1["score"] * _WEIGHTS["real_rate"] +
            d2["score"] * _WEIGHTS["dollar"] +
            d3["score"] * _WEIGHTS["inflation"]
        )
        composite = round(float(np.clip(composite, -100, 100)), 1)
        
        # 方向判定
        if composite > 25:
            direction = "bullish"
            direction_cn = "看多黄金"
        elif composite < -25:
            direction = "bearish"
            direction_cn = "看空黄金"
        else:
            direction = "neutral"
            direction_cn = "黄金中性"
        
        # 配置建议
        allocation = 5  # 默认中性
        alloc_label = "中性配置"
        for threshold, alloc, label in _ALLOCATION_MAP:
            if composite >= threshold:
                allocation = alloc
                alloc_label = label
                break
        
        return {
            "status": "success",
            "gold_signal": composite,
            "gold_direction": direction,
            "gold_direction_cn": direction_cn,
            "suggested_allocation": allocation,
            "allocation_label": alloc_label,
            "components": {
                "real_rate": d1,
                "dollar": d2,
                "inflation": d3,
            },
            "weights": _WEIGHTS,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error("黄金信号计算异常: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "gold_signal": 0,
            "gold_direction": "neutral",
            "suggested_allocation": 5,
        }
