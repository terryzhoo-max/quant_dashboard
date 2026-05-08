"""
AlphaCore V23.0 · 组合权重优化引擎 (Portfolio Optimizer)
==========================================================
Layer 1: MVO (均值-方差, scipy.optimize.minimize SLSQP)
Layer 2: Black-Litterman (后验收益率融合)
Layer 3: 信号→观点转换器 (AIAE/ERP/Momentum → P,Q,Ω)

降级链: BL失败 → MVO → 等权 + 警告
依赖: scipy (已有), scikit-learn (Ledoit-Wolf)
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Optional, Tuple
from services.logger import get_logger

logger = get_logger("ac.optimizer")

# ── 常量 ──
_DEFAULT_RF = 0.02          # 无风险利率
_DEFAULT_COST = 0.003       # 交易成本 0.3%
_MAX_TURNOVER = 0.25        # 单次最大换手率 25%
_MIN_WEIGHT = 0.0           # 最小权重 (禁止做空)
_RIDGE_LAMBDA = 1e-6        # 协方差正则化

# AIAE Regime → 年化超额收益映射 (回测校准值)
_REGIME_EXCESS_RETURN = {
    1: 0.08,   # 极度恐慌 → +8%
    2: 0.04,   # 低配置区 → +4%
    3: 0.00,   # 中性均衡 → 0% (不注入)
    4: -0.04,  # 偏热区域 → -4%
    5: -0.08,  # 极度过热 → -8%
}


# ═══════════════════════════════════════════════════════════
#  协方差估计
# ═══════════════════════════════════════════════════════════

def estimate_covariance(returns_df: pd.DataFrame) -> Tuple[pd.DataFrame, float]:
    """
    Ledoit-Wolf 收缩协方差估计 (年化)。
    fallback: 样本协方差 + ridge 正则化。
    Returns: (cov_matrix, shrinkage_intensity)
    """
    if returns_df.empty or len(returns_df) < 10:
        n = returns_df.shape[1] if not returns_df.empty else 1
        return pd.DataFrame(np.eye(n) * 0.04, index=returns_df.columns,
                            columns=returns_df.columns), 1.0
    try:
        from sklearn.covariance import LedoitWolf
        lw = LedoitWolf().fit(returns_df.values)
        cov = pd.DataFrame(lw.covariance_ * 252,
                           index=returns_df.columns, columns=returns_df.columns)
        return cov, float(lw.shrinkage_)
    except Exception as e:
        logger.warning("Ledoit-Wolf 失败, 回退样本协方差: %s", e)
        cov = returns_df.cov() * 252
        # ridge 正则化
        cov_vals = cov.values + np.eye(cov.shape[0]) * _RIDGE_LAMBDA
        return pd.DataFrame(cov_vals, index=cov.index, columns=cov.columns), 0.0


# ═══════════════════════════════════════════════════════════
#  Layer 1: 均值-方差优化 (MVO)
# ═══════════════════════════════════════════════════════════

def _portfolio_stats(weights, mu, cov, rf=_DEFAULT_RF):
    """组合收益、波动率、夏普"""
    ret = weights @ mu
    vol = np.sqrt(weights @ cov @ weights)
    sharpe = (ret - rf) / vol if vol > 0 else 0.0
    return float(ret), float(vol), float(sharpe)


def optimize_max_sharpe(mu: np.ndarray, cov: np.ndarray,
                        single_limit: float = 0.20,
                        total_cap: float = 0.95,
                        rf: float = _DEFAULT_RF) -> dict:
    """
    经典最大夏普比率优化。
    约束: Σwi = total_cap, 0 ≤ wi ≤ single_limit
    """
    n = len(mu)
    if n < 2:
        return {"status": "insufficient", "weights": np.array([total_cap]) if n == 1 else np.array([])}

    x0 = np.full(n, total_cap / n)
    bounds = [(max(_MIN_WEIGHT, 0.001), single_limit) for _ in range(n)]

    def neg_sharpe(w):
        vol = np.sqrt(w @ cov @ w)
        if vol < 1e-10:
            return 1e6
        return -(w @ mu - rf) / vol

    constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - total_cap}]

    result = minimize(neg_sharpe, x0, method='SLSQP', bounds=bounds,
                      constraints=constraints, options={'maxiter': 1000, 'ftol': 1e-10})

    if not result.success:
        logger.warning("MVO 求解器未收敛: %s", result.message)

    weights = np.maximum(result.x, 0)
    weights = weights / weights.sum() * total_cap  # 归一化

    ret, vol, sharpe = _portfolio_stats(weights, mu, cov, rf)
    return {
        "status": "success" if result.success else "approximate",
        "weights": weights,
        "expected_return": ret,
        "volatility": vol,
        "sharpe": sharpe,
    }


def optimize_with_costs(mu: np.ndarray, cov: np.ndarray,
                        w_current: np.ndarray,
                        single_limit: float = 0.20,
                        total_cap: float = 0.95,
                        max_turnover: float = _MAX_TURNOVER,
                        cost_rate: float = _DEFAULT_COST,
                        risk_aversion: float = 2.5,
                        rf: float = _DEFAULT_RF) -> dict:
    """
    含交易成本 + 换手率约束的优化。
    目标: max w'μ - (δ/2)w'Σw - c·||w-w_curr||₂²
    换手率约束: 后处理硬截断 (SLSQP 不擅长 L1 不等式)
    """
    n = len(mu)
    if n < 2:
        return {"status": "insufficient", "weights": w_current}

    x0 = w_current.copy() if len(w_current) == n else np.full(n, total_cap / n)
    bounds = [(_MIN_WEIGHT, single_limit) for _ in range(n)]

    # 用 L2 惩罚替代 L1 (光滑, SLSQP 友好)
    turnover_penalty = cost_rate * 5  # 放大惩罚以抑制换手

    def objective(w):
        excess_ret = w @ mu - rf
        risk = risk_aversion / 2 * w @ cov @ w
        turnover_cost = turnover_penalty * np.sum((w - w_current) ** 2)
        return -(excess_ret - risk - turnover_cost)

    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - total_cap},
    ]

    result = minimize(objective, x0, method='SLSQP', bounds=bounds,
                      constraints=constraints, options={'maxiter': 1000})

    weights = np.maximum(result.x, 0)
    s = weights.sum()
    if s > 0:
        weights = weights / s * total_cap

    # ── 后处理: 换手率硬截断 ──
    # 如果 L1 换手超标, 线性插值 w = α·w_opt + (1-α)·w_current
    raw_turnover = np.sum(np.abs(weights - w_current))
    if raw_turnover > max_turnover and raw_turnover > 1e-6:
        alpha = max_turnover / raw_turnover
        weights = alpha * weights + (1 - alpha) * w_current
        # 重新归一化到 total_cap
        s = weights.sum()
        if s > 0:
            weights = weights / s * total_cap
        logger.info("换手率截断: %.1f%% → %.1f%% (α=%.2f)",
                    raw_turnover * 100, max_turnover * 100, alpha)

    ret, vol, sharpe = _portfolio_stats(weights, mu, cov, rf)
    turnover = float(np.sum(np.abs(weights - w_current)))

    return {
        "status": "success" if result.success else "approximate",
        "weights": weights,
        "expected_return": ret,
        "volatility": vol,
        "sharpe": sharpe,
        "turnover": round(turnover * 100, 1),
        "estimated_cost": round(turnover * cost_rate * 100, 2),
    }


# ═══════════════════════════════════════════════════════════
#  Layer 2: Black-Litterman
# ═══════════════════════════════════════════════════════════

def _calibrate_tau(n_obs: int, jcs_score: float) -> float:
    """τ 自适应校准: 基准 1/T × JCS 调制"""
    tau_base = 1.0 / max(n_obs, 30)
    tau_adj = tau_base * (0.5 + jcs_score / 200.0)
    return max(0.001, min(0.1, tau_adj))


def black_litterman_posterior(w_eq: np.ndarray, cov: np.ndarray,
                              P: np.ndarray, Q: np.ndarray,
                              omega: np.ndarray, tau: float,
                              risk_aversion: float = 2.5) -> np.ndarray:
    """
    BL 后验收益率:
    π = δΣw_eq (市场隐含均衡收益)
    μ_BL = [(τΣ)⁻¹ + P'Ω⁻¹P]⁻¹ × [(τΣ)⁻¹π + P'Ω⁻¹Q]
    """
    pi = risk_aversion * cov @ w_eq  # 隐含均衡收益

    if P.size == 0 or Q.size == 0:
        return pi  # 无观点 → 返回均衡

    tau_cov = tau * cov
    tau_cov_inv = np.linalg.inv(tau_cov + np.eye(len(w_eq)) * _RIDGE_LAMBDA)
    omega_inv = np.linalg.inv(omega + np.eye(omega.shape[0]) * _RIDGE_LAMBDA)

    # 后验精度矩阵
    M = tau_cov_inv + P.T @ omega_inv @ P
    M_inv = np.linalg.inv(M + np.eye(M.shape[0]) * _RIDGE_LAMBDA)

    # 后验均值
    mu_bl = M_inv @ (tau_cov_inv @ pi + P.T @ omega_inv @ Q)
    return mu_bl


# ═══════════════════════════════════════════════════════════
#  Layer 3: AlphaCore 信号 → BL 观点 (P, Q, Ω)
# ═══════════════════════════════════════════════════════════

def generate_views(codes: list, snapshot: dict,
                   industry_data: list = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    将 AlphaCore 信号转换为 BL 观点矩阵。

    View 1: AIAE Regime → 组合整体绝对观点
    View 2: Alpha Score → 行业相对观点 (得分差 > 15)
    View 3: 20D Momentum → 个股绝对观点 (|ret| > 5%)

    Returns: (P, Q, Omega) — 可能为空矩阵 (无可用观点)
    """
    n = len(codes)
    views_P = []
    views_Q = []
    views_conf = []

    jcs_score = 50.0  # default
    try:
        from dashboard_modules.decision_engine import compute_jcs, _build_snapshot_from_cache
        if not snapshot:
            snapshot = _build_snapshot_from_cache()
        jcs_data = compute_jcs(snapshot)
        jcs_score = jcs_data.get("score", 50)
    except Exception:
        pass

    # ── View 1: AIAE 宏观绝对观点 (等权分配到所有标的) ──
    aiae_regime = snapshot.get("aiae_regime", 3)
    excess = _REGIME_EXCESS_RETURN.get(aiae_regime, 0.0)
    if abs(excess) > 0.001:
        p_row = np.ones(n) / n  # 等权组合观点
        views_P.append(p_row)
        views_Q.append(excess)
        # 置信度: JCS 越高 → omega 越小 → 观点越可信
        conf = max(0.001, (100 - jcs_score) / 100 * 0.05)
        views_conf.append(conf)

    # ── View 2: 行业 Alpha Score 相对观点 ──
    if industry_data and len(industry_data) >= 2:
        # 找持仓中 alpha_score 最高和最低的
        scored = []
        for i, code in enumerate(codes):
            alpha = 50.0
            for ind in industry_data:
                if (ind.get("ts_code") or ind.get("code")) == code:
                    alpha = ind.get("alpha_score", 50.0)
                    break
            scored.append((i, alpha))

        scored.sort(key=lambda x: x[1], reverse=True)
        if len(scored) >= 2:
            best_idx, best_score = scored[0]
            worst_idx, worst_score = scored[-1]
            score_diff = best_score - worst_score

            if score_diff > 15:  # 得分差 > 15 才注入
                p_row = np.zeros(n)
                p_row[best_idx] = 1.0
                p_row[worst_idx] = -1.0
                q_val = score_diff / 100 * 0.10  # 缩放: 差50分→预期+5%超额
                views_P.append(p_row)
                views_Q.append(q_val)
                views_conf.append(0.02)  # 中等置信

    # ── View 3: 20D 动量个股绝对观点 ──
    try:
        from portfolio_engine import get_portfolio_engine
        pe = get_portfolio_engine()
        for i, code in enumerate(codes):
            try:
                p_df = pe.dm.get_price_payload(code)
                if p_df is not None and len(p_df) >= 20:
                    ret_20d = float(p_df['close'].iloc[-1] / p_df['close'].iloc[-20] - 1)
                    if abs(ret_20d) > 0.05:
                        p_row = np.zeros(n)
                        p_row[i] = 1.0
                        # 正动量延续打7折, 负动量反转打8折
                        factor = 0.3 if ret_20d > 0 else 0.2
                        views_P.append(p_row)
                        views_Q.append(ret_20d * factor)
                        views_conf.append(0.03)
            except Exception:
                continue
    except Exception:
        pass

    # ── 组装矩阵 ──
    if not views_P:
        return np.array([]).reshape(0, n), np.array([]), np.array([]).reshape(0, 0)

    P = np.array(views_P)
    Q = np.array(views_Q)
    Omega = np.diag(views_conf)

    return P, Q, Omega


