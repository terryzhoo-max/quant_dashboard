"""AlphaCore 产业/回测/因子/动量 API — 从 main.py 提取"""
import asyncio
import traceback
import logging
from datetime import datetime, timedelta
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter

import numpy as np
import pandas as pd
import tushare as ts
from config import TUSHARE_TOKEN
from models.schemas import BacktestRequest, BatchBacktestRequest, FactorAnalysisRequest
from data_manager import FactorDataManager
from backtest_engine import AlphaBacktester
from factor_analyzer import FactorAnalyzer
from strategies_backtest import (
    mean_reversion_strategy_vectorized,
    dividend_trend_strategy_vectorized,
    momentum_rotation_strategy_vectorized,
    erp_timing_strategy_vectorized
)
from erp_backtest_data import prepare_erp_backtest_data
from momentum_backtest_engine import run_momentum_backtest, run_momentum_optimize
from core_etf_config import CORE_ETFS, CORE_ETF_CODES, ETF_CONSTITUENTS, FALLBACK_MOMENTUM
from industry_engine import IndustryEngine
from services.industry_tracker import (
    _tracking_cache_get, _tracking_cache_set, _get_tracking_ttl,
    compute_price_percentile, compute_dynamic_rps, compute_momentum_20d,
    compute_sector_heat_score, compute_alpha_score, compute_risk_alerts,
    generate_sector_advice
)

router = APIRouter(prefix="/api/v1", tags=["industry"])
executor = ThreadPoolExecutor(max_workers=6)
logger = logging.getLogger("alphacore.industry")

