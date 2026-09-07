"""AlphaCore 产业/回测/因子/动量 API — 从 main.py 提取"""
import asyncio
import traceback
import logging
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Query

import numpy as np
import pandas as pd
from models.schemas import BacktestRequest, BatchBacktestRequest, FactorAnalysisRequest
from data_manager import FactorDataManager
from backtest_engine import AlphaBacktester
from engines.factor_analyzer import FactorAnalyzer
from strategies_backtest import (
    mean_reversion_strategy_vectorized,
    dividend_trend_strategy_vectorized,
    momentum_rotation_strategy_vectorized,
    erp_timing_strategy_vectorized
)
from erp_backtest_data import prepare_erp_backtest_data
from momentum_backtest_engine import run_momentum_backtest, run_momentum_optimize
from core_etf_config import CORE_ETFS, CORE_ETF_CODES
from engines.industry_engine import IndustryEngine
from services.industry_tracker import (
    _tracking_cache_get, _tracking_cache_set, _get_tracking_ttl,
    compute_price_percentile, compute_dynamic_rps, compute_momentum_20d,
    compute_sector_heat_score, compute_alpha_score, compute_risk_alerts,
)
from services.industry_policy import (
    build_industry_abstention_plan,
    build_industry_decision_context,
    build_industry_liquidity_profile,
    evaluate_industry_candidate,
)
from services.industry_validation import (
    load_industry_validation_status,
    run_local_industry_validation,
)
from services.industry_challenger import (
    load_challenger_status,
    run_local_challenger_validation,
)
from services.industry_forward_monitor import (
    get_forward_monitor_status,
    run_forward_monitor,
)
from services.industry_universe import (
    get_industry_universe_status,
    refresh_existing_industry_universe,
)
from services.industry_constituents import (
    get_constituents_for_etf,
    get_industry_constituent_status,
    refresh_industry_constituents,
)
from services.market_regime import get_market_regime_snapshot

router = APIRouter(prefix="/api/v1", tags=["industry"])
executor = ThreadPoolExecutor(max_workers=6)
logger = logging.getLogger("alphacore.industry")

def get_etf_constituent_snapshot(ts_code):
    """Return only verified official tracking-index weights; never static guesses."""
    return get_constituents_for_etf(ts_code)


def _apply_data_lock(item: dict, reasons: list) -> None:
    """Fail closed：数据质量未通过时覆盖一切买入型文案。"""
    clean_reasons = list(dict.fromkeys(str(reason) for reason in reasons if reason))
    item.update({
        "decision_locked": True,
        "decision_status": "data_locked",
        "decision_lock_reasons": clean_reasons,
        "advice": "行业数据质量或新鲜度未通过，禁止形成买入决策",
        "advice_action": "data_locked",
        "advice_label": "🔒 数据锁定",
        "buy_strategy": "等待全部行业数据通过质量检查",
        "take_profit": "—",
        "stop_loss": "—",
        "position_cap": "0%",
    })


# ─────────────────────────────────────────────
# 宏观ERP择时引擎 V1.0 API
# ─────────────────────────────────────────────