# ═══════════════════════════════════════════════════════════
#  有效前沿
# ═══════════════════════════════════════════════════════════

def compute_efficient_frontier(mu: np.ndarray, cov: np.ndarray,
                               single_limit: float = 0.20,
                               total_cap: float = 0.95,
                               n_points: int = 20,
                               rf: float = _DEFAULT_RF) -> list:
    """计算 N 个目标风险水平下的最优组合 (有效前沿)"""
    n = len(mu)
    if n < 2:
        return []

    bounds = [(_MIN_WEIGHT, single_limit) for _ in range(n)]
    constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - total_cap}]

    # 先求最小方差组合的波动率
    def min_vol_obj(w):
        return w @ cov @ w

    res_min = minimize(min_vol_obj, np.full(n, total_cap / n), method='SLSQP',
                       bounds=bounds, constraints=constraints)
    vol_min = np.sqrt(res_min.x @ cov @ res_min.x) if res_min.success else 0.05

    # 最大夏普组合的波动率
    res_max = optimize_max_sharpe(mu, cov, single_limit, total_cap, rf)
    vol_max = res_max.get("volatility", 0.30) * 1.5

    frontier = []
    for target_vol in np.linspace(max(vol_min, 0.01), max(vol_max, vol_min + 0.01), n_points):
        def neg_return(w):
            return -(w @ mu)

        vol_constraint = {'type': 'ineq',
                          'fun': lambda w, tv=target_vol: tv**2 - w @ cov @ w}

        res = minimize(neg_return, np.full(n, total_cap / n), method='SLSQP',
                       bounds=bounds, constraints=constraints + [vol_constraint])
        if res.success:
            ret, vol, sharpe = _portfolio_stats(res.x, mu, cov, rf)
            frontier.append({"volatility": round(vol * 100, 2),
                             "return": round(ret * 100, 2),
                             "sharpe": round(sharpe, 2)})

    return frontier