def get_etf_constituents(ts_code):
    """V5.1 Fix P0#2: 统一引用 core_etf_config.ETF_CONSTITUENTS (Single Source of Truth)"""
    return ETF_CONSTITUENTS.get(ts_code, [])


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
            p_df = dm.get_price_payload(code)

            if p_df.empty:
                # Tushare实时拉取兜底
                try:
                    df_live = ts.pro_bar(ts_code=code, asset='FD', start_date='20241001', adj='qfq')
                    if df_live is not None and not df_live.empty:
                        p_df = df_live.sort_values('trade_date')
                        p_df['trade_date'] = p_df['trade_date'].astype(str)
                except Exception as e:
                    logger.warning(f"[industry-detail] Tushare fallback failed for {code}: {e}")

            if p_df.empty:
                return {"code": code, "metrics": {"rps": 50, "pe_percentile": 50, "crowding": 1.0,
                        "momentum_20d": {"ret_20d": 0, "label": "数据不足", "trend": "neutral"},
                        "constituents": get_etf_constituents(code)},
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
                "metrics": {
                    "rps": rps_val,
                    "pe_percentile": pe_val,
                    "crowding": crowding_val,
                    "momentum_20d": mom_20d,
                    "constituents": get_etf_constituents(code)
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
    top_n: int = 4,
    rebalance_days: int = 10,
    mom_s_window: int = 20,
    stop_loss: float = -0.08
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
    """自动识别市场状态 BULL/RANGE/BEAR — 与 V4.0 激活参数面板使用相同算法"""
    from mean_reversion_engine import _classify_regime_from_series
    def _detect():
        import numpy as np
        ts.set_token(TUSHARE_TOKEN)
        pro_ = ts.pro_api()
        end_dt   = datetime.now().strftime("%Y%m%d")
        start_dt = (datetime.now() - timedelta(days=300)).strftime("%Y%m%d")
        df = pro_.index_daily(ts_code="000300.SH", start_date=start_dt, end_date=end_dt,
                              fields="trade_date,close,pct_chg")
        if df is None or len(df) < 30:
            return {"status": "error", "message": "CSI300 数据不足"}
        df = df.sort_values("trade_date").reset_index(drop=True)
        close = df["close"].astype(float).values

        # ── 统一算法 ──
        info   = _classify_regime_from_series(close)
        regime = info["regime"]
        rc     = info["regime_color"]
        ri     = info["regime_icon"]
        regime_cn = info["regime_cn"]

        latest = float(close[-1])
        ma120  = info["ma120"]
        ma60   = info["ma60"]
        slope5 = info["slope5"]
        ret5   = info["ret5"]
        ret20  = info["ret20"]

        pct    = df["pct_chg"].astype(float) / 100
        vol20  = float(pct.iloc[-20:].std() * (252**0.5) * 100) if len(pct) >= 20 else 20.0
        ret60  = float((close[-1]/close[-61] - 1)*100) if len(close) >= 61 else 0.0

        desc_map = {
            "BULL":  f"CSI300 ({latest:.0f}) 站上MA120 ({ma120:.0f})，均线向上，全力进攻。",
            "RANGE": f"CSI300 ({latest:.0f}) 站上MA120 ({ma120:.0f})，均线走平，均衡配置。",
            "BEAR":  f"CSI300 ({latest:.0f}) 跌破MA120 ({ma120:.0f})，防御优先。",
            "CRASH": f"CSI300 ({latest:.0f}) 触发熔断，禁止新建仓。",
        }
        # 震荡反弹子状态
        if regime == "RANGE" and not info["above_ma120"]:
            desc_map["RANGE"] = f"CSI300 ({latest:.0f}) 跌破MA120 ({ma120:.0f})，近5日反弹+{ret5:.1f}%，谨慎。"

        note_map = {
            "BULL":  "全力进攻：信号达标即可满仓",
            "RANGE": "均衡配置：仓位×0.77",
            "BEAR":  "防御模式：止损收至-6%",
            "CRASH": "禁止新建仓",
        }
        sg = {"BULL": 65, "RANGE": 68, "BEAR": 75, "CRASH": 999}.get(regime, 68)
        sl = -6 if regime == "BEAR" else -8

        # ── V6.0: 三层级联仓位建议 ──
        # Layer 1: AIAE 缓存 (matrix_position, AIAE×ERP 交叉查表)
        # Layer 2: config.POSITION_CONFIG (Regime 仓位上限)
        # Layer 3: AUDIT 硬天花板 95%
        # 输出: min(L1, L2, L3)
        aiae_cap = None
        pos_source = "regime"
        try:
            from services.cache_service import cache_manager
            aiae_ctx = cache_manager.get_json("aiae_ctx")
            if aiae_ctx and aiae_ctx.get("cap"):
                aiae_cap = int(aiae_ctx["cap"])
                pos_source = "aiae"
        except Exception:
            pass

        try:
            from config import POSITION_CONFIG as _PC
            # 取动量 Regime Cap (产业追踪页更贴近动量逻辑)
            regime_cap = _PC.get("mom_regime_cap", {}).get(regime, 66)
            audit_cap = int(_PC.get("total_cap", 95))
        except ImportError:
            regime_cap = {"BULL": 85, "RANGE": 60, "BEAR": 35, "CRASH": 0}.get(regime, 66)
            audit_cap = 95

        # 三层取最严
        candidates = [regime_cap, audit_cap]
        if aiae_cap is not None:
            candidates.append(aiae_cap)
        pc = min(candidates)

        return {
            "status": "ok", "as_of": datetime.now().strftime("%Y-%m-%d"),
            "latest_date": df["trade_date"].iloc[-1],
            "csi300": round(latest, 2), "ma60": round(ma60, 2), "ma120": round(ma120, 2),
            "above_ma120": info["above_ma120"], "ma120_rising": slope5 > 0,
            "ma120_slope5": round(slope5, 4),
            "ret5d": round(ret5, 2), "ret20d": round(ret20, 2),
            "ret60d": round(ret60, 2), "vol20d": round(vol20, 1),
            "regime": regime, "regime_cn": regime_cn,
            "regime_color": rc, "regime_icon": ri,
            "regime_desc": desc_map.get(regime, ""),
            "pos_cap": pc, "score_gate": sg,
            # V6.0: 分层仓位透明化
            "aiae_cap": aiae_cap,       # AIAE 宏观建议 (可能为 null)
            "regime_cap": regime_cap,    # Regime 仓位上限
            "audit_cap": audit_cap,      # 审计硬天花板
            "pos_source": pos_source,    # 数据来源: "aiae" 或 "regime"
            "optimal_params": {
                "top_n": 3, "rebalance_days": 5, "mom_window": 30,
                "stop_loss": sl, "pos_cap": pc, "entry_threshold": sg,
                "note": note_map.get(regime, ""),
            },
        }
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, _detect)
    except Exception as e:
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

            # V5.1 Fix P0#2: 统一引用 core_etf_config (Single Source of Truth)
            etf_list = CORE_ETFS

            sector_data = []
            # V4.0: 保存每个ETF的price_df用于detail API复用
            _price_cache = {}

            for etf in etf_list:
                code = etf['code']
                p_df = dm.get_price_payload(code)
                if p_df.empty:
                    sector_data.append({
                        "ts_code": code, "code": code, "name": etf['name'],
                        "trend_5d": 0.0, "ret_20d": 0.0,
                        "heat_score": 30.0, "heat_tier": "❄️ 冷淡",
                        "vol_ratio": 1.0, "vol_score": 50.0, "mom_score": 50.0, "crowd_score": 80.0,
                        "pe_percentile": 50.0,
                        "alpha_score": 30.0, "alpha_grade": "F",
                        "f_heat": 30.0, "f_momentum": 50.0, "f_valuation": 50.0, "f_trend": 0.0,
                        "trend_strength": {"above_ma20": False, "above_ma60": False, "ma20_slope": 0.0},
                        "risk_alerts": [],
                        "momentum_20d": {"ret_20d": 0.0, "label": "数据同步中", "trend": "neutral"},
                        "advice": "数据同步中", "advice_action": "neutral", "advice_label": "⚪ 等待同步",
                        "buy_strategy": "等待数据同步后再评估", "take_profit": "—", "stop_loss": "—", "position_cap": "0%"
                    })
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

                # V3.0: 生成五级建议 (入参升级为 alpha 驱动)
                advice = generate_sector_advice(
                    alpha['alpha_score'], alpha['alpha_grade'],
                    heat['heat_score'], pe_pct, trend,
                    alpha['trend_strength']
                )

                sector_data.append({
                    "ts_code": code, "code": code, "name": etf['name'],
                    "trend_5d": trend,
                    # V2.0 热度字段
                    "heat_score": heat['heat_score'],
                    "heat_tier": heat['heat_tier'],
                    "vol_ratio": heat['vol_ratio'],
                    "vol_score": heat['vol_score'],
                    "mom_score": heat['mom_score'],
                    "crowd_score": heat['crowd_score'],
                    "pe_percentile": pe_pct,
                    # V3.0 Alpha Score 字段
                    "alpha_score": alpha['alpha_score'],
                    "alpha_grade": alpha['alpha_grade'],
                    "ret_20d": alpha['ret_20d'],
                    "f_heat": alpha['f_heat'],
                    "f_momentum": alpha['f_momentum'],
                    "f_valuation": alpha['f_valuation'],
                    "f_trend": alpha['f_trend'],
                    "trend_strength": alpha['trend_strength'],
                    # V3.0 风险警示
                    "risk_alerts": alerts,
                    # V4.0 20D动量趋势 (替代北向资金)
                    "momentum_20d": mom_20d,
                    # V3.0 五级建议
                    "advice": advice['text'],
                    "advice_action": advice['action'],
                    "advice_label": advice['label'],
                    "buy_strategy": advice.get('buy_strategy', '—'),
                    "take_profit": advice.get('take_profit', '—'),
                    "stop_loss": advice.get('stop_loss', '—'),
                    "position_cap": advice.get('position_cap', '—')
                })

            # 影子排序数据兜底 (如果同步未就绪)
            if all(r['trend_5d'] == 0.0 for r in sector_data):
                # V5.1 Fix P0#2: 统一引用 core_etf_config.FALLBACK_MOMENTUM
                fallback = FALLBACK_MOMENTUM
                for r in sector_data:
                    r['trend_5d'] = fallback.get(r['ts_code'], 0.0)
                    heat = compute_sector_heat_score(pd.DataFrame(), r['trend_5d'])
                    r.update({"heat_score": heat['heat_score'], "heat_tier": heat['heat_tier'], "vol_ratio": 1.0})
                    pe_pct = 50.0  # V4.0: 兜底时用中性值而非硬编码
                    r['pe_percentile'] = pe_pct
                    alpha = compute_alpha_score(pd.DataFrame(), heat['heat_score'], r['trend_5d'], pe_pct)
                    r.update({
                        "alpha_score": alpha['alpha_score'], "alpha_grade": alpha['alpha_grade'],
                        "ret_20d": 0.0, "f_heat": alpha['f_heat'], "f_momentum": alpha['f_momentum'],
                        "f_valuation": alpha['f_valuation'], "f_trend": alpha['f_trend'],
                        "trend_strength": alpha['trend_strength'], "risk_alerts": [],
                        "momentum_20d": {"ret_20d": 0.0, "label": "数据兜底", "trend": "neutral"}
                    })
                    adv = generate_sector_advice(
                        alpha['alpha_score'], alpha['alpha_grade'],
                        heat['heat_score'], pe_pct, r['trend_5d'],
                        alpha['trend_strength']
                    )
                    r.update({
                        "advice": adv['text'], "advice_action": adv['action'], "advice_label": adv['label'],
                        "buy_strategy": adv.get('buy_strategy', '—'), "take_profit": adv.get('take_profit', '—'),
                        "stop_loss": adv.get('stop_loss', '—'), "position_cap": adv.get('position_cap', '—')
                    })

            # V3.0: 按 alpha_score 降序排列 (综合评分优先)
            sector_data.sort(key=lambda x: x.get('alpha_score', 0), reverse=True)

            # V4.0: 计算动态RPS排名 (需要全部sector_data准备好后)
            for item in sector_data:
                item['rps'] = compute_dynamic_rps(sector_data, item.get('ts_code') or item.get('code'))

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
                "last_update": datetime.now().strftime("%Y%m%d")
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

        # V6.0: freshness 从 latest 缓存读取
        _, latest_ts, _ = _tracking_cache_get("latest")
        return {"status": "success", "data": results,
                "data_freshness": {
                    "last_calc": latest_ts or datetime.now().isoformat(),
                    "etf_count": len(results.get("sector_heatmap", [])),
                    "cache_ttl_sec": _get_tracking_ttl()
                }}
    except Exception as e:
        logger.error(f"Industry Analysis Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

@router.post("/sync/industry")
async def sync_industry_data():
    """手动触发行业数据同步 (同步全部核心 ETF 及相关成分股)"""
    try:
        # V5.1 Fix P0#2: 统一引用 core_etf_config (Single Source of Truth)
        etf_codes = CORE_ETF_CODES
        
        def do_sync():
            mgr = FactorDataManager()
            # 同步 ETF 行情 (Tushare asset 'E' 代表 ETF)
            mgr.sync_daily_prices(etf_codes, asset='E') 
            # 同时也同步一部分成分股行情(可选)
            engine = IndustryEngine()
            stocks = engine._get_industry_stocks()
            if not stocks.empty:
                mgr.sync_daily_prices(stocks.head(10)['ts_code'].tolist())
            return mgr.get_last_sync_date(etf_codes)

        loop = asyncio.get_running_loop()
        last_date = await loop.run_in_executor(executor, do_sync)
        return {"status": "success", "last_date": last_date}
    except Exception as e:
        logger.error(f"Sync Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

# --- Portfolio Management API V2.0 (Singleton + Validation) ---

from portfolio_engine import get_portfolio_engine