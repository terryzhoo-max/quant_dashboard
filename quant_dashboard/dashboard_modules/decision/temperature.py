"""
AlphaCore · 全球市场温度聚合
==============================
从 decision_engine.py 拆分 (P2-A)

纯缓存读取, 零 API 调用。
聚合四大市场 (A股/美股/港股/日股) AIAE 温度数据。

公开 API:
  - _build_global_temperature() → dict
  - _GLOBAL_REGIMES, _GLOBAL_GAUGE_BANDS, _REGIME_CAP_LOOKUP: dict
"""

from services.cache_service import cache_manager

# V3.0 加固: CN 分界线从参数中心派生, 消除硬编码漂移
try:
    from aiae_params import REGIME_THRESHOLDS as _CN_THRESHOLDS
except ImportError:
    _CN_THRESHOLDS = [12.5, 17, 23, 30]

# 各市场 AIAE 五档定义 (从各引擎同步, 用于 action 文案)
_GLOBAL_REGIMES = {
    "cn": {
        1: {"cn": "极度恐慌", "emoji": "🟢", "color": "#10b981", "action": "满配进攻", "range": f"<{_CN_THRESHOLDS[0]}%", "pos": "90-95%"},
        2: {"cn": "低配置区", "emoji": "🔵", "color": "#3b82f6", "action": "标准建仓", "range": f"{_CN_THRESHOLDS[0]}-{_CN_THRESHOLDS[1]}%", "pos": "70-85%"},
        3: {"cn": "中性均衡", "emoji": "🟡", "color": "#eab308", "action": "均衡持有", "range": f"{_CN_THRESHOLDS[1]}-{_CN_THRESHOLDS[2]}%", "pos": "50-65%"},
        4: {"cn": "偏热区域", "emoji": "🟠", "color": "#f97316", "action": "系统减仓", "range": f"{_CN_THRESHOLDS[2]}-{_CN_THRESHOLDS[3]}%", "pos": "25-40%"},
        5: {"cn": "极度过热", "emoji": "🔴", "color": "#ef4444", "action": "清仓防守", "range": f">{_CN_THRESHOLDS[3]}%", "pos": "0-15%"},
    },
    "us": {
        1: {"cn": "极度恐慌", "emoji": "🟢", "color": "#10b981", "action": "满配进攻", "range": "<15%", "pos": "90-95%"},
        2: {"cn": "低配置区", "emoji": "🔵", "color": "#3b82f6", "action": "标准建仓", "range": "15-20%", "pos": "70-85%"},
        3: {"cn": "中性均衡", "emoji": "🟡", "color": "#eab308", "action": "均衡持有", "range": "20-27%", "pos": "50-65%"},
        4: {"cn": "偏热区域", "emoji": "🟠", "color": "#f97316", "action": "系统减仓", "range": "27-34%", "pos": "25-40%"},
        5: {"cn": "极度过热", "emoji": "🔴", "color": "#ef4444", "action": "清仓防守", "range": ">34%", "pos": "0-15%"},
    },
    "hk": {
        1: {"cn": "极度恐慌", "emoji": "🟢", "color": "#10b981", "action": "满配进攻", "range": "<8%", "pos": "90-95%"},
        2: {"cn": "低配置区", "emoji": "🔵", "color": "#3b82f6", "action": "标准建仓", "range": "8-12%", "pos": "70-85%"},
        3: {"cn": "中性均衡", "emoji": "🟡", "color": "#eab308", "action": "均衡持有", "range": "12-18%", "pos": "50-65%"},
        4: {"cn": "偏热区域", "emoji": "🟠", "color": "#f97316", "action": "系统减仓", "range": "18-25%", "pos": "25-40%"},
        5: {"cn": "极度过热", "emoji": "🔴", "color": "#ef4444", "action": "清仓防守", "range": ">25%", "pos": "0-15%"},
    },
    "jp": {
        1: {"cn": "极度悲观", "emoji": "🟢", "color": "#10b981", "action": "全力买入", "range": "<10%", "pos": "90-95%"},
        2: {"cn": "低配置区", "emoji": "🔵", "color": "#3b82f6", "action": "标准建仓", "range": "10-14%", "pos": "70-85%"},
        3: {"cn": "中性均衡", "emoji": "🟡", "color": "#eab308", "action": "均衡持有", "range": "14-20%", "pos": "50-65%"},
        4: {"cn": "偏热区域", "emoji": "🟠", "color": "#f97316", "action": "系统减仓", "range": "20-28%", "pos": "25-40%"},
        5: {"cn": "泡沫警报", "emoji": "🔴", "color": "#ef4444", "action": "全面撤退", "range": ">28%", "pos": "0-15%"},
    },
}