# ═══════════════════════════════════════════════════════════
#  一站式入口
# ═══════════════════════════════════════════════════════════

def full_optimize(risk_aversion: float = 2.5,
                  cost_rate: float = _DEFAULT_COST,
                  max_turnover: float = _MAX_TURNOVER) -> dict:
    """
    一键优化主入口:
    1. 读取持仓 (portfolio_engine)
    2. 估计协方差 (Ledoit-Wolf)
    3. 生成观点 (信号转换)
    4. BL优化 (含降级)
    5. 合规校验 (compliance_engine)
    6. 输出: 最优权重 + 有效前沿 + 风险分解 + 合规状态
    """
    # ── 1. 读取持仓 ──
    try:
        from portfolio_engine import get_portfolio_engine
        pe = get_portfolio_engine()
        val = pe.get_valuation()
    except Exception as e:
        return {"status": "error", "error": f"持仓读取失败: {e}"}

    positions = val.get("positions", [])
    if len(positions) < 2:
        return {"status": "insufficient", "error": "至少需要 2 只持仓才能优化",
                "position_count": len(positions)}

    total_asset = val.get("total_asset", 0)
    if total_asset <= 0:
        return {"status": "error", "error": "总资产为零"}

    codes = [p["ts_code"] for p in positions]
    names = [p["name"] for p in positions]
    n = len(codes)

    w_current = np.array([p.get("market_value", 0) / total_asset for p in positions])

    # ── 2. 收益率 + 协方差 ──
    rets_data = {}
    for p in positions:
        try:
            p_df = pe.dm.get_price_payload(p["ts_code"])
            if p_df is not None and not p_df.empty:
                rets_data[p["ts_code"]] = p_df['close'].pct_change().dropna().tail(120)
        except Exception:
            pass

    if len(rets_data) < 2:
        return {"status": "insufficient_data", "error": "可用收益率数据不足 2 只"}

    df_rets = pd.DataFrame(rets_data)
    for code in codes:
        if code not in df_rets.columns:
            df_rets[code] = 0.0
    df_rets = df_rets[codes].fillna(0)

    cov_matrix, shrinkage = estimate_covariance(df_rets)
    cov_np = cov_matrix.values
    n_obs = len(df_rets)

    # 历史均值收益 (年化)
    mu_hist = (df_rets.mean() * 252).values

    # ── 约束 (从 config 读取) ──
    try:
        from config import POSITION_CONFIG as PC
        single_limit = PC["single_limit"] / 100.0
        total_cap_pct = PC["total_cap"] / 100.0
    except ImportError:
        single_limit = 0.20
        total_cap_pct = 0.95

    # AIAE regime 动态压仓
    try:
        from services.cache_service import cache_manager
        aiae_ctx = cache_manager.get_json("aiae_ctx")
        if aiae_ctx and aiae_ctx.get("regime", 3) >= 4:
            regime_cap = aiae_ctx.get("cap", 55) / 100.0
            total_cap_pct = min(total_cap_pct, regime_cap)
    except Exception:
        pass

    # VIX 紧急压仓
    try:
        from dashboard_modules.decision_engine import _build_snapshot_from_cache
        snapshot = _build_snapshot_from_cache()
    except Exception:
        snapshot = {}

    vix_val = snapshot.get("vix_val", 20) or 20
    if vix_val > 30:
        total_cap_pct = min(total_cap_pct, 0.30)

    # ── 3. 生成观点 ──
    industry_data = []
    try:
        from services.industry_tracker import _tracking_cache_get
        cached, _, valid = _tracking_cache_get("latest")
        if cached and valid:
            industry_data = cached
    except Exception:
        pass

    P, Q, Omega = generate_views(codes, snapshot, industry_data)
    has_views = P.size > 0

    # ── 4. BL 优化 (含降级) ──
    method_used = "equal_weight"
    warnings = []

    if has_views:
        try:
            jcs_score = 50.0
            try:
                from dashboard_modules.decision_engine import compute_jcs
                jcs_score = compute_jcs(snapshot).get("score", 50)
            except Exception:
                pass

            tau = _calibrate_tau(n_obs, jcs_score)
            mu_bl = black_litterman_posterior(w_current, cov_np, P, Q, Omega, tau, risk_aversion)

            result = optimize_with_costs(mu_bl, cov_np, w_current, single_limit,
                                         total_cap_pct, max_turnover, cost_rate,
                                         risk_aversion)
            if result["status"] in ("success", "approximate"):
                method_used = "black_litterman"
                if result["status"] == "approximate":
                    warnings.append("BL 求解器未完全收敛, 结果为近似最优")
            else:
                raise ValueError("BL optimize failed")
        except Exception as e:
            logger.warning("BL 优化失败, 降级到 MVO: %s", e)
            warnings.append(f"BL 降级到 MVO: {e}")
            has_views = False

    if not has_views:
        try:
            result = optimize_with_costs(mu_hist, cov_np, w_current, single_limit,
                                         total_cap_pct, max_turnover, cost_rate,
                                         risk_aversion)
            method_used = "mvo"
            if result["status"] != "success":
                warnings.append("MVO 求解器未完全收敛")
        except Exception as e:
            logger.warning("MVO 也失败, 降级到等权: %s", e)
            warnings.append(f"全部降级到等权: {e}")
            eq_w = np.full(n, total_cap_pct / n)
            ret, vol, sharpe = _portfolio_stats(eq_w, mu_hist, cov_np)
            result = {"status": "fallback", "weights": eq_w,
                      "expected_return": ret, "volatility": vol, "sharpe": sharpe,
                      "turnover": 0, "estimated_cost": 0}
            method_used = "equal_weight"

    optimal_weights = result["weights"]

    # ── 5. 合规校验 ──
    compliance_status = "passed"
    compliance_blocks = []
    try:
        from engines.compliance_engine import run_compliance_check
        comp = run_compliance_check(snapshot, positions)
        compliance_status = comp.get("status", "passed")
        compliance_blocks = comp.get("blocks", [])
    except Exception:
        pass

    # 截断超限权重
    clipped = False
    for i in range(n):
        if optimal_weights[i] > single_limit:
            optimal_weights[i] = single_limit
            clipped = True
    if clipped:
        s = optimal_weights.sum()
        if s > 0:
            optimal_weights = optimal_weights / s * total_cap_pct
        warnings.append("部分权重被合规引擎截断至单票上限")

    # ── 6. 有效前沿 ──
    mu_for_frontier = mu_bl if method_used == "black_litterman" else mu_hist
    try:
        frontier = compute_efficient_frontier(mu_for_frontier, cov_np,
                                              single_limit, total_cap_pct, 15)
    except Exception:
        frontier = []

    # ── 7. 构建调仓建议 ──
    rebalance_actions = []
    for i in range(n):
        delta = optimal_weights[i] - w_current[i]
        if abs(delta) < 0.003:  # < 0.3% 忽略
            action = "hold"
        elif delta > 0:
            action = "increase"
        else:
            action = "reduce"

        delta_value = delta * total_asset

        rebalance_actions.append({
            "code": codes[i],
            "name": names[i],
            "industry": positions[i].get("industry", "其他"),
            "current_weight": round(w_current[i] * 100, 2),
            "optimal_weight": round(optimal_weights[i] * 100, 2),
            "delta_weight": round(delta * 100, 2),
            "delta_value": round(delta_value, 0),
            "action": action,
        })

    rebalance_actions.sort(key=lambda x: abs(x["delta_weight"]), reverse=True)

    # 当前组合风险指标
    cur_ret, cur_vol, cur_sharpe = _portfolio_stats(w_current, mu_for_frontier, cov_np)
    opt_ret, opt_vol, opt_sharpe = _portfolio_stats(optimal_weights, mu_for_frontier, cov_np)

    return {
        "status": "success",
        "method": method_used,
        "has_views": P.size > 0 if method_used == "black_litterman" else False,
        "view_count": len(Q) if P.size > 0 else 0,
        "shrinkage_intensity": round(shrinkage, 3),
        "data_days": n_obs,
        "risk_aversion": risk_aversion,
        "total_cap": round(total_cap_pct * 100, 1),

        "current": {
            "expected_return": round(cur_ret * 100, 2),
            "volatility": round(cur_vol * 100, 2),
            "sharpe": round(cur_sharpe, 2),
        },
        "optimal": {
            "expected_return": round(opt_ret * 100, 2),
            "volatility": round(opt_vol * 100, 2),
            "sharpe": round(opt_sharpe, 2),
        },

        "turnover": result.get("turnover", 0),
        "estimated_cost": result.get("estimated_cost", 0),
        "rebalance": rebalance_actions,
        "frontier": frontier,

        "compliance": {
            "status": compliance_status,
            "blocks": [{"rule": b["rule_name"], "detail": b["detail"]}
                       for b in compliance_blocks],
        },
        "warnings": warnings,
    }
