"""8Y渐进式池参数快速调优"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from strategies.momentum_backtest_engine import (
    MomentumBacktester, PerformanceEvaluator, FactorDataManager,
    load_price_matrix, BENCHMARK_CODE
)

dm = FactorDataManager()

FULL_POOL = [
    {"code": "159905.SZ", "group": "A"}, {"code": "159915.SZ", "group": "A"},
    {"code": "513500.SH", "group": "B"}, {"code": "159941.SZ", "group": "B"},
    {"code": "159949.SZ", "group": "A"}, {"code": "512100.SH", "group": "C"},
    {"code": "512560.SH", "group": "D"}, {"code": "512400.SH", "group": "E"},
    {"code": "512480.SH", "group": "F"}, {"code": "515000.SH", "group": "F"},
    {"code": "515880.SH", "group": "F"}, {"code": "515070.SH", "group": "F"},
    {"code": "512660.SH", "group": "D"}, {"code": "512720.SH", "group": "F"},
    {"code": "512760.SH", "group": "F"}, {"code": "512880.SH", "group": "G"},
    {"code": "159995.SZ", "group": "F"}, {"code": "515030.SH", "group": "E"},
    {"code": "159819.SZ", "group": "F"}, {"code": "515790.SH", "group": "E"},
    {"code": "516160.SH", "group": "E"}, {"code": "159870.SZ", "group": "E"},
    {"code": "159869.SZ", "group": "H"}, {"code": "513130.SH", "group": "H"},
]

all_codes = [e["code"] for e in FULL_POOL] + [BENCHMARK_CODE]
group_map = {e["code"]: e["group"] for e in FULL_POOL}

pm = load_price_matrix(all_codes, "2017-01-01", "2025-12-31", dm)
bench_prices = pm.get(BENCHMARK_CODE)
strat_prices = pm.drop(columns=[BENCHMARK_CODE], errors="ignore")
bench_returns = bench_prices.pct_change().dropna()
hs300 = load_price_matrix(["000300.SH"], "2017-01-01", "2025-12-31", dm).get("000300.SH")

BASE = dict(
    top_n=4, rebalance_days=10, mom_s_window=20, mom_m_window=60,
    w_mom_s=0.40, w_mom_m=0.20, w_slope=0.15, w_sharpe=0.15, w_trend=0.10,
    stop_loss=-0.08, position_cap=0.90,
    cumulative_stop=True, stop_bull=-0.99, stop_range=-0.10, stop_bear=-0.07,
    adaptive_rebalance=True, rebal_bull=3, rebal_range=10, rebal_bear=20,
    dual_ma_regime=True,
)

configs = [
    ("BASE",                {}),
    ("top3",                {"top_n": 3}),
    ("top5",                {"top_n": 5}),
    ("cap85",               {"position_cap": 0.85}),
    ("cap95",               {"position_cap": 0.95}),
    ("rebal_bear25",        {"rebal_bear": 25}),
    ("rebal_bear30",        {"rebal_bear": 30}),
    ("rebal_bull5",         {"rebal_bull": 5}),
    ("moms45",              {"w_mom_s": 0.45, "w_mom_m": 0.15}),
    ("moms50+slope20",      {"w_mom_s": 0.50, "w_mom_m": 0.10, "w_slope": 0.20}),
    ("bear30+top3",         {"rebal_bear": 30, "top_n": 3}),
    ("bear25+cap95",        {"rebal_bear": 25, "position_cap": 0.95}),
    ("bear30+moms45",       {"rebal_bear": 30, "w_mom_s": 0.45, "w_mom_m": 0.15}),
    ("bear25+top3+moms45",  {"rebal_bear": 25, "top_n": 3, "w_mom_s": 0.45, "w_mom_m": 0.15}),
]

print("%-25s %7s %7s %7s %8s %7s %8s %8s" % (
    "Config", "CAGR%", "MaxDD%", "Sharpe", "ExCAGR%", "IR", "OOS_Sh", "OOS_Ex"))
print("-" * 95)

for label, overrides in configs:
    params = {**BASE, **overrides}
    bt = MomentumBacktester(**params)

    # Full
    r = bt.run(strat_prices, hs300, group_map)
    p = PerformanceEvaluator.evaluate(r["portfolio_returns"], bench_returns, "f")

    # OOS 2022+
    sp_oos = strat_prices.loc["2022-01-01":]
    br_oos = bench_returns.loc["2022-01-01":]
    r_oos = bt.run(sp_oos, hs300, group_map)
    p_oos = PerformanceEvaluator.evaluate(r_oos["portfolio_returns"], br_oos, "o")

    cagr = p.get("cagr", "?")
    mdd = p.get("max_drawdown", "?")
    sh = p.get("sharpe", "?")
    ex = p.get("excess_cagr", "?")
    ir = p.get("information_ratio", "?")
    oos_sh = p_oos.get("sharpe", "?")
    oos_ex = p_oos.get("excess_cagr", "?")

    print("%-25s %7s %7s %7s %8s %7s %8s %8s" % (label, cagr, mdd, sh, ex, ir, oos_sh, oos_ex))

print("\nDONE")
