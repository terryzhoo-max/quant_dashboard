import asyncio
import copy
import math
import time
import threading
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import tushare as ts

from config import TUSHARE_TOKEN
from services.logger import get_logger

logger = get_logger("dashboard")
from services.cache_service import cache_manager
from services.cache_store import get_cache_ttl as _get_cache_ttl, get_global_aiae_ttl as _get_global_aiae_ttl
from services.aiae_safety import build_aiae_context
from services.position_engine import (
    get_vix_analysis, get_position_path, get_tomorrow_plan,
    get_institutional_mindset,
)
from aiae_engine import get_aiae_engine, REGIMES as AIAE_REGIMES

executor = ThreadPoolExecutor(max_workers=10)

# P0-4: 统一策略缓存写入锁 (Single Source of Truth, 供 main.py / strategy.py 共用)
_STRATEGY_LOCK = threading.Lock()

CACHE_TTL = 3600  # 向下兼容

def _get_cache_ttl_compat() -> int:
    """P2-1: 统一使用 cache_store 的 TTL 计算 (DRY)"""
    return _get_cache_ttl()


def _get_global_aiae_ttl_compat() -> int:
    """P2-1: 统一使用 cache_store 的海外 AIAE TTL (DRY)"""
    return _get_global_aiae_ttl()


def _hot_data_reactor_tick():
    """后台高频预热循环：盘中提取 VIX/CNY，主动写入缓存"""
    from dashboard_modules.fetch_macro import fetch_vix_for_dashboard, fetch_cny_for_dashboard
    try:
        now_dt = datetime.now()
        is_trading_hours = now_dt.weekday() < 5 and ((now_dt.hour == 9 and now_dt.minute >= 30) or (10 <= now_dt.hour < 15))
        with _STRATEGY_LOCK:
            has_strategy_cache = cache_manager.get_json("dashboard_data") is not None

        if is_trading_hours and has_strategy_cache:
            hot_vix, prev_vix = fetch_vix_for_dashboard()
            cny_result = fetch_cny_for_dashboard()

            hot_vix_change = ((hot_vix - prev_vix) / prev_vix * 100) if prev_vix > 0 else 0
            hot_vix_status = "down" if hot_vix_change < 0 else "up"
            hot_vix_analysis = get_vix_analysis(hot_vix)

            with _STRATEGY_LOCK:
                # P0-3: deepcopy 防止并发读取半修改状态
                hot_data = copy.deepcopy(cache_manager.get_json("dashboard_data"))
                _hot_aiae_ctx = cache_manager.get_json("aiae_ctx")

            if not hot_data or not isinstance(hot_data, dict):
                logger.debug("Reactor tick 跳过: dashboard_data 缓存为空")
                return

            mc = hot_data.get("data", {}).get("macro_cards", {})
            if "vix" in mc:
                mc["vix"]["value"] = round(hot_vix, 2)
                mc["vix"]["trend"] = f"{round(hot_vix_change, 1)}%"
                mc["vix"]["status"] = hot_vix_status
                mc["vix"]["regime"] = hot_vix_analysis["label"]
                mc["vix"]["class"] = hot_vix_analysis["class"]
                mc["vix"]["desc"] = hot_vix_analysis.get("desc", "")
                mc["vix"]["percentile"] = hot_vix_analysis.get("percentile", 0)
            if mc.get("regime_banner"):
                mc["regime_banner"]["vix"] = round(hot_vix, 2)
                mc["regime_banner"]["vix_label"] = hot_vix_analysis.get("label", "—")
            if mc.get("market_temp") and "multiplier" in hot_vix_analysis:
                mc["market_temp"]["market_vix_multiplier"] = hot_vix_analysis["multiplier"]

            if "tomorrow_plan" in mc:
                mc["tomorrow_plan"] = get_tomorrow_plan(hot_vix_analysis, mc.get("market_temp", {}).get("value", 50), _hot_aiae_ctx)
            hot_data["timestamp"] = now_dt.isoformat()

            with _STRATEGY_LOCK:
                _hot_ttl = _get_cache_ttl()
                cache_manager.set_json("last_hot_update", time.time(), ttl_seconds=_hot_ttl)
                cache_manager.set_json("dashboard_data", hot_data, ttl_seconds=_hot_ttl)
        elif has_strategy_cache:
            # 盘后安全网: 周期性续期缓存 TTL (30 分钟节流, O(1) 无数据拷贝)
            # 防止 TTL 计算异常导致最后一次合格快照过早过期。
            _last_ka = getattr(_hot_data_reactor_tick, '_last_keepalive', 0)
            if time.time() - _last_ka > 1800:
                _renew_ttl = _get_cache_ttl()
                cache_manager.touch("dashboard_data", _renew_ttl)
                cache_manager.touch("last_update", _renew_ttl)
                cache_manager.touch("last_hot_update", _renew_ttl)
                cache_manager.touch("aiae_ctx", _renew_ttl)
                _hot_data_reactor_tick._last_keepalive = time.time()
                logger.debug("盘后缓存续期: TTL=%ds", _renew_ttl)
    except Exception as e:
        logger.warning(f"Reactor tick 异常: {e}")


