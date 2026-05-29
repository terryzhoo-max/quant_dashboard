"""
AlphaCore V5.0 · 子策略联合回测引擎
============================================================
验证 V5 配额矩阵下的组合策略表现。

方法论:
  · 使用 ETF 月收益率作为各子策略收益代理
  · 每月按 AIAE regime → SUB_STRATEGY_ALLOC 分配权重
  · 计算组合净值曲线 / CAGR / MDD / Sharpe
  · 对比: V5联合 vs 等权 vs 纯沪深300 vs 纯红利

ETF 代理:
  · MR  → 沪深300 (510300) — 均值回归主战场
  · DIV → 红利低波100 (515100) — 红利策略核心
  · MOM → 创业板 (159915) — 动量轮动代理
  · GEM → 纳指100 QDII (513100) / 黄金 (518880) 混合
  · ERP → 国债ETF (511010) — 低风险配置

用法: python engines/portfolio_backtest.py
"""

import sys
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════
#  子策略 ETF 代理标的
# ═══════════════════════════════════════════════════════

STRATEGY_PROXY = {
    "mr":  {"code": "510300.SH", "name": "沪深300ETF",   "fallback_annual": 0.08},
    "div": {"code": "515100.SH", "name": "红利低波100",   "fallback_annual": 0.10},
    "mom": {"code": "159915.SZ", "name": "创业板ETF",     "fallback_annual": 0.06},
    "gem": {"code": "518880.SH", "name": "黄金ETF",       "fallback_annual": 0.05},
    "erp": {"code": "511010.SH", "name": "国债ETF",       "fallback_annual": 0.03},
}

# 现金收益率 (年化)
CASH_RATE = 0.02


def _fetch_monthly_returns(start_month: str = "2018-01") -> pd.DataFrame:
    """
    获取 ETF 月收益率矩阵。
    优先使用 Tushare API，失败时使用本地缓存或合成数据。
    """
    cache_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data_lake", "portfolio_backtest_returns.parquet"
    )

    if os.path.exists(cache_path):
        df = pd.read_parquet(cache_path)
        if len(df) > 50:
            print(f"[联合回测] 使用缓存月收益矩阵: {len(df)} 月")
            return df

    # 尝试 Tushare 获取
    try:
        return _fetch_from_tushare(start_month, cache_path)
    except Exception as e:
        print(f"[联合回测] Tushare 不可用 ({e}), 使用合成收益")
        return _generate_synthetic_returns(start_month)


def _fetch_from_tushare(start_month: str, cache_path: str) -> pd.DataFrame:
    """从 Tushare 获取真实 ETF 月收益率"""
    import tushare as ts
    from config import TUSHARE_TOKEN
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    start_date = start_month.replace("-", "") + "01"
    end_date = datetime.now().strftime("%Y%m%d")

    all_returns = {}

    for strat_key, proxy in STRATEGY_PROXY.items():
        code = proxy["code"]
        try:
            df = ts.pro_bar(
                ts_code=code, asset='FD', adj='qfq',
                start_date=start_date, end_date=end_date,
                freq='M'
            )
            if df is None or len(df) < 10:
                # 月频失败时用日频聚合
                df = ts.pro_bar(
                    ts_code=code, asset='FD', adj='qfq',
                    start_date=start_date, end_date=end_date,
                )
                if df is not None and not df.empty:
                    df = df.sort_values('trade_date')
                    df['month'] = df['trade_date'].str[:7]
                    monthly = df.groupby('month')['close'].last()
                    returns = monthly.pct_change().dropna()
                    all_returns[strat_key] = returns
                    print(f"  [OK] {proxy['name']}({code}): {len(returns)} 月 (日→月)")
                    continue

            if df is not None and not df.empty:
                df = df.sort_values('trade_date')
                df['month'] = df['trade_date'].str[:7]
                returns = df.set_index('month')['close'].pct_change().dropna()
                all_returns[strat_key] = returns
                print(f"  [OK] {proxy['name']}({code}): {len(returns)} 月")
            else:
                print(f"  [WARN] {proxy['name']}({code}): 无数据, 使用回退")
                all_returns[strat_key] = None
        except Exception as e:
            print(f"  [WARN] {proxy['name']}({code}): {e}")
            all_returns[strat_key] = None

    # 合并为矩阵
    valid = {k: v for k, v in all_returns.items() if v is not None}
    if len(valid) < 3:
        raise ValueError(f"仅获取 {len(valid)} 只ETF数据, 不足")

    result = pd.DataFrame(valid)
    result.index.name = 'month'

    # 填充缺失策略
    for key in STRATEGY_PROXY:
        if key not in result.columns:
            annual = STRATEGY_PROXY[key]["fallback_annual"]
            result[key] = annual / 12

    result = result.sort_index()
    result = result[result.index >= start_month]

    # 缓存
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    result.to_parquet(cache_path)
    print(f"[联合回测] 月收益矩阵已缓存: {len(result)} 月")
    return result


