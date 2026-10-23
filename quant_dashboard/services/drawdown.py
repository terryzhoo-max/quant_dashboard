"""
AlphaCore · 组合级最大回撤 (MDD) 监控与刹车 (纯计算, 无 I/O)
==============================================================

1. 净值口径: 时间加权 (TWR), 剔除资金进出
   NAV_t = NAV_{t-1} × (1 + PnL_t / MV_{t-1}),  PnL_t = Σ 持仓_{t-1} × (P_t − P_{t-1})
   持仓按 "券商持仓快照 + 成交台账回滚" 逐日还原 → 追加资金/取出资金不会伪装成收益或亏损。
   (直接用总资产算回撤会把 "边亏边加仓" 的真实亏损掩盖掉。)

2. 回撤读数: 当前回撤 · 高水位日 · 最大回撤 · 水下天数 · 回本所需涨幅 · Ulcer 指数

3. 前瞻: 以当前持仓的近 250 日日收益做分块自助法 (20 日块), 估计未来 250 日最大回撤分布,
   给出 P(回撤 ≥ 12% / 20% / 28%) —— 回答 "按现在这样拿, 一年内大概率会回撤多少"。
   风险口径: 收益去均值 (不外推过去一年的涨幅), 波动取 max(样本, EWMA λ=0.94) —— 近期波动放大时自动变保守。

5. 缺行情的已清仓标的: 用台账成交价作锚点, 锚点之间按 "组合其余持仓的收益 + 线性校正" 桥接,
   使合成价格在每个成交日精确等于成交均价; 合成部分的市值占比单独披露。

4. 刹车 (校准见 docs/drawdown_control.md):
   分档 D  回撤 ≥12% → 仓位上限 75% 且禁止加仓; ≥20% → 50%; ≥28% → 25%
           自谷底收复 1/2 回撤 (或创新高) 才回升一档 —— 迟滞, 防止来回打脸
           信号口径 = 风险资产净值 (与生产一致); 校准为次日开盘执行、开盘跌停卖出顺延
   参考    Grossman–Zhou: 仓位 = min(1, m × (NAV − (1−Dmax)·HWM) / NAV)
   刹车是 "上限", 不是 "目标"; 与 AIAE / 市场刹车 / 组合波动预算 取最严。
"""
from __future__ import annotations

import copy
import math
from typing import Any, Callable, Iterable, Mapping, Optional

import numpy as np
import pandas as pd

DEFAULT_POLICY: dict[str, Any] = {
    "tiers": [
        {"dd": 0.12, "cap": 75, "label": "一档 · 禁止加仓", "no_add": True},
        {"dd": 0.20, "cap": 50, "label": "二档 · 降至 50%"},
        {"dd": 0.28, "cap": 25, "label": "三档 · 降至 25%"},
    ],
    "rerisk_recover": 0.5,          # 自谷底收复 1/2 回撤 → 回升一档 (v2 校准: 较 1/3 换手低 ~35%, 回撤削减略多, 收益代价相同)
    "gz": {"dmax": 0.25, "m": 2.0},  # Grossman–Zhou 参考
    "forecast": {"horizon": 250, "block": 20, "sims": 2000, "lookback": 250, "seed": 7,
                 "demean": True, "ewma_lambda": 0.94},
}


# ═══════════════════════════════════════════════════════
#  ① 剔除资金进出的组合净值
# ═══════════════════════════════════════════════════════

def holdings_history(dates: pd.DatetimeIndex, end_holdings: Mapping[str, float],
                     trades: Iterable[Mapping[str, Any]], snapshot_date: Optional[str] = None) -> pd.DataFrame:
    """从持仓快照出发按台账回滚 (快照日之后的成交向前滚), 得到每日收盘持仓。"""
    snap = pd.Timestamp(snapshot_date) if snapshot_date else dates[-1]
    tr = sorted((t for t in trades if t.get("ts_code") and t.get("qty")),
                key=lambda t: (t["date"], t.get("time", "")))
    codes = sorted(set(end_holdings) | {t["ts_code"] for t in tr})
    signed = {}
    for t in tr:
        d = pd.Timestamp(t["date"])
        s = int(t["qty"]) * (1 if t.get("side") == "buy" else -1)
        signed.setdefault(d, {}).setdefault(t["ts_code"], 0)
        signed[d][t["ts_code"]] += s
    rows = {}
    base = {c: float(end_holdings.get(c, 0) or 0) for c in codes}
    # 快照日及之前: 从快照向过去回滚
    q = dict(base)
    after_snap = [d for d in signed if d > snap]
    for d in sorted(dates[dates <= snap], reverse=True):
        rows[d] = dict(q)
        for c, s in signed.get(d, {}).items():
            q[c] = q.get(c, 0) - s
    # 快照日之后: 向未来滚动 (快照之后又导入了成交)
    q = dict(base)
    for d in sorted(dates[dates > snap]):
        for c, s in signed.get(d, {}).items():
            q[c] = q.get(c, 0) + s
        rows[d] = dict(q)
    del after_snap
    H = pd.DataFrame(rows).T.sort_index().reindex(columns=codes).fillna(0.0)
    return H.clip(lower=0)


