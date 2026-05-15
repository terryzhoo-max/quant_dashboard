"""
AlphaCore · 快照构建器
========================
从 decision_engine.py 拆分 (P2-A)

核心基础设施: 从缓存组装系统快照，供所有决策模块使用。

公开 API:
  - _parse_erp_value(raw) → float
  - _build_snapshot_from_cache() → dict
"""

from services.logger import get_logger

logger = get_logger("ac.decision.snapshot")


def _parse_erp_value(raw) -> float:
    """安全解析 ERP 值: '4.5%' → 4.5, 4.5 → 4.5, None → 4.5"""
    if raw is None:
        return 4.5
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).replace('%', '').strip())
    except (ValueError, TypeError):
        return 4.5


def _build_snapshot_from_cache() -> dict:
    """
    V17.1: 从缓存组装当前系统快照 (不调引擎, 纯读取)

    缓存结构 (由 assemble_response.py 写入):
      data.macro_cards.vix.value          → vix_val (float)
      data.macro_cards.erp.value          → erp_val (字符串 '4.5%', 需解析)
      data.macro_cards.market_temp.hub_factors.{key}.score  → 各因子得分
      data.macro_cards.market_temp.hub_composite             → 综合得分
      data.macro_cards.regime_banner.aiae_cap                → 建议仓位
      data.macro_cards.market_temp.degraded_modules          → 降级模块
    """
    from services.cache_service import cache_manager

    snapshot = {}

    # Dashboard 数据 (V17.1: 修正读取路径, 从 macro_cards.market_temp 读取)
    dashboard = cache_manager.get_json("dashboard_data")
    if dashboard and dashboard.get("data"):
        d = dashboard["data"]
        macro = d.get("macro_cards", {})
        market_temp = macro.get("market_temp", {})
        regime_banner = macro.get("regime_banner", {})

        # VIX — 从 macro_cards.vix.value 读取 (float)
        snapshot["vix_val"] = macro.get("vix", {}).get("value")

        # ERP — value 是字符串 "4.5%", 需解析为浮点数
        snapshot["erp_val"] = _parse_erp_value(macro.get("erp", {}).get("value"))

        # Hub 因子得分 — 从 market_temp.hub_factors 读取
        hub_factors = market_temp.get("hub_factors", {})
        snapshot["erp_score"] = hub_factors.get("erp_value", {}).get("score", 50)
        snapshot["vix_score"] = hub_factors.get("vix_fear", {}).get("score", 50)
        snapshot["liquidity_score"] = hub_factors.get("capital_flow", {}).get("score", 50)
        snapshot["macro_temp_score"] = hub_factors.get("macro_temp", {}).get("score", 50)

        # Hub composite + position
        snapshot["hub_composite"] = market_temp.get("hub_composite", 50)
        snapshot["suggested_position"] = regime_banner.get("aiae_cap", 55)

        # 降级模块
        snapshot["degraded_modules"] = market_temp.get("degraded_modules", [])

        # V17.1: 快照完整性日志
        _real_count = sum(1 for k in ["erp_score", "vix_score", "hub_composite"]
                         if snapshot.get(k) != 50)
        _is_cold = _real_count == 0 and not hub_factors
        if _is_cold:
            logger.warning("快照警告: hub_factors 为空, 可能缓存未预热")
        else:
            logger.debug("快照组装: erp=%.1f vix_s=%.1f comp=%.1f pos=%s",
                         snapshot.get("erp_score", 0), snapshot.get("vix_score", 0),
                         snapshot.get("hub_composite", 0), snapshot.get("suggested_position"))

        # V20.0: 数据质量透传 — 前端据此决定是否显示冷启动提示
        snapshot["_data_quality"] = {
            "real_sources": _real_count,
            "total_expected": 4,
            "is_cold_start": _is_cold,
        }

    # AIAE 上下文 (V17.5: 扩展完整字段供仪表卡片使用)
    aiae_ctx = cache_manager.get_json("aiae_ctx")
    if aiae_ctx:
        snapshot["aiae_regime"] = aiae_ctx.get("regime", 3)
        snapshot["aiae_v1"] = aiae_ctx.get("aiae_v1", 22)
        snapshot["aiae_regime_cn"] = aiae_ctx.get("regime_cn", "中性均衡")
        snapshot["aiae_cap"] = aiae_ctx.get("cap", 55)
        snapshot["aiae_slope"] = aiae_ctx.get("slope", 0)
        snapshot["aiae_slope_dir"] = aiae_ctx.get("slope_direction", "flat")
        snapshot["margin_heat"] = aiae_ctx.get("margin_heat", 2.0)
        snapshot["fund_position"] = aiae_ctx.get("fund_position", 80)

    # 策略结果
    strategy_results = cache_manager.get_json("strategy_results") or {}
    mr_data = strategy_results.get("mr", {})
    if isinstance(mr_data, dict):
        mr_ov = mr_data.get("data", {}).get("market_overview", {})
        mr_regime = mr_ov.get("regime", "RANGE") if mr_ov else "RANGE"
    else:
        mr_regime = "RANGE"
    snapshot["mr_regime"] = mr_regime

    # V25.3 P3-B: 黄金信号 (从 SWR 缓存读取)
    gold_data = cache_manager.get_json("swr_gold_signal")
    if gold_data and isinstance(gold_data, dict):
        snapshot["gold_signal"] = gold_data.get("gold_signal", 0)
        snapshot["gold_direction"] = gold_data.get("gold_direction", "neutral")
    else:
        snapshot["gold_signal"] = None
        snapshot["gold_direction"] = None

    # V25.3 P3-B: 国债信号 (从利率引擎缓存读取)
    rates_data = cache_manager.get_json("swr_rates_strategy")
    if rates_data and isinstance(rates_data, dict):
        # rates engine 输出 composite_signal + allocation.bond_pct
        snapshot["bond_signal"] = rates_data.get("composite_signal", 0)
        snapshot["bond_direction"] = rates_data.get("bond_direction", "neutral")
    else:
        snapshot["bond_signal"] = None
        snapshot["bond_direction"] = None

    return snapshot