async def _build_dashboard_data_full():
    """由后台 Reactor 主动触发的全量构建逻辑，绝不在 API 线程中直接调用"""
    from dashboard_modules.fetch_macro import fetch_vix_for_dashboard, fetch_cny_for_dashboard, fetch_macro_data
    from dashboard_modules.run_strategies import run_all_strategies, wrap_mr_results
    from dashboard_modules.capital_flow import compute_capital_flow
    from dashboard_modules.market_temp import compute_market_temperature
    from dashboard_modules.sector_heatmap import compute_sector_heatmap
    from dashboard_modules.assemble_response import assemble_dashboard_response

    current_time = time.time()

    # ── 全量刷新: 子模块并发编排 ──
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    today_str = datetime.now().strftime('%Y%m%d')
    loop = asyncio.get_running_loop()

    try:
        # 第一层: 并发执行 I/O 和独立计算
        async def fetch_macro_safe():
            # Fail closed: the outer build handler leaves the last-known-good
            # cache untouched when primary macro inputs cannot be verified.
            return await fetch_macro_data(executor)

        async def get_capital_flow():
            return await loop.run_in_executor(executor, compute_capital_flow, pro, today_str)

        async def get_aiae_report():
            def _fetch():
                try:
                    eng = get_aiae_engine()
                    return eng.generate_report()
                except Exception as e:
                    logger.error(f"AIAE引擎异常: {e}")
                    return {"status": "error", "message": str(e)}
            return await loop.run_in_executor(executor, _fetch)

        macro_task = asyncio.create_task(fetch_macro_safe())
        strat_task = asyncio.create_task(run_all_strategies(executor))
        cap_task = asyncio.create_task(get_capital_flow())
        aiae_task = asyncio.create_task(get_aiae_report())

        # 等待第一层完成
        macro_res, strat_res, cap_res, aiae_report = await asyncio.gather(
            macro_task, strat_task, cap_task, aiae_task
        )

        # 解包第一层结果
        latest_vix, prev_vix, latest_cny = macro_res
        vix_change = ((latest_vix - prev_vix) / prev_vix * 100) if prev_vix > 0 else 0
        vix_status = "down" if vix_change < 0 else "up"

        mr_res, div_res, mom_res = strat_res
        cache_manager.set_json("strategy_results", {"mr": mr_res, "div": div_res, "mom": mom_res})

        capital_a, capital_h, liquidity_score, total_money_z, z_s = cap_res

        # 处理 AIAE
        _full_aiae_ctx = build_aiae_context(aiae_report)
        if _full_aiae_ctx.get("decision_locked") is not False:
            logger.error("AIAE 上下文未通过状态、质量或仓位校验，停止发布 Dashboard")
            raise RuntimeError("AIAE_CONTEXT_UNUSABLE")
        try:
            aiae_regime = int(_full_aiae_ctx["regime"])
            aiae_cap = float(_full_aiae_ctx["cap"])
            aiae_v1_value = float(_full_aiae_ctx["aiae_v1"])
            aiae_regime_cn = str(_full_aiae_ctx["regime_cn"] or "").strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("AIAE_CONTEXT_UNUSABLE") from exc
        if (
            aiae_regime not in AIAE_REGIMES
            or not math.isfinite(aiae_cap)
            or not 0 <= aiae_cap <= 100
            or not math.isfinite(aiae_v1_value)
            or not aiae_regime_cn
        ):
            raise RuntimeError("AIAE_CONTEXT_UNUSABLE")
        logger.info(
            "AIAE注入成功: BasisValue=%.2f%% Regime=%s Cap=%s%%",
            aiae_v1_value,
            aiae_regime,
            aiae_cap,
        )

        # 第二层: 温度分析与热力图
        vix_analysis = get_vix_analysis(latest_vix)

        async def get_temp():
            def _calc():
                return compute_market_temperature(
                    pro, today_str, latest_vix, latest_cny, liquidity_score, z_s,
                    aiae_regime, aiae_cap, aiae_v1_value, aiae_regime_cn, aiae_report, vix_analysis
                )
            return await loop.run_in_executor(executor, _calc)

        temp_task = asyncio.create_task(get_temp())
        heatmap_task = asyncio.create_task(compute_sector_heatmap(executor, mr_res, mom_res))

        temp_data, sector_heatmap = await asyncio.gather(temp_task, heatmap_task)

        import aiae_params as AP
        is_v5 = getattr(AP, 'V5_ENABLED', False)
        fallback_thresholds = list(AP.V5_REGIME_THRESHOLDS) if is_v5 else list(AP.REGIME_THRESHOLDS)

        # 单一 AIAE 上下文同时供全量响应、热更新与缓存使用，避免健康字段在组装时丢失。
        _full_aiae_ctx.update({
            "regime_cn": aiae_regime_cn,
            "regime_info": _full_aiae_ctx.get("regime_info") or AIAE_REGIMES.get(aiae_regime, AIAE_REGIMES[3]),
            "aiae_v1": round(aiae_v1_value, 2),
            "erp_val": round(temp_data["erp_val"], 2),
            "erp_label": temp_data["valuation_label"],
            "erp_tier": temp_data["erp_tier"],
            "margin_heat": _full_aiae_ctx.get("margin_heat"),
            "fund_position": _full_aiae_ctx.get("fund_position"),
            "fund_position_source": _full_aiae_ctx.get("fund_position_source"),
            "fund_position_date": _full_aiae_ctx.get("fund_position_date"),
            "regime_basis_value": aiae_v1_value,
            "regime_thresholds": _full_aiae_ctx.get("regime_thresholds") or fallback_thresholds,
            "regime_mode": _full_aiae_ctx.get("regime_mode") or ("V5_simple" if is_v5 else "V3_composite"),
        })

        # Step 8: 组装最终响应
        final_data = assemble_dashboard_response(
            latest_vix=latest_vix, vix_change=vix_change,
            vix_status=vix_status, vix_analysis=vix_analysis,
            capital_a=capital_a, capital_h=capital_h,
            total_money_z=total_money_z,
            temp_data=temp_data,
            mr_res=mr_res, div_res=div_res, mom_res=mom_res,
            aiae_regime=aiae_regime, aiae_cap=aiae_cap,
            aiae_v1_value=aiae_v1_value, aiae_regime_cn=aiae_regime_cn,
            aiae_report=aiae_report, aiae_ctx=_full_aiae_ctx,
            sector_heatmap=sector_heatmap,
            get_tomorrow_plan_fn=get_tomorrow_plan,
            get_position_path_fn=get_position_path,
            get_institutional_mindset_fn=get_institutional_mindset,
            liquidity_score=liquidity_score,
        )

        # 更新缓存 (P0-2: 原子写入, R7: 智能 TTL 防陈旧)
        _build_ttl = _get_cache_ttl()
        with _STRATEGY_LOCK:
            cache_manager.set_json("last_update", current_time, ttl_seconds=_build_ttl)
            cache_manager.set_json("dashboard_data", final_data, ttl_seconds=_build_ttl)
            cache_manager.set_json("aiae_ctx", _full_aiae_ctx, ttl_seconds=_build_ttl)
        return final_data

    except Exception as e:
        logger.error(f"Dashboard 全量构建异常: {traceback.format_exc()}")
        return {"status": "error", "message": f"Global Error: {str(e)}"}
