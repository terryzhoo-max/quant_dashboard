"""
AlphaCore · 持仓跟踪止盈引擎 (纯计算, 无 I/O)
=============================================

方法: 吊灯止损 (Chandelier Exit) + R 倍数分层 + 棘轮 (只升不降), 参数按资产类别分别校准。

  R (初始风险)  = init_k × ATR(建仓日)                     ATR = Wilder ATR20 (拆分/分红连续化)
  S0 初始止损   = 成本 − R
  S1 保本       浮盈 ≥ 1R → 成本 + 0.3% (覆盖往返费用)
  S2 跟踪       浮盈 ≥ trail_start_r × R → max(本轮最高收盘 − trail_k × ATR, 保本线), 同时卖出 1/3 锁利
  阶段按 "曾达到的最大浮盈" 判定 (只升不降); 止损线 stop_t = max(stop_{t-1}, 候选)。

校准 (2026-10, 本机 data_lake 103 只可交易 ETF/个股, 2018–2026, 样本内 <2024-10 / 样本外 ≥2024-10,
     收盘确认 + 次日开盘成交 + 一字跌停顺延 + 往返 0.2%, 止损后按再入场规则回补):
  主题 ETF  init 2.0 · trail 5.0 · 3R 起跟踪 · 卖 1/3 · 20 日新高再入场
            → Calmar 改善占比 70% / 59%, 年化中位差 +6.6 / −2.1 pp, 最大回撤中位改善 19 / 13 pp
  宽基 ETF  init 3.0 · trail 5.0 · 0.5R 起跟踪 · 卖 1/3 · 上穿 MA60 再入场
            → 78% / 70%, +2.8 / −1.0 pp, 12 / 11 pp
  个股      init 5.0 · trail 4.0 · 1R 起跟踪 · 卖 1/3 · 上穿 MA60 再入场
            → 29% / 53%, −4.8 / −1.8 pp, 2 / 10 pp —— 个股止损改善不了风险收益比, 风险主要靠仓位控制
  (样本内 / 样本外; 复现: python -m strategies.trailing_stop_calibration)
  被否决 (样本外更差): 按市场环境调整倍数、主题 ETF 15% 回撤封顶、4R 收紧、个股 8% 硬止损、v1 默认参数。

触发口径: 收盘价 < 前一日收盘后确定的止损线 → 次一交易日执行 (A 股 T+1, 收盘确认过滤盘中噪声)。
确定性重放: 每天从锚点日按日线重放; 已发布的止损线以 "止损/收盘" 比值存为下限, 复权变化不致下移。

状态: RED 已触发未执行 · LEGACY 跟踪前已越线 (需一次性决策) · ACTION 分批止盈待执行 ·
      YELLOW 距止损 < 0.5 ATR · GREEN 持有 · NO_DATA 行情不足
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

CALIBRATION = {
    "version": "2026-10-22",
    "universe": "103 只 (个股 55 / 主题 ETF 32 / 宽基 ETF 10 / QDII 6), data_lake/daily_prices",
    "split": "样本内 < 2024-10-01 ≤ 样本外",
    "method": "逐资产连续持有模拟 (止损 → 再入场), 对比买入持有; 另以每 10 日随机入场检验分布",
    "execution": "收盘确认, 次日开盘成交, 一字跌停顺延, 往返 0.2%, 空仓年化 1.5%",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "atr_period": 20,
    "breakeven_r": 1.0,
    "breakeven_buffer_pct": 0.003,
    "classes": {
        "theme_etf": {"init_atr_mult": 2.0, "trail_atr_mult": 5.0, "trail_start_r": 3.0,
                      "partial_fraction": 1 / 3, "reentry": "breakout20"},
        "broad_etf": {"init_atr_mult": 3.0, "trail_atr_mult": 5.0, "trail_start_r": 0.5,
                      "partial_fraction": 1 / 3, "reentry": "ma60"},
        "stock":     {"init_atr_mult": 5.0, "trail_atr_mult": 4.0, "trail_start_r": 1.0,
                      "partial_fraction": 1 / 3, "reentry": "ma60"},
    },
    # 长期底仓: 只防灾难, 不分批 (未单独校准, 偏宽)
    "core": {"init_atr_mult": 5.0, "trail_atr_mult": 6.0, "trail_start_r": 1.0, "partial_fraction": 0.0},
    # 以下调节项经校准无增益, 默认关闭, 保留供实验 (正数 = 放宽)
    "regime_trail_adj": {"BULL": 0.0, "RANGE": 0.0, "BEAR": 0.0, "CRASH": 0.0},
    "aiae_tighten_regime": 4,
    "aiae_tighten_step": 0.0,
    "near_stop_atr": 0.5,
    "min_r_pct": 0.03,                 # R 下限 (成本的 3%)
    "disaster_stop_atr": 1.0,          # 券商条件单兜底价 = 收盘确认线 − 1 ATR (防跳空/盘中崩)
    "lot_size": 100,
    "round_trip_cost": 0.002,
    # 风险预算: 单票 "到止损线的潜在亏损" ≤ 总资产 × per_position_pct; 全组合合计 ≤ heat_limit_pct
    "risk": {"per_position_pct": 0.02, "heat_limit_pct": 0.12},
    "broad_etf_keywords": ["沪深300", "300ETF", "中证500", "500ETF", "1000ETF", "中证1000",
                           "上证50", "50ETF", "A500", "A50", "红利", "低波", "央企", "深证100",
                           "标普", "纳指", "日经", "恒生ETF"],
    "broad_etf_exclude": ["科创", "创业板50", "半导体", "芯片", "恒生科技"],
}

STATUS_ORDER = {"RED": 0, "LEGACY": 1, "ACTION": 2, "YELLOW": 3, "GREEN": 4, "NO_DATA": 5}
STAGE_LABEL = {0: "S0 初始止损", 1: "S1 保本", 2: "S2 跟踪止盈"}


def merge_config(override: Optional[Mapping[str, Any]] = None) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    def _deep(dst: dict, src: Mapping[str, Any]) -> None:
        for k, v in src.items():
            if k.startswith("_"):
                continue
            if isinstance(v, Mapping) and isinstance(dst.get(k), dict):
                _deep(dst[k], v)
            else:
                dst[k] = v

    if override:
        _deep(cfg, override)
    return cfg


# ═══════════════════════════════════════════════════════
#  分类 / 工具
# ═══════════════════════════════════════════════════════

def is_etf(ts_code: str) -> bool:
    c = (ts_code or "").split(".")[0]
    return c.startswith(("51", "52", "56", "58", "159", "16"))


def asset_class(ts_code: str, name: str, cfg: Mapping[str, Any]) -> str:
    if not is_etf(ts_code):
        return "stock"
    n = name or ""
    if any(x in n for x in cfg["broad_etf_exclude"]):
        return "theme_etf"
    if any(x in n for x in cfg["broad_etf_keywords"]):
        return "broad_etf"
    return "theme_etf"


def tick_size(ts_code: str) -> float:
    return 0.001 if is_etf(ts_code) else 0.01


def round_down(price: float, tick: float) -> float:
    digits = max(0, -int(math.floor(math.log10(tick) + 1e-9)))
    return round(math.floor(price / tick + 1e-9) * tick, digits)


def round_lot(qty: float, lot: int) -> int:
    return int(qty // lot) * lot


def wilder_atr(bars: pd.DataFrame, period: int) -> pd.Series:
    close = bars["close"].astype(float)
    prev = close.shift(1)
    if {"high", "low"} <= set(bars.columns) and bars[["high", "low"]].notna().all().all():
        high, low = bars["high"].astype(float), bars["low"].astype(float)
        tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    else:  # 仅收盘价: 用 |ΔC| × 1.25 近似 TR (经验值, 结果标记 atr_approx)
        tr = (close - prev).abs() * 1.25
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    """接受 tushare 日线 (trade_date 列) 或日期索引的 DataFrame → 日期索引 OHLC。"""
    d = df.copy()
    if "trade_date" in d.columns:
        d.index = pd.to_datetime(d["trade_date"].astype(str), errors="coerce")
    else:
        d.index = pd.to_datetime(d.index, errors="coerce")
    d = d[~d.index.isna()].sort_index()
    d = d[~d.index.duplicated(keep="last")]
    for c in ("open", "high", "low", "close", "pre_close"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["close"])
    return back_adjust(d)


def back_adjust(d: pd.DataFrame, tol: float = 0.003) -> pd.DataFrame:
    """拆分/分红连续化 (锚定最新收盘, 向前调整)。

    交易所 pre_close 是除权除息后的参考价; 当 pre_close_t 与 close_{t-1} 偏离 > tol 时,
    t 之前的 OHLC 全部乘以 pre_close_t / close_{t-1}。前复权个股 (两者一致) 不受影响;
    未复权 ETF 的份额拆分 (如 1 拆 2) 与分红缺口被消除, 避免伪造 −50% 暴跌触发止损。
    原始收盘保留在 raw_close 列供审计。
    """
    if "pre_close" not in d.columns or len(d) < 2:
        return d
    close = d["close"].to_numpy(dtype=float)
    pre = d["pre_close"].to_numpy(dtype=float)
    ratio = np.ones(len(d))
    with np.errstate(divide="ignore", invalid="ignore"):
        r = pre[1:] / close[:-1]
    bad = np.isfinite(r) & (np.abs(r - 1.0) > tol) & (r > 0)
    if not bad.any():
        return d
    ratio[:-1][bad] = r[bad]                       # 作用于 t-1 及更早
    factor = np.cumprod(ratio[::-1])[::-1]         # 行 i = 所有 j ≥ i 事件比率之积
    out = d.copy()
    out["raw_close"] = d["close"]
    for c in ("open", "high", "low", "close", "pre_close"):
        if c in out.columns:
            out[c] = out[c].to_numpy(dtype=float) * factor
    out["adj_events"] = int(bad.sum())
    return out


# ═══════════════════════════════════════════════════════
#  核心: 单持仓确定性重放
# ═══════════════════════════════════════════════════════

@dataclass
class PositionInput:
    ts_code: str
    name: str
    qty: int
    cost: float                      # 券商成本 (含费)
    anchor_date: Optional[str]       # 本轮建仓日 (高水位起点)
    anchor_quality: str = "unknown"
    sleeve: str = "satellite"        # core / satellite
    basis_price: Optional[float] = None   # 重新基准化后的计量基准 (默认 = 成本)
    tracking_since: Optional[str] = None  # 系统开始跟踪日 (早于此的突破 = LEGACY)
    sells_after: tuple = ()          # 台账中锚点之后的卖出 [(date, qty)]
    acked_stages: tuple = ()         # 手动确认已执行的分批阶段
    published_floor: Optional[tuple] = None  # (日期, 止损/当日收盘 比值): 已发布止损线的下限 (复权口径无关)


def class_params(cls: str, sleeve: str, cfg: Mapping[str, Any]) -> dict:
    base = dict(cfg["classes"].get(cls) or cfg["classes"]["theme_etf"])
    if sleeve == "core":
        base.update(cfg["core"])
    return base


def _trail_mult(regime: str, cls: str, sleeve: str, aiae_regime: Optional[int], cfg: Mapping[str, Any]) -> float:
    k = float(class_params(cls, sleeve, cfg)["trail_atr_mult"])
    k += float((cfg.get("regime_trail_adj") or {}).get((regime or "RANGE").upper(), 0.0))
    if aiae_regime is not None and aiae_regime >= int(cfg["aiae_tighten_regime"]):
        k -= float(cfg["aiae_tighten_step"])
    return max(1.0, k)


def _path(tail: pd.DataFrame, stop_path: Mapping[Any, float], tick: float) -> dict:
    """图表用: 近 N 日收盘与当日收盘后生效的止损线 (锚点前为 null)。"""
    nd = 3 if tick < 0.01 else 2
    return {
        "d": [d.strftime("%m-%d") for d in tail.index],
        "c": [round(float(x), nd) for x in tail["close"]],
        "s": [round(float(stop_path[d]), nd) if d in stop_path else None for d in tail.index],
    }


def evaluate_position(pos: PositionInput, bars: pd.DataFrame, *, regime: str = "RANGE",
                      aiae_regime: Optional[int] = None, cfg: Optional[Mapping[str, Any]] = None,
                      as_of: Optional[str] = None, regime_hist: Optional[pd.Series] = None,
                      path_days: int = 60) -> dict:
    """regime_hist: 日期索引的市场环境序列 (point-in-time)。每个交易日用当日环境的 ATR 倍数,
    避免环境切换后用今天的倍数改写历史 → 已发布止损线下移。缺失日期用 regime 兜底。"""
    cfg = cfg or DEFAULT_CONFIG
    cls = asset_class(pos.ts_code, pos.name, cfg)
    base = {
        "ts_code": pos.ts_code, "name": pos.name, "qty": pos.qty, "cost": round(pos.cost, 4),
        "asset_class": cls, "sleeve": pos.sleeve, "anchor_date": pos.anchor_date,
        "anchor_quality": pos.anchor_quality,
    }
    if bars is None or len(bars) == 0:
        return {**base, "status": "NO_DATA", "action": "缺少日线行情, 请先同步数据"}
    b = normalize_bars(bars)
    if as_of:
        b = b[b.index <= pd.Timestamp(as_of)]
    period = int(cfg["atr_period"])
    if len(b) < period + 2:
        return {**base, "status": "NO_DATA", "action": f"日线不足 {period + 2} 根"}
    approx_atr = not ({"high", "low"} <= set(b.columns) and b[["high", "low"]].notna().all().all())
    atr = wilder_atr(b, period)

    anchor = pd.Timestamp(pos.anchor_date) if pos.anchor_date else b.index[-1]
    sub = b[b.index >= anchor]
    if sub.empty:
        sub = b.tail(1)
        anchor = sub.index[0]
    prior = atr[atr.index <= anchor].dropna()
    atr0 = float(prior.iloc[-1]) if len(prior) else float(atr.dropna().iloc[0])

    cp = class_params(cls, pos.sleeve, cfg)
    basis = float(pos.basis_price or pos.cost)
    r_unit = max(float(cp["init_atr_mult"]) * atr0, float(cfg["min_r_pct"]) * basis)
    init_stop = basis - r_unit
    breakeven = basis * (1 + float(cfg["breakeven_buffer_pct"]))
    trail_r, be_r = float(cp["trail_start_r"]), float(cfg["breakeven_r"])
    k_trail = _trail_mult(regime, cls, pos.sleeve, aiae_regime, cfg)
    if regime_hist is not None and len(regime_hist):
        rh = pd.Series(regime_hist).copy()
        rh.index = pd.to_datetime(rh.index)
        rh = rh.sort_index().reindex(sub.index, method="ffill").fillna(regime)
        k_by_day = {d: _trail_mult(str(r), cls, pos.sleeve, None, cfg) for d, r in rh.items()}
        # AIAE 过热收紧只作用于最新交易日 (收紧只会抬高止损线, 不破坏棘轮)
        k_by_day[sub.index[-1]] = k_trail
    else:
        k_by_day = None
    floor_date, floor_px = None, None
    if pos.published_floor:
        fd, ratio = pos.published_floor
        fts = pd.Timestamp(fd)
        if fts in b.index and fts >= sub.index[0]:
            floor_date, floor_px = fts, float(ratio) * float(b.loc[fts, "close"])

    stop = init_stop
    stage = 0
    hwm, hwm_date = -math.inf, None
    stage_dates: dict[int, str] = {}
    first_breach: Optional[pd.Timestamp] = None
    breach_stop = None
    stop_path: dict = {}
    for i, (d, row) in enumerate(sub.iterrows()):
        c = float(row["close"])
        if floor_date is not None and d > floor_date:
            stop = max(stop, floor_px)
        if i > 0 and c < stop and first_breach is None:
            first_breach, breach_stop = d, stop
        if c > hwm:
            hwm, hwm_date = c, d
        reached = (hwm - basis) / r_unit
        new_stage = 2 if reached >= trail_r else 1 if reached >= be_r else 0
        if new_stage > stage:
            for s in range(stage + 1, new_stage + 1):
                stage_dates.setdefault(s, d.strftime("%Y-%m-%d"))
            stage = new_stage
        a = float(atr.get(d, np.nan))
        if not np.isfinite(a):
            a = atr0
        if stage == 0:
            cand = init_stop
        elif stage == 1:
            cand = breakeven
        else:
            kt = k_by_day.get(d, k_trail) if k_by_day else k_trail
            cand = max(hwm - kt * a, breakeven)
        stop = max(stop, cand)
        stop_path[d] = stop

    last_d = sub.index[-1]
    close = float(sub["close"].iloc[-1])
    breach_at_anchor = False
    if first_breach is None and close < stop and len(sub) == 1:
        # 锚点即最新交易日 (无台账/快照日锚点) 且已低于初始止损: 属于跟踪前遗留
        first_breach, breach_stop, breach_at_anchor = last_d, stop, True
    atr_now = float(atr.iloc[-1]) if np.isfinite(atr.iloc[-1]) else atr0
    tick = tick_size(pos.ts_code)
    stop_r = round_down(stop, tick)
    dist = close - stop
    lot = int(cfg["lot_size"])

    # 分批止盈执行核对: 阶段达成后台账中出现卖出, 或人工确认
    frac = float(cp.get("partial_fraction") or 0.0)
    pending: list[dict] = []
    if frac > 0 and 2 in stage_dates and 2 not in pos.acked_stages:
        sold = sum(q for sd, q in pos.sells_after if sd >= stage_dates[2])
        target = round_lot((pos.qty + sold) * frac, lot)
        q = round_lot(pos.qty * frac, lot)
        if not (target > 0 and sold >= 0.8 * target) and q > 0:   # 零星卖出不算执行了分批止盈
            pending.append({"stage": 2, "since": stage_dates[2], "qty": q, "fraction": frac})

    gain = close / pos.cost - 1 if pos.cost else None
    out = {
        **base,
        "close": round(close, 4),
        "as_of": last_d.strftime("%Y-%m-%d"),
        "atr": round(atr_now, 4),
        "atr_pct": round(atr_now / close, 4) if close else None,
        "atr_approx": approx_atr,
        "r_unit": round(r_unit, 4),
        "basis_price": round(basis, 4),
        "init_stop": round_down(init_stop, tick),
        "hwm": round(hwm, 4),
        "hwm_date": hwm_date.strftime("%Y-%m-%d") if hwm_date is not None else None,
        "gain_pct": round(gain, 4) if gain is not None else None,
        "gain_r": round((close - basis) / r_unit, 2),
        "max_gain_r": round((hwm - basis) / r_unit, 2),
        "stage": stage,
        "stage_label": STAGE_LABEL[stage],
        "stage_dates": stage_dates,
        "k_trail": k_trail,
        "params": {"init_k": cp["init_atr_mult"], "trail_k": k_trail, "trail_start_r": trail_r,
                   "partial": frac, "reentry": cp.get("reentry")},
        "stop": stop_r,
        "distance_pct": round(dist / close, 4) if close else None,
        "distance_atr": round(dist / atr_now, 2) if atr_now else None,
        "disaster_stop": round_down(stop - float(cfg["disaster_stop_atr"]) * atr_now, tick),
        "first_breach": first_breach.strftime("%Y-%m-%d") if first_breach is not None else None,
        "breach_stop": round_down(breach_stop, tick) if breach_stop is not None else None,
        "pending_partial": pending[0] if pending else None,
        "sell_qty": 0,
        "path": _path(b.tail(path_days), stop_path, tick),
    }

    tracking = pd.Timestamp(pos.tracking_since) if pos.tracking_since else None
    if first_breach is not None:
        days = int(((sub.index > first_breach)).sum())
        out["days_since_breach"] = days
        if breach_at_anchor or (tracking is not None and first_breach < tracking):
            out["status"] = "LEGACY"
            out["action"] = (f"{out['first_breach']} 已跌破止损线 {out['breach_stop']} (系统跟踪前)。"
                             "需一次性决策: 执行止损, 或『重新基准化』以今日为新起点")
        else:
            out["status"] = "RED"
            out["sell_qty"] = pos.qty
            late = f", 已逾期 {days} 个交易日" if days > 0 else ""
            out["action"] = f"收盘跌破止损线 {out['breach_stop']} → 下一交易日卖出 {pos.qty} 股{late}"
    elif pending:
        p = pending[0]
        out["status"] = "ACTION"
        out["sell_qty"] = p["qty"]
        out["action"] = (f"{STAGE_LABEL[p['stage']]} 自 {p['since']} 达成 → 卖出 {p['qty']} 股 "
                         f"(≈1/{round(1 / p['fraction'])}) 锁定利润, 余仓按止损线 {stop_r} 跟踪")
    elif atr_now and dist < float(cfg["near_stop_atr"]) * atr_now:
        out["status"] = "YELLOW"
        out["action"] = f"距止损线 {stop_r} 仅 {out['distance_atr']} ATR, 收盘跌破即卖出"
    else:
        out["status"] = "GREEN"
        out["action"] = f"持有 · 止损线 {stop_r} ({STAGE_LABEL[stage]})"
    return out


# ═══════════════════════════════════════════════════════
#  再入场 (校准结果依赖它: 止损离场后若不回补, 会系统性错过反弹)
# ═══════════════════════════════════════════════════════

def reentry_signal(bars: pd.DataFrame, rule: str) -> dict:
    """breakout20: 收盘 > 前 20 日最高收盘; ma60: 收盘上穿 MA60。返回 TRIGGER / ABOVE / WAIT。"""
    if bars is None or len(bars) < 62:
        return {"state": "NO_DATA"}
    b = normalize_bars(bars)
    c = b["close"]
    if rule == "breakout20":
        level = c.shift(1).rolling(20).max()
        trig = bool(c.iloc[-1] > level.iloc[-1])
        state = "TRIGGER" if trig else "WAIT"
        label = "20 日新高"
    else:
        level = c.rolling(60).mean()
        above, was = c.iloc[-1] > level.iloc[-1], c.iloc[-2] > level.iloc[-2]
        state = "TRIGGER" if (above and not was) else "ABOVE" if above else "WAIT"
        label = "上穿 MA60"
    lv = float(level.iloc[-1])
    return {"state": state, "rule": label, "level": round(lv, 4), "close": round(float(c.iloc[-1]), 4),
            "gap_pct": round(float(c.iloc[-1]) / lv - 1, 4) if lv else None,
            "as_of": b.index[-1].strftime("%Y-%m-%d")}


# ═══════════════════════════════════════════════════════
#  回合复盘: 实际卖出 vs 规则卖出
# ═══════════════════════════════════════════════════════

def next_fill(b: pd.DataFrame, signal_day: pd.Timestamp, ts_code: str) -> tuple[str, float]:
    """收盘确认 → 次一交易日开盘成交; 一字跌停 (最高 = 最低 且跌幅触及限制) 无法成交, 顺延。"""
    lim = 0.20 if ts_code.split(".")[0].startswith(("688", "689", "300", "301")) else 0.10
    nxt = b[b.index > signal_day]
    pc = nxt["pre_close"] if "pre_close" in nxt.columns else b["close"].shift(1).reindex(nxt.index)
    for d, row in nxt.iterrows():
        locked = ("high" in nxt.columns and abs(float(row["high"]) - float(row["low"])) < 1e-9
                  and float(row["close"]) / float(pc.loc[d]) - 1 <= -lim + 0.003)
        if locked:
            continue
        px = float(row["open"]) if "open" in nxt.columns and np.isfinite(row["open"]) else float(row["close"])
        return d.strftime("%Y-%m-%d"), px
    return signal_day.strftime("%Y-%m-%d"), float(b.loc[signal_day, "close"])


def review_round_trip(trip: Mapping[str, Any], bars: pd.DataFrame, *, regime: str = "RANGE",
                      cfg: Optional[Mapping[str, Any]] = None) -> dict:
    """对一个已完成回合计算 MFE (最大浮盈) / 利润回吐率, 以及规则若执行会在何时何价离场。"""
    cfg = cfg or DEFAULT_CONFIG
    out = dict(trip)
    if bars is None or len(bars) == 0:
        out["review"] = "no_data"
        return out
    b = normalize_bars(bars)
    entry, exit_ = pd.Timestamp(trip["entry_date"]), pd.Timestamp(trip["exit_date"])
    window = b[(b.index >= entry) & (b.index <= exit_)]
    if window.empty:
        out["review"] = "no_data"
        return out
    avg_buy, avg_sell = float(trip["avg_buy"]), float(trip["avg_sell"])
    peak = float(window["close"].max())
    out["mfe_pct"] = round(peak / avg_buy - 1, 4)
    out["giveback"] = round((peak - avg_sell) / (peak - avg_buy), 3) if peak > avg_buy else None
    out["hold_days"] = int(len(window))

    pos = PositionInput(ts_code=trip["ts_code"], name=trip.get("name", ""), qty=int(trip["buy_qty"]),
                        cost=avg_buy, anchor_date=trip["entry_date"], anchor_quality="exact")
    # 重放到实际离场后 90 天: first_breach 即规则的首次触发日 (确定性重放, 一次即可)
    after = b[(b.index >= entry) & (b.index <= exit_ + pd.Timedelta(days=90))]
    r = evaluate_position(pos, b[b.index <= after.index[-1]], regime=regime, cfg=cfg)
    if r.get("first_breach"):
        fb = pd.Timestamp(r["first_breach"])
        d_exec, px = next_fill(after, fb, trip["ts_code"])
        cost = float(cfg.get("round_trip_cost", 0.002))
        out["rule_exit_date"], out["rule_exit_price"] = d_exec, px
        out["rule_ret"] = round(px / avg_buy - 1 - cost, 4)
        out["rule_minus_actual"] = round(out["rule_ret"] - float(trip["ret"]), 4)
    out["review"] = "ok"
    return out
