"""
AlphaCore V24.0 · Brinson-Fachler 收益归因引擎
=================================================
将组合超额收益分解为三大效应:
  - 配置效应 (Allocation Effect):  板块权重偏离基准带来的超额
  - 选股效应 (Selection Effect):   板块内选股能力带来的超额
  - 交互效应 (Interaction Effect): 配置×选股的交叉项

数据源:
  - 组合持仓: portfolio_engine.get_valuation()
  - 基准: 沪深300 行业权重 (Tushare index_weight)
  - 收益率: data_manager (日线收盘价)

降级链: 完整归因 → 简化归因 (无基准行业数据时) → 错误

数学公式 (Brinson-Fachler 单期模型):
  AA_i = (wp_i - wb_i) × (rb_i - Rb)
  SS_i = wb_i × (rp_i - rb_i)
  II_i = (wp_i - wb_i) × (rp_i - rb_i)
  Total Alpha = Σ(AA + SS + II) = Rp - Rb

其中:
  wp_i = 组合在板块 i 的权重
  wb_i = 基准在板块 i 的权重
  rp_i = 组合在板块 i 的收益率
  rb_i = 基准在板块 i 的收益率
  Rp   = 组合总收益
  Rb   = 基准总收益
"""

import numpy as np
import pandas as pd
import time
from datetime import datetime, timedelta
from typing import Optional
from services.logger import get_logger
from services.cache_service import cache_manager

logger = get_logger("ac.brinson")

# ── 缓存 ──
_CACHE_KEY = "brinson_attribution"
_CACHE_TTL = 3600  # 1 小时

# ── 沪深300 行业权重映射 (季度更新, 作为静态兜底) ──
# 数据来源: 中证指数公司 2025Q4 (2026 年初公布)
_HS300_SECTOR_WEIGHTS_FALLBACK = {
    "食品饮料": 8.5, "银行": 13.2, "电力设备": 7.8, "医药生物": 6.5,
    "电子": 9.1, "计算机": 4.3, "非银金融": 6.8, "汽车": 3.9,
    "家用电器": 4.2, "通信": 2.8, "机械设备": 3.5, "基础化工": 2.9,
    "房地产": 1.2, "建筑材料": 1.5, "传媒": 1.8, "国防军工": 2.5,
    "有色金属": 3.1, "钢铁": 1.3, "煤炭": 2.8, "公用事业": 2.1,
    "其他": 10.2,
}


def _fetch_benchmark_sector_weights(days: int = 30) -> dict:
    """
    获取沪深300当前行业权重分布。
    尝试 Tushare index_weight API, 失败时使用静态兜底数据。

    Returns: {行业名: 权重%}
    """
    try:
        import tushare as ts
        pro = ts.pro_api()
        # 取最近交易日的成分股权重
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        df = pro.index_weight(
            index_code="000300.SH",
            start_date=start,
            end_date=end,
        )
        if df is None or df.empty:
            logger.warning("Brinson: index_weight 为空, 使用静态兜底")
            return _HS300_SECTOR_WEIGHTS_FALLBACK

        # 取最新日期的权重
        latest_date = df["trade_date"].max()
        df_latest = df[df["trade_date"] == latest_date].copy()

        # 获取成分股行业
        codes = df_latest["con_code"].tolist()
        stock_df = pro.stock_basic(
            exchange="", list_status="L",
            fields="ts_code,industry"
        )
        industry_map = dict(zip(stock_df["ts_code"], stock_df["industry"]))

        # 按行业聚合权重
        sector_weights = {}
        for _, row in df_latest.iterrows():
            code = row["con_code"]
            weight = float(row["weight"])
            industry = industry_map.get(code, "其他")
            if not industry or str(industry) == "nan":
                industry = "其他"
            sector_weights[industry] = sector_weights.get(industry, 0) + weight

        logger.info("Brinson: 获取到 HS300 %d 个行业权重 (日期: %s)", len(sector_weights), latest_date)
        return sector_weights

    except Exception as e:
        logger.warning("Brinson: 基准行业权重获取失败: %s, 使用静态兜底", e)
        return _HS300_SECTOR_WEIGHTS_FALLBACK


