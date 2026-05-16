"""
AlphaCore V24.1 · 三因子风险归因引擎
==========================================
将组合风险/收益暴露分解为 3 大风格因子 (可构建严格时间序列代理):

  - 市场因子 (Market/Beta):  大盘系统性风险
  - 规模因子 (Size/SMB):     小盘溢价暴露
  - 价值因子 (Value/HML):    低估值偏好

辅助横截面得分 (不参与回归, 仅用于个股画像):
  - 动量 (Momentum):   20日收益率排名百分位
  - 波动率 (Volatility): 20日已实现波动率排名百分位
  - 质量 (Quality):     行业启发式 ROE 档位

方法论:
  1. 从持仓日收益率和因子代理指数收益率构建回归矩阵
  2. 多元 OLS 回归 (Ridge λ=1e-6) 得到因子 Beta (载荷)
  3. 因子贡献 = Beta × Σ(因子日收益) (精确累计, 非均值×天数)
  4. 残差 = Alpha (选股能力)

因子代理:
  - Market: 沪深300 (000300.SH)
  - SMB:    中证1000 - 沪深300
  - HML:    上证红利 - 创业板指

降级: 完整回归 → 简化因子暴露 (回归数据不足时)
"""

import numpy as np
import pandas as pd
import statistics
from datetime import datetime, timedelta
from typing import Optional
from services.logger import get_logger
from services.cache_service import cache_manager

logger = get_logger("ac.factor_attr")

_CACHE_KEY = "factor_attribution"
_CACHE_TTL = 3600 * 2  # 2 小时

# ── 因子代理索引 ──
FACTOR_PROXIES = {
    "market":     {"ts_code": "000300.SH", "name": "沪深300",    "api": "index"},
    "small_cap":  {"ts_code": "000852.SH", "name": "中证1000",   "api": "index"},
    "value":      {"ts_code": "000015.SH", "name": "上证红利",   "api": "index"},
    "growth":     {"ts_code": "399006.SZ", "name": "创业板指",   "api": "index"},
}

# 因子元信息 (展示用)
FACTOR_META = {
    "market":     {"cn": "市场因子", "en": "Market β",   "icon": "📈", "color": "#6366f1"},
    "smb":        {"cn": "规模因子", "en": "Size/SMB",   "icon": "📐", "color": "#3b82f6"},
    "hml":        {"cn": "价值因子", "en": "Value/HML",  "icon": "💎", "color": "#f59e0b"},
    "momentum":   {"cn": "动量因子", "en": "Momentum",   "icon": "🚀", "color": "#10b981"},
    "volatility": {"cn": "波动率因子", "en": "Volatility", "icon": "⚡", "color": "#ef4444"},
    "quality":    {"cn": "质量因子", "en": "Quality/ROE", "icon": "🏆", "color": "#8b5cf6"},
}


def _to_date_indexed(df: pd.DataFrame) -> pd.DataFrame:
    """确保 DataFrame 以 trade_date 为索引, 消除整数 index 对齐错误。"""
    if df is None or df.empty:
        return df
    if 'trade_date' in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index('trade_date')
    return df


