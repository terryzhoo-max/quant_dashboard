"""
AlphaCore · 策略 API 路由
==========================
Batch 7 架构解耦: 从 main.py 提取全部策略 API

包含:
  - /api/v1/strategy (均值回归)
  - /api/v1/dividend_strategy (红利趋势)
  - /api/v1/momentum_strategy (动量轮动)
  - /api/v1/erp_strategy (ERP择时)
  - /api/v1/aiae_strategy (AIAE ETF信号)
  - /api/v1/strategy/run-all (五策略并行 + 共振 + 风险覆盖)
"""

import asyncio
import threading
from datetime import datetime as _dt
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter
from services.logger import get_logger

logger = get_logger("strategy")

from mean_reversion_engine import run_strategy
from dividend_trend_engine import run_dividend_strategy
from momentum_rotation_engine import run_momentum_strategy
from erp_timing_engine import get_erp_engine
from aiae_engine import get_aiae_engine, REGIMES as AIAE_REGIMES
from services.cache_service import cache_manager

router = APIRouter(prefix="/api/v1", tags=["strategy"])
executor = ThreadPoolExecutor(max_workers=10)
_STRATEGY_LOCK = threading.Lock()


# ─────────────────────────────────────────────
# ERP 标的池定义
# ─────────────────────────────────────────────
ERP_TARGET_POOL = [
    {"ts_code": "510300.SH", "name": "沪深300ETF", "style": "核心宽基"},
    {"ts_code": "510500.SH", "name": "中证500ETF", "style": "中盘成长"},
    {"ts_code": "510880.SH", "name": "红利ETF",    "style": "防御红利"},
    {"ts_code": "510900.SH", "name": "H股ETF",     "style": "港股宽基"},
]


# ═══════════════════════════════════════════════
#  单策略 API
# ═══════════════════════════════════════════════

@router.get("/strategy")
async def get_strategy():
    """均值回归策略详情 — V4.2 包装层"""
    from dashboard_modules.run_strategies import wrap_mr_results
    if cache_manager.get_json("strategy_results", {}).get("mr"):
        cached = cache_manager.get_json("strategy_results", {}).get("mr")
        if isinstance(cached, dict) and "status" in cached:
            return cached
        return wrap_mr_results(cached)
    raw = await asyncio.get_running_loop().run_in_executor(executor, run_strategy)
    wrapped = wrap_mr_results(raw)
    _sr = cache_manager.get_json("strategy_results", {}); _sr["mr"] = wrapped; cache_manager.set_json("strategy_results", _sr)
    return wrapped


@router.get("/dividend_strategy")
async def get_dividend_strategy(regime: str = None):
    """红利增强策略详情 V3.1 · 支持市场状态参数"""
    if not regime and cache_manager.get_json("strategy_results", {}).get("div"):
        return cache_manager.get_json("strategy_results", {}).get("div")
    result = await asyncio.get_running_loop().run_in_executor(
        executor, lambda: run_dividend_strategy(regime=regime)
    )
    if not regime:
        _sr = cache_manager.get_json("strategy_results", {}); _sr["div"] = result; cache_manager.set_json("strategy_results", _sr)
    return result


@router.get("/momentum_strategy")
async def get_momentum_strategy():
    """行业动量策略详情"""
    if cache_manager.get_json("strategy_results", {}).get("mom"):
        return cache_manager.get_json("strategy_results", {}).get("mom")
    return await asyncio.get_running_loop().run_in_executor(executor, run_momentum_strategy)