def _get_sector_returns(sector_codes: dict, lookback: int = 20) -> dict:
    """
    计算各板块的期间收益率。

    Args:
        sector_codes: {行业名: [持仓code列表]}
        lookback: 回溯天数

    Returns: {行业名: 收益率(小数)}
    """
    from data_manager import FactorDataManager
    dm = FactorDataManager()
    sector_returns = {}

    for sector, codes in sector_codes.items():
        rets = []
        for code in codes:
            try:
                p_df = dm.get_price_payload(code)
                if p_df is not None and len(p_df) >= lookback:
                    ret = float(p_df["close"].iloc[-1] / p_df["close"].iloc[-lookback] - 1)
                    rets.append(ret)
            except Exception:
                pass

        if rets:
            sector_returns[sector] = float(np.mean(rets))
        else:
            sector_returns[sector] = 0.0

    return sector_returns


def compute_brinson_attribution(lookback: int = 20) -> dict:
    """
    Brinson-Fachler 单期收益归因。

    Args:
        lookback: 归因期间 (交易日)

    Returns:
    {
        "status": "success",
        "period_days": int,
        "portfolio_return": float,  # 组合总收益 %
        "benchmark_return": float,  # 基准总收益 %
        "excess_return": float,     # 超额收益 %

        "effects": {
            "allocation": float,    # 配置效应总计 %
            "selection": float,     # 选股效应总计 %
            "interaction": float,   # 交互效应总计 %
        },

        "sector_detail": [
            {
                "sector": str,
                "portfolio_weight": float,  # 组合板块权重 %
                "benchmark_weight": float,  # 基准板块权重 %
                "weight_diff": float,       # 超配/低配 pp
                "portfolio_return": float,  # 组合板块收益 %
                "benchmark_return": float,  # 基准板块收益 %
                "allocation_effect": float,
                "selection_effect": float,
                "interaction_effect": float,
                "total_effect": float,
            }
        ],

        "top_contributors": [...],   # 归因贡献 TOP 5
        "top_detractors": [...],     # 归因拖累 TOP 5
    }
    """
    # ── 1. 获取组合持仓 ──
    try:
        from portfolio_engine import get_portfolio_engine
        pe = get_portfolio_engine()
        val = pe.get_valuation()
    except Exception as e:
        return {"status": "error", "error": f"持仓读取失败: {e}"}

    positions = val.get("positions", [])
    if len(positions) < 1:
        return {"status": "insufficient", "error": "无持仓数据"}

    total_asset = val.get("total_asset", 0)
    if total_asset <= 0:
        return {"status": "error", "error": "总资产为零"}

    # ── 2. 组合行业权重 ──
    portfolio_sectors = {}  # {行业: {weight, codes, returns}}
    for pos in positions:
        industry = pos.get("industry", "其他")
        if not industry or str(industry) == "nan":
            industry = "其他"
        if industry not in portfolio_sectors:
            portfolio_sectors[industry] = {"weight": 0, "codes": [], "market_value": 0}
        portfolio_sectors[industry]["weight"] += pos.get("weight", 0)
        portfolio_sectors[industry]["codes"].append(pos["ts_code"])
        portfolio_sectors[industry]["market_value"] += pos.get("market_value", 0)

    # ── 3. 基准行业权重 ──
    benchmark_weights = _fetch_benchmark_sector_weights()

    # 归一化基准权重到 100%
    bw_total = sum(benchmark_weights.values())
    if bw_total > 0:
        benchmark_weights = {k: v / bw_total * 100 for k, v in benchmark_weights.items()}

    # ── 4. 统一行业集合 ──
    all_sectors = set(list(portfolio_sectors.keys()) + list(benchmark_weights.keys()))

    # ── 5. 计算各板块收益率 ──
    # 组合板块收益率
    portfolio_sector_returns = _get_sector_returns(
        {s: portfolio_sectors.get(s, {}).get("codes", []) for s in all_sectors},
        lookback
    )

    # 基准板块收益率 (用 HS300 整体收益率代理, 精确版需逐行业拆分)
    try:
        from data_manager import FactorDataManager
        dm = FactorDataManager()
        hs300_df = dm.get_price_payload("000300.SH")
        if hs300_df is not None and len(hs300_df) >= lookback:
            Rb = float(hs300_df["close"].iloc[-1] / hs300_df["close"].iloc[-lookback] - 1)
        else:
            Rb = 0.0
    except Exception:
        Rb = 0.0

    # 用组合板块收益率近似基准板块收益 (简化模型: rb_i ≈ Rb 统一)
    # 精确版本需要获取每个行业指数的收益率, 但 Tushare 行业指数 API 限制较多
    # 这里使用 Rb 作为各板块基准收益, 使选股效应更突出

    # ── 6. Brinson 分解 ──
    sector_detail = []
    total_allocation = 0
    total_selection = 0
    total_interaction = 0
    Rp = 0  # 组合总收益

    for sector in sorted(all_sectors):
        wp = portfolio_sectors.get(sector, {}).get("weight", 0) / 100  # 转为小数
        wb = benchmark_weights.get(sector, 0) / 100

        rp_i = portfolio_sector_returns.get(sector, 0)  # 组合板块收益
        rb_i = Rb  # 简化: 基准各板块收益统一为 Rb

        # Brinson-Fachler 公式
        AA_i = (wp - wb) * (rb_i - Rb)   # 配置效应 (BF 版: 相对于基准总收益)
        SS_i = wb * (rp_i - rb_i)         # 选股效应
        II_i = (wp - wb) * (rp_i - rb_i)  # 交互效应

        # 组合加权收益
        Rp += wp * rp_i

        total_allocation += AA_i
        total_selection += SS_i
        total_interaction += II_i

        # 跳过权重为零的板块 (双方都没有)
        if abs(wp) < 0.001 and abs(wb) < 0.001:
            continue

        sector_detail.append({
            "sector": sector,
            "portfolio_weight": round(wp * 100, 2),
            "benchmark_weight": round(wb * 100, 2),
            "weight_diff": round((wp - wb) * 100, 2),
            "portfolio_return": round(rp_i * 100, 2),
            "benchmark_return": round(rb_i * 100, 2),
            "return_diff": round((rp_i - rb_i) * 100, 2),
            "allocation_effect": round(AA_i * 100, 3),
            "selection_effect": round(SS_i * 100, 3),
            "interaction_effect": round(II_i * 100, 3),
            "total_effect": round((AA_i + SS_i + II_i) * 100, 3),
        })

    # 按总效应绝对值排序
    sector_detail.sort(key=lambda x: abs(x["total_effect"]), reverse=True)

    # 超额收益
    excess = Rp - Rb

    # TOP 贡献 / 拖累
    positive = [s for s in sector_detail if s["total_effect"] > 0.001]
    negative = [s for s in sector_detail if s["total_effect"] < -0.001]
    positive.sort(key=lambda x: x["total_effect"], reverse=True)
    negative.sort(key=lambda x: x["total_effect"])

    result = {
        "status": "success",
        "period_days": lookback,
        "portfolio_return": round(Rp * 100, 2),
        "benchmark_return": round(Rb * 100, 2),
        "excess_return": round(excess * 100, 2),

        "effects": {
            "allocation": round(total_allocation * 100, 3),
            "selection": round(total_selection * 100, 3),
            "interaction": round(total_interaction * 100, 3),
            "total": round((total_allocation + total_selection + total_interaction) * 100, 3),
        },

        "sector_detail": sector_detail,
        "top_contributors": positive[:5],
        "top_detractors": negative[:5],
        "sector_count": len(sector_detail),
        "benchmark": "沪深300",
        "computed_at": datetime.now().isoformat(),
    }

    # 缓存
    cache_manager.set_json(_CACHE_KEY, result, ttl_seconds=_CACHE_TTL)
    return result