def nav_series(H: pd.DataFrame, P: pd.DataFrame) -> pd.DataFrame:
    """TWR 净值。H: 每日收盘持仓, P: 收盘价 (同索引)。缺价持仓不计入当日收益与市值。"""
    P = P.reindex(index=H.index, columns=H.columns)
    P = P.ffill()
    mv = (H * P).sum(axis=1, min_count=1)
    dp = P - P.shift(1)
    pnl = (H.shift(1) * dp).sum(axis=1, min_count=1).fillna(0.0)
    base = (H.shift(1) * P.shift(1)).sum(axis=1, min_count=1)
    ret = (pnl / base).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    nav = (1 + ret).cumprod()
    missing = ((H > 0) & P.isna()).sum(axis=1)
    return pd.DataFrame({"mv": mv, "pnl": pnl, "ret": ret, "nav": nav, "missing_px": missing})


# ═══════════════════════════════════════════════════════
#  ② 回撤读数
# ═══════════════════════════════════════════════════════

def dd_stats(nav: pd.Series) -> dict:
    nav = nav.dropna()
    if len(nav) < 2:
        return {}
    hwm = nav.cummax()
    dd = nav / hwm - 1
    cur = float(dd.iloc[-1])
    hwm_date = nav[: dd.index[-1]].idxmax()
    trough_date = dd.idxmin()
    mdd_peak = nav[:trough_date].idxmax()
    under = 0
    for v in reversed(dd.to_numpy()):
        if v < -1e-9:
            under += 1
        else:
            break
    return {
        "current_dd": round(cur, 4), "hwm": round(float(hwm.iloc[-1]), 6),
        "hwm_date": hwm_date.strftime("%Y-%m-%d"), "nav": round(float(nav.iloc[-1]), 6),
        "mdd": round(float(dd.min()), 4), "mdd_peak": mdd_peak.strftime("%Y-%m-%d"),
        "mdd_trough": trough_date.strftime("%Y-%m-%d"), "days_underwater": under,
        "recovery_needed": round(1 / (1 + cur) - 1, 4) if cur > -1 else None,
        "ulcer": round(float(np.sqrt((dd ** 2).mean())), 4),
        "start": nav.index[0].strftime("%Y-%m-%d"), "end": nav.index[-1].strftime("%Y-%m-%d"),
    }


# ═══════════════════════════════════════════════════════
#  ③ 前瞻: 分块自助法估计未来最大回撤
# ═══════════════════════════════════════════════════════

_FC_MEMO: "dict[tuple, dict]" = {}


def forecast_mdd(returns: pd.Series, horizon: int = 250, block: int = 20, sims: int = 2000,
                 seed: int = 7, thresholds: Iterable[float] = (0.12, 0.20, 0.28),
                 demean: bool = True, ewma_lambda: Optional[float] = 0.94) -> dict:
    """同一输入 (收益序列 + 参数) 结果确定 (固定种子), 进程内记忆化: 页面刷新不重复跑 2000 条路径。"""
    r = pd.Series(returns).dropna().to_numpy(dtype=float)
    thresholds = tuple(thresholds)
    key = (hash(r.tobytes()), len(r), horizon, block, sims, seed, thresholds, demean, ewma_lambda)
    if key in _FC_MEMO:
        return copy.deepcopy(_FC_MEMO[key])
    res = _forecast_mdd(r, horizon, block, sims, seed, thresholds, demean, ewma_lambda)
    if len(_FC_MEMO) > 32:
        _FC_MEMO.clear()
    _FC_MEMO[key] = copy.deepcopy(res)
    return res


