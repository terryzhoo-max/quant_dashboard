"""AlphaCore AIAE 宏观仓位 + MR参数 + 港股ERP API — 从 main.py 提取"""
import asyncio
import time
import json
import os
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter

from models.schemas import (
    FundPositionUpdate, HKSouthboundUpdate, HKAHPremiumUpdate,
    JPMarginUpdate, JPForeignUpdate,
)
from aiae_engine import get_aiae_engine
from aiae_us_engine import get_us_aiae_engine
from aiae_jp_engine import get_jp_aiae_engine
from aiae_hk_engine import get_hk_aiae_engine
from erp_hk_engine import get_hk_erp_engine
from mean_reversion_engine import detect_regime, get_all_regime_params, needs_reoptimize
from services.cache_store import (
    AIAE_GLOBAL_CACHE, _AIAE_GLOBAL_LOCK, get_global_aiae_ttl,
)

router = APIRouter(prefix="/api/v1", tags=["aiae"])
executor = ThreadPoolExecutor(max_workers=6)


# ─── AIAE 中国 ───

@router.get("/aiae/report")
async def get_aiae_report():
    """AIAE 完整报告: 当前AIAE值、五档状态、仓位矩阵、子策略配额、信号"""
    try:
        loop = asyncio.get_event_loop()
        engine = get_aiae_engine()
        report = await loop.run_in_executor(executor, engine.generate_report)
        return {"status": "success", "data": report, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        print(f"[AIAE API] report error: {e}")
        return {"status": "error", "message": str(e)}

@router.get("/aiae/chart")
async def get_aiae_chart():
    """AIAE 历史走势图数据"""
    try:
        engine = get_aiae_engine()
        chart = engine.get_chart_data()
        return {"status": "success", "data": chart}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/aiae/refresh")
async def refresh_aiae():
    """强制刷新AIAE数据(清除缓存)"""
    try:
        loop = asyncio.get_event_loop()
        engine = get_aiae_engine()
        engine.refresh()
        report = await loop.run_in_executor(executor, engine.generate_report)
        return {"status": "success", "data": report, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/aiae/update_fund_position")
async def update_fund_position(req: FundPositionUpdate):
    """手动更新基金仓位数据 (C1: 季报发布后调用)"""
    try:
        engine = get_aiae_engine()
        result = engine.update_fund_position(req.value, req.date)
        if result["success"]:
            engine.refresh()
            return {"status": "success", **result}
        else:
            return {"status": "error", "message": result["message"]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── AIAE 全球 (US + JP + HK) ───

@router.get("/aiae_global/report")
async def get_aiae_global_report():
    """海外 AIAE 全球报告: L1缓存 + 并行执行 US + JP + HK 引擎, 含四地对比 V2.0"""
    current_time = time.time()
    ttl = get_global_aiae_ttl()
    with _AIAE_GLOBAL_LOCK:
        _aiae_g_ts = AIAE_GLOBAL_CACHE["last_update"]
        _aiae_g_data = AIAE_GLOBAL_CACHE["report_data"]
    if _aiae_g_ts and (current_time - _aiae_g_ts < ttl):
        age = int(current_time - _aiae_g_ts)
        ttl_label = "美股盘中30min" if ttl == 1800 else ("周末24h" if ttl == 86400 else "盘后4h")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Global AIAE Cache Hit [{ttl_label}] ({age}s ago)")
        return _aiae_g_data

    try:
        loop = asyncio.get_event_loop()
        us_engine = get_us_aiae_engine()
        jp_engine = get_jp_aiae_engine()
        hk_engine = get_hk_aiae_engine()

        us_task = loop.run_in_executor(executor, us_engine.generate_report)
        jp_task = loop.run_in_executor(executor, jp_engine.generate_report)
        hk_task = loop.run_in_executor(executor, hk_engine.generate_report)

        us_report, jp_report, hk_report = await asyncio.gather(us_task, jp_task, hk_task)

        # 获取中国 AIAE 用于四地对比
        cn_aiae_v1 = 22.0
        cn_regime = 3
        try:
            cn_engine = get_aiae_engine()
            cn_report = cn_engine.generate_report()
            if cn_report.get("status") in ("success", "fallback"):
                cn_aiae_v1 = cn_report["current"]["aiae_v1"]
                cn_regime = cn_report["current"]["regime"]
        except Exception as e:
            print(f"[GlobalAIAE] CN engine fallback: {e}")

        us_v1 = us_report.get("current", {}).get("aiae_v1", 25.0)
        jp_v1 = jp_report.get("current", {}).get("aiae_v1", 17.0)
        hk_v1 = hk_report.get("current", {}).get("aiae_v1", 14.0)
        us_regime = us_report.get("current", {}).get("regime", 3)
        jp_regime = jp_report.get("current", {}).get("regime", 3)
        hk_regime = hk_report.get("current", {}).get("regime", 3)

        vals = {"cn": cn_aiae_v1, "us": us_v1, "jp": jp_v1, "hk": hk_v1}
        coldest = min(vals, key=vals.get)
        hottest = max(vals, key=vals.get)
        region_names = {"cn": "A股", "us": "美股", "jp": "日股", "hk": "港股"}
        recommendation = f"当前{region_names[coldest]}(AIAE={vals[coldest]:.1f}%)配置热度最低, 超配优先; {region_names[hottest]}(AIAE={vals[hottest]:.1f}%)最高, 谨慎配置"

        data = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "us": us_report,
            "jp": jp_report,
            "hk": hk_report,
            "global_comparison": {
                "cn_aiae": cn_aiae_v1, "cn_regime": cn_regime,
                "us_aiae": us_v1, "us_regime": us_regime,
                "jp_aiae": jp_v1, "jp_regime": jp_regime,
                "hk_aiae": hk_v1, "hk_regime": hk_regime,
                "coldest": coldest, "hottest": hottest,
                "recommendation": recommendation,
            }
        }

        with _AIAE_GLOBAL_LOCK:
            AIAE_GLOBAL_CACHE["last_update"] = current_time
            AIAE_GLOBAL_CACHE["report_data"] = data
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Global AIAE Cache Miss -> 已重建 (US={us_v1:.1f}% JP={jp_v1:.1f}% HK={hk_v1:.1f}%)")

        return data
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

@router.get("/aiae_global/refresh")
async def refresh_aiae_global():
    """强制刷新海外 AIAE 数据: 清除L1+L2缓存后重建"""
    try:
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        us_engine = get_us_aiae_engine()
        jp_engine = get_jp_aiae_engine()
        hk_engine = get_hk_aiae_engine()
        us_engine.refresh()
        jp_engine.refresh()
        hk_engine.refresh()
        return await get_aiae_global_report()
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/aiae_global/chart")
async def get_aiae_global_chart():
    """海外 AIAE 历史走势数据 (V2.0: US+JP+HK)"""
    try:
        us_engine = get_us_aiae_engine()
        jp_engine = get_jp_aiae_engine()
        hk_engine = get_hk_aiae_engine()
        return {
            "status": "success",
            "us_chart": us_engine.get_chart_data(),
            "jp_chart": jp_engine.get_chart_data(),
            "hk_chart": hk_engine.get_chart_data(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── 港股 ERP 择时 ───

@router.get("/strategy/erp-hk")
async def get_erp_hk(market: str = "HSI"):
    """港股ERP择时 — 五维信号 + HSI/HSTECH 双轨"""
    try:
        if market not in ("HSI", "HSTECH"):
            return {"status": "error", "message": "market must be HSI or HSTECH"}
        engine = get_hk_erp_engine(market)
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(executor, engine.generate_report)
        return {"status": "success", "data": report}
    except Exception as e:
        print(f"[HK ERP API] Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


# ─── 港股 AIAE ───

@router.get("/aiae_hk/report")
async def get_aiae_hk_report():
    """港股 AIAE 完整报告"""
    try:
        engine = get_hk_aiae_engine()
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(executor, engine.generate_report)
        return {"status": "success", "data": report, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        print(f"[HK AIAE API] report error: {e}")
        return {"status": "error", "message": str(e)}

@router.get("/aiae_hk/refresh")
async def refresh_aiae_hk():
    """强制刷新港股AIAE数据"""
    try:
        engine = get_hk_aiae_engine()
        engine.refresh()
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(executor, engine.generate_report)
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        return {"status": "success", "data": report, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/aiae_hk/chart")
async def get_aiae_hk_chart():
    """港股 AIAE 历史走势数据"""
    try:
        engine = get_hk_aiae_engine()
        return {"status": "success", "data": engine.get_chart_data()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── 港股手动更新 ───

@router.post("/aiae_hk/update_southbound")
async def update_hk_southbound(req: HKSouthboundUpdate):
    """手动更新南向资金数据: 写入文件 + 清除缓存"""
    try:
        engine = get_hk_aiae_engine()
        engine.update_southbound(
            req.weekly_net_buy_billion_rmb,
            req.monthly_net_buy_billion_rmb,
            req.cumulative_12m_billion_rmb
        )
        for mkt in ["HSI", "HSTECH"]:
            erp_engine = get_hk_erp_engine(mkt)
            erp_engine.update_southbound(
                req.weekly_net_buy_billion_rmb,
                req.monthly_net_buy_billion_rmb,
                req.cumulative_12m_billion_rmb
            )
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        return {"status": "success", "message": f"南向资金已更新: 周净买入={req.weekly_net_buy_billion_rmb}亿RMB"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/aiae_hk/update_ah_premium")
async def update_hk_ah_premium(req: HKAHPremiumUpdate):
    """手动更新AH溢价指数"""
    try:
        engine = get_hk_aiae_engine()
        engine.update_ah_premium(req.index_value)
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        return {"status": "success", "message": f"AH溢价指数已更新为 {req.index_value}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── 日股手动更新 ───

@router.post("/aiae_jp/update_margin")
async def update_jp_margin(req: JPMarginUpdate):
    """手动更新日股信用取引残高"""
    try:
        engine = get_jp_aiae_engine()
        engine.update_jp_margin(req.margin_buying_trillion_jpy)
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        return {"status": "success", "message": f"信用取引残高已更新为 {req.margin_buying_trillion_jpy}兆円"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/aiae_jp/update_foreign")
async def update_jp_foreign(req: JPForeignUpdate):
    """手动更新日股外国人投資家流向"""
    try:
        engine = get_jp_aiae_engine()
        engine.update_jp_foreign(req.net_buy_billion_jpy, req.cumulative_12m_billion_jpy)
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        return {"status": "success", "message": f"外資流向已更新: 周次净買越={req.net_buy_billion_jpy}億円"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── 均值回归 V4.0 三态参数 ───

@router.get("/mr_backtest_results")
async def get_mr_backtest_results():
    fp = "mr_optimization_results.json"
    if not os.path.exists(fp):
        return {"status": "error", "message": "请先运行 mr_regime_backtest.py"}
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/mr_per_regime_params")
async def get_per_regime_params():
    """返回三态（BEAR/RANGE/BULL）各自的回测最优参数"""
    try:
        return {
            "status": "ok",
            "regimes": get_all_regime_params(),
            "needs_reoptimize": needs_reoptimize(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/mr_current_params")
async def get_current_regime_params():
    """实时识别当前市场状态，返回对应的最优参数"""
    try:
        info = detect_regime()
        return {
            "status":      "ok",
            "regime":      info.get("regime"),
            "params":      info.get("params", {}),
            "pos_cap":     info.get("pos_cap"),
            "score_gate":  info.get("score_gate"),
            "csi300":      info.get("csi300"),
            "ret5":        info.get("ret5"),
            "ret20":       info.get("ret20"),
            "needs_reoptimize": info.get("needs_reoptimize", False),
            "all_regimes": get_all_regime_params(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