def _generate_synthetic_returns(start_month: str) -> pd.DataFrame:
    """
    无 API 时的合成收益率（基于各 ETF 的历史统计特征）。
    用于演示和验证管道正确性。
    """
    # 历史统计特征 (月均收益率 / 月波动率)
    params = {
        "mr":  (0.006, 0.065),   # 沪深300: ~7.5% CAGR, ~22% vol
        "div": (0.008, 0.040),   # 红利低波: ~10% CAGR, ~14% vol
        "mom": (0.005, 0.085),   # 创业板: ~6% CAGR, ~29% vol
        "gem": (0.004, 0.035),   # 黄金: ~5% CAGR, ~12% vol
        "erp": (0.0025, 0.008),  # 国债: ~3% CAGR, ~3% vol
    }

    months = pd.date_range(start_month + "-01", datetime.now(), freq='MS')
    month_strs = [m.strftime("%Y-%m") for m in months]

    np.random.seed(42)
    data = {}
    for key, (mu, sigma) in params.items():
        data[key] = np.random.normal(mu, sigma, len(month_strs))

    df = pd.DataFrame(data, index=month_strs)
    df.index.name = 'month'
    print(f"[联合回测] 合成收益矩阵: {len(df)} 月 (seed=42)")
    return df


# ═══════════════════════════════════════════════════════
#  组合回测核心
# ═══════════════════════════════════════════════════════

