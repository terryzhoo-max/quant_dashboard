"""
AlphaCore · Dashboard 数据构建器
=================================
Batch 7 架构解耦: 从 main.py 提取

职责:
  - _build_dashboard_data_full()  — 全量仪表盘构建 (由 warmup_pipeline 调用)
  - _hot_data_reactor_tick()      — 盘中 VIX/CNY 热刷新
  - 智能缓存 TTL 计算
"""

import asyncio
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
from services.position_engine import (
    get_vix_analysis, get_position_path, get_tomorrow_plan,
    get_institutional_mindset,
)
from aiae_engine import get_aiae_engine, REGIMES as AIAE_REGIMES

executor = ThreadPoolExecutor(max_workers=10)

# 线程安全锁 (原 main.py 的 _STRATEGY_LOCK)
_STRATEGY_LOCK = threading.Lock()

CACHE_TTL = 3600  # 向下兼容


def _get_cache_ttl() -> int:
    """智能缓存 TTL：盘中5分钟 / 盘后1小时 / 周末24小时"""
    now = datetime.now()
    weekday = now.weekday()  # 0=周一 ... 6=周日
    if weekday >= 5:               # 周末
        return 86400
    h, m = now.hour, now.minute
    in_session = (h == 9 and m >= 30) or (10 <= h < 15)  # 09:30-15:00
    return 300 if in_session else 3600


def _get_global_aiae_ttl() -> int:
    """海外AIAE缓存TTL: 美股盘中30min / 盘后4h / 周末24h (UTC+8)"""
    now = datetime.now()
    if now.weekday() >= 5:
        return 86400    # 周末 24h
    h = now.hour
    # 美股盘中 (北京 21:30~04:00)
    if h >= 21 or h < 4:
        return 1800     # 30min
    return 14400        # 4h


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
                hot_data = cache_manager.get_json("dashboard_data")
                _hot_aiae_ctx = cache_manager.get_json("aiae_ctx")

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
                cache_manager.set_json("last_update", time.time())
                cache_manager.set_json("dashboard_data", hot_data)
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
    latest_vix, vix_change, vix_status = 18.25, -1.5, "down"
    latest_cny = 7.23

    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    today_str = datetime.now().strftime('%Y%m%d')
    loop = asyncio.get_event_loop()

    try:
        # 第一层: 并发执行 I/O 和独立计算
        async def fetch_macro_safe():
            try:
                v, p, c = await fetch_macro_data(executor)
                return v, p, c
            except Exception as e:
                logger.warning(f"Macro fetch partial failure: {e}")
                return 18.25, 18.25, 7.23

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
        aiae_regime = 3
        aiae_cap = 65
        aiae_v1_value = 0.0
        aiae_regime_cn = "中性均衡"
        if aiae_report.get("status") == "success":
            aiae_regime = aiae_report["current"]["regime"]
            aiae_v1_value = aiae_report["current"]["aiae_v1"]
            aiae_cap = aiae_report["position"]["matrix_position"]
            aiae_regime_cn = aiae_report["current"]["regime_info"]["cn"]
            logger.info(f"AIAE注入成功: V1={aiae_v1_value:.1f}% Regime={aiae_regime} Cap={aiae_cap}%")
        else:
            logger.warning(f"AIAE降级: {aiae_report.get('message', 'unknown')}")

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
            aiae_report=aiae_report,
            sector_heatmap=sector_heatmap,
            get_tomorrow_plan_fn=get_tomorrow_plan,
            get_position_path_fn=get_position_path,
            get_institutional_mindset_fn=get_institutional_mindset,
            liquidity_score=liquidity_score,
        )

        # P0-1: 构建并缓存原始 aiae_ctx (供 Hot-Refresh 复用)
        _full_aiae_ctx = {
            "regime": aiae_regime,
            "regime_cn": aiae_regime_cn,
            "regime_info": AIAE_REGIMES.get(aiae_regime, AIAE_REGIMES[3]),
            "cap": aiae_cap,
            "aiae_v1": round(aiae_v1_value, 1),
            "slope": aiae_report.get("current", {}).get("slope", {}).get("slope", 0),
            "slope_direction": aiae_report.get("current", {}).get("slope", {}).get("direction", "flat"),
            "erp_val": round(temp_data["erp_val"], 2),
            "erp_label": temp_data["valuation_label"],
            "erp_tier": temp_data["erp_tier"],
            "margin_heat": aiae_report.get("current", {}).get("margin_heat", 2.0),
            "fund_position": aiae_report.get("current", {}).get("fund_position", 80),
        }

        # 更新缓存 (P0-2: 原子写入)
        with _STRATEGY_LOCK:
            cache_manager.set_json("last_update", current_time)
            cache_manager.set_json("dashboard_data", final_data)
            cache_manager.set_json("aiae_ctx", _full_aiae_ctx)
        return final_data

    except Exception as e:
        logger.error(f"Dashboard 全量构建异常: {traceback.format_exc()}")
        return {"status": "error", "message": f"Global Error: {str(e)}"}