@router.get("/industry-detail")
async def get_industry_detail(code: str):
    """
    V4.0 产业深度追踪接口: 复用tracking缓存 + 补充图表数据
    消灭所有Mock: RPS动态 + PE实时 + 20D动量(替代北向)
    """
    try:
        def fetch_data():
            # V6.0: 只从 "latest" 命名空间读取实时缓存，杜绝历史数据污染
            cached, cached_ts, cache_valid = _tracking_cache_get("latest")
            cached_item = None
            if cached and cache_valid:
                cached_item = next((d for d in cached if (d.get('ts_code') or d.get('code')) == code), None)

            # 获取图表用价格数据
            dm = FactorDataManager()
            p_df = dm.get_industry_price_payload(code)
            constituent_snapshot = get_etf_constituent_snapshot(code)

            if p_df.empty:
                return {"code": code, "decision_locked": True,
                        "decision_lock_reasons": ["MISSING_INDUSTRY_QFQ_DATA"],
                        "metrics": {"rps": 50, "pe_percentile": 50, "price_percentile": 50, "crowding": 1.0,
                        "momentum_20d": {"ret_20d": 0, "label": "数据不足", "trend": "neutral"},
                        "constituents": constituent_snapshot.get("top_constituents", []),
                        "constituent_snapshot": constituent_snapshot},
                        "chart_data": {"dates": [], "prices": [], "relative_strength": []}}

            p_df = p_df.sort_values('trade_date')

            # V4.0: 从缓存取已计算的真实指标
            if cached_item:
                rps_val = cached_item.get('rps', 50)
                pe_val = cached_item.get('pe_percentile', 50)
                crowding_val = cached_item.get('vol_ratio', 1.0)
                mom_20d = cached_item.get('momentum_20d', {"ret_20d": 0, "label": "—", "trend": "neutral"})
            else:
                # 无缓存时动态计算
                rps_val = 50.0
                pe_val = compute_price_percentile(p_df)
                amt_col = 'amount' if 'amount' in p_df.columns else None
                if amt_col and len(p_df) >= 20:
                    vol_ma20 = float(p_df[amt_col].tail(20).mean())
                    crowding_val = round(float(p_df[amt_col].iloc[-1]) / vol_ma20, 2) if vol_ma20 > 0 else 1.0
                else:
                    crowding_val = 1.0
                mom_20d = compute_momentum_20d(p_df)

            # 图表数据 (取最近60天做more context)
            chart_df = p_df.tail(60)
            dates = chart_df['trade_date'].astype(str).tolist()
            prices = chart_df['close'].tolist()
            base = float(chart_df['close'].iloc[0]) if not chart_df.empty else 1
            rs = [(float(p) / base * 100) for p in prices]

            detail_data = {
                "code": code,
                "decision_locked": (
                    cached_item.get("decision_locked", True) if cached_item else True
                ),
                "decision_lock_reasons": (
                    cached_item.get("decision_lock_reasons", [])
                    if cached_item else ["TRACKING_QUALITY_NOT_EVALUATED"]
                ),
                "decision_status": (
                    cached_item.get("decision_status", "data_locked")
                    if cached_item else "data_locked"
                ),
                "policy_qualified": bool(
                    cached_item.get("policy_qualified", False) if cached_item else False
                ),
                "eligibility_checks": (
                    cached_item.get("eligibility_checks", {}) if cached_item else {}
                ),
                "veto_reasons": (
                    cached_item.get("veto_reasons", []) if cached_item else []
                ),
                "execution": (
                    cached_item.get("execution", {}) if cached_item else {}
                ),
                "data_as_of": (
                    cached_item.get("data_as_of") if cached_item
                    else p_df['trade_date'].iloc[-1].strftime("%Y%m%d")
                ),
                "metrics": {
                    "rps": rps_val,
                    "pe_percentile": pe_val,
                    "price_percentile": pe_val,
                    "crowding": crowding_val,
                    "momentum_20d": mom_20d,
                    "constituents": constituent_snapshot.get("top_constituents", []),
                    "constituent_snapshot": constituent_snapshot,
                },
                "chart_data": {
                    "dates": dates[-30:],
                    "prices": prices[-30:],
                    "relative_strength": rs[-30:]
                }
            }
            return detail_data

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, fetch_data)
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/backtest")
async def run_backtest_api(req: BacktestRequest):
    """
    工业级回测执行接口 - 强化版 (支持 QFQ, POV, Trade Log)
    """
    try:
        bt = AlphaBacktester(initial_cash=req.initial_cash, benchmark_code=req.benchmark_code)
        
        # 1. 获取数据 (Fund 日线数据 + Adj Factors)
        logger.info(f"Backtest Req: {req.ts_code} ({req.strategy})")
        df = await asyncio.get_running_loop().run_in_executor(
            executor, bt.fetch_tushare_data, req.ts_code, req.start_date, req.end_date, req.adj
        )
        
        if df.empty:
            return {"status": "error", "message": f"未找到代码 {req.ts_code} 的历史数据，请检查代码或日期范围。"}
        
        # 2. 选择并执行策略逻辑 (V2.0: 与策略中心生产引擎参数完全对齐)
        p = req.params
        if req.strategy == 'mr':
            valid_keys = ['N_trend', 'rsi_period', 'rsi_buy', 'rsi_sell', 'bias_buy', 'stop_loss']
            filtered_p = {k: v for k, v in p.items() if k in valid_keys}
            # bias_buy 从前端 ×10 格式转换 (前端-20 → 引擎-2.0)
            if 'bias_buy' in filtered_p:
                filtered_p['bias_buy'] = filtered_p['bias_buy'] / 10.0
            signals = mean_reversion_strategy_vectorized(df, **filtered_p)
        elif req.strategy == 'div':
            valid_keys = ['ma_trend', 'rsi_period', 'rsi_buy', 'rsi_sell', 'bias_buy', 'ma_defend', 'stop_loss']
            filtered_p = {k: v for k, v in p.items() if k in valid_keys}
            if 'bias_buy' in filtered_p:
                filtered_p['bias_buy'] = filtered_p['bias_buy'] / 10.0
            signals = dividend_trend_strategy_vectorized(df, **filtered_p)
        elif req.strategy == 'mom':
            valid_keys = ['lookback_s', 'lookback_m', 'momentum_threshold', 'stop_loss']
            filtered_p = {k: v for k, v in p.items() if k in valid_keys}
            signals = momentum_rotation_strategy_vectorized(df, **filtered_p)
        elif req.strategy == 'erp':
            # ERP宏观择时: 需要额外加载宏观日频宽表
            valid_keys = ['buy_threshold', 'sell_threshold', 'erp_window', 'vol_window',
                          'w_erp_abs', 'w_erp_pct', 'w_m1', 'w_vol', 'w_credit', 'stop_loss']
            filtered_p = {k: v for k, v in p.items() if k in valid_keys}
            # 提前1年拉数据作为ERP分位回溯期
            macro_start = (datetime.strptime(req.start_date, '%Y%m%d') - timedelta(days=400)).strftime('%Y%m%d')
            macro_df = await asyncio.get_running_loop().run_in_executor(
                executor, prepare_erp_backtest_data, macro_start, req.end_date
            )
            signals = erp_timing_strategy_vectorized(df, macro_df=macro_df, **filtered_p)
        else:
            return {"status": "error", "message": "无效的策略类型"}
            
        # 3. V2.0 回测引擎 (含 grade/round_trips/diagnosis)
        results = bt.run_vectorized(df, signals, ts_code=req.ts_code, order_pct=req.order_pct)
        
        # 4. V2.0 蒙特卡洛 (Block Bootstrap 500x + 破产概率)
        equity_cv = pd.Series(results['equity_curve'])
        strat_returns = equity_cv.pct_change().fillna(0)
        results['monte_carlo'] = bt.run_monte_carlo(strat_returns, iterations=500)
            
        return {
            "status": "success",
            "data": results
        }
        
    except Exception as e:
        logger.error(f"Backtest Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

@router.post("/batch-backtest")
async def run_batch_backtest(req: BatchBacktestRequest):
    """
    多策略对比 (Strategy PK) 接口
    """
    tasks = [run_backtest_api(item) for item in req.items]
    results = await asyncio.gather(*tasks)
    return {"status": "success", "data": results}

@router.post("/factor-analysis")
async def run_factor_analysis(req: FactorAnalysisRequest):
    """
    因子看板核心 API V2.0：IC分布 + 分组收益 + 质量评级
    """
    try:
        dm = FactorDataManager()
        fa = FactorAnalyzer()
        
        # 1. 获取样本池
        all_stocks = dm.get_all_stocks()
        if req.stock_pool == "top30":
            sample_codes = all_stocks.head(30)["ts_code"].tolist()
        else:
            sample_codes = all_stocks.head(100)["ts_code"].tolist()
            
        logger.info(f"Factor Analysis V5.0: {req.factor_name} on {len(sample_codes)} stocks")
        
        def run_analysis():
            # V5.0: 按需检查数据新鲜度, 过期则自动同步
            freshness = dm.check_data_freshness(sample_codes)
            sync_result = None
            if freshness['is_stale']:
                logger.info(f"[Factor] 数据过期 {freshness['stale_days']} 天, 触发智能同步...")
                sync_result = dm.smart_sync(sample_codes)
                freshness = sync_result.get('freshness', freshness)

            analysis_data = fa.prepare_analysis_data(sample_codes, req.factor_name)
            if analysis_data.empty:
                return {"error": "未找到有效数据，请检查数据同步情况"}
                
            metrics = fa.calculate_metrics(analysis_data, req.factor_name)
            
            ic_series = metrics["ic_series"]
            q_rets = metrics["quantile_rets"]
            
            if isinstance(q_rets, pd.Series) and isinstance(q_rets.index, pd.MultiIndex):
                q_rets = q_rets.unstack()
            
            # V4.0: 构建增强返回数据
            q_avg_vals = q_rets.mean().values if not q_rets.empty else []
            
            return {
                "ic_mean": float(metrics["ic_mean"]),
                "ic_std": float(metrics["ic_std"]),
                "ic_ir": float(metrics["ir"]),
                "ic_win_rate": float(metrics["ic_win_rate"]),
                "monotonicity": float(metrics["monotonicity"]),
                "ic_stability": float(metrics["ic_stability"]),
                "grade": metrics["grade"],
                "ls_spread": float(metrics["ls_spread"]),
                "alpha_score": float(metrics["alpha_score"]),
                "score_breakdown": metrics["score_breakdown"],
                "advice": metrics["advice"],
                "ic_distribution": metrics.get("ic_distribution", {}),
                "health_status": metrics.get("health_status", []),
                "ic_rolling": metrics.get("ic_rolling", {}),
                "ic_series": {
                    "dates": ic_series.index.strftime("%Y-%m-%d").tolist(),
                    "values": [float(x) if not np.isnan(x) else 0 for x in ic_series.values]
                },
                "quantile_rets": {
                    "quantiles": [f"Q{i+1}" for i in range(len(q_avg_vals))],
                    "avg_rets": [float(x) for x in q_avg_vals],
                    "cum_rets": {
                        "dates": q_rets.index.strftime("%Y-%m-%d").tolist() if not q_rets.empty else [],
                        "series": [
                            ((1 + q_rets[c]).cumprod() - 1).fillna(0).tolist()
                            for c in q_rets.columns
                        ] if not q_rets.empty else []
                    }
                }
            }
            
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(executor, run_analysis)
        
        if "error" in results:
            return {"status": "error", "message": results["error"]}
        
        # V5.0: 返回数据新鲜度信息
        freshness_info = dm.check_data_freshness(sample_codes)
            
        return {
            "status": "success",
            "data": results,
            "data_freshness": freshness_info
        }
    except Exception as e:
        logger.error(f"Factor Analysis Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

@router.get("/strategy/momentum-backtest")
async def get_momentum_backtest(
    start_date: str = "2021-01-01",
    end_date: str = None,
    top_n: int = Query(default=4, ge=1, le=20),
    rebalance_days: int = Query(default=10, ge=1, le=60),
    mom_s_window: int = Query(default=20, ge=5, le=120),
    stop_loss: float = Query(default=-0.08, ge=-0.5, le=0)
):
    """运行行业动量轮动多因子历史回测 (V2.0)"""
    try:
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        params = {
            "top_n": top_n,
            "rebalance_days": rebalance_days,
            "mom_s_window": mom_s_window,
            "mom_m_window": mom_s_window * 3,
            "w_mom_s": 0.40, "w_mom_m": 0.30,
            "w_slope": 0.15, "w_sharpe": 0.15,
            "stop_loss": stop_loss if stop_loss != 0 else None,
            "position_cap": 0.85,
        }
        
        def do_backtest():
            return run_momentum_backtest(start_date, end_date, params)
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, do_backtest)
        return result
    except Exception as e:
        logger.error(f"Momentum Backtest Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


@router.get("/strategy/momentum-optimize")
async def get_momentum_optimize(
    in_sample_end: str = "2023-12-31",
    out_sample_start: str = "2024-01-01"
):
    """运行参数网格搜索优化 (警告: 耗时较长)"""
    try:
        def do_optimize():
            return run_momentum_optimize(in_sample_end, out_sample_start)
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, do_optimize)
        return result
    except Exception as e:
        logger.error(f"Momentum Optimize Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

@router.get("/market/regime")
async def get_market_regime():
    """返回统一的 Regime、AIAE 安全状态与仓位参数快照。"""
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, get_market_regime_snapshot)
    except Exception as e:
        logger.error(f"Market Regime Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

@router.get("/industry-tracking")
async def get_industry_tracking(date: Optional[str] = None):
    """
    V4.0 行业追踪核心 API: Data-Honest Alpha Score + 动态RPS + 真实价格百分位
    """
    try:
        def run_ind_analysis():
            dm = FactorDataManager()
            target_dt = pd.to_datetime(date) if date else pd.Timestamp.now().normalize()
            today = pd.Timestamp.now().normalize()
            historical_query = bool(date) and target_dt.normalize() < today

            # V5.1 Fix P0#2: 统一引用 core_etf_config (Single Source of Truth)
            etf_list = CORE_ETFS
            quality_kwargs = {}
            if date:
                quality_kwargs["as_of"] = target_dt.replace(hour=23, minute=59).to_pydatetime()
            data_quality = dm.check_industry_data_quality(
                CORE_ETF_CODES, **quality_kwargs
            )
            data_locked = bool(data_quality.get("decision_locked", True))
            market_snapshot = {}
            if not data_locked and not historical_query:
                try:
                    market_snapshot = get_market_regime_snapshot()
                except Exception as exc:
                    logger.warning("[industry-tracking] Regime snapshot error: %s", exc)
                    market_snapshot = {"status": "error", "message": str(exc)}
            decision_context = build_industry_decision_context(
                data_quality,
                market_snapshot,
                historical_query=historical_query,
            )
            validation_status = decision_context["model_validation"]
            global_lock = decision_context["decision_locked"]
            global_lock_reasons = decision_context["decision_lock_reasons"]
            quality_items = data_quality.get("items", {})

            sector_data = []
            # V4.0: 保存每个ETF的price_df用于detail API复用
            _price_cache = {}

            for etf in etf_list:
                code = etf['code']
                p_df = dm.get_industry_price_payload(code)
                item_quality = quality_items.get(code, {})
                if p_df.empty:
                    empty_item = {
                        "ts_code": code, "code": code, "name": etf['name'],
                        "trend_5d": 0.0, "ret_20d": 0.0,
                        "heat_score": 30.0, "heat_tier": "❄️ 冷淡",
                        "vol_ratio": 1.0, "vol_score": 50.0, "mom_score": 50.0, "crowd_score": 80.0,
                        "pe_percentile": 50.0, "price_percentile": 50.0,
                        "alpha_score": 30.0, "alpha_grade": "F",
                        "research_score": 30.0,
                        "f_heat": 30.0, "f_momentum": 50.0, "f_valuation": 50.0,
                        "f_price_position_safety": 50.0, "f_trend": 0.0,
                        "trend_strength": {"above_ma20": False, "above_ma60": False, "ma20_slope": 0.0},
                        "risk_alerts": [],
                        "momentum_20d": {"ret_20d": 0.0, "label": "数据同步中", "trend": "neutral"},
                        "data_as_of": item_quality.get("latest_trade_date"),
                        "data_quality": item_quality,
                        "execution_quality": build_industry_liquidity_profile([]),
                    }
                    empty_context = build_industry_decision_context(
                        {
                            "decision_locked": True,
                            "is_usable": False,
                            "reasons": global_lock_reasons
                            + item_quality.get("issues", ["MISSING_DATA"]),
                            "expected_trade_date": data_quality.get("expected_trade_date"),
                        },
                        market_snapshot,
                        model_validation_status=validation_status,
                        historical_query=historical_query,
                    )
                    empty_item.update(evaluate_industry_candidate(empty_item, empty_context))
                    sector_data.append(empty_item)
                    continue

                # 过滤至目标日期
                p_df = p_df[p_df['trade_date'] <= target_dt].sort_values('trade_date')
                _price_cache[code] = p_df  # V4.0: 缓存用于detail复用

                if len(p_df) >= 5:
                    ret = (p_df['close'].iloc[-1] / p_df['close'].iloc[-5] - 1)
                    trend = round(float(ret) * 100, 2) if np.isfinite(ret) else 0.0
                else:
                    trend = 0.0

                # V2.0: 计算资金热度得分
                heat = compute_sector_heat_score(p_df, trend)

                # V4.0: 动态价格百分位 (替代硬编码PE分位)
                pe_pct = compute_price_percentile(p_df)

                # V4.0: 20D动量趋势 (替代虚假北向资金)
                mom_20d = compute_momentum_20d(p_df)

                # V3.0: 计算 Alpha Score 综合评分
                alpha = compute_alpha_score(p_df, heat['heat_score'], trend, pe_pct)

                # V3.0: 风险警示检测
                alerts = compute_risk_alerts(
                    heat['vol_ratio'], pe_pct, trend,
                    heat['heat_score'], heat['crowd_score']
                )

                item = {
                    "ts_code": code, "code": code, "name": etf['name'],
                    "trend_5d": trend,
                    # V2.0 热度字段
                    "heat_score": heat['heat_score'],
                    "heat_tier": heat['heat_tier'],
                    "vol_ratio": heat['vol_ratio'],
                    "vol_score": heat['vol_score'],
                    "mom_score": heat['mom_score'],
                    "crowd_score": heat['crowd_score'],
                    # pe_percentile 仅为兼容旧前端；该值是历史价格位置，不是 PE/PB 估值。
                    "pe_percentile": pe_pct,
                    "price_percentile": pe_pct,
                    # V3.0 Alpha Score 字段
                    "alpha_score": alpha['alpha_score'],
                    "research_score": alpha['alpha_score'],
                    "alpha_grade": alpha['alpha_grade'],
                    "ret_20d": alpha['ret_20d'],
                    "f_heat": alpha['f_heat'],
                    "f_momentum": alpha['f_momentum'],
                    "f_valuation": alpha['f_valuation'],
                    "f_price_position_safety": alpha['f_valuation'],
                    "f_trend": alpha['f_trend'],
                    "trend_strength": alpha['trend_strength'],
                    # V3.0 风险警示
                    "risk_alerts": alerts,
                    # V4.0 20D动量趋势 (替代北向资金)
                    "momentum_20d": mom_20d,
                    "data_as_of": (
                        p_df['trade_date'].iloc[-1].strftime("%Y%m%d")
                        if not p_df.empty else item_quality.get("latest_trade_date")
                    ),
                    "data_quality": item_quality,
                    "execution_quality": build_industry_liquidity_profile(
                        p_df["amount"].tolist() if "amount" in p_df.columns else []
                    ),
                }
                item_context = decision_context
                if not item_quality.get("is_usable", not data_locked):
                    item_context = build_industry_decision_context(
                        {
                            "decision_locked": True,
                            "is_usable": False,
                            "reasons": global_lock_reasons + item_quality.get("issues", []),
                            "expected_trade_date": data_quality.get("expected_trade_date"),
                        },
                        market_snapshot,
                        model_validation_status=validation_status,
                        historical_query=historical_query,
                    )
                item.update(evaluate_industry_candidate(item, item_context))
                sector_data.append(item)

            # V3.0: 按 alpha_score 降序排列 (综合评分优先)
            sector_data.sort(key=lambda x: x.get('alpha_score', 0), reverse=True)

            # V4.0: 计算动态RPS排名 (需要全部sector_data准备好后)
            for item in sector_data:
                item['rps'] = compute_dynamic_rps(sector_data, item.get('ts_code') or item.get('code'))

            abstention_plan = build_industry_abstention_plan(
                sector_data, decision_context
            )

            # 轮动矩阵
            try:
                engine = IndustryEngine()
                rotation = engine.get_industry_rotation(base_date=date)
            except Exception as e:
                logger.warning(f"[industry-tracking] Rotation matrix error: {e}")
                rotation = {}

            result = {
                "performance": sector_data,
                "sector_heatmap": sector_data,
                "rotation": rotation,
                "last_update": datetime.now().strftime("%Y%m%d"),
                "decision_locked": global_lock,
                "decision_lock_reasons": global_lock_reasons,
                "execution_context": decision_context,
                "abstention_plan": abstention_plan,
                "qualified_count": sum(1 for item in sector_data if item.get("policy_qualified")),
                "candidate_count": sum(
                    1 for item in sector_data
                    if item.get("advice_action") == "candidate_eligible"
                ),
                "eligible_buy_count": sum(
                    1 for item in sector_data
                    if item.get("advice_action") == "eligible_buy"
                ),
                "_data_quality": data_quality,
            }

            # V6.0: 日期隔离缓存写入
            # 仅当请求 latest (date=None 或 date=today) 时写入 "latest" 命名空间
            today_str = datetime.now().strftime("%Y-%m-%d")
            request_date_str = str(date) if date else today_str
            is_latest = (date is None) or (request_date_str == today_str)

            if is_latest:
                _tracking_cache_set("latest", sector_data)
            else:
                # 历史查询: 存入对应日期的独立命名空间，绝不碰 latest
                _tracking_cache_set(request_date_str, sector_data)

            return result

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(executor, run_ind_analysis)
        data_quality = results.pop("_data_quality", {})

        # V6.0: freshness 从 latest 缓存读取
        _, latest_ts, _ = _tracking_cache_get("latest")
        return {"status": "success", "data": results,
                "decision_locked": bool(results.get("decision_locked", True)),
                "decision_lock_reasons": results.get("decision_lock_reasons", []),
                "data_quality": data_quality,
                "data_freshness": {
                    "last_calc": latest_ts or datetime.now().isoformat(),
                    "etf_count": len(results.get("sector_heatmap", [])),
                    "cache_ttl_sec": _get_tracking_ttl(),
                    "expected_trade_date": data_quality.get("expected_trade_date"),
                    "daily_latest": data_quality.get("daily_latest"),
                    "daily_earliest_latest": data_quality.get("daily_earliest_latest"),
                    "usable_count": data_quality.get("usable_count", 0),
                    "coverage_ratio": data_quality.get("coverage_ratio", 0.0),
                    "is_usable": data_quality.get("is_usable", False),
                }}
    except Exception as e:
        logger.error(f"Industry Analysis Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


@router.get("/industry-validation")
async def get_industry_validation():
    """Return independently re-evaluated industry model-promotion evidence."""
    try:
        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(executor, load_industry_validation_status)
        return {"status": "success", "data": status}
    except Exception as exc:
        logger.error("Industry validation status error: %s", traceback.format_exc())
        return {
            "status": "error",
            "data": {
                "ready": False,
                "stage": "error",
                "reasons": ["VALIDATION_STATUS_UNAVAILABLE"],
            },
            "message": str(exc),
        }


@router.post("/industry-validation/run")
async def run_industry_validation_audit():
    """Rebuild the versioned local shadow-validation artifact."""
    try:
        loop = asyncio.get_running_loop()
        artifact = await loop.run_in_executor(executor, run_local_industry_validation)
        status = load_industry_validation_status()
        return {
            "status": "success" if status["ready"] else "degraded",
            "data": status,
            "coverage": artifact.get("coverage", {}),
        }
    except Exception as exc:
        logger.error("Industry validation run error: %s", traceback.format_exc())
        return {
            "status": "error",
            "data": {"ready": False, "reasons": ["VALIDATION_RUN_FAILED"]},
            "message": str(exc),
        }


@router.get("/industry-challenger")
async def get_industry_challenger():
    """Return isolated shadow evidence; this endpoint never grants execution."""
    try:
        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(executor, load_challenger_status)
        return {"status": "success", "data": status}
    except Exception as exc:
        logger.error("Industry challenger status error: %s", traceback.format_exc())
        return {
            "status": "error",
            "data": {
                "lifecycle": "shadow",
                "evidence_ready": False,
                "execution_ready": False,
                "reasons": ["CHALLENGER_STATUS_UNAVAILABLE"],
            },
            "message": str(exc),
        }


@router.post("/industry-challenger/run")
async def run_industry_challenger_audit():
    """Rebuild the pre-registered challenger artifact without publishing it."""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(executor, run_local_challenger_validation)
        status = load_challenger_status()
        return {
            "status": "success" if status["evidence_ready"] else "degraded",
            "data": status,
        }
    except Exception as exc:
        logger.error("Industry challenger run error: %s", traceback.format_exc())
        return {
            "status": "error",
            "data": {
                "lifecycle": "shadow",
                "evidence_ready": False,
                "execution_ready": False,
                "reasons": ["CHALLENGER_RUN_FAILED"],
            },
            "message": str(exc),
        }


@router.get("/industry-forward-monitor")
async def get_industry_forward_monitor():
    """Return hash-chain integrity and forward-only sample maturity."""
    try:
        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(executor, get_forward_monitor_status)
        return {"status": "success", "data": status}
    except Exception as exc:
        logger.error("Industry forward monitor status error: %s", traceback.format_exc())
        return {
            "status": "error",
            "data": {
                "integrity_ok": False,
                "execution_allowed": False,
                "integrity_errors": ["FORWARD_MONITOR_STATUS_UNAVAILABLE"],
            },
            "message": str(exc),
        }


@router.post("/industry-forward-monitor/run")
async def run_industry_forward_monitor():
    """Record an idempotent closed-session snapshot and settle matured signals."""
    try:
        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(executor, run_forward_monitor)
        return {"status": "success", "data": status}
    except Exception as exc:
        logger.error("Industry forward monitor run error: %s", traceback.format_exc())
        return {
            "status": "error",
            "data": {
                "integrity_ok": False,
                "execution_allowed": False,
                "integrity_errors": ["FORWARD_MONITOR_RUN_FAILED"],
            },
            "message": str(exc),
        }


@router.get("/industry-universe-status")
async def get_industry_universe_registry_status():
    """Return ETF-master lineage and prospective versus historical PIT coverage."""
    try:
        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(executor, get_industry_universe_status)
        return {"status": "success", "data": status}
    except Exception as exc:
        logger.error("Industry universe status error: %s", traceback.format_exc())
        return {
            "status": "error",
            "data": {
                "integrity_ok": False,
                "current_date_covered": False,
                "historical_validation_covered": False,
                "execution_allowed": False,
                "reasons": ["INDUSTRY_UNIVERSE_STATUS_UNAVAILABLE"],
            },
            "message": str(exc),
        }


@router.get("/industry-constituents-status")
async def get_industry_constituents_registry_status():
    """Return official tracking-index constituent coverage and integrity."""
    try:
        loop = asyncio.get_running_loop()
        status = await loop.run_in_executor(executor, get_industry_constituent_status)
        return {
            "status": "success" if status.get("integrity_ok") else "degraded",
            "data": status,
        }
    except Exception as exc:
        logger.error("Industry constituent status error: %s", traceback.format_exc())
        return {
            "status": "error",
            "data": {
                "integrity_ok": False,
                "verified_count": 0,
                "reasons": ["INDUSTRY_CONSTITUENT_STATUS_UNAVAILABLE"],
            },
            "message": str(exc),
        }


@router.post("/industry-constituents/refresh")
async def refresh_industry_constituent_registry():
    """Refresh official monthly weights without falling back to static mappings."""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(executor, refresh_industry_constituents)
        status = await loop.run_in_executor(executor, get_industry_constituent_status)
        return {"status": "success", "data": status}
    except Exception as exc:
        logger.error("Industry constituent refresh error: %s", traceback.format_exc())
        return {
            "status": "error",
            "data": {
                "integrity_ok": False,
                "verified_count": 0,
                "reasons": ["INDUSTRY_CONSTITUENT_REFRESH_FAILED"],
            },
            "message": str(exc),
        }


@router.post("/industry-universe/refresh")
async def refresh_industry_universe_registry():
    """Refresh authoritative ETF metadata without changing the policy freeze date."""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(executor, refresh_existing_industry_universe)
        await loop.run_in_executor(executor, refresh_industry_constituents)
        await loop.run_in_executor(executor, run_local_industry_validation)
        await loop.run_in_executor(executor, run_local_challenger_validation)
        status = await loop.run_in_executor(executor, get_industry_universe_status)
        return {"status": "success", "data": status}
    except Exception as exc:
        logger.error("Industry universe refresh error: %s", traceback.format_exc())
        return {
            "status": "error",
            "data": {
                "integrity_ok": False,
                "execution_allowed": False,
                "reasons": ["INDUSTRY_UNIVERSE_REFRESH_FAILED"],
            },
            "message": str(exc),
        }

@router.post("/sync/industry")
async def sync_industry_data():
    """手动触发行业数据同步 (同步全部核心 ETF 及相关成分股)"""
    try:
        # V5.1 Fix P0#2: 统一引用 core_etf_config (Single Source of Truth)
        etf_codes = CORE_ETF_CODES
        
        def do_sync():
            mgr = FactorDataManager()
            # 同步至产业专用前复权命名空间，绝不与实时动量原始缓存混写。
            mgr.sync_industry_prices(etf_codes)
            # 同时也同步一部分成分股行情(可选)
            engine = IndustryEngine()
            stocks = engine._get_industry_stocks()
            if not stocks.empty:
                mgr.sync_daily_prices(stocks.head(10)['ts_code'].tolist())
            return mgr.check_industry_data_quality(etf_codes)

        loop = asyncio.get_running_loop()
        quality = await loop.run_in_executor(executor, do_sync)
        locked = bool(quality.get("decision_locked", True))
        return {
            "status": "degraded" if locked else "success",
            "last_date": quality.get("daily_latest", "N/A"),
            "decision_locked": locked,
            "decision_lock_reasons": quality.get("reasons", []),
            "data_quality": quality,
        }
    except Exception as e:
        logger.error(f"Sync Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

# --- Portfolio Management API V2.0 (Singleton + Validation) ---

from portfolio_engine import get_portfolio_engine