def run_portfolio_backtest(start_month: str = "2018-01") -> dict:
    """
    执行 V5 联合回测。

    策略:
      1. V5_ALLOC: 按 AIAE regime → SUB_STRATEGY_ALLOC 动态配比
      2. EQUAL_WEIGHT: 各子策略等权 20%
      3. PURE_300: 纯沪深300
      4. PURE_DIV: 纯红利低波
      5. CASH: 纯现金
    """
    from engines.aiae_engine import get_aiae_engine
    from engines.aiae_params import SUB_STRATEGY_ALLOC, V5_POSITION_MATRIX

    engine = get_aiae_engine()

    # 1. 加载 regime 历史
    pq_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data_lake", "aiae_true_history.parquet"
    )
    history = pd.read_parquet(pq_path)
    history = history[history['month'] >= start_month].copy()

    # 重新计算 V5 regime
    history['v5_regime'] = history['aiae_simple'].apply(
        lambda x: engine.classify_regime(25.0, None, aiae_simple=x)
    )

    # 获取仓位上限 (使用 matrix_position 或默认 erp_4_6)
    def _get_cap(row):
        r = row['v5_regime']
        erp_tier = row.get('erp_tier', 'erp_4_6')
        if pd.isna(erp_tier) or not erp_tier:
            erp_tier = 'erp_4_6'
        return engine.get_position_from_matrix(r, erp_tier, aiae_value=row['aiae_simple']) / 100.0
    history['v5_cap'] = history.apply(_get_cap, axis=1)

    regime_months = history.set_index('month')[['v5_regime', 'v5_cap', 'aiae_simple']].to_dict('index')
    print(f"[联合回测] Regime 历史: {len(regime_months)} 月")

    # 2. 加载月收益矩阵
    returns = _fetch_monthly_returns(start_month)

    # 对齐月份
    common_months = sorted(set(regime_months.keys()) & set(returns.index))
    if len(common_months) < 12:
        print(f"[联合回测] 仅 {len(common_months)} 个共同月份, 数据不足")
        return {"status": "error", "error": f"仅 {len(common_months)} 共同月份"}

    print(f"[联合回测] 共同月份: {len(common_months)} ({common_months[0]}~{common_months[-1]})")

    # 3. 计算各策略净值
    strategies = {
        "V5_联合配置": {},
        "等权20%": {},
        "纯沪深300": {},
        "纯红利低波": {},
    }

    nav = {k: 1.0 for k in strategies}
    nav_series = {k: [] for k in strategies}
    monthly_detail = []

    for month in common_months:
        rm = regime_months[month]
        regime = rm['v5_regime']
        cap = rm['v5_cap']
        aiae = rm['aiae_simple']
        ret = returns.loc[month]

        # V5 联合配置: regime → 配额 → 仓位上限约束
        alloc = SUB_STRATEGY_ALLOC.get(regime, SUB_STRATEGY_ALLOC[3])
        total_equity_pct = cap  # AIAE 总仓位上限

        # 子策略权重 (配额归一化后乘以总仓位)
        alloc_sum = sum(alloc.values())
        weights_v5 = {}
        for key in ["mr", "div", "mom", "gem", "erp"]:
            raw_weight = alloc.get(key, 0) / alloc_sum
            weights_v5[key] = raw_weight * total_equity_pct

        cash_pct = max(0, 1.0 - sum(weights_v5.values()))
        v5_ret = sum(weights_v5.get(k, 0) * ret.get(k, 0) for k in STRATEGY_PROXY) + cash_pct * CASH_RATE / 12

        # 等权 20%
        eq_ret = sum(0.2 * ret.get(k, 0) for k in STRATEGY_PROXY)

        # 纯沪深300
        pure300_ret = ret.get("mr", 0)

        # 纯红利
        pure_div_ret = ret.get("div", 0)

        # 更新净值
        nav["V5_联合配置"] *= (1 + v5_ret)
        nav["等权20%"] *= (1 + eq_ret)
        nav["纯沪深300"] *= (1 + pure300_ret)
        nav["纯红利低波"] *= (1 + pure_div_ret)

        for k in strategies:
            nav_series[k].append({"month": month, "nav": round(nav[k], 4)})

        monthly_detail.append({
            "month": month,
            "aiae_simple": round(aiae, 1),
            "regime": regime,
            "cap": round(cap * 100, 0),
            "weights": {k: round(v * 100, 1) for k, v in weights_v5.items()},
            "cash_pct": round(cash_pct * 100, 1),
            "returns": {
                "V5": round(v5_ret * 100, 2),
                "EQ": round(eq_ret * 100, 2),
                "300": round(pure300_ret * 100, 2),
                "DIV": round(pure_div_ret * 100, 2),
            }
        })

    # 4. 计算绩效指标
    results = {}
    for name, series in nav_series.items():
        navs = [s["nav"] for s in series]
        rets = [navs[i] / navs[i-1] - 1 for i in range(1, len(navs))]

        # CAGR
        n_years = len(common_months) / 12
        cagr = (navs[-1] / navs[0]) ** (1 / n_years) - 1 if n_years > 0 else 0

        # MDD
        peak = navs[0]
        mdd = 0
        for n in navs:
            peak = max(peak, n)
            dd = (peak - n) / peak
            mdd = max(mdd, dd)

        # Sharpe (月频 → 年化)
        if len(rets) > 2:
            sharpe = (np.mean(rets) / np.std(rets)) * np.sqrt(12) if np.std(rets) > 0 else 0
        else:
            sharpe = 0

        # Calmar
        calmar = cagr / mdd if mdd > 0 else 0

        # Win rate
        win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100 if rets else 0

        results[name] = {
            "final_nav": round(navs[-1], 4),
            "cagr_pct": round(cagr * 100, 2),
            "mdd_pct": round(mdd * 100, 2),
            "sharpe": round(sharpe, 2),
            "calmar": round(calmar, 2),
            "win_rate": round(win_rate, 1),
            "months": len(common_months),
            "nav_series": series,
        }

    # 5. Regime 分析
    regime_stats = {}
    for r in range(1, 6):
        r_months = [d for d in monthly_detail if d["regime"] == r]
        if r_months:
            v5_rets = [d["returns"]["V5"] for d in r_months]
            regime_stats[f"R{r}"] = {
                "months": len(r_months),
                "avg_return": round(np.mean(v5_rets), 2),
                "avg_cap": round(np.mean([d["cap"] for d in r_months]), 0),
            }

    # 6. 组装结果
    output = {
        "status": "success",
        "period": f"{common_months[0]} ~ {common_months[-1]}",
        "total_months": len(common_months),
        "strategies": results,
        "regime_analysis": regime_stats,
        "monthly_detail": monthly_detail[-6:],  # 最近 6 月明细
        "generated_at": datetime.now().isoformat(),
    }

    # 保存结果
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "portfolio_backtest_results.json"
    )
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[联合回测] 结果已保存: {out_path}")

    return output


def print_summary(result: dict):
    """打印回测摘要"""
    if result["status"] != "success":
        print(f"回测失败: {result.get('error')}")
        return

    print("\n" + "=" * 65)
    print(f"  V5 子策略联合回测报告 | {result['period']} ({result['total_months']}月)")
    print("=" * 65)

    header = f"{'策略':<14} {'终值':>6} {'CAGR':>7} {'MDD':>7} {'Sharpe':>7} {'Calmar':>7} {'胜率':>6}"
    print(header)
    print("-" * 65)
    for name, s in result["strategies"].items():
        row = (f"{name:<14} {s['final_nav']:>6.2f} {s['cagr_pct']:>6.1f}% "
               f"{s['mdd_pct']:>6.1f}% {s['sharpe']:>7.2f} {s['calmar']:>7.2f} {s['win_rate']:>5.1f}%")
        print(row)

    print("\n  Regime 分析:")
    for rk, rv in result.get("regime_analysis", {}).items():
        print(f"    {rk}: {rv['months']}月, 月均收益={rv['avg_return']:.2f}%, 平均仓位={rv['avg_cap']:.0f}%")

    print("=" * 65)


if __name__ == "__main__":
    result = run_portfolio_backtest("2018-01")
    print_summary(result)
