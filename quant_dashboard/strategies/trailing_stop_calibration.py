"""
AlphaCore · 跟踪止盈参数校准 (可复现)
=====================================

用法 (项目根目录):
    python -m strategies.trailing_stop_calibration            # 默认网格, 结果写 data_lake/trailing_stop_calibration.json
    python -m strategies.trailing_stop_calibration --quick    # 只评估当前配置 vs 买入持有

方法 (与 services/trailing_stop.py 同一套规则; 2026-10 校准时引擎与模拟器的触发日 80/80 一致):
  · 资产池: data_lake/daily_prices 下所有 ETF / 个股 (≥160 根日线); 拆分/分红按 pre_close 连续化
  · 逐资产连续持有: 首日买入 → 跟踪止盈离场 → 按类别再入场规则回补 → …, 对比同期买入持有
  · 执行: 收盘确认, 次日开盘成交, 一字跌停顺延, 单边 0.1% 费用, 空仓年化 1.5%
  · 样本外检验: 2024-10-01 前为样本内, 之后为样本外; 只采用两段都稳健的平台区, 不取单点最优
  · 评价: 年化差 (vs 买入持有) 中位数、最大回撤改善中位数、Calmar 改善的资产占比

结论随市场结构变化, 建议每季度重跑; 参数变更写入 config/trailing_stop.json 并在审计中注明。
"""
from __future__ import annotations

import argparse
import glob
import itertools
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

from services.trailing_stop import DEFAULT_CONFIG, normalize_bars, wilder_atr  # noqa: E402

PRICE_DIR = os.path.join(_ROOT, "data_lake", "daily_prices")
OUT_PATH = os.path.join(_ROOT, "data_lake", "trailing_stop_calibration.json")
SPLIT = pd.Timestamp("2024-10-01")
CASH = 0.015 / 250
COST = 0.001
BROAD = {"510050", "510300", "510500", "512100", "159915", "510880", "515080", "515180", "512890",
         "159905", "515100", "159545", "515000", "510310", "159919", "563300", "512500", "159338"}
QDII = {"513090", "513120", "513130", "513500", "513530", "513950", "513970", "513100", "159941", "513050"}


def klass(code: str) -> str:
    c = code.split(".")[0]
    if c.startswith(("51", "52", "56", "58", "159", "16")):
        if c in BROAD:
            return "broad_etf"
        if c in QDII:
            return "qdii_etf"
        return "theme_etf"
    return "stock"


def limit_pct(code: str) -> float:
    return 0.20 if code.split(".")[0].startswith(("688", "689", "300", "301")) else 0.10


def load_assets(loader: Optional[Callable[[str], pd.DataFrame]] = None, codes: Optional[list] = None) -> list[dict]:
    if codes is None:
        codes = [os.path.basename(f)[:-8] for f in glob.glob(os.path.join(PRICE_DIR, "*.parquet"))
                 if not os.path.basename(f).startswith(("gem_", "backtest_"))]
    loader = loader or (lambda c: pd.read_parquet(os.path.join(PRICE_DIR, f"{c}.parquet")))
    out = []
    for code in sorted(codes):
        if code.split(".")[0] in ("000300", "000852", "000015", "399006", "000922", "000016"):
            continue   # 指数, 不可交易
        try:
            d = normalize_bars(loader(code))
        except Exception:
            continue
        if len(d) < 160 or not {"open", "high", "low"} <= set(d.columns):
            continue
        pc = d["pre_close"] if "pre_close" in d.columns else d["close"].shift(1)
        locked = ((d["high"] - d["low"]).abs() < 1e-9) & (d["close"] / pc - 1 <= -limit_pct(code) + 0.003)
        c = d["close"]
        out.append(dict(code=code, cls=klass(code), idx=d.index, C=c.to_numpy(float),
                        O=d["open"].to_numpy(float), A=wilder_atr(d, 20).to_numpy(float),
                        LD=locked.to_numpy(bool), MA60=c.rolling(60).mean().to_numpy(),
                        HH20=c.shift(1).rolling(20).max().to_numpy()))
    return out