# ─────────────────────────────────────────────
# ERP 宏观择时策略
# ─────────────────────────────────────────────
def _run_erp_strategy() -> dict:
    """ERP策略执行：获取宏观评分 → 对标的池ETF生成标准化信号"""
    try:
        engine = get_erp_engine()
        report = engine.compute_signal()
        if report.get("status") not in ("success", "fallback"):
            return {"status": "error", "message": report.get("message", "ERP引擎异常")}

        score = report["signal"]["score"]
        snap = report["current_snapshot"]
        dims = report["dimensions"]

        if score >= 55:
            std_signal = "buy"
        elif score <= 40:
            std_signal = "sell"
        else:
            std_signal = "hold"

        pos_map = {"buy": 80, "hold": 50, "sell": 0}
        base_pos = pos_map.get(std_signal, 50)

        signals = []
        for etf in ERP_TARGET_POOL:
            signals.append({
                "name": etf["name"], "ts_code": etf["ts_code"],
                "code": etf["ts_code"].split(".")[0],
                "signal": std_signal, "signal_score": round(score),
                "suggested_position": base_pos if std_signal == "buy" else 0,
                "style": etf["style"],
                "erp_abs": snap.get("erp_value", 0),
                "erp_pct": snap.get("erp_percentile", 0),
                "m1_yoy": dims.get("m1_trend", {}).get("m1_info", {}).get("current", 0),
                "pe_vol": dims.get("volatility", {}).get("vol_info", {}).get("current_vol", 0),
                "scissor": dims.get("credit", {}).get("credit_info", {}).get("scissor", 0),
            })

        buy_count = sum(1 for s in signals if s["signal"] == "buy")
        sell_count = sum(1 for s in signals if s["signal"] == "sell")

        return {
            "status": "success", "timestamp": _dt.now().isoformat(),
            "data": {
                "signals": signals,
                "market_overview": {
                    "composite_score": round(score),
                    "signal_key": std_signal,
                    "signal_label": report["signal"]["label"],
                    "buy_count": buy_count, "sell_count": sell_count,
                    "total_suggested_pos": sum(s["suggested_position"] for s in signals if s["signal"] == "buy"),
                },
            },
        }
    except Exception as e:
        logger.error(f"ERP Strategy Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.get("/erp_strategy")
async def get_erp_strategy():
    """ERP宏观择时策略实时信号"""
    return await asyncio.get_running_loop().run_in_executor(executor, _run_erp_strategy)


# ─────────────────────────────────────────────
# AIAE 宏观仓位管控策略
# ─────────────────────────────────────────────
def _run_aiae_strategy() -> dict:
    """AIAE策略执行：获取AIAE五档判定 → 对ETF标的池生成标准化信号"""
    try:
        engine = get_aiae_engine()
        report = engine.generate_report()

        if report.get("status") not in ("success", "fallback"):
            return {"status": "error", "message": "AIAE引擎异常"}

        regime = report["current"]["regime"]
        regime_info = report["current"]["regime_info"]
        aiae_v1 = report["current"]["aiae_v1"]
        matrix_pos = report["position"]["matrix_position"]

        signals = engine.generate_etf_signals(regime)

        erp_score_for_weights = None
        try:
            erp_eng = get_erp_engine()
            erp_sig = erp_eng.compute_signal()
            if erp_sig.get("status") == "success":
                erp_score_for_weights = erp_sig["signal"].get("score", None)
        except Exception:
            pass

        run_all_weights, erp_tier = engine.get_run_all_weights(regime, erp_score_for_weights)

        buy_count = sum(1 for s in signals if s["signal"] == "buy")
        sell_count = sum(1 for s in signals if s["signal"] == "sell")

        return {
            "status": "success", "timestamp": _dt.now().isoformat(),
            "data": {
                "signals": signals,
                "market_overview": {
                    "aiae_value": aiae_v1, "regime": regime,
                    "regime_cn": regime_info["cn"], "matrix_position": matrix_pos,
                    "buy_count": buy_count, "sell_count": sell_count,
                    "composite_score": max(10, 100 - (regime - 1) * 20),
                    "erp_score_for_weights": erp_score_for_weights,
                    "erp_tier": erp_tier,
                },
                "run_all_weights": run_all_weights,
                "erp_tier": erp_tier,
                "aiae_report": report,
            },
        }
    except Exception as e:
        logger.error(f"AIAE Strategy Error: {e}", exc_info=True)
        try:
            engine = get_aiae_engine()
            fallback_signals = engine.generate_etf_signals(3)
            return {
                "status": "fallback", "timestamp": _dt.now().isoformat(),
                "data": {
                    "signals": fallback_signals,
                    "market_overview": {
                        "aiae_value": 22.0, "regime": 3, "regime_cn": "中性均衡",
                        "matrix_position": 55, "buy_count": 5, "sell_count": 0,
                        "composite_score": 60,
                    },
                    "run_all_weights": engine.get_run_all_weights(3, None)[0],
                },
            }
        except Exception as e2:
            return {"status": "error", "message": str(e2)}


@router.get("/aiae_strategy")
async def get_aiae_strategy():
    """AIAE ETF标的池实时信号"""
    return await asyncio.get_running_loop().run_in_executor(executor, _run_aiae_strategy)


# ═══════════════════════════════════════════════
#  五策略并行 + 共振分析 + 风险覆盖
# ═══════════════════════════════════════════════

def _extract_signals_normalized(strategy_type: str, raw_result) -> list:
    """从各策略原始返回中提取标准化信号列表"""
    if isinstance(raw_result, dict) and "data" in raw_result:
        return raw_result["data"].get("signals", [])
    if strategy_type == "mr" and isinstance(raw_result, list):
        return [s for s in raw_result if s.get("signal") != "error"]
    return []


def _compute_resonance(mr_signals, div_signals, mom_signals, erp_signals=None, aiae_signals=None):
    """计算五策略信号共振：找到多策略一致看好/看空的重叠标的 (V4.2)"""
    if erp_signals is None: erp_signals = []
    if aiae_signals is None: aiae_signals = []

    def build_map(signals):
        m = {}
        for s in signals:
            code = s.get("ts_code") or s.get("code", "")
            if code:
                m[code] = {
                    "name": s.get("name", ""), "signal": s.get("signal", "hold"),
                    "score": s.get("signal_score", 0), "position": s.get("suggested_position", 0),
                }
        return m

    mr_map, div_map, mom_map = build_map(mr_signals), build_map(div_signals), build_map(mom_signals)
    erp_map, aiae_map = build_map(erp_signals), build_map(aiae_signals)

    all_codes = set(list(mr_map.keys()) + list(div_map.keys()) + list(mom_map.keys()) + list(erp_map.keys()) + list(aiae_map.keys()))

    consensus_buy, consensus_sell, divergence = [], [], []

    for code in all_codes:
        maps = {"mr": mr_map, "div": div_map, "mom": mom_map, "erp": erp_map, "aiae": aiae_map}
        present = sum(1 for m in maps.values() if code in m)
        if present < 2:
            continue

        name = next((maps[k].get(code, {}).get("name", code) for k in maps if code in maps[k]), code)
        signals = {k: maps[k].get(code, {}).get("signal", "-") for k in maps}
        scores = {k: maps[k].get(code, {}).get("score", 0) for k in maps}

        buy_count = sum(1 for v in signals.values() if v == "buy")
        sell_count = sum(1 for v in signals.values() if v in ("sell", "sell_half", "sell_weak"))

        entry = {"code": code, "name": name, "signals": signals, "scores": scores}

        if buy_count >= 2:
            entry["resonance"], entry["label"] = "strong_buy", "Strong Buy Resonance"
            consensus_buy.append(entry)
        elif sell_count >= 2:
            entry["resonance"], entry["label"] = "strong_sell", "Strong Sell Resonance"
            consensus_sell.append(entry)
        elif buy_count >= 1 and sell_count >= 1:
            entry["resonance"], entry["label"] = "divergence", "Signal Divergence"
            divergence.append(entry)

    consensus_buy.sort(key=lambda x: sum(x["scores"].values()), reverse=True)
    consensus_sell.sort(key=lambda x: sum(x["scores"].values()))

    return {
        "consensus_buy": consensus_buy, "consensus_sell": consensus_sell,
        "divergence": divergence,
        "total_overlap": len(consensus_buy) + len(consensus_sell) + len(divergence),
    }


def _compute_risk_overlay(all_signals):
    """计算风险覆盖层：集中度+波动率预警"""
    sector_counts = {}
    vol_alerts = []

    for s in all_signals:
        group = s.get("group", s.get("sector", "unknown"))
        if group and group != "unknown":
            sector_counts[group] = sector_counts.get(group, 0) + 1
        vol = s.get("vol_30d", s.get("annualized_vol", 0))
        if vol and float(vol) > 25:
            vol_alerts.append({"name": s.get("name", ""), "code": s.get("ts_code") or s.get("code", ""), "vol_30d": round(float(vol), 1)})

    top_sector = max(sector_counts, key=sector_counts.get) if sector_counts else "N/A"
    top_ratio = round(sector_counts.get(top_sector, 0) / max(len(all_signals), 1) * 100) if sector_counts else 0
    vol_alerts.sort(key=lambda x: x["vol_30d"], reverse=True)

    return {
        "concentration": {
            "top_sector": top_sector, "ratio": f"{top_ratio}%",
            "sectors": dict(sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:5]),
        },
        "volatility_alerts": vol_alerts[:5], "alert_count": len(vol_alerts),
    }