def _forecast_mdd(r: np.ndarray, horizon: int, block: int, sims: int, seed: int, thresholds: tuple,
                  demean: bool, ewma_lambda: Optional[float]) -> dict:
    if len(r) < block * 3:
        return {}
    sample_vol = float(np.std(r, ddof=1))
    sample_drift = float(np.mean(r))
    if demean:                       # 风险口径: 不把过去一年的趋势外推到未来
        r = r - sample_drift
    scale = 1.0
    ewma_vol = None
    if ewma_lambda:
        w = (1 - ewma_lambda) * ewma_lambda ** np.arange(len(r))[::-1]
        ewma_vol = float(np.sqrt((w * r ** 2).sum() / w.sum()))
        if ewma_vol > sample_vol > 0:   # 近期波动更高 → 按近期放大 (只放大, 不缩小)
            scale = ewma_vol / sample_vol
            r = r * scale
    rng = np.random.default_rng(seed)
    nblocks = math.ceil(horizon / block)
    starts = rng.integers(0, len(r) - block + 1, size=(sims, nblocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(sims, -1)[:, :horizon]
    paths = np.cumprod(1 + r[idx], axis=1)
    paths = np.concatenate([np.ones((sims, 1)), paths], axis=1)
    mdd = (paths / np.maximum.accumulate(paths, axis=1) - 1).min(axis=1)
    q = np.quantile(mdd, [0.5, 0.25, 0.05])
    vol = float(np.std(r, ddof=1) * np.sqrt(250))
    assumptions = {"drift": "去均值 (样本年化 {:+.0%} 未外推)".format(sample_drift * 250) if demean else "样本均值",
                   "vol": ("EWMA 放大 ×{:.2f}".format(scale) if scale > 1 else "样本波动 (EWMA {:.0%} 未高于样本)".format(
                       (ewma_vol or 0) * np.sqrt(250))) if ewma_lambda else "样本波动",
                   "sample_drift_ann": round(sample_drift * 250, 4)}
    budget = max(thresholds)

    def p95_at(e: float) -> float:          # 仓位 e, 其余现金 (年化 1.5%)
        pe = np.cumprod(1 + e * r[idx] + (1 - e) * 0.015 / 250, axis=1)
        pe = np.concatenate([np.ones((sims, 1)), pe], axis=1)
        return float(np.quantile((pe / np.maximum.accumulate(pe, axis=1) - 1).min(axis=1), 0.05))

    lo_e, hi_e = 0.0, 1.0
    if p95_at(1.0) >= -budget:
        max_expo = 1.0
    else:
        for _ in range(14):
            mid = (lo_e + hi_e) / 2
            lo_e, hi_e = (mid, hi_e) if p95_at(mid) >= -budget else (lo_e, mid)
        max_expo = lo_e
    return {
        "budget_dd": budget, "max_exposure_for_budget": round(max_expo, 3),
        "horizon_days": horizon, "sims": sims, "ann_vol": round(vol, 4),
        "mdd_median": round(float(q[0]), 4), "mdd_p75": round(float(q[1]), 4), "mdd_p95": round(float(q[2]), 4),
        "prob": {f"{int(t * 100)}": round(float((mdd <= -t).mean()), 3) for t in thresholds},
        "assumptions": assumptions,
    }


def book_returns(holdings: Mapping[str, float], P: pd.DataFrame, lookback: int = 250) -> pd.Series:
    """当前持仓 (固定股数) 的历史日收益 —— 风险前瞻用 (pro-forma)。"""
    cols = [c for c in holdings if c in P.columns and holdings[c] > 0]
    if not cols:
        return pd.Series(dtype=float)
    Q = pd.Series({c: float(holdings[c]) for c in cols})
    mv = (P[cols].ffill() * Q).sum(axis=1, min_count=len(cols))
    return mv.pct_change().dropna().tail(lookback)


def synth_prices(codes: Iterable[str], trades: Iterable[Mapping[str, Any]], proxy_nav: pd.Series) -> pd.DataFrame:
    """无行情标的的合成收盘价: 台账成交均价为锚点, 锚点之间 = 代理收益 + 线性校正 (布朗桥式),
    首个锚点之前 / 最后锚点之后按代理收益外推。代理 = 组合其余有行情持仓的净值。"""
    idx = proxy_nav.index
    L = np.log(proxy_nav.astype(float).to_numpy())
    pos = {d: i for i, d in enumerate(idx)}
    out = {}
    for c in codes:
        amt: dict[int, list[float]] = {}
        for t in trades:
            if t.get("ts_code") != c or not t.get("qty") or not t.get("price"):
                continue
            i = pos.get(pd.Timestamp(t["date"]))
            if i is None:
                continue
            a = amt.setdefault(i, [0.0, 0.0])
            a[0] += float(t["price"]) * float(t["qty"]); a[1] += float(t["qty"])
        if not amt:
            continue
        anchors = sorted((i, math.log(v[0] / v[1])) for i, v in amt.items() if v[1] > 0)
        lp = np.empty(len(idx))
        i0, p0 = anchors[0]
        lp[: i0 + 1] = p0 + (L[: i0 + 1] - L[i0])
        for (ia, pa), (ib, pb) in zip(anchors, anchors[1:]):
            seg = np.arange(ia, ib + 1)
            gap = (pb - pa) - (L[ib] - L[ia])
            lp[seg] = pa + (L[seg] - L[ia]) + gap * (seg - ia) / (ib - ia)
        il, pl = anchors[-1]
        lp[il:] = pl + (L[il:] - L[il])
        out[c] = np.exp(lp)
    return pd.DataFrame(out, index=idx)


# ═══════════════════════════════════════════════════════
#  ④ 刹车: 分档 + 迟滞 (确定性重放) / Grossman–Zhou 参考
# ═══════════════════════════════════════════════════════

def replay_tiers(nav: pd.Series, policy: Optional[Mapping[str, Any]] = None) -> dict:
    """在净值路径上逐日重放分档状态机 (与校准回测同一逻辑)。返回当前档位与历史切换事件。"""
    pol = policy or DEFAULT_POLICY
    tiers = pol["tiers"]
    rr = float(pol["rerisk_recover"])
    hwm, tier, trough = -math.inf, 0, None
    events = []
    for d, v in nav.dropna().items():
        v = float(v)
        hwm = max(hwm, v)
        dd = v / hwm - 1
        lvl = tier
        while lvl < len(tiers) and dd <= -float(tiers[lvl]["dd"]):
            lvl += 1
        if lvl > tier:
            tier, trough = lvl, v
            events.append({"date": d.strftime("%Y-%m-%d"), "to": tier, "dd": round(dd, 4), "dir": "down"})
            continue
        if tier > 0:
            trough = min(trough, v)
            if v >= trough + rr * (hwm - trough) or v >= hwm:
                tier -= 1
                trough = v
                events.append({"date": d.strftime("%Y-%m-%d"), "to": tier, "dd": round(dd, 4), "dir": "up"})
    cap = 100 if tier == 0 else int(tiers[tier - 1]["cap"])
    nxt = tiers[tier] if tier < len(tiers) else None
    up_at = None
    if tier > 0 and trough is not None and hwm > 0:
        up_at = round((trough + rr * (hwm - trough)) / hwm - 1, 4)
    return {
        "tier": tier, "cap_pct": cap, "label": "正常" if tier == 0 else tiers[tier - 1]["label"],
        "no_add": tier > 0 and bool(tiers[0].get("no_add", True)),
        "next_trigger_dd": -float(nxt["dd"]) if nxt else None, "next_cap_pct": int(nxt["cap"]) if nxt else None,
        "rerisk_at_dd": up_at, "events": events[-12:],
    }


def gz_exposure(nav: pd.Series, dmax: float, m: float) -> Optional[float]:
    nav = nav.dropna()
    if nav.empty:
        return None
    v, hwm = float(nav.iloc[-1]), float(nav.max())
    return round(min(1.0, max(0.0, m * (v - (1 - dmax) * hwm) / v)), 3)


# ═══════════════════════════════════════════════════════
#  组装
# ═══════════════════════════════════════════════════════

def monitor(end_holdings: Mapping[str, float], trades: list[Mapping[str, Any]], loader: Callable[[str], Any],
            *, snapshot_date: Optional[str], equity: float, invested_value: float,
            baseline: Optional[Mapping[str, Any]] = None, policy: Optional[Mapping[str, Any]] = None,
            history_days: int = 400) -> dict:
    """组合回撤全景。baseline: 人工设定的回撤基准 (自该日起重新计高水位, 需留痕)。"""
    from services.trailing_stop import normalize_bars
    pol = policy or DEFAULT_POLICY
    codes = sorted(set(end_holdings) | {t["ts_code"] for t in trades})
    closes, missing = {}, []
    for c in codes:
        try:
            b = loader(c)
            if b is None or len(b) == 0:
                missing.append(c)
                continue
            closes[c] = normalize_bars(b)["close"]
        except Exception:
            missing.append(c)
    if not closes:
        return {"status": "no_data", "missing_prices": missing}
    P = pd.DataFrame(closes).sort_index()
    held_px = [c for c in end_holdings if c in P.columns]
    P = P.dropna(how="all")
    if held_px:
        last_common = P[held_px].dropna(how="any").index
        if len(last_common):
            P = P[P.index <= last_common[-1]]
    ledger_start = min((t["date"] for t in trades), default=None)
    # 实盘净值窗口: 台账起点前一个交易日起 (之前持仓未知); 无台账时只做前瞻
    if ledger_start:
        pre = P.index[P.index < pd.Timestamp(ledger_start)]
        start = pre[-1] if len(pre) else P.index[0]
    else:
        start = P.index[-1]
    dates = P.index[P.index >= start]
    out: dict[str, Any] = {"status": "ok", "missing_prices": missing, "policy": {
        "tiers": pol["tiers"], "rerisk_recover": pol["rerisk_recover"], "gz": pol["gz"]}}

    realized = None
    if len(dates) >= 2:
        H = holdings_history(dates, end_holdings, trades, snapshot_date)
        PX = P.loc[dates]
        ns = nav_series(H, PX)                       # 第一遍: 仅有行情的持仓 → 代理净值
        proxy = {"codes": [], "max_share": 0.0, "avg_share": 0.0}
        need = [c for c in missing if c in H.columns and (H[c] > 0).any()]
        if need:
            SP = synth_prices(need, trades, ns["nav"])
            if not SP.empty:
                PX = PX.join(SP, how="left")
                ns = nav_series(H, PX)
                held = H[SP.columns].shift(1).fillna(0)
                smv = (held * SP.shift(1)).sum(axis=1)
                tmv = (H.shift(1) * PX.shift(1)).sum(axis=1, min_count=1)
                share = (smv / tmv).replace([np.inf, -np.inf], np.nan).dropna()
                proxy = {"codes": list(SP.columns), "max_share": round(float(share.max()), 4) if len(share) else 0.0,
                         "avg_share": round(float(share.mean()), 4) if len(share) else 0.0}
        realized = ns
        out["realized"] = {**dd_stats(ns["nav"]), "missing_px_days": int((ns["missing_px"] > 0).sum()),
                           "proxy": proxy, "window": "台账覆盖期 (剔除资金进出的时间加权净值)"}
    # 当前持仓回看 (pro-forma): 若一直持有今天的持仓
    br = book_returns(end_holdings, P, lookback=history_days)
    if len(br) > 20:
        pf_nav = (1 + br).cumprod()
        out["proforma"] = {**dd_stats(pf_nav), "window": f"当前持仓回看近 {len(br)} 个交易日"}
        fc = pol["forecast"]
        out["forecast"] = forecast_mdd(br.tail(fc["lookback"]), fc["horizon"], fc["block"], fc["sims"], fc["seed"],
                                       [t["dd"] for t in pol["tiers"]], demean=fc.get("demean", True),
                                       ewma_lambda=fc.get("ewma_lambda", 0.94))

    # 刹车判定所用净值: 实盘 TWR (有台账) ; 基准重设后从基准日起
    base_nav = realized["nav"] if realized is not None else None
    if base_nav is not None and baseline and baseline.get("date"):
        base_nav = base_nav[base_nav.index >= pd.Timestamp(baseline["date"])]
    if base_nav is not None and len(base_nav) >= 2:
        brake = replay_tiers(base_nav, pol)
        brake["basis"] = "baseline" if baseline else "realized"
        brake["dd"] = round(float(base_nav.iloc[-1] / base_nav.max() - 1), 4)
        brake["gz_exposure"] = gz_exposure(base_nav, pol["gz"]["dmax"], pol["gz"]["m"])
        invested_pct = round(invested_value / equity * 100, 1) if equity else None
        brake["invested_pct"] = invested_pct
        if invested_pct is not None and invested_pct > brake["cap_pct"]:
            excess = (invested_pct - brake["cap_pct"]) / 100 * equity
            brake["reduce_value"] = round(excess, 2)
        out["brake"] = brake
        out["_nav"] = base_nav                       # 内部: 供编排层做时点一致性 (重述) 检查, 不出接口
        tail = base_nav.tail(120)
        hw = base_nav.cummax().reindex(tail.index)
        out["curve"] = {"d": [d.strftime("%m-%d") for d in tail.index],
                        "nav": [round(float(v), 5) for v in tail], "hwm": [round(float(v), 5) for v in hw]}
    out["baseline"] = dict(baseline) if baseline else None
    out["ledger_start"] = ledger_start
    return out
