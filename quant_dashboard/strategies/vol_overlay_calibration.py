"""
市场波动刹车 · 时点安全校准脚本
================================
复现 docs/vol_overlay_calibration.md 中的结论, 可在服务器上用更长/更新的数据重跑。

    python -m strategies.vol_overlay_calibration
    python -m strategies.vol_overlay_calibration --codes 000300.SH 000852.SH --grid

方法:
  - t 日收盘计算系数, t+1 日按 系数 × 基础仓位 持有 (无前视)
  - 对照组 = 平均仓位相同的固定仓位 (唯一公平的比较: 否则降仓本身就会"降低回撤")
  - 现金年化 1.5%, 调仓成本 5bp / 单位仓位变化
上线标准: 在多数指数上 ΔSharpe ≥ 0 且 ΔMaxDD ≥ 0, 换手增幅可接受。
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.vol_regime import DEFAULT_MARKET_VOL_CONFIG, compute_vol_factor_frame  # noqa: E402

CASH_DAILY = 0.015 / 252
COST = 0.0005
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_lake", "daily_prices")


def load_close(code: str) -> pd.Series:
    df = pd.read_parquet(os.path.join(DATA_DIR, f"{code}.parquet")).sort_values("trade_date")
    idx = pd.to_datetime(df["trade_date"].astype(str))
    return pd.Series(df["close"].astype(float).values, index=idx)


def metrics(ret: pd.Series, expo: pd.Series) -> dict:
    nav = (1 + ret).cumprod()
    yrs = len(ret) / 252
    cagr = nav.iloc[-1] ** (1 / yrs) - 1
    vol = ret.std() * np.sqrt(252)
    dd = (nav / nav.cummax() - 1).min()
    monthly = (1 + ret).resample("ME").prod() - 1
    return {
        "CAGR": cagr, "Vol": vol,
        "Sharpe": (ret.mean() * 252 - 0.015) / vol if vol > 0 else 0.0,
        "MaxDD": dd, "WorstMonth": monthly.min(),
        "AvgExpo": expo.mean(), "TurnoverYr": expo.diff().abs().sum() / yrs,
    }


def backtest(close: pd.Series, cfg: dict | None = None):
    frame = compute_vol_factor_frame(close, cfg)
    simple = close.pct_change()
    expo = frame["factor"].reindex(simple.index).shift(1).dropna().clip(upper=1.0)
    s = simple.reindex(expo.index).fillna(0)
    ret = expo * s + (1 - expo) * CASH_DAILY - expo.diff().abs().fillna(0) * COST
    static_expo = pd.Series(expo.mean(), index=s.index)
    static_ret = static_expo * s + (1 - static_expo) * CASH_DAILY
    return metrics(ret, expo), metrics(static_ret, static_expo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", nargs="+", default=["000300.SH", "000852.SH", "399006.SZ", "000015.SH"])
    ap.add_argument("--grid", action="store_true", help="同时跑参数网格 (平台检查)")
    args = ap.parse_args()

    rows = []
    for code in args.codes:
        m, st = backtest(load_close(code))
        rows.append({"code": code, **{f"overlay_{k}": v for k, v in m.items()},
                     "dSharpe": m["Sharpe"] - st["Sharpe"], "dMaxDD": m["MaxDD"] - st["MaxDD"]})
    print("默认参数:", {k: DEFAULT_MARKET_VOL_CONFIG[k] for k in ("trigger_ratio", "alpha", "floor", "ceiling")})
    print(pd.DataFrame(rows).round(3).to_string(index=False))

    if args.grid:
        grid = {"trigger_ratio": [1.0, 1.5, 2.0, 2.5], "alpha": [0.5, 0.75, 1.0], "floor": [0.5, 0.6]}
        out = []
        closes = {c: load_close(c) for c in args.codes}
        for vals in itertools.product(*grid.values()):
            cfg = dict(zip(grid, vals))
            if cfg["trigger_ratio"] == 1.0:
                cfg["ceiling"] = 1.10  # 连续择时版本 (V2 草案)
            d = [backtest(cl, cfg) for cl in closes.values()]
            out.append({**cfg,
                        "avg_dSharpe": np.mean([m["Sharpe"] - s["Sharpe"] for m, s in d]),
                        "min_dSharpe": np.min([m["Sharpe"] - s["Sharpe"] for m, s in d]),
                        "avg_dMaxDD": np.mean([m["MaxDD"] - s["MaxDD"] for m, s in d]),
                        "avg_turnover": np.mean([m["TurnoverYr"] for m, _ in d])})
        print(pd.DataFrame(out).sort_values("avg_dSharpe", ascending=False).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