@router.get("/strategy/run-all")
async def run_all_strategies_api(override_cap: int = None):
    """V4.0 五策略并行执行 (MR+DIV+MOM+ERP+AIAE_ETF)
    + AIAE主控仓位Cap + 动态权重 + 共振分析
    """
    loop = asyncio.get_running_loop()

    try:
        # ── 并行执行5策略 ──
        mr_task   = loop.run_in_executor(executor, run_strategy)
        div_task  = loop.run_in_executor(executor, lambda: run_dividend_strategy(regime=None))
        mom_task  = loop.run_in_executor(executor, run_momentum_strategy)
        erp_task  = loop.run_in_executor(executor, _run_erp_strategy)
        aiae_task = loop.run_in_executor(executor, _run_aiae_strategy)

        mr_raw, div_raw, mom_raw, erp_raw, aiae_raw = await asyncio.gather(
            mr_task, div_task, mom_task, erp_task, aiae_task
        )

        from dashboard_modules.run_strategies import wrap_mr_results
        mr_result = wrap_mr_results(mr_raw) if isinstance(mr_raw, list) else mr_raw
        div_result, mom_result, erp_result, aiae_result = div_raw, mom_raw, erp_raw, aiae_raw

        with _STRATEGY_LOCK:
            _sr = cache_manager.get_json("strategy_results", {})
            _sr["mr"] = mr_result; _sr["div"] = div_result; _sr["mom"] = mom_result
            cache_manager.set_json("strategy_results", _sr)

        # 提取标准化信号
        mr_signals   = _extract_signals_normalized("mr", mr_result)
        div_signals  = _extract_signals_normalized("div", div_result)
        mom_signals  = _extract_signals_normalized("mom", mom_result)
        erp_signals  = _extract_signals_normalized("erp", erp_result)
        aiae_signals = _extract_signals_normalized("aiae_etf", aiae_result)

        resonance = _compute_resonance(mr_signals, div_signals, mom_signals, erp_signals, aiae_signals)

        all_buy_signals = (
            [s for s in mr_signals if s.get("signal") == "buy"] +
            [s for s in div_signals if s.get("signal") == "buy"] +
            [s for s in mom_signals if s.get("signal") == "buy"] +
            [s for s in aiae_signals if s.get("signal") == "buy"]
        )
        risk_overlay = _compute_risk_overlay(all_buy_signals)

        # 全局指标
        mr_ov   = mr_result.get("data", {}).get("market_overview", {}) if isinstance(mr_result, dict) else {}
        div_ov  = div_result.get("data", {}).get("market_overview", {}) if isinstance(div_result, dict) else {}
        mom_ov  = mom_result.get("data", {}).get("market_overview", {}) if isinstance(mom_result, dict) else {}
        erp_ov  = erp_result.get("data", {}).get("market_overview", {}) if isinstance(erp_result, dict) else {}
        aiae_ov = aiae_result.get("data", {}).get("market_overview", {}) if isinstance(aiae_result, dict) else {}

        mr_regime = mr_signals[0].get("regime", "RANGE") if mr_signals else "RANGE"
        total_buy = (mr_ov.get("signal_count", {}).get("buy", 0) + div_ov.get("buy_count", 0) +
                     mom_ov.get("buy_count", 0) + erp_ov.get("buy_count", 0) + aiae_ov.get("buy_count", 0))
        total_sell = (mr_ov.get("signal_count", {}).get("sell", 0) + div_ov.get("sell_count", 0) +
                      mom_ov.get("sell_count", 0) + erp_ov.get("sell_count", 0) + aiae_ov.get("sell_count", 0))

        # ─── 科学仓位计算 V4.0 (AIAE主控) ───
        def _avg_confidence(signals_list):
            buy_sigs = [s for s in signals_list if s.get("signal") == "buy"]
            if not buy_sigs: return 0.0
            positions = [s.get("suggested_position", 0) for s in buy_sigs]
            return sum(positions) / len(positions) if positions else 0.0

        mr_conf, div_conf = _avg_confidence(mr_signals), _avg_confidence(div_signals)
        mom_conf, erp_conf = _avg_confidence(mom_signals), _avg_confidence(erp_signals)
        aiae_conf = _avg_confidence(aiae_signals)

        aiae_regime = aiae_ov.get("regime", 3)
        erp_score = erp_ov.get("composite_score", 50)

        aiae_weights = aiae_result.get("data", {}).get("run_all_weights", None)
        erp_tier = aiae_result.get("data", {}).get("erp_tier", "neutral")

        if aiae_weights:
            w = aiae_weights
        else:
            try:
                engine = get_aiae_engine()
                w, erp_tier = engine.get_run_all_weights(aiae_regime, erp_score)
            except Exception:
                w = {"mr": 0.15, "div": 0.30, "mom": 0.10, "erp": 0.15, "aiae_etf": 0.30}
                erp_tier = "neutral"

        raw_pos = round(
            mr_conf * w["mr"] + div_conf * w["div"] + mom_conf * w["mom"] +
            erp_conf * w["erp"] + aiae_conf * w["aiae_etf"]
        )

        aiae_cap = aiae_ov.get("matrix_position", 65)
        ma_cap_map = {"BULL": 95, "RANGE": 70, "BEAR": 50, "CRASH": 20}
        ma_cap = ma_cap_map.get(mr_regime, 70)
        cap = min(aiae_cap, ma_cap)

        override_active = False
        original_cap = cap
        if override_cap is not None and 0 <= override_cap <= 100:
            cap = override_cap
            override_active = True
            logger.info(f"手动覆盖仓位Cap: {original_cap}% → {cap}%")

        avg_pos = min(raw_pos, cap)

        # V2.1: 矩阵锚定地板
        regime_info_for_floor = AIAE_REGIMES.get(aiae_regime, AIAE_REGIMES[3])
        regime_floor = regime_info_for_floor.get("pos_min", 50)
        if erp_tier == "bull":
            regime_floor = min(regime_floor + 5, cap)
        elif erp_tier == "bear":
            regime_floor = max(regime_floor - 10, 0)

        avg_pos = max(avg_pos, regime_floor)
        logger.info(f"矩阵锚定: raw={raw_pos}% floor={regime_floor}%(R{aiae_regime}/{erp_tier}) cap={cap}% → final={avg_pos}%")

        erp_cap_active = False

        regimes = [mr_regime]
        div_regime = div_result.get("data", {}).get("regime_params", {}).get("regime", "RANGE") if isinstance(div_result, dict) else "RANGE"
        regimes.append(div_regime)
        consistency = "high" if len(set(regimes)) == 1 else "low"

        if consistency != "high" and not override_active:
            avg_pos = max(round(avg_pos * 0.8), regime_floor)

        return {
            "status": "success", "timestamp": _dt.now().isoformat(),
            "data": {
                "global": {
                    "regime": mr_regime, "total_position": avg_pos,
                    "regime_cap": cap, "total_buy": total_buy, "total_sell": total_sell,
                    "consistency": consistency, "strategy_count": 5,
                    "erp_score": erp_score, "erp_cap_active": erp_cap_active,
                    "confidence": {
                        "mr": round(mr_conf), "div": round(div_conf), "mom": round(mom_conf),
                        "erp": round(erp_conf), "aiae_etf": round(aiae_conf),
                    },
                    "weights": w,
                    "aiae": {
                        "regime": aiae_regime, "regime_cn": aiae_ov.get("regime_cn", "中性均衡"),
                        "aiae_value": aiae_ov.get("aiae_value", 22.0),
                        "aiae_cap": aiae_cap, "regime_floor": regime_floor,
                        "raw_pos": raw_pos, "ma_cap": ma_cap, "erp_tier": erp_tier,
                        "erp_score_tier": {"bull": "🟢看多", "neutral": "🟡中性", "bear": "🔴看空"}.get(erp_tier, "🟡中性"),
                        "override_active": override_active,
                        "override_cap": override_cap if override_active else None,
                        "original_cap": original_cap,
                    },
                },
                "strategies": {
                    "mr": mr_result.get("data", mr_result) if isinstance(mr_result, dict) else {"signals": mr_signals},
                    "div": div_result.get("data", div_result) if isinstance(div_result, dict) else {"signals": div_signals},
                    "mom": mom_result.get("data", mom_result) if isinstance(mom_result, dict) else {"signals": mom_signals},
                    "erp": erp_result.get("data", erp_result) if isinstance(erp_result, dict) else {"signals": erp_signals},
                    "aiae_etf": aiae_result.get("data", aiae_result) if isinstance(aiae_result, dict) else {"signals": aiae_signals},
                },
                "resonance": resonance,
                "risk_overlay": risk_overlay,
            },
        }
    except Exception as e:
        import traceback
        logger.error(f"RUN-ALL 异常: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}
