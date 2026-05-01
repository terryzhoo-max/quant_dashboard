"""AlphaCore 市场/ERP/利率/个股查询 API — 从 main.py 提取"""
import asyncio
import time
import traceback
import logging
from datetime import datetime
from typing import Dict
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter

import tushare as ts
from config import TUSHARE_TOKEN
from erp_timing_engine import get_erp_engine
from erp_hk_engine import get_hk_erp_engine

router = APIRouter(prefix="/api/v1", tags=["market"])
executor = ThreadPoolExecutor(max_workers=4)
logger = logging.getLogger("alphacore.market")

# 个股名称本地缓存
_NAME_CACHE: Dict[str, str] = {}


@router.get("/strategy/erp-timing")
async def get_erp_timing():
    """宏观ERP择时引擎 — V2: SWR 三级缓存 (1h fresh / 6h stale)"""
    from services.cache_service import stale_while_revalidate

    def _compute():
        engine = get_erp_engine()
        report = engine.generate_report()
        return {"status": "success", "data": report}

    return stale_while_revalidate("swr_erp_timing", _compute, fresh_ttl=3600, stale_ttl=21600)


@router.get("/strategy/erp-global")
async def get_erp_global():
    """海外ERP择时 — V2: SWR 三级缓存 (30min fresh / 4h stale)"""
    from services.cache_service import stale_while_revalidate
    return stale_while_revalidate("swr_erp_global", _compute_erp_global, fresh_ttl=1800, stale_ttl=14400)


def _compute_erp_global():
    """全球 ERP 计算核心 (5引擎并行)"""
    from erp_us_engine import get_us_erp_engine
    from erp_jp_engine import get_jp_erp_engine
    import numpy as np

    us_engine = get_us_erp_engine()
    jp_engine = get_jp_erp_engine()
    cn_engine = get_erp_engine()
    hk_hsi_engine = get_hk_erp_engine("HSI")
    hk_tech_engine = get_hk_erp_engine("HSTECH")

    us_report = us_engine.generate_report()
    jp_report = jp_engine.generate_report()
    cn_signal = cn_engine.compute_signal()
    hk_hsi_report = hk_hsi_engine.generate_report()
    hk_tech_report = hk_tech_engine.generate_report()

    cn_snap = cn_signal.get("current_snapshot", {})
    cn_sig = cn_signal.get("signal", {})
    hk_hsi_snap = hk_hsi_report.get("current_snapshot", {})
    hk_hsi_sig = hk_hsi_report.get("signal", {})

    def _extract_region(snap, sig):
        return {
            "erp": snap.get("erp_value", 0), "score": sig.get("score", 0),
            "key": sig.get("key", "hold"), "label": sig.get("label", "--"),
            "color": sig.get("color", "#94a3b8"), "emoji": sig.get("emoji", ""),
            "pe": snap.get("pe_ttm", 0), "yield": snap.get("yield_10y", snap.get("blended_rf", 0)),
        }

    global_comparison = {
        "cn": _extract_region(cn_snap, cn_sig),
        "us": _extract_region(us_report.get("current_snapshot", {}), us_report.get("signal", {})),
        "jp": _extract_region(jp_report.get("current_snapshot", {}), jp_report.get("signal", {})),
        "hk": _extract_region(hk_hsi_snap, hk_hsi_sig),
    }

    scores = {r: global_comparison[r]["score"] for r in ["cn", "us", "jp", "hk"]}
    sorted_r = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    rn = {"cn": "A股", "us": "美股", "jp": "日股", "hk": "港股"}

    vals = np.array([scores[r] for r in ["cn", "us", "jp", "hk"]], dtype=float)
    exp_vals = np.exp((vals - vals.mean()) / 20.0)
    softmax_ratios = exp_vals / exp_vals.sum()
    us_jp_pct = (softmax_ratios[1] + softmax_ratios[2]) * 100
    if us_jp_pct > 55:
        excess = (us_jp_pct - 55) / 100
        softmax_ratios[1] -= excess * 0.5
        softmax_ratios[2] -= excess * 0.5
        softmax_ratios[0] += excess * 0.3
        softmax_ratios[3] += excess * 0.2
    raw_alloc = np.maximum(softmax_ratios * 100, 10)
    raw_alloc = (raw_alloc / raw_alloc.sum() * 100).round().astype(int)
    alloc = dict(zip(["cn", "us", "jp", "hk"], raw_alloc.tolist()))
    diff = 100 - sum(alloc.values())
    alloc[sorted_r[0][0]] += diff

    global_comparison["allocation"] = alloc
    global_comparison["advice"] = f"超配{rn[sorted_r[0][0]]}({sorted_r[0][1]:.0f}), 低配{rn[sorted_r[-1][0]]}({sorted_r[-1][1]:.0f})"
    global_comparison["allocation_text"] = f"🇨🇳 {alloc['cn']}% / 🇺🇸 {alloc['us']}% / 🇯🇵 {alloc['jp']}% / 🇭🇰 {alloc['hk']}%"

    return {"status": "success", "us": us_report, "jp": jp_report,
            "hk_hsi": hk_hsi_report, "hk_tech": hk_tech_report,
            "global_comparison": global_comparison, "updated_at": datetime.now().isoformat()}


@router.get("/strategy/rates")
async def get_rates_strategy():
    """利率择时 — V2: SWR 三级缓存 (1h fresh / 6h stale)"""
    from services.cache_service import stale_while_revalidate

    def _compute():
        from rates_strategy_engine import get_rates_engine
        engine = get_rates_engine()
        report = engine.generate_report()
        return {"status": "success", "data": report}

    return stale_while_revalidate("swr_rates", _compute, fresh_ttl=3600, stale_ttl=21600)


@router.get("/stock/name")
async def get_stock_name(ts_code: str):
    """查询单只标的的中文名称，支持 A 股和场内 ETF"""
    ts_code = ts_code.strip().upper()

    if ts_code in _NAME_CACHE:
        return {"ts_code": ts_code, "name": _NAME_CACHE[ts_code], "type": "cached"}

    def do_lookup():
        pro = ts.pro_api(TUSHARE_TOKEN)
        suffix = ts_code.split(".")[-1] if "." in ts_code else ""
        code_num = ts_code.split(".")[0] if "." in ts_code else ts_code

        try:
            df_fund = pro.fund_basic(ts_code=ts_code, market="E")
            if df_fund is not None and not df_fund.empty:
                name = df_fund.iloc[0]["name"]
                _NAME_CACHE[ts_code] = name
                return {"ts_code": ts_code, "name": name, "type": "etf"}
        except Exception:
            pass

        try:
            df_stock = pro.stock_basic(ts_code=ts_code, fields="ts_code,name")
            if df_stock is not None and not df_stock.empty:
                name = df_stock.iloc[0]["name"]
                _NAME_CACHE[ts_code] = name
                return {"ts_code": ts_code, "name": name, "type": "stock"}
        except Exception:
            pass

        try:
            df_idx = pro.index_basic(ts_code=ts_code, fields="ts_code,name")
            if df_idx is not None and not df_idx.empty:
                name = df_idx.iloc[0]["name"]
                _NAME_CACHE[ts_code] = name
                return {"ts_code": ts_code, "name": name, "type": "index"}
        except Exception:
            pass

        return {"ts_code": ts_code, "name": ts_code, "type": "unknown"}

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, do_lookup)
        return result
    except Exception as e:
        logger.error(f"[StockName] Error for {ts_code}: {e}")
        return {"ts_code": ts_code, "name": ts_code, "type": "unknown"}