def run_asset(a: dict, p: dict) -> tuple[np.ndarray, np.ndarray]:
    """逐日模拟: 持有 → 跟踪止盈 (含 1/3 分批) → 再入场。返回 (净值, 仓位暴露)。"""
    C, O, A, LD, n = a["C"], a["O"], a["A"], a["LD"], len(a["C"])
    st = 60
    eq = np.ones(n)
    expo = np.zeros(n)
    pos = entry = stop = hwm = R = 0.0
    stage = 0
    pending = ("enter", 1.0)
    for t in range(st, n):
        if pending and not LD[t]:
            kind, f = pending
            px = O[t] if np.isfinite(O[t]) else C[t]
            pending = None
            if kind == "enter":
                pos, entry = 1.0, px
                R = max(p["init_atr_mult"] * A[t - 1], 0.03 * px)
                stop, hwm, stage = entry - R, px, 0
                eq[t] = eq[t - 1] * (1 + C[t] / px - 1 - COST)
                expo[t] = 1.0
                continue
            sold = pos if kind == "exit" else min(pos, f)
            keep = 0.0 if kind == "exit" else pos - sold
            eq[t] = eq[t - 1] * (1 + sold * (px / C[t - 1] - 1 - COST) + keep * (C[t] / C[t - 1] - 1)
                                 + (1 - pos) * CASH)
            pos = keep
            expo[t] = pos
            continue
        eq[t] = eq[t - 1] * (1 + (pos * (C[t] / C[t - 1] - 1) + (1 - pos) * CASH if pos > 0 else CASH))
        expo[t] = pos
        if pos > 0:
            c = C[t]
            if c < stop:
                pending = ("exit", pos)
                continue
            hwm = max(hwm, c)
            reached = (hwm - entry) / R
            new = 2 if reached >= p["trail_start_r"] else 1 if reached >= 1.0 else 0
            if p.get("partial_fraction") and new >= 2 > stage:
                pending = ("partial", p["partial_fraction"])
            stage = max(stage, new)
            if stage == 1:
                stop = max(stop, entry * 1.003)
            elif stage == 2:
                stop = max(stop, hwm - p["trail_atr_mult"] * A[t], entry * 1.003)
        else:
            if p.get("reentry", "ma60") == "breakout20":
                ok = C[t] > a["HH20"][t]
            else:
                ok = C[t] > a["MA60"][t] and C[t - 1] <= a["MA60"][t - 1]
            if ok:
                pending = ("enter", 1.0)
    return eq[st:], expo[st:]


def _metrics(s: pd.Series) -> Optional[dict]:
    if len(s) < 60:
        return None
    s = s / s.iloc[0]
    cagr = s.iloc[-1] ** (250 / len(s)) - 1
    dd = float((s / s.cummax() - 1).min())
    return dict(cagr=cagr, mdd=dd, calmar=cagr / abs(dd) if dd < 0 else np.nan)


def evaluate(assets: list[dict], p: dict) -> pd.DataFrame:
    rows = []
    for a in assets:
        eq, ex = run_asset(a, p)
        idx = a["idx"][60:]
        bh = a["C"][60:] / a["C"][60]
        for samp, mask in (("IS", idx < SPLIT), ("OOS", idx >= SPLIT)):
            m = _metrics(pd.Series(eq[mask], index=idx[mask]))
            b = _metrics(pd.Series(bh[mask], index=idx[mask]))
            if m and b:
                rows.append(dict(code=a["code"], cls=a["cls"], sample=samp, **m, bh_cagr=b["cagr"],
                                 bh_mdd=b["mdd"], bh_calmar=b["calmar"], expo=float(ex[mask].mean())))
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    df = df.assign(d_cagr=df.cagr - df.bh_cagr, d_mdd=df.mdd - df.bh_mdd, better=df.calmar > df.bh_calmar)
    out = {}
    for (cls, samp), g in df.groupby(["cls", "sample"]):
        out.setdefault(cls, {})[samp] = dict(n=int(len(g)), d_cagr=round(float(g.d_cagr.median()), 4),
                                             d_mdd=round(float(g.d_mdd.median()), 4),
                                             calmar_better=round(float(g.better.mean()), 3),
                                             exposure=round(float(g.expo.mean()), 3))
    return out


def grid(assets: list[dict], cls: str) -> list[dict]:
    A = [a for a in assets if a["cls"] == cls]
    res = []
    for ik, tk, tr, pf, re_ in itertools.product([2, 2.5, 3, 4, 5], [3, 4, 5, 6], [0.5, 1, 2, 3], [0, 1 / 3],
                                                 ["breakout20", "ma60"]):
        p = dict(init_atr_mult=ik, trail_atr_mult=tk, trail_start_r=tr, partial_fraction=pf, reentry=re_)
        s = summarize(evaluate(A, p)).get(cls, {})
        if "IS" in s and "OOS" in s:
            res.append(dict(params=p, IS=s["IS"], OOS=s["OOS"],
                            robust=min(s["IS"]["calmar_better"], s["OOS"]["calmar_better"])))
    res.sort(key=lambda x: (x["robust"], x["IS"]["d_cagr"] + x["OOS"]["d_cagr"]), reverse=True)
    return res


def main(argv: Optional[list] = None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args(argv)
    assets = load_assets()
    report = {"generated_at": datetime.now().isoformat(timespec="seconds"), "assets": len(assets),
              "split": str(SPLIT.date()), "current": {}}
    for cls in ("theme_etf", "broad_etf", "stock"):
        p = DEFAULT_CONFIG["classes"][cls]
        report["current"][cls] = {"params": p, **summarize(evaluate([a for a in assets if a["cls"] == cls], p)).get(cls, {})}
        if not args.quick:
            report.setdefault("grid_top", {})[cls] = grid(assets, cls)[:10]
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=float)
    print(json.dumps(report["current"], ensure_ascii=False, indent=1, default=float))
    return report


if __name__ == "__main__":
    main()