def _fetch_factor_returns(lookback: int = 120) -> dict:
    """
    获取因子代理收益率序列 (以 trade_date 为索引)。

    Returns: {
        "market": pd.Series (index=DatetimeIndex),
        "smb": pd.Series (中证1000 - 沪深300),
        "hml": pd.Series (红利 - 创业板),
    }
    """
    from data_manager import FactorDataManager
    dm = FactorDataManager()

    factor_rets = {}

    # Market
    try:
        mkt_df = _to_date_indexed(dm.get_price_payload("000300.SH"))
        if mkt_df is not None and len(mkt_df) >= lookback:
            mkt_ret = mkt_df["close"].pct_change().dropna().tail(lookback)
            factor_rets["market"] = mkt_ret
    except Exception as e:
        logger.warning("Factor: 市场因子获取失败: %s", e)

    # SMB = 小盘 - 大盘 (中证1000 - 沪深300)
    try:
        small_df = _to_date_indexed(dm.get_price_payload("000852.SH"))
        if small_df is not None and len(small_df) >= lookback and "market" in factor_rets:
            small_ret = small_df["close"].pct_change().dropna().tail(lookback)
            # 对齐日期 (DatetimeIndex 交集)
            common = small_ret.index.intersection(factor_rets["market"].index)
            if len(common) > 30:
                factor_rets["smb"] = small_ret.loc[common] - factor_rets["market"].loc[common]
    except Exception as e:
        logger.warning("Factor: SMB 因子构建失败: %s", e)

    # HML = 价值 - 成长 (红利 - 创业板)
    try:
        val_df = _to_date_indexed(dm.get_price_payload("000015.SH"))
        gro_df = _to_date_indexed(dm.get_price_payload("399006.SZ"))
        if val_df is not None and gro_df is not None:
            val_ret = val_df["close"].pct_change().dropna().tail(lookback)
            gro_ret = gro_df["close"].pct_change().dropna().tail(lookback)
            common = val_ret.index.intersection(gro_ret.index)
            if len(common) > 30:
                factor_rets["hml"] = val_ret.loc[common] - gro_ret.loc[common]
    except Exception as e:
        logger.warning("Factor: HML 因子构建失败: %s", e)

    return factor_rets


def _compute_stock_factor_scores(positions: list) -> dict:
    """
    计算个股因子得分 (横截面):
    - Momentum: 20日收益率排名百分位
    - Volatility: 20日已实现波动率排名百分位
    - Quality: 根据行业推断 ROE 档位

    Returns: {ts_code: {"momentum": float, "volatility": float, "quality": float}}
    """
    from data_manager import FactorDataManager
    dm = FactorDataManager()
    scores = {}

    # 收集原始指标
    raw_data = []
    for pos in positions:
        code = pos["ts_code"]
        try:
            p_df = dm.get_price_payload(code)
            if p_df is not None and len(p_df) >= 20:
                closes = p_df["close"].values
                ret_20d = closes[-1] / closes[-20] - 1
                daily_rets = np.diff(closes[-21:]) / closes[-21:-1]
                vol_20d = float(np.std(daily_rets) * np.sqrt(252))
                raw_data.append({
                    "ts_code": code,
                    "momentum": ret_20d,
                    "volatility": vol_20d,
                })
        except Exception:
            raw_data.append({"ts_code": code, "momentum": 0, "volatility": 0.2})

    if not raw_data:
        return {}

    # 排名百分位化
    n = len(raw_data)
    mom_sorted = sorted(raw_data, key=lambda x: x["momentum"])
    vol_sorted = sorted(raw_data, key=lambda x: x["volatility"])

    mom_rank = {d["ts_code"]: (i / max(n - 1, 1)) for i, d in enumerate(mom_sorted)}
    vol_rank = {d["ts_code"]: (i / max(n - 1, 1)) for i, d in enumerate(vol_sorted)}

    # Quality: 基于行业启发式 (精确版本需拉取 ROE 数据)
    quality_map = {
        "食品饮料": 0.85, "银行": 0.75, "贵金属": 0.6, "半导体": 0.5,
        "电力设备": 0.55, "医药生物": 0.6, "证券": 0.45, "房地产": 0.3,
        "红利/低波": 0.8, "宽基-沪深300": 0.65, "宽基-科创板": 0.4,
    }

    for d in raw_data:
        code = d["ts_code"]
        # 找到对应持仓获取行业
        industry = "其他"
        for pos in positions:
            if pos["ts_code"] == code:
                industry = pos.get("industry", "其他")
                break

        scores[code] = {
            "momentum": round(mom_rank.get(code, 0.5), 3),
            "volatility": round(vol_rank.get(code, 0.5), 3),
            "quality": round(quality_map.get(industry, 0.5), 3),
        }

    return scores


