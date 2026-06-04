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

from fastapi import APIRouter, Query
from services.logger import get_logger

logger = get_logger("strategy")

from mean_reversion_engine import run_strategy
from dividend_trend_engine import run_dividend_strategy
from momentum_rotation_engine import run_momentum_strategy
from dual_momentum_engine import run_gem_strategy
from erp_timing_engine import get_erp_engine
from aiae_engine import get_aiae_engine, REGIMES as AIAE_REGIMES
from services.cache_service import cache_manager, stale_while_revalidate
# P0-4: 使用统一的策略缓存写入锁 (与 dashboard_builder / main.py 共享同一实例)
from services.dashboard_builder import _STRATEGY_LOCK

router = APIRouter(prefix="/api/v1", tags=["strategy"])
executor = ThreadPoolExecutor(max_workers=10)


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

# ── V22.0: 信号参数对比 (旧通用 vs 新资产分类) ──

@router.get("/strategy/signal-compare")
async def signal_compare():
    """
    对比新旧参数系统的信号差异。
    使用缓存的 MR 信号数据 + 资产类别参数重新评分。
    """
    try:
        from services.cache_service import cache_manager
        from engines.mean_reversion_engine import (
            calculate_score, get_asset_params, get_asset_class_label,
            FALLBACK_PARAMS, MR_POOL,
        )

        cached = cache_manager.get_json("strategy_results", {})
        mr_data = cached.get("mr", {})
        if isinstance(mr_data, dict):
            signals = mr_data.get("data", {}).get("buy_signals", []) + \
                      mr_data.get("data", {}).get("hold_signals", []) + \
                      mr_data.get("data", {}).get("sell_signals", [])
        else:
            signals = []

        if not signals:
            return {"status": "error", "message": "无缓存 MR 信号, 请先运行策略"}

        comparison = []
        for s in signals[:25]:  # 最多 25 只
            code = s.get("ts_code") or s.get("code", "")
            name = s.get("name", "")
            regime = s.get("regime", "RANGE")

            # 当前信号分数
            old_score = s.get("signal_score") or s.get("score", 0)

            # 用新参数重算评分 (基于现有指标值的理论分数)
            # 注意: 这里用现有指标近似估算, 非完整重新计算
            try:
                asset_class = get_asset_class_label(code, name)
                new_params = get_asset_params(code, regime, name)
                old_params = FALLBACK_PARAMS.get(regime, FALLBACK_PARAMS["RANGE"])

                # 关键参数差异
                rsi_buy_old = old_params.get("rsi_buy", 40)
                rsi_buy_new = new_params.get("rsi_buy", 40)
                bias_buy_old = old_params.get("bias_buy", -2.0)
                bias_buy_new = new_params.get("bias_buy", -2.0)
                stop_old = f'{old_params.get("stop_loss", 0.07)*100:.0f}%'
                stop_new = f'{new_params.get("stop_loss", 0.08)*100:.0f}%'

                rsi_val = s.get("rsi", 50)
                # RSI 阈值越紧 → 信号越难触发 → 当前分数理论降低
                rsi_delta = (rsi_buy_old - rsi_buy_new) * (-0.3)  # 粗略映射
                bias_val = s.get("bias", 0)
                bias_delta = (abs(bias_buy_old) - abs(bias_buy_new)) * 1.5

                new_score_est = min(100, max(0, round(old_score + rsi_delta + bias_delta)))
                score_delta = round(new_score_est - old_score, 1)

                comparison.append({
                    "code": code,
                    "name": name,
                    "asset_class": asset_class,
                    "regime": regime,
                    "old_score": old_score,
                    "new_score_est": new_score_est,
                    "score_delta": score_delta,
                    "rsi_buy_old": rsi_buy_old,
                    "rsi_buy_new": rsi_buy_new,
                    "bias_buy_old": bias_buy_old,
                    "bias_buy_new": bias_buy_new,
                    "stop_loss_old": stop_old,
                    "stop_loss_new": stop_new,
                })
            except Exception:
                comparison.append({
                    "code": code, "name": name, "error": "计算异常",
                })

        # 统计
        improved = sum(1 for c in comparison if c.get("score_delta", 0) > 3)
        worsened = sum(1 for c in comparison if c.get("score_delta", 0) < -3)
        changed = sum(1 for c in comparison if abs(c.get("score_delta", 0)) > 3)

        return {
            "status": "success",
            "total": len(comparison),
            "improved": improved,
            "worsened": worsened,
            "unchanged": len(comparison) - changed,
            "comparison": comparison,
        }
    except Exception as e:
        logger.error(f"Signal Compare Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.get("/strategy")
async def get_strategy():
    """均值回归策略详情 — V4.2 含缓存优化"""
    from dashboard_modules.run_strategies import wrap_mr_results
    cached = cache_manager.get_json("strategy_results", {}).get("mr")
    if cached:
        if isinstance(cached, dict) and "status" in cached:
            return cached
        return wrap_mr_results(cached)
    raw = await asyncio.get_running_loop().run_in_executor(executor, run_strategy)
    wrapped = wrap_mr_results(raw)
    with _STRATEGY_LOCK:
        _sr = cache_manager.get_json("strategy_results", {})
        _sr["mr"] = wrapped
        cache_manager.set_json("strategy_results", _sr, ttl_seconds=86400)
    return wrapped


@router.get("/dividend_strategy")
async def get_dividend_strategy(regime: str = None):
    """红利增强策略详情 V3.1 · 含缓存优化"""
    if regime and regime not in ("BULL", "RANGE", "BEAR", "CRASH"):
        return {"status": "error", "message": f"无效 regime: {regime}"}
    if not regime:
        cached = cache_manager.get_json("strategy_results", {}).get("div")
        if cached:
            return cached
    result = await asyncio.get_running_loop().run_in_executor(
        executor, lambda: run_dividend_strategy(regime=regime)
    )
    if not regime and isinstance(result, dict) and result.get("status") == "success":
        with _STRATEGY_LOCK:
            _sr = cache_manager.get_json("strategy_results", {})
            _sr["div"] = result
            cache_manager.set_json("strategy_results", _sr, ttl_seconds=86400)
    return result


@router.get("/momentum_strategy")
async def get_momentum_strategy():
    """行业动量策略详情 — V3.1 含缓存写回"""
    cached = cache_manager.get_json("strategy_results", {}).get("mom")
    if cached:
        return cached
    result = await asyncio.get_running_loop().run_in_executor(executor, run_momentum_strategy)
    # V3.1: 写回缓存，供页面自动加载和后续请求复用
    if isinstance(result, dict) and result.get("status") == "success":
        with _STRATEGY_LOCK:
            _sr = cache_manager.get_json("strategy_results", {})
            _sr["mom"] = result
            cache_manager.set_json("strategy_results", _sr, ttl_seconds=86400)
    return result


# ─────────────────────────────────────────────
# GEM 双重动量策略 (第 1.5 层战术资产配置)
# ─────────────────────────────────────────────
_GEM_SWR_KEY = "swr_gem_strategy"
_GEM_FRESH_TTL = 1800   # 30 分钟内直接返回缓存 (GEM 月度调仓, 不需要秒级)
_GEM_STALE_TTL = 21600  # 6 小时过期容忍 (Tushare 限频, 避免重复调用)


def _run_gem_strategy() -> dict:
    """GEM 策略执行包装 (与其他策略统一格式)"""
    try:
        result = run_gem_strategy()
        # 同步写入 strategy_results 缓存 (供 run-all / decision hub 读取)
        with _STRATEGY_LOCK:
            _sr = cache_manager.get_json("strategy_results", {})
            _sr["gem"] = result
            cache_manager.set_json("strategy_results", _sr, ttl_seconds=86400)
        return result
    except Exception as e:
        logger.error(f"GEM Strategy Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.get("/gem_strategy")
async def get_gem_strategy_api(refresh: int = 0):
    """双重动量策略信号 (GEM) — 第 1.5 层战术资产配置

    生产级接口:
      - SWR 三级缓存 (Fresh 30min / Stale 6h / Miss 同步计算)
      - ?refresh=1 强制跳过缓存重新计算
      - 计算结果同时写入 strategy_results (供 run-all / decision hub 联动)
    """
    # ?refresh=1 → 清除 SWR 缓存, 强制重算
    if refresh:
        from services.cache_service import swr_clear
        swr_clear(_GEM_SWR_KEY)
        # 同时清除 strategy_results 中的 gem 缓存
        with _STRATEGY_LOCK:
            _sr = cache_manager.get_json("strategy_results", {})
            _sr.pop("gem", None)
            cache_manager.set_json("strategy_results", _sr, ttl_seconds=86400)

    # 优先检查 strategy_results 缓存 (run-all 写入的)
    cached = cache_manager.get_json("strategy_results", {}).get("gem")
    if cached and not refresh:
        if isinstance(cached, dict) and cached.get("status") == "success":
            return cached

    # SWR 三级缓存
    return await asyncio.get_running_loop().run_in_executor(
        executor,
        lambda: stale_while_revalidate(_GEM_SWR_KEY, _run_gem_strategy, _GEM_FRESH_TTL, _GEM_STALE_TTL)
    )


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

        signals = engine.generate_etf_signals(regime, matrix_position=matrix_pos)

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


def _compute_resonance(mr_signals, div_signals, mom_signals, erp_signals=None, aiae_signals=None, gem_signals=None):
    """计算六策略信号共振：找到多策略一致看好/看空的重叠标的 (V5.0 含 GEM)"""
    if erp_signals is None: erp_signals = []
    if aiae_signals is None: aiae_signals = []
    if gem_signals is None: gem_signals = []

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
    erp_map, aiae_map, gem_map = build_map(erp_signals), build_map(aiae_signals), build_map(gem_signals)

    all_codes = set(list(mr_map.keys()) + list(div_map.keys()) + list(mom_map.keys()) + list(erp_map.keys()) + list(aiae_map.keys()) + list(gem_map.keys()))

    consensus_buy, consensus_sell, divergence = [], [], []

    for code in all_codes:
        maps = {"mr": mr_map, "div": div_map, "mom": mom_map, "erp": erp_map, "aiae": aiae_map, "gem": gem_map}
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
async def run_all_strategies_api(override_cap: int = Query(default=None, ge=0, le=100)):
    """V5.0 六策略并行执行 (MR+DIV+MOM+GEM+ERP+AIAE_ETF)
    + AIAE主控仓位Cap + 动态权重 + 共振分析
    含第 1.5 层 GEM 双重动量战术配置
    """
    loop = asyncio.get_running_loop()

    try:
        # ── 并行执行6策略 ──
        mr_task   = loop.run_in_executor(executor, run_strategy)
        div_task  = loop.run_in_executor(executor, lambda: run_dividend_strategy(regime=None))
        mom_task  = loop.run_in_executor(executor, run_momentum_strategy)
        gem_task  = loop.run_in_executor(executor, _run_gem_strategy)
        erp_task  = loop.run_in_executor(executor, _run_erp_strategy)
        aiae_task = loop.run_in_executor(executor, _run_aiae_strategy)

        results = await asyncio.gather(
            mr_task, div_task, mom_task, gem_task, erp_task, aiae_task,
            return_exceptions=True,
        )

        # ── V5.2: 错误隔离 — 异常策略降级为空结果，不阻塞其他策略 ──
        _FALLBACK = {"status": "error", "data": {"signals": [], "market_overview": {}}}
        degraded = []
        _names = ["mr", "div", "mom", "gem", "erp", "aiae"]
        sanitized = []
        for i, (sname, r) in enumerate(zip(_names, results)):
            if isinstance(r, Exception):
                logger.error(f"策略 {sname} 执行异常(已隔离): {r}")
                degraded.append(sname)
                sanitized.append(_FALLBACK.copy())
            else:
                sanitized.append(r)
        mr_raw, div_raw, mom_raw, gem_raw, erp_raw, aiae_raw = sanitized

        from dashboard_modules.run_strategies import wrap_mr_results
        mr_result = wrap_mr_results(mr_raw) if isinstance(mr_raw, list) else mr_raw
        div_result, mom_result, gem_result, erp_result, aiae_result = div_raw, mom_raw, gem_raw, erp_raw, aiae_raw

        with _STRATEGY_LOCK:
            _sr = cache_manager.get_json("strategy_results", {})
            _sr["mr"] = mr_result; _sr["div"] = div_result; _sr["mom"] = mom_result
            _sr["gem"] = gem_result; _sr["erp"] = erp_result; _sr["aiae"] = aiae_result
            _sr["_cached_at"] = _dt.now().isoformat()
            cache_manager.set_json("strategy_results", _sr, ttl_seconds=86400)  # 24h TTL

        # 提取标准化信号
        mr_signals   = _extract_signals_normalized("mr", mr_result)
        div_signals  = _extract_signals_normalized("div", div_result)
        mom_signals  = _extract_signals_normalized("mom", mom_result)
        gem_signals  = _extract_signals_normalized("gem", gem_result)
        erp_signals  = _extract_signals_normalized("erp", erp_result)
        aiae_signals = _extract_signals_normalized("aiae_etf", aiae_result)

        resonance = _compute_resonance(mr_signals, div_signals, mom_signals, erp_signals, aiae_signals, gem_signals)

        all_buy_signals = (
            [s for s in mr_signals if s.get("signal") == "buy"] +
            [s for s in div_signals if s.get("signal") == "buy"] +
            [s for s in mom_signals if s.get("signal") == "buy"] +
            [s for s in gem_signals if s.get("signal") == "buy"] +
            [s for s in aiae_signals if s.get("signal") == "buy"]
        )
        risk_overlay = _compute_risk_overlay(all_buy_signals)

        # 全局指标
        mr_ov   = mr_result.get("data", {}).get("market_overview", {}) if isinstance(mr_result, dict) else {}
        div_ov  = div_result.get("data", {}).get("market_overview", {}) if isinstance(div_result, dict) else {}
        mom_ov  = mom_result.get("data", {}).get("market_overview", {}) if isinstance(mom_result, dict) else {}
        gem_ov  = gem_result.get("data", {}).get("market_overview", {}) if isinstance(gem_result, dict) else {}
        erp_ov  = erp_result.get("data", {}).get("market_overview", {}) if isinstance(erp_result, dict) else {}
        aiae_ov = aiae_result.get("data", {}).get("market_overview", {}) if isinstance(aiae_result, dict) else {}

        mr_regime = mr_signals[0].get("regime", "RANGE") if mr_signals else "RANGE"
        total_buy = (mr_ov.get("signal_count", {}).get("buy", 0) + div_ov.get("buy_count", 0) +
                     mom_ov.get("buy_count", 0) + gem_ov.get("buy_count", 0) +
                     erp_ov.get("buy_count", 0) + aiae_ov.get("buy_count", 0))
        total_sell = (mr_ov.get("signal_count", {}).get("sell", 0) + div_ov.get("sell_count", 0) +
                      mom_ov.get("sell_count", 0) + erp_ov.get("sell_count", 0) + aiae_ov.get("sell_count", 0))

        # ─── 科学仓位计算 V4.0 (AIAE主控) ───
        def _avg_confidence(signals_list):
            buy_sigs = [s for s in signals_list if s.get("signal") == "buy"]
            if not buy_sigs: return 0.0
            positions = [s.get("suggested_position", 0) for s in buy_sigs]
            return sum(positions) / len(positions) if positions else 0.0

        mr_conf, div_conf = _avg_confidence(mr_signals), _avg_confidence(div_signals)
        mom_conf, gem_conf = _avg_confidence(mom_signals), _avg_confidence(gem_signals)
        erp_conf = _avg_confidence(erp_signals)
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
                w = {"mr": 0.12, "div": 0.25, "mom": 0.08, "gem": 0.12, "erp": 0.13, "aiae_etf": 0.30}
                erp_tier = "neutral"

        raw_pos = round(
            mr_conf * w["mr"] + div_conf * w["div"] + mom_conf * w["mom"] +
            gem_conf * w.get("gem", 0) + erp_conf * w["erp"] + aiae_conf * w["aiae_etf"]
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

        # V5.2: 零信号安全阀 — 全策略无买入信号时 floor 不应强推仓位
        total_buy_signals = sum(1 for s in mr_signals + div_signals + mom_signals +
                                gem_signals + aiae_signals if s.get("signal") == "buy")
        if total_buy_signals == 0:
            original_floor = regime_floor
            regime_floor = round(regime_floor * 0.3)
            logger.warning(f"零信号安全阀触发: 0买入信号, floor {original_floor}%→{regime_floor}%")

        avg_pos = max(avg_pos, regime_floor)
        logger.info(f"矩阵锚定: raw={raw_pos}% floor={regime_floor}%(R{aiae_regime}/{erp_tier}) cap={cap}% → final={avg_pos}%")

        erp_cap_active = False

        # V5.2: 多策略 Regime 一致性增强 (MR+DIV+MOM 三维度)
        div_regime = div_result.get("data", {}).get("regime_params", {}).get("regime", "RANGE") if isinstance(div_result, dict) else "RANGE"
        mom_regime = mom_result.get("data", {}).get("market_overview", {}).get("regime", "RANGE") if isinstance(mom_result, dict) else "RANGE"
        aiae_regime_mapped = {1: "BULL", 2: "BULL", 3: "RANGE", 4: "BEAR", 5: "BEAR"}.get(aiae_regime, "RANGE")
        regime_map = {"mr": mr_regime, "div": div_regime, "mom": mom_regime, "aiae_mapped": aiae_regime_mapped}
        unique_regimes = set([mr_regime, div_regime, mom_regime])
        if len(unique_regimes) == 1:
            consistency = "high"
        elif len(unique_regimes) == 2:
            consistency = "medium"
        else:
            consistency = "low"

        consistency_penalty = {"high": 1.0, "medium": 0.85, "low": 0.75}
        if consistency != "high" and not override_active:
            avg_pos = max(round(avg_pos * consistency_penalty[consistency]), regime_floor)

        return {
            "status": "success", "timestamp": _dt.now().isoformat(),
            "data": {
                "global": {
                    "regime": mr_regime, "total_position": avg_pos,
                    "regime_cap": cap, "total_buy": total_buy, "total_sell": total_sell,
                    "consistency": consistency, "regime_map": regime_map, "strategy_count": 6,
                    "degraded_strategies": degraded,
                    "erp_score": erp_score, "erp_cap_active": erp_cap_active,
                    "confidence": {
                        "mr": round(mr_conf), "div": round(div_conf), "mom": round(mom_conf),
                        "gem": round(gem_conf),
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
                    "gem": gem_result.get("data", gem_result) if isinstance(gem_result, dict) else {"signals": gem_signals},
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
