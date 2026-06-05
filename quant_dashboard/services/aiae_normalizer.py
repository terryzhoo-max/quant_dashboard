"""
AlphaCore · 跨区域温度归一化工具
================================
将不同市场的 AIAE 值映射到统一 0-100 温度标尺。
消除 routers/aiae.py 和 services/warmup_pipeline.py 中的重复实现。

标度映射:
  Ⅰ/Ⅱ边界 → 20°,  Ⅱ/Ⅲ → 40°,  Ⅲ/Ⅳ → 60°,  Ⅳ/Ⅴ → 80°

V26.1: 从 aiae.py + warmup_pipeline.py 提取。
"""
from typing import Dict


# 各区域五档阈值 (AIAE 百分比 → 五档分界线)
# CN 从 aiae_params 动态读取，其余硬编码
_STATIC_REGION_THRESHOLDS = {
    "us": [15, 20, 27, 34],
    "jp": [10, 14, 20, 28],
    "hk": [8, 12, 18, 25],
}


def get_region_thresholds() -> Dict[str, list]:
    """获取含 CN 在内的四区域阈值 (Single Source of Truth)"""
    thresholds = dict(_STATIC_REGION_THRESHOLDS)
    try:
        import aiae_params as _AP
        if getattr(_AP, 'V5_ENABLED', False):
            thresholds["cn"] = list(_AP.V5_REGIME_THRESHOLDS)
        else:
            thresholds["cn"] = list(_AP.REGIME_THRESHOLDS)
    except ImportError:
        thresholds["cn"] = [12.5, 17, 23, 30]
    return thresholds


def normalize_temp(aiae_val: float, region: str,
                   thresholds: Dict[str, list] = None) -> float:
    """将区域 AIAE 值归一化到 0-100 统一温度标尺

    Args:
        aiae_val: 原始 AIAE 百分比值
        region: 区域代码 ("cn"/"us"/"jp"/"hk")
        thresholds: 可选, 外部传入的阈值字典。默认自动获取。

    Returns:
        归一化温度 (0-100)
    """
    if thresholds is None:
        thresholds = get_region_thresholds()

    t = thresholds[region]
    anchors = [(t[0], 20), (t[1], 40), (t[2], 60), (t[3], 80)]

    if aiae_val <= anchors[0][0]:
        return max(0, 20 * aiae_val / anchors[0][0]) if anchors[0][0] > 0 else 0

    for i in range(len(anchors) - 1):
        lo_v, lo_n = anchors[i]
        hi_v, hi_n = anchors[i + 1]
        if aiae_val <= hi_v:
            return lo_n + (hi_n - lo_n) * (aiae_val - lo_v) / (hi_v - lo_v)

    return min(100, 80 + 20 * (aiae_val - anchors[-1][0]) / max(anchors[-1][0] * 0.3, 1))


def compute_global_position(avg_temp: float, regimes: Dict[str, int]) -> Dict:
    """根据四市场平均温度计算全局权益仓位建议

    Args:
        avg_temp: 四市场归一化温度均值
        regimes: 各区域 regime 字典

    Returns:
        全局仓位建议 dict
    """
    if avg_temp >= 80:
        gp = {"label": "极度过热·清仓", "position": "0-15%", "color": "#ef4444", "emoji": "🔴", "equity_pct": 8}
    elif avg_temp >= 65:
        gp = {"label": "偏热·系统减配", "position": "20-35%", "color": "#f97316", "emoji": "🟠", "equity_pct": 28}
    elif avg_temp >= 50:
        gp = {"label": "中性·均衡持有", "position": "45-60%", "color": "#eab308", "emoji": "🟡", "equity_pct": 52}
    elif avg_temp >= 35:
        gp = {"label": "偏冷·标准建仓", "position": "65-80%", "color": "#3b82f6", "emoji": "🔵", "equity_pct": 72}
    elif avg_temp >= 20:
        gp = {"label": "极冷·积极加仓", "position": "80-95%", "color": "#10b981", "emoji": "🟢", "equity_pct": 88}
    else:
        gp = {"label": "历史级底部·满配", "position": "90-100%", "color": "#10b981", "emoji": "🟢🟢", "equity_pct": 95}

    gp["cash_pct"] = 100 - gp["equity_pct"]
    gp["avg_temp"] = round(avg_temp, 1)
    gp["extreme_warnings"] = [r for r, reg in regimes.items() if reg == 5]
    return gp


REGION_NAMES = {"cn": "A股", "us": "美股", "jp": "日股", "hk": "港股"}