def _ols_regression(y: np.ndarray, X: np.ndarray, ridge_lambda: float = 1e-6) -> dict:
    """
    Ridge 回归 (OLS + 微正则化, 消除多重共线性不稳定)。

    Args:
        ridge_lambda: 正则化系数 (1e-6 几乎不影响估计, 但保证数值稳定)

    Returns: {"alpha": float, "betas": list, "r_squared": float, "residuals": array}
    """
    n = len(y)
    # 加常数项
    ones = np.ones((n, 1))
    X_aug = np.hstack([ones, X])
    k = X_aug.shape[1]

    try:
        XtX = X_aug.T @ X_aug

        # 条件数检查
        cond = np.linalg.cond(XtX)
        if cond > 1e10:
            logger.warning("OLS: XtX 条件数过高 (%.2e), 因子间可能存在多重共线性", cond)

        # Ridge 正则化: (X'X + λI)^(-1) X'y  (不惩罚截距项)
        reg_matrix = ridge_lambda * np.eye(k)
        reg_matrix[0, 0] = 0  # 截距不正则化
        XtX_reg = XtX + reg_matrix

        Xty = X_aug.T @ y
        betas = np.linalg.solve(XtX_reg, Xty)

        y_hat = X_aug @ betas
        residuals = y - y_hat

        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = max(0.0, 1 - ss_res / ss_tot) if ss_tot > 0 else 0

        return {
            "alpha": float(betas[0]),
            "betas": betas[1:].tolist(),
            "r_squared": float(r_squared),
            "residuals": residuals,
            "condition_number": float(cond),
        }
    except np.linalg.LinAlgError as e:
        logger.error("OLS: 回归失败 (LinAlgError): %s", e)
        return {
            "alpha": 0, "betas": [0] * X.shape[1],
            "r_squared": 0, "residuals": np.zeros(n),
            "condition_number": float('inf'),
        }