# Cap lookup (erp_4_6 行中位值, 用于全球温度聚合)
try:
    from aiae_params import POSITION_MATRIX as _PM2
    _REGIME_CAP_LOOKUP = {i+1: _PM2["erp_4_6"][i] for i in range(5)}
except ImportError:
    _REGIME_CAP_LOOKUP = {1: 90, 2: 80, 3: 60, 4: 35, 5: 10}

# 各市场 AIAE gauge 色带阈值 (用于 ECharts)
_GLOBAL_GAUGE_BANDS = {
    "cn": _CN_THRESHOLDS + [40],  # 前4个从参数中心派生, 最后一个为 gauge 满刻度
    "us": [15, 20, 27, 34, 45],
    "hk": [8, 12, 18, 25, 35],
    "jp": [10, 14, 20, 28, 40],
}


def _build_global_temperature() -> dict:
    """
    V19.0: 从缓存聚合四大市场温度数据 (A股/美股/港股/日股)
    数据源:
      - A股: aiae_ctx 缓存 (由 warmup_pipeline 写入)
      - 海外: aiae_global_report_data 缓存 (由 /api/v1/aiae_global/report 写入)
    零 API 调用, 纯缓存读取。
    """
    markets = []
    market_names = {"cn": "A股", "us": "美股", "hk": "港股", "jp": "日股"}
    market_flags = {"cn": "🇨🇳", "us": "🇺🇸", "hk": "🇭🇰", "jp": "🇯🇵"}

    # ── A 股: 从 aiae_ctx 读取 ──
    aiae_ctx = cache_manager.get_json("aiae_ctx")
    if aiae_ctx:
        regime = aiae_ctx.get("regime", 3)
        ri = _GLOBAL_REGIMES["cn"].get(regime, _GLOBAL_REGIMES["cn"][3])
        markets.append({
            "key": "cn", "name": market_names["cn"], "flag": market_flags["cn"],
            "aiae_v1": aiae_ctx.get("aiae_v1", 22.0),
            "regime": regime, "regime_cn": ri["cn"], "regime_color": ri["color"],
            "emoji": ri["emoji"], "cap": aiae_ctx.get("cap", _REGIME_CAP_LOOKUP.get(regime, 57)),
            "action": ri["action"], "range": ri["range"], "pos": ri["pos"],
            "gauge_bands": _GLOBAL_GAUGE_BANDS["cn"],
            "status": "ready",
        })
    else:
        markets.append({"key": "cn", "name": market_names["cn"], "flag": market_flags["cn"], "status": "loading"})

    # ── 海外 (US/HK/JP): 从 aiae_global_report_data 读取 ──
    global_data = cache_manager.get_json("aiae_global_report_data")
    for mkt_key in ["us", "hk", "jp"]:
        if global_data and global_data.get("status") == "success":
            report = global_data.get(mkt_key, {})
            current = report.get("current", {})
            # P5: 多路径 fallback — 兼容不同海外引擎的 JSON 结构
            aiae_v1 = (
                current.get("aiae_v1")
                or report.get("aiae_v1")
                or report.get("summary", {}).get("aiae_v1")
            )
            regime = current.get("regime", 3)
            ri = _GLOBAL_REGIMES[mkt_key].get(regime, _GLOBAL_REGIMES[mkt_key][3])

            # 从 position 字段获取仓位, 回退到 regime 默认
            position_data = report.get("position", {})
            cap = position_data.get("matrix_position", _REGIME_CAP_LOOKUP.get(regime, 57))

            markets.append({
                "key": mkt_key, "name": market_names[mkt_key], "flag": market_flags[mkt_key],
                "aiae_v1": aiae_v1 if aiae_v1 is not None else 22.0,
                "regime": regime, "regime_cn": ri["cn"], "regime_color": ri["color"],
                "emoji": ri["emoji"], "cap": cap,
                "action": ri["action"], "range": ri["range"], "pos": ri["pos"],
                "gauge_bands": _GLOBAL_GAUGE_BANDS[mkt_key],
                "status": "ready" if aiae_v1 is not None else "fallback",
            })
        else:
            markets.append({"key": mkt_key, "name": market_names[mkt_key], "flag": market_flags[mkt_key], "status": "loading"})

    # ── 全球对比 (直接复用已有的 global_comparison) ──
    comparison = {}
    if global_data and global_data.get("global_comparison"):
        comparison = global_data["global_comparison"]

    return {
        "markets": markets,
        "comparison": comparison,
    }
