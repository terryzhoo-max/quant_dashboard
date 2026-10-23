"""
组合回撤刹车 (分档 + 迟滞) 校准
================================

    python -m strategies.drawdown_calibration          # 结果写 data_lake/drawdown_calibration.json

方法 (与生产 services/drawdown.py 同一口径):
  · 信号: 风险资产净值 (不含现金) 自高水位的回撤, 收盘判定
  · 执行: 次日开盘调仓, 隔夜收益按旧仓位、日内按新仓位; 开盘即跌停 → 卖出顺延; 单边成本 0.1%; 现金年化 1.5%
  · 资产池: data_lake/daily_prices 全部可交易标的, 每只单独作为一个 "组合" ——
    本账户有效独立押注 ≈1.3, 行为更接近单一资产而不是分散组合
  · 样本内 < 2021-01-01 ≤ 样本外; 指标取各资产相对买入持有的中位数
  · 网格 = 当前参数的邻域 (±2pp / 软硬两种仓位上限 / 回补 1/3 vs 1/2) —— 选平稳区域, 不追单点最优
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Callable, Optional

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from strategies.trailing_stop_calibration import load_assets, limit_pct  # noqa: E402

OUT_PATH = os.path.join(_ROOT, "data_lake", "drawdown_calibration.json")
SPLIT = "2021-01-01"
CASH = 0.015 / 250
COST = 0.001

GRID = {
    "D 12/20/28→75/50/25": [(0.12, 0.75), (0.20, 0.50), (0.28, 0.25)],
    "D− 10/18/26": [(0.10, 0.75), (0.18, 0.50), (0.26, 0.25)],
    "D+ 14/22/30": [(0.14, 0.75), (0.22, 0.50), (0.30, 0.25)],
    "软 →80/60/40": [(0.12, 0.80), (0.20, 0.60), (0.28, 0.40)],
    "硬 →70/40/20": [(0.12, 0.70), (0.20, 0.40), (0.28, 0.20)],
}


def simulate(open_: np.ndarray, close: np.ndarray, pre_close: np.ndarray, lim: float,
             tiers: list, rerisk: float, signal: str = "book") -> tuple[np.ndarray, np.ndarray]:
    n = len(close)
    acct, book, e, target = 1.0, 1.0, 1.0, 1.0
    hwm, tier, trough = 1.0, 0, 1.0
    nav, expo = np.ones(n), np.ones(n)
    for t in range(1, n):
        r_on = open_[t] / close[t - 1] - 1
        r_id = close[t] / open_[t] - 1
        locked = open_[t] <= pre_close[t] * (1 - lim) * 1.002
        acct *= 1 + e * r_on + (1 - e) * CASH / 2
        if target != e and not (target < e and locked):
            acct *= 1 - COST * abs(target - e)
            e = target
        acct *= 1 + e * r_id + (1 - e) * CASH / 2
        book *= (1 + r_on) * (1 + r_id)
        nav[t], expo[t] = acct, e
        x = book if signal == "book" else acct
        hwm = max(hwm, x)
        dd = x / hwm - 1
        lvl = tier
        while lvl < len(tiers) and dd <= -tiers[lvl][0]:
            lvl += 1
        if lvl > tier:
            tier, trough = lvl, x
        elif tier > 0:
            trough = min(trough, x)
            if x >= trough + rerisk * (hwm - trough) or x >= hwm:
                tier, trough = tier - 1, x
        target = 1.0 if tier == 0 else tiers[tier - 1][1]
    return nav, expo


def _metrics(nav: pd.Series, expo: pd.Series) -> dict:
    nav = nav / nav.iloc[0]
    yrs = len(nav) / 250
    cagr = nav.iloc[-1] ** (1 / yrs) - 1
    dd = nav / nav.cummax() - 1
    mdd = float(dd.min())
    return {"cagr": cagr, "mdd": mdd, "calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
            "ulcer": float(np.sqrt((dd ** 2).mean())), "expo": float(expo.mean()),
            "turn": float(expo.diff().abs().sum() / yrs)}


def run(loader: Optional[Callable[[str], pd.DataFrame]] = None, codes: Optional[list] = None) -> dict:
    assets = load_assets(loader, codes)
    pols = {"BH": ([], 0.0, "book")}
    for name, t in GRID.items():
        for rr in (1 / 3, 1 / 2):
            pols[f"{name} 回补{round(rr * 100)}%"] = (t, rr, "book")
    rows = []
    for a in assets:
        if len(a["C"]) < 500:
            continue
        c = a["C"]
        o = np.where(a["O"] > 0, a["O"], c)
        pc = np.r_[c[0], c[:-1]]                     # 已连续化收盘 → 前收
        for pn, (t, rr, sig) in pols.items():
            nav, ex = simulate(o, c, pc, limit_pct(a["code"]), t, rr, sig)
            nav, ex = pd.Series(nav, index=a["idx"]), pd.Series(ex, index=a["idx"])
            for per, m in (("all", slice(None)), ("is", nav.index < SPLIT), ("oos", nav.index >= SPLIT)):
                if isinstance(m, slice):
                    nv, ee = nav, ex
                else:
                    nv, ee = nav[m], ex[m]
                if len(nv) < 250:
                    continue
                rows.append({"code": a["code"], "policy": pn, "period": per, **_metrics(nv, ee)})
    df = pd.DataFrame(rows)
    bh = df[df.policy == "BH"].set_index(["code", "period"])
    x = df[df.policy != "BH"].join(bh[["cagr", "mdd", "calmar"]], on=["code", "period"], rsuffix="_bh")
    x["d_mdd"], x["d_cagr"] = x.mdd - x.mdd_bh, x.cagr - x.cagr_bh
    x["calmar_up"] = x.calmar > x.calmar_bh
    g = x.groupby(["period", "policy"]).agg(n=("code", "size"), d_mdd=("d_mdd", "median"), d_cagr=("d_cagr", "median"),
                                            calmar_up=("calmar_up", "mean"), expo=("expo", "mean"),
                                            turn=("turn", "median")).round(4)
    out = {"generated_at": datetime.now().isoformat(timespec="seconds"), "assets": int(df.code.nunique()),
           "method": __doc__.strip().splitlines()[4:11],
           "summary": [{"period": p, "policy": q, **v} for (p, q), v in g.to_dict("index").items()]}
    return out


if __name__ == "__main__":
    res = run()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    df = pd.DataFrame(res["summary"])
    with pd.option_context("display.width", 200, "display.max_rows", 100):
        print(df[df.period == "all"].sort_values("d_mdd", ascending=False).to_string(index=False))
    print(f"→ {OUT_PATH}")