def compute_factor_attribution(lookback: int = 60) -> dict:
    """
    多因子风险归因主函数。

    Args:
        lookback: 回归窗口 (交易日)

    Returns: {
        "status": "success",
        "factors": [
            {
                "name": "market", "cn": "市场因子",
                "beta": float,           # 因子载荷
                "contribution": float,   # 期间贡献 %
                "exposure_level": str,   # "high" / "neutral" / "low"
            }
        ],
        "regression": {
            "r_squared": float,  # 模型解释力
            "alpha": float,      # 截距 (选股能力)
            "alpha_annual": float,
        },
        "portfolio_decomposition": {
            "systematic_pct": float,  # 系统性风险占比
            "idiosyncratic_pct": float,  # 特质风险占比
        },
        "stock_exposures": [...],  # 个股因子得分
    }
    """
    # ── 1. 获取组合持仓和收益率 ──
    try:
        from portfolio_engine import get_portfolio_engine
        pe = get_portfolio_engine()
        val = pe.get_valuation()
    except Exception as e:
        return {"status": "error", "error": f"持仓读取失败: {e}"}

    positions = val.get("positions", [])
    if len(positions) < 2:
        return {"status": "insufficient", "error": "至少需要 2 只持仓"}

    # ── 2. 构建组合日收益率 ──
    from data_manager import FactorDataManager
    dm = FactorDataManager()

    total_mv = sum(p.get("market_value", 0) for p in positions)
    if total_mv <= 0:
        return {"status": "error", "error": "总市值为零"}

    weights = {p["ts_code"]: p.get("market_value", 0) / total_mv for p in positions}

    stock_rets = {}
    for pos in positions:
        try:
            p_df = _to_date_indexed(dm.get_price_payload(pos["ts_code"]))
            if p_df is not None and len(p_df) >= lookback:
                sr = p_df["close"].pct_change().dropna().tail(lookback)
                if sr.index.duplicated().any():
                    sr = sr[~sr.index.duplicated(keep='last')]
                stock_rets[pos["ts_code"]] = sr
        except Exception:
            pass

    if len(stock_rets) < 2:
        return {"status": "insufficient", "error": "可用收益率数据不足"}

    # 构建组合收益率序列
    df_rets = pd.DataFrame(stock_rets).fillna(0)
    if df_rets.index.duplicated().any():
        df_rets = df_rets[~df_rets.index.duplicated(keep='last')]

    available_codes = list(df_rets.columns)
    w_arr = np.array([weights.get(c, 0) for c in available_codes])
    w_arr = w_arr / w_arr.sum()  # 重新归一化

    port_ret = df_rets.values @ w_arr

    # ── 3. 获取因子收益率 ──
    factor_rets = _fetch_factor_returns(lookback)

    if "market" not in factor_rets:
        return {"status": "degraded", "error": "市场因子数据不可用"}

    # 对齐日期
    factor_names = list(factor_rets.keys())
    common_idx = df_rets.index
    for fn in factor_names:
        common_idx = common_idx.intersection(factor_rets[fn].index)

    if len(common_idx) < 30:
        return {"status": "insufficient", "error": f"对齐后数据不足 ({len(common_idx)} 日)"}

    # 构建因子矩阵
    port_ret_aligned = pd.Series(port_ret, index=df_rets.index).loc[common_idx].values
    X = np.column_stack([factor_rets[fn].loc[common_idx].values for fn in factor_names])

    # ── 4. OLS 回归 ──
    reg = _ols_regression(port_ret_aligned, X)

    # ── 5. 因子贡献 (精确累计: β × Σ因子日收益) ──
    factors_result = []
    for i, fn in enumerate(factor_names):
        beta = reg["betas"][i]
        factor_cumulative = float(factor_rets[fn].loc[common_idx].sum())
        factor_mean_ret = float(factor_rets[fn].loc[common_idx].mean())
        contribution = beta * factor_cumulative  # β × Σ(r_f) 精确累计

        # 暴露等级
        if fn == "market":
            level = "high" if beta > 1.1 else ("low" if beta < 0.8 else "neutral")
        else:
            level = "high" if abs(beta) > 0.3 else ("low" if abs(beta) < 0.1 else "neutral")

        meta = FACTOR_META.get(fn, {"cn": fn, "en": fn, "icon": "📊", "color": "#64748b"})
        factors_result.append({
            "name": fn,
            "cn": meta["cn"],
            "en": meta["en"],
            "icon": meta["icon"],
            "color": meta["color"],
            "beta": round(beta, 4),
            "contribution": round(contribution * 100, 3),
            "factor_return": round(factor_mean_ret * 252 * 100, 2),  # 年化%
            "exposure_level": level,
        })

    # ── 6. 个股因子得分 ──
    stock_scores = _compute_stock_factor_scores(positions)

    stock_exposures = []
    for pos in positions:
        code = pos["ts_code"]
        sc = stock_scores.get(code, {})
        stock_exposures.append({
            "ts_code": code,
            "name": pos["name"],
            "weight": round(weights.get(code, 0) * 100, 2),
            "industry": pos.get("industry", "其他"),
            "momentum": sc.get("momentum", 0.5),
            "volatility": sc.get("volatility", 0.5),
            "quality": sc.get("quality", 0.5),
        })
    stock_exposures.sort(key=lambda x: x["weight"], reverse=True)

    # ── 7. 系统性 vs 特质风险 (clamp 防溢出) ──
    systematic_var = np.var(port_ret_aligned - reg["residuals"])
    total_var = np.var(port_ret_aligned)
    systematic_pct = min(100.0, max(0.0, systematic_var / total_var * 100)) if total_var > 0 else 0

    # Alpha 年化 (线性法, 对小日频 alpha 更稳健)
    alpha_daily = reg["alpha"]
    alpha_annual = alpha_daily * 252

    result = {
        "status": "success",
        "lookback_days": len(common_idx),
        "factor_count": len(factors_result),

        "factors": factors_result,

        "regression": {
            "r_squared": round(reg["r_squared"], 4),
            "r_squared_pct": round(reg["r_squared"] * 100, 1),
            "alpha_daily": round(alpha_daily * 10000, 2),  # bps
            "alpha_annual": round(alpha_annual * 100, 2),  # %
        },

        "portfolio_decomposition": {
            "systematic_pct": round(systematic_pct, 1),
            "idiosyncratic_pct": round(100 - systematic_pct, 1),
        },

        "stock_exposures": stock_exposures[:20],  # Top 20
        "computed_at": datetime.now().isoformat(),
    }

    cache_manager.set_json(_CACHE_KEY, result, ttl_seconds=_CACHE_TTL)
    return result
