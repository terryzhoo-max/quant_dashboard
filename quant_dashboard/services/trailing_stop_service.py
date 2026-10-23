"""
AlphaCore · 跟踪止盈执行闭环 (I/O 编排层)
==========================================

把纯计算引擎 services/trailing_stop.py 接到真实数据上, 并补齐 "建议 → 执行" 的闭环:

  持仓快照 (券商, 权威数量/成本)  data_lake/portfolio_store.json
  成交台账 (时间线, 建仓日锚点)    data_lake/trade_ledger.json      ← 历史成交导入
  日线行情 (前复权 OHLC)           data_lake/daily_prices/{code}.parquet
  跟踪状态 (人工决策 + 审计)       data_lake/trailing_stop_state.json
  参数 (可选覆盖)                  config/trailing_stop.json

输出:
  · 每只持仓的止损线 / 阶段 / 状态 / 当日指令
  · 券商条件单清单 (收盘确认线 + 兜底价)
  · 执行纪律分 (触发后是否在 T+1 内卖出, 由台账自动核对)
  · 已完成回合复盘 (最大浮盈 / 利润回吐 / 规则 vs 实际)
  · 推送预警 (复用 alert_monitor 的 Server酱 / 邮件 / 企业微信通道)
"""
from __future__ import annotations

import copy
import math
import hashlib
import json
import os
import threading
from datetime import datetime
from typing import Any, Callable, Mapping, Optional

import pandas as pd

from services import drawdown_service as _dds
from services.logger import get_logger
from services.trade_import import closed_round_trips, load_ledger, reconcile_positions
from services.trailing_stop import (
    CALIBRATION, STATUS_ORDER, PositionInput, asset_class, class_params, evaluate_position, is_etf,
    merge_config, reentry_signal, review_round_trip, round_down, tick_size,
)

logger = get_logger("ac.trailing")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_ROOT, "data_lake")
STORE_PATH = os.path.join(DATA_DIR, "portfolio_store.json")
STATE_PATH = os.path.join(DATA_DIR, "trailing_stop_state.json")
SNAPSHOT_DIR = os.path.join(DATA_DIR, "trailing_snapshots")
SCHEMA_VERSION = 2
ENGINE_VERSION = "trailing-stop/2.1 (calibrated 2026-10-22)"
CONFIG_PATH = os.path.join(_ROOT, "config", "trailing_stop.json")
PRICE_DIR = os.path.join(DATA_DIR, "daily_prices")

_LOCK = threading.Lock()


# ═══════════════════════════════════════════════════════
#  存取
# ═══════════════════════════════════════════════════════

def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("读取 %s 失败: %s", path, e)
        return default


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_config() -> dict:
    return merge_config(_read_json(CONFIG_PATH, {}) or {})


def load_state(path: Optional[str] = None) -> dict:
    st = _read_json(path or STATE_PATH, {}) or {}
    st.setdefault("positions", {})
    st.setdefault("audit", [])
    st.setdefault("alerts", {})
    return st


def save_state(state: dict, path: Optional[str] = None) -> None:
    state["audit"] = state.get("audit", [])[-500:]
    _write_json(path or STATE_PATH, state)


def default_bars_loader(ts_code: str) -> Optional[pd.DataFrame]:
    fpath = os.path.join(PRICE_DIR, f"{ts_code}.parquet")
    if not os.path.exists(fpath):
        return None
    try:
        return pd.read_parquet(fpath)
    except Exception as e:
        logger.warning("读取行情 %s 失败: %s", ts_code, e)
        return None


def sync_prices(codes: list[str]) -> dict:
    """增量同步持仓日线 (ETF 走 asset='FD', 个股 'E'; 前复权)。失败不致命。"""
    out = {"ok": [], "failed": []}
    try:
        from data.data_manager import FactorDataManager
        dm = FactorDataManager()
    except Exception as e:
        logger.warning("行情同步不可用: %s", e)
        return {"ok": [], "failed": codes, "error": str(e)}
    for code in codes:
        try:
            dm.sync_daily_prices([code], start_date="20240101", asset="FD" if is_etf(code) else "E")
            out["ok"].append(code)
        except Exception as e:
            out["failed"].append(code)
            logger.warning("同步 %s 失败: %s", code, e)
    return out


_SYNC_STATE = {"running": False, "last": 0.0, "last_result": None}


def ensure_prices_async(codes: list[str], min_interval_sec: int = 1800) -> dict:
    """缺行情 / 行情滞后的持仓: 后台线程增量同步 (不阻塞页面), 30 分钟内不重复触发。"""
    import time as _t
    if not codes:
        return {"started": False, "reason": "无需同步"}
    if _SYNC_STATE["running"]:
        return {"started": False, "reason": "同步进行中", "codes": codes}
    if _t.time() - _SYNC_STATE["last"] < min_interval_sec:
        return {"started": False, "reason": "近期已同步过", "last_result": _SYNC_STATE["last_result"]}

    def _run():
        _SYNC_STATE["running"] = True
        try:
            _SYNC_STATE["last_result"] = sync_prices(codes)
        finally:
            _SYNC_STATE["running"], _SYNC_STATE["last"] = False, _t.time()

    threading.Thread(target=_run, daemon=True, name="trailing-price-sync").start()
    return {"started": True, "codes": codes}


def _market_context() -> tuple[str, Optional[int]]:
    regime, aiae = "RANGE", None
    try:
        from services.market_regime import get_market_regime_snapshot
        regime = str(get_market_regime_snapshot().get("regime") or "RANGE").upper()
    except Exception as e:
        logger.debug("市场环境不可用, 默认 RANGE: %s", e)
    try:
        from services.cache_service import cache_manager
        ctx = cache_manager.get_json("aiae_ctx") or {}
        if ctx.get("regime") is not None:
            aiae = int(ctx["regime"])
    except Exception:
        pass
    return regime, aiae


def regime_history(state: Optional[Mapping[str, Any]] = None,
                   bars_loader: Optional[Callable[[str], Any]] = None) -> Optional[pd.Series]:
    """Point-in-time 市场环境序列: 实盘记录 (regime_log) 优先, 之前的日期用沪深300 重建。

    重建口径 (近似 services/market_regime): 收盘 > MA120 且 MA120 5 日斜率 > 0 → BULL;
    收盘 < MA120 且斜率 < 0 → BEAR; 3 日跌幅 ≥ 7% → CRASH; 其余 RANGE。
    """
    hist = None
    try:
        raw = (bars_loader or default_bars_loader)("000300.SH")
        if raw is not None and len(raw) > 130:
            from services.trailing_stop import normalize_bars
            b = normalize_bars(raw)
            c = b["close"]; ma = c.rolling(120).mean(); slope = ma.diff(5)
            hist = pd.Series("RANGE", index=b.index)
            hist[(c > ma) & (slope > 0)] = "BULL"
            hist[(c < ma) & (slope < 0)] = "BEAR"
            hist[c.pct_change(3) <= -0.07] = "CRASH"
    except Exception as e:
        logger.debug("环境历史重建失败: %s", e)
    log = (state or {}).get("regime_log") or {}
    if log:
        live = pd.Series(log)
        live.index = pd.to_datetime(live.index)
        hist = live if hist is None else pd.concat([hist[hist.index < live.index.min()], live]).sort_index()
    return hist


def _audit(state: dict, ts_code: str, action: str, detail: str) -> None:
    state["audit"].append({"at": datetime.now().isoformat(timespec="seconds"),
                           "ts_code": ts_code, "action": action, "detail": detail})


# ═══════════════════════════════════════════════════════
#  核心报告
# ═══════════════════════════════════════════════════════

ANCHOR_NOTE = {
    "exact": "台账可见 0→持仓 的建仓日",
    "inferred_cost": "成交记录早于台账: 取台账起点前最近一次『日内价格区间包含持仓成本』的交易日 (推断)",
    "pre_window": "成交记录早于台账, 且无法用成本反推: 暂取台账首日 (偏晚, 高水位可能偏低)",
    "manual": "人工设定 (已留痕)",
    "rebaselined": "重新基准化",
    "unknown": "无成交记录且无法反推: 暂取持仓快照日",
    "approx": "台账与持仓对不上, 近似",
}


def infer_anchor_from_cost(bars: Any, cost: float, before: Optional[str], max_lookback: int = 750) -> Optional[str]:
    """建仓日推断: 在 `before` 之前, 找最近一个 最低价 ≤ 持仓成本 ≤ 最高价 的交易日。

    多笔摊薄成本未必真实成交过, 结果只是 "成本重心" 的近似; 只用于高水位起点与建仓 ATR,
    对已经亏损的持仓 (止损线 = 成本 − k×ATR) 影响很小。
    """
    if bars is None or not cost:
        return None
    try:
        from services.trailing_stop import normalize_bars
        b = normalize_bars(bars)
    except Exception:
        return None
    if before:
        b = b[b.index < pd.Timestamp(before)]
    b = b.tail(max_lookback)
    if b.empty or not {"high", "low"} <= set(b.columns):
        return None
    hit = b[(b["low"] <= cost) & (b["high"] >= cost)]
    return hit.index[-1].strftime("%Y-%m-%d") if len(hit) else None


def ledger_freshness(ledger: Mapping[str, Any], today: str, warn_days: int = 40) -> dict:
    """通达信历史成交只能导出近 60 天: 两次导出间隔超过 60 天会产生永久缺口。"""
    imports = [i for i in (ledger.get("imports") or []) if i.get("at")]
    if not imports:
        return {"import_due": True, "days_since_import": None,
                "import_note": "尚未导入历史成交: 建仓日只能推断"}
    last = max(i["at"][:10] for i in imports)
    days = (pd.Timestamp(today) - pd.Timestamp(last)).days
    due = days >= warn_days
    note = (f"距上次导入已 {days} 天, 请尽快导出 (通达信只保留近 60 天, 超期将出现无法补回的缺口)"
            if due else f"距上次导入 {days} 天 · 建议每月导出一次, 拖入 data_lake/trade_imports 自动累积")
    return {"import_due": due, "days_since_import": days, "last_import_date": last, "import_note": note}


def resolve_anchor(rec: Mapping[str, Any], ps: Mapping[str, Any], bars: Any, cost: float,
                   snapshot_date: Optional[str]) -> tuple[Optional[str], str, Optional[float]]:
    """锚点优先级: 重新基准化 > 人工设定 > 台账精确 > 成本反推 > 台账首日 / 快照日。"""
    if ps.get("rebaseline"):
        return ps["rebaseline"]["date"], "rebaselined", float(ps["rebaseline"]["price"])
    if ps.get("manual_anchor"):
        return ps["manual_anchor"]["date"], "manual", None
    anchor, quality = rec.get("anchor_date"), rec.get("anchor_quality", "no_history")
    if quality == "exact" and anchor:
        return anchor, "exact", None
    if quality in ("pre_window", "no_history") or not anchor:
        before = anchor if quality == "pre_window" else snapshot_date
        guess = infer_anchor_from_cost(bars, cost, before)
        if guess:
            return guess, "inferred_cost", None
        if quality == "pre_window" and anchor:
            return anchor, "pre_window", None
        return snapshot_date, "unknown", None
    return anchor, quality, None


def build_report(*, store: Optional[Mapping[str, Any]] = None, ledger: Optional[Mapping[str, Any]] = None,
                 state: Optional[dict] = None, cfg: Optional[Mapping[str, Any]] = None,
                 bars_loader: Optional[Callable[[str], Any]] = None,
                 regime: Optional[str] = None, aiae_regime: Optional[int] = None,
                 today: Optional[str] = None, persist: bool = False) -> dict:
    """纯计算 (默认不写任何文件)。persist=True 仅供日终任务: 计算后立即 commit_eod。"""
    store = store if store is not None else _read_json(STORE_PATH, {}) or {}
    ledger = ledger if ledger is not None else load_ledger()
    own_state = state is None
    state = state if state is not None else load_state()
    cfg = cfg or load_config()
    loader = bars_loader or default_bars_loader
    if regime is None:
        regime, ctx_aiae = _market_context()
        aiae_regime = aiae_regime if aiae_regime is not None else ctx_aiae
    today = today or datetime.now().strftime("%Y-%m-%d")

    started = not state.get("tracking_since")
    if started:
        state["tracking_since"] = today          # 首次运行: 此前的突破一律视为遗留 (LEGACY)

    state = copy.deepcopy(state)              # 纯函数: 不修改调用方 / 磁盘上的状态
    state.setdefault("regime_log", {})[today] = regime
    rhist = regime_history(state, loader)

    holdings = {k: v for k, v in (store.get("positions") or {}).items() if float(v.get("amount", 0) or 0) > 0}
    trades = ledger.get("trades", [])
    rec = reconcile_positions(trades, holdings, as_of=store.get("import_date"))

    rows = []
    for code, p in holdings.items():
        ps = state["positions"].get(code, {})
        r = rec.get(code, {})
        try:
            bars = loader(code)
        except Exception as e:
            logger.warning("读取行情 %s 失败: %s", code, e)
            bars = None
        cost = float(p.get("cost") or 0) or float(p.get("broker_price") or 0)
        anchor, quality, basis = resolve_anchor(r, ps, bars, cost, store.get("import_date"))
        sells = tuple((t["date"], int(t["qty"])) for t in trades
                      if t.get("ts_code") == code and t.get("side") == "sell" and (anchor is None or t["date"] >= anchor))
        tracking = max(state["tracking_since"], ps["rebaseline"]["date"]) if ps.get("rebaseline") else state["tracking_since"]
        pin = PositionInput(
            ts_code=code, name=p.get("name", code), qty=int(round(float(p.get("amount", 0)))),
            cost=cost,
            anchor_date=anchor, anchor_quality=quality, sleeve=ps.get("sleeve", "satellite"),
            basis_price=basis, tracking_since=tracking, sells_after=sells,
            acked_stages=tuple(ps.get("acked_stages", [])),
            published_floor=((ps["published"]["date"], ps["published"]["ratio"])
                             if (ps.get("published") or {}).get("anchor") == anchor else None),
        )
        try:
            row = evaluate_position(pin, bars, regime=regime, aiae_regime=aiae_regime, cfg=cfg,
                                    regime_hist=rhist)
        except Exception as e:
            logger.warning("跟踪止盈计算 %s 失败: %s", code, e)
            row = {"ts_code": code, "name": pin.name, "qty": pin.qty, "cost": pin.cost,
                   "status": "NO_DATA", "action": f"计算失败: {e}"}
        row["reconcile_status"] = r.get("status", "no_history")
        row["anchor_note"] = ANCHOR_NOTE.get(quality, "")
        if row.get("as_of"):
            lag = len(pd.bdate_range(row["as_of"], today)) - 1
            row["data_lag_days"] = max(0, lag)
            if lag > 1:
                row["action"] = f"⚠ 行情滞后 {lag} 个交易日 (截至 {row['as_of']}), 结论可能过时 · " + str(row.get("action", ""))
        row["market_value"] = float(p.get("broker_market_value") or 0) or None
        if row.get("status") not in ("NO_DATA",) and row.get("close") is not None:
            row["market_value"] = round(row["close"] * pin.qty, 2)
        rows.append(row)

    rows.sort(key=lambda x: (STATUS_ORDER.get(x.get("status"), 9), -(x.get("market_value") or 0)))
    total_mv = sum(r.get("market_value") or 0 for r in rows) or 1.0
    for r in rows:
        r["weight"] = round((r.get("market_value") or 0) / total_mv, 4)

    equity, cash, equity_basis = _dds.marked_equity(store, sum(r.get("market_value") or 0 for r in rows))
    heat = portfolio_heat(rows, equity, cfg)
    adds = averaging_down(trades, holdings, store.get("import_date"),
                          breaches={r["ts_code"]: r.get("first_breach") for r in rows if r.get("first_breach")})
    for r in rows:
        if r.get("status") == "LEGACY":
            r["reunderwrite"] = reunderwrite_preview(r, equity, cfg)
    reentry = reentry_watch(trades, holdings, loader, cfg, today)
    corr = correlation_risk(rows, loader)
    ddm = _dds.section(holdings=holdings, trades=trades, loader=loader, store=store, state=state, cfg=cfg,
                       equity=equity, invested_value=sum(r.get("market_value") or 0 for r in rows), rows=rows)

    summary: dict[str, int] = {}
    for r in rows:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    at_risk_mv = sum((r.get("market_value") or 0) for r in rows if r["status"] in ("RED", "LEGACY"))

    orders = []
    for r in rows:
        if r.get("status") in ("NO_DATA", "LEGACY"):
            continue
        if r["status"] == "RED":
            orders.append({"ts_code": r["ts_code"], "name": r["name"], "type": "次日开盘卖出",
                           "qty": r["qty"], "trigger": None, "note": r["action"]})
            continue
        if r["status"] == "ACTION" and r.get("pending_partial"):
            orders.append({"ts_code": r["ts_code"], "name": r["name"], "type": "分批止盈 (限价/开盘)",
                           "qty": r["pending_partial"]["qty"], "trigger": None, "note": r["action"]})
        orders.append({"ts_code": r["ts_code"], "name": r["name"], "type": "股价≤ 兜底价 全部卖出",
                       "qty": r["qty"], "trigger": r.get("disaster_stop"),
                       "note": f"收盘确认线 {r.get('stop')} 由系统每日 15:50 核对; 条件单仅防跳空/盘中崩"})

    report = {
        "as_of": max((r.get("as_of") or "" for r in rows), default=None) or today,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "regime": regime,
        "aiae_regime": aiae_regime,
        "tracking_since": state["tracking_since"],
        "summary": summary,
        "at_risk_market_value": round(at_risk_mv, 2),
        "equity": round(equity, 2),
        "equity_basis": {"basis": equity_basis, "cash": round(cash, 2) if cash is not None else None,
                         "broker_total_asset": store.get("broker_total_asset"), "snapshot_date": store.get("import_date"),
                         "note": "总资产 = 最新收盘持仓市值 + 快照现金 (同一时点口径)"},
        "heat": heat,
        "correlation": corr,
        "drawdown": ddm,
        "averaging_down": adds,
        "reentry": reentry,
        "positions": rows,
        "orders": orders,
        "price_sync_needed": [r["ts_code"] for r in rows
                              if r.get("status") == "NO_DATA" or (r.get("data_lag_days") or 0) > 1],
        "price_sync_history": [c for c in (ddm.get("missing_prices") or []) if c not in holdings],
        "ledger": {
            **ledger_freshness(ledger, today),
            "trades": len(trades),
            "date_from": trades[0]["date"] if trades else None,
            "date_to": trades[-1]["date"] if trades else None,
            "last_import": (ledger.get("imports") or [None])[-1],
        },
        "reconciliation": [{"ts_code": k, **{x: v.get(x) for x in ("held_qty", "ledger_net", "opening_qty", "status", "anchor_date", "anchor_quality")}}
                           for k, v in rec.items()],
        "discipline": None,
        "params": {
            "atr_period": cfg["atr_period"], "breakeven_r": cfg["breakeven_r"],
            "classes": cfg["classes"], "core": cfg["core"],
            "risk_per_position_pct": cfg["risk"]["per_position_pct"],
            "heat_limit_pct": cfg["risk"]["heat_limit_pct"],
            "calibration": CALIBRATION,
        },
    }
    state["discipline_log"] = _update_discipline_log(state.get("discipline_log", {}), rows, today)
    report["discipline"] = discipline_from_rows(rows, state)
    report["meta"] = _provenance(report, cfg, ledger, rows)
    report["actions"] = build_actions(report)
    if persist and own_state:
        commit_eod(report, regime=regime, today=today)
    return report


# ═══════════════════════════════════════════════════════
#  日终提交 (唯一写入方) · 快照 · 日间差异
# ═══════════════════════════════════════════════════════

def snapshot_path(as_of: str) -> str:
    return os.path.join(SNAPSHOT_DIR, f"{as_of}.json")


def _snapshot_of(report: Mapping[str, Any]) -> dict:
    keys = ("ts_code", "name", "status", "stage", "stop", "close", "qty", "weight", "gain_pct",
            "first_breach", "anchor_date", "anchor_quality", "open_risk")
    return {
        "schema_version": SCHEMA_VERSION, "as_of": report["as_of"], "generated_at": report["generated_at"],
        "regime": report.get("regime"), "summary": report.get("summary"), "heat": report.get("heat"),
        "correlation": {k: (report.get("correlation") or {}).get(k) for k in ("avg_corr", "n_eff", "n")},
        "meta": report.get("meta"),
        "drawdown": _dd_brief(report.get("drawdown")),
        "positions": [{k: r.get(k) for k in keys} for r in report.get("positions", [])],
    }


def load_previous_snapshot(as_of: str) -> Optional[dict]:
    if not os.path.isdir(SNAPSHOT_DIR):
        return None
    days = sorted(f[:-5] for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".json") and f[:-5] < as_of)
    return _read_json(snapshot_path(days[-1]), None) if days else None


def diff_snapshots(prev: Optional[Mapping[str, Any]], cur: Mapping[str, Any]) -> dict:
    """日间变化: 状态迁移 / 止损线上移 / 新增与清仓。"""
    if not prev:
        return {"base": None, "items": [], "note": "暂无上一交易日快照 (从下一个交易日起可对比)"}
    p = {x["ts_code"]: x for x in prev.get("positions", [])}
    c = {x["ts_code"]: x for x in cur.get("positions", [])}
    items = []
    for code, x in c.items():
        y = p.get(code)
        if not y:
            items.append({"ts_code": code, "name": x.get("name"), "type": "new", "text": "新增持仓"})
            continue
        if x.get("status") != y.get("status"):
            items.append({"ts_code": code, "name": x.get("name"), "type": "status",
                          "from": y.get("status"), "to": x.get("status"),
                          "text": f"{y.get('status')} → {x.get('status')}"})
        if x.get("stop") and y.get("stop") and abs(x["stop"] / y["stop"] - 1) > 0.0005:
            ch = x["stop"] / y["stop"] - 1
            items.append({"ts_code": code, "name": x.get("name"), "type": "stop", "change": round(ch, 4),
                          "text": f"止损线 {y['stop']} → {x['stop']} ({ch:+.1%})"})
        if x.get("qty") != y.get("qty"):
            items.append({"ts_code": code, "name": x.get("name"), "type": "qty",
                          "text": f"持仓 {y.get('qty')} → {x.get('qty')}"})
    for code, y in p.items():
        if code not in c:
            items.append({"ts_code": code, "name": y.get("name"), "type": "closed", "text": "已清仓"})
    order = {"status": 0, "closed": 1, "new": 2, "qty": 3, "stop": 4}
    items.sort(key=lambda i: order.get(i["type"], 9))
    return {"base": prev.get("as_of"), "items": items}


def commit_eod(report: Mapping[str, Any], *, regime: str, today: str) -> None:
    """日终提交 —— 唯一会改写跟踪状态的路径 (定时任务 / 手动重算 / 错过收盘后的首次访问补跑)。

    写入: 已发布止损线下限、纪律日志、环境日志、日终快照 (不可变, 供审计与日间对比)、合规缓存。
    同一 as_of 重复提交是幂等的 (快照覆盖同名文件, 下限取同一收盘)。
    """
    rows = report.get("positions", [])
    with _LOCK:
        fresh = load_state()
        if not fresh.get("tracking_since"):
            fresh["tracking_since"] = report.get("tracking_since") or today
            _audit(fresh, "*", "start_tracking", f"跟踪止盈自 {fresh['tracking_since']} 起生效")
        fresh["discipline_log"] = _update_discipline_log(fresh.get("discipline_log", {}), rows, today)
        fresh["last_discipline"] = {**(report.get("discipline") or {}), "at": report.get("generated_at")}
        rl = fresh.setdefault("regime_log", {})
        rl[report["as_of"]] = regime
        for k in sorted(rl)[:-800]:
            rl.pop(k, None)
        for r in rows:
            if r.get("status") == "NO_DATA" or not r.get("close") or r.get("stop") is None:
                continue
            fp = fresh["positions"].setdefault(r["ts_code"], {})
            fp["published"] = {"anchor": r.get("anchor_date"), "date": r.get("as_of"),
                               "ratio": round(float(r["stop"]) / float(r["close"]), 6)}
        _dds.publish(fresh, report.get("drawdown"), report["as_of"])
        fresh["last_eod"] = {"as_of": report["as_of"], "at": datetime.now().isoformat(timespec="seconds"),
                             "config_hash": (report.get("meta") or {}).get("config_hash")}
        save_state(fresh)
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        _write_json(snapshot_path(report["as_of"]), _snapshot_of(report))
        snaps = sorted(f for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".json"))
        for f in snaps[:-400]:
            try:
                os.remove(os.path.join(SNAPSHOT_DIR, f))
            except OSError:
                pass
    try:   # 供预交易合规 (stop_breach_no_add) 读取
        from services.cache_service import cache_manager
        cache_manager.set_json("trailing_stop_report", {
            "as_of": report["as_of"], "generated_at": report.get("generated_at"),
            "positions": [{k: r.get(k) for k in ("ts_code", "name", "status", "stop", "close")} for r in rows],
        }, ttl_seconds=24 * 3600)
        brief = _dd_brief(report.get("drawdown"))
        if brief:
            cache_manager.set_json("drawdown_brake", {**brief, "as_of": report["as_of"]}, ttl_seconds=30 * 24 * 3600)  # 长 TTL: 过期由合规层按 as_of 判定, 不静默消失
    except Exception:
        pass
    logger.info("跟踪止盈日终提交 · as_of %s · %s", report["as_of"], report.get("summary"))


def get_report(allow_commit: bool = True, **kw) -> dict:
    """页面读取入口: 纯计算; 若出现尚未提交的新收盘 (如 15:50 时服务未运行), 自动补跑一次日终提交。"""
    report = build_report(**kw)
    st = load_state()
    last = (st.get("last_eod") or {}).get("as_of")
    report["eod"] = {"last_as_of": last, "committed_now": False}
    has_data = any(r.get("status") != "NO_DATA" for r in report.get("positions", []))
    if allow_commit and has_data and (last is None or report["as_of"] > last):
        commit_eod(report, regime=report.get("regime") or "RANGE",
                   today=kw.get("today") or datetime.now().strftime("%Y-%m-%d"))
        report["eod"] = {"last_as_of": report["as_of"], "committed_now": True}
        st = load_state()
    report["changes"] = diff_snapshots(load_previous_snapshot(report["as_of"]), _snapshot_of(report))
    report["audit"] = list(reversed(st.get("audit", [])[-30:]))
    return report


# ═══════════════════════════════════════════════════════
#  行动队列: 把 "信息" 变成 "下一交易日开盘前要做的事"
# ═══════════════════════════════════════════════════════

def build_actions(report: Mapping[str, Any]) -> list[dict]:
    acts: list[dict] = []
    rows = report.get("positions", [])
    for r in rows:
        mv = r.get("market_value") or 0
        if r.get("status") == "RED":
            acts.append({"priority": 1, "type": "EXIT", "ts_code": r["ts_code"], "name": r["name"], "qty": r["qty"],
                         "value": mv, "title": f"卖出 {r['name']} {r['qty']} 股",
                         "detail": f"{r.get('first_breach')} 收盘跌破止损线 {r.get('breach_stop')}, 规则要求次一交易日开盘执行"})
    for r in rows:
        if r.get("status") == "LEGACY":
            ru = r.get("reunderwrite") or {}
            acts.append({"priority": 2, "type": "DECIDE", "ts_code": r["ts_code"], "name": r["name"], "qty": r["qty"],
                         "value": r.get("market_value") or 0,
                         "title": f"决策 {r['name']}: 止损 或 重新承保",
                         "detail": (f"{r.get('first_breach')} 已越过止损线 {r.get('breach_stop')} (跟踪前)。"
                                    f"若保留: 新止损 {ru.get('new_stop')} (−{(ru.get('stop_distance_pct') or 0):.0%}), "
                                    f"风险预算内最多 {ru.get('max_qty')} 股"
                                    + (f", 需减 {ru.get('reduce_qty')} 股" if ru.get("reduce_qty") else ""))})
    acts.extend(_drawdown_actions(report.get("drawdown") or {}))
    for r in rows:
        if r.get("status") == "ACTION" and r.get("pending_partial"):
            pp = r["pending_partial"]
            acts.append({"priority": 3, "type": "TRIM", "ts_code": r["ts_code"], "name": r["name"], "qty": pp["qty"],
                         "value": pp["qty"] * (r.get("close") or 0), "title": f"分批止盈 {r['name']} {pp['qty']} 股",
                         "detail": f"浮盈自 {pp['since']} 进入跟踪段, 卖出约 1/3 锁利, 余仓按 {r.get('stop')} 跟踪"})
    for r in rows:
        if r.get("risk_excess_qty"):
            acts.append({"priority": 4, "type": "RESIZE", "ts_code": r["ts_code"], "name": r["name"],
                         "qty": r["risk_excess_qty"], "value": r["risk_excess_qty"] * (r.get("close") or 0),
                         "title": f"减仓 {r['name']} {r['risk_excess_qty']} 股 (超单票风险预算)",
                         "detail": f"到止损线的潜在亏损 {r.get('open_risk'):,.0f} > 预算 {report['heat']['per_position_budget']:,.0f}"})
    h = report.get("heat") or {}
    if h.get("over_limit"):
        acts.append({"priority": 4, "type": "HEAT", "title": "组合热度超限",
                     "detail": f"所有持仓同时打到止损线将亏 {h.get('heat_pct', 0):.1%} > 上限 {h.get('limit_pct', 0):.0%}"})
    cr = report.get("correlation") or {}
    if cr.get("n_eff") is not None and cr["n_eff"] < 3 and (cr.get("n") or 0) >= 4:
        acts.append({"priority": 4, "type": "CONCENTRATION",
                     "title": f"集中度: {cr['n']} 只持仓 ≈ {cr['n_eff']} 个独立押注",
                     "detail": (f"60 日市值加权平均相关 {cr['avg_corr']:.2f}; 板块同跌时各单票止损会同时触发, "
                                f"实际回撤接近组合热度合计 {h.get('heat_pct', 0):.1%}。保留遗留仓位时按一个整体核定风险预算, "
                                "而不是每只各占 2%")})
    for x in report.get("reentry") or []:
        if x.get("state") == "TRIGGER":
            acts.append({"priority": 5, "type": "REENTRY", "ts_code": x["ts_code"], "name": x["name"],
                         "title": f"再入场信号 {x['name']}", "detail": f"{x.get('rule')} 已触发 (收盘 {x.get('close')} > {x.get('level')})"})
    led = report.get("ledger") or {}
    if led.get("import_due"):
        acts.append({"priority": 6, "type": "IMPORT", "title": "导出通达信历史成交", "detail": led.get("import_note", "")})
    if report.get("price_sync_needed"):
        acts.append({"priority": 6, "type": "SYNC", "title": f"{len(report['price_sync_needed'])} 只持仓行情缺失或滞后",
                     "detail": "已触发后台同步; 未补齐前相关结论可能过时"})
    if report.get("price_sync_history"):
        acts.append({"priority": 6, "type": "SYNC", "title": f"{len(report['price_sync_history'])} 只已清仓标的缺行情",
                     "detail": "组合净值按其卖出前的持仓计算, 缺行情的日子按 0 收益处理, 回撤读数可能偏乐观; 已触发后台同步"})
    acts.sort(key=lambda a: (a["priority"], -(a.get("value") or 0)))
    return acts


# ═══════════════════════════════════════════════════════
#  组合级回撤: 编排在 services/drawdown_service.py (此处保留旧名, 兼容调用方)
# ═══════════════════════════════════════════════════════

derisk_plan = _dds.derisk_plan
_dd_brief = _dds.brief
_drawdown_actions = _dds.actions
set_drawdown_baseline = _dds.set_baseline
clear_drawdown_baseline = _dds.clear_baseline


# ═══════════════════════════════════════════════════════
#  相关性风险: 同板块持仓不是独立风险
# ═══════════════════════════════════════════════════════

def correlation_risk(rows: list[dict], loader: Callable[[str], Any], window: int = 60) -> dict:
    """60 日收益相关矩阵 → 市值加权平均相关 与 有效独立押注数 N_eff = 1 / (wᵀρw)。"""
    try:
        from services.trailing_stop import normalize_bars
        rets, w = {}, {}
        for r in rows:
            if r.get("status") == "NO_DATA" or not r.get("market_value"):
                continue
            b = loader(r["ts_code"])
            if b is None:
                continue
            c = normalize_bars(b)["close"].pct_change().dropna().tail(window)
            if len(c) >= window // 2:
                rets[r["ts_code"]] = c
                w[r["ts_code"]] = float(r["market_value"])
        if len(rets) < 2:
            return {"n": len(rets), "avg_corr": None, "n_eff": None}
        df = pd.DataFrame(rets).dropna()
        rho = df.corr().to_numpy()
        codes = list(df.columns)
        wv = pd.Series(w)[codes].to_numpy()
        wv = wv / wv.sum()
        quad = float(wv @ rho @ wv)
        import numpy as _np
        mask = ~_np.eye(len(codes), dtype=bool)
        ww = _np.outer(wv, wv)[mask]
        avg = float((ww * rho[mask]).sum() / ww.sum())
        return {"n": len(codes), "avg_corr": round(avg, 3), "n_eff": round(1.0 / quad, 2) if quad > 0 else None,
                "window": window,
                "note": f"{len(codes)} 只持仓 ≈ {1.0 / quad:.1f} 个独立押注 (市值加权平均相关 {avg:.2f})"}
    except Exception as e:
        logger.debug("相关性风险计算失败: %s", e)
        return {"n": 0, "avg_corr": None, "n_eff": None}


def _provenance(report: Mapping[str, Any], cfg: Mapping[str, Any], ledger: Mapping[str, Any], rows: list[dict]) -> dict:
    asofs = sorted(r["as_of"] for r in rows if r.get("as_of"))
    cfg_hash = hashlib.sha1(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:10]
    return {"schema_version": SCHEMA_VERSION, "engine": ENGINE_VERSION, "config_hash": cfg_hash,
            "calibration": CALIBRATION.get("version"), "price_as_of_min": asofs[0] if asofs else None,
            "price_as_of_max": asofs[-1] if asofs else None,
            "ledger_trades": len(ledger.get("trades", [])), "positions": len(rows)}


# ═══════════════════════════════════════════════════════
#  组合热度 (Portfolio Heat) + 风险预算定仓
# ═══════════════════════════════════════════════════════

def portfolio_heat(rows: list[dict], equity: float, cfg: Mapping[str, Any]) -> dict:
    """止损线即风险: 若所有持仓同时打到止损线, 组合亏多少 (占总资产)。

    open_risk_i = 数量 × max(收盘 − 止损线, 0); 单票上限 = 风险预算 ÷ 每股风险 (仓位由止损距离决定)。
    已触发 / 遗留持仓不计入 open_risk (止损线已在现价之上), 单列为 "已越线市值"。
    """
    rk = cfg["risk"]
    budget = float(rk["per_position_pct"]) * equity if equity else 0.0
    lot = int(cfg["lot_size"])
    total = 0.0
    breached = 0.0
    for r in rows:
        r["open_risk"] = None
        if r.get("status") == "NO_DATA" or r.get("close") is None or r.get("stop") is None:
            continue
        per_share = float(r["close"]) - float(r["stop"])
        mv = float(r.get("market_value") or 0)
        if r.get("status") in ("RED", "LEGACY") or per_share <= 0:
            breached += mv
            continue
        risk = per_share * int(r["qty"])
        total += risk
        r["open_risk"] = round(risk, 2)
        r["risk_pct"] = round(risk / equity, 4) if equity else None
        if budget and r.get("sleeve") != "core":
            cap = int(budget / per_share // lot) * lot
            r["risk_qty_cap"] = cap
            if int(r["qty"]) > cap:
                r["risk_excess_qty"] = int(r["qty"]) - cap
    pct = total / equity if equity else None
    limit = float(rk["heat_limit_pct"])
    return {
        "open_risk": round(total, 2), "heat_pct": round(pct, 4) if pct is not None else None,
        "limit_pct": limit, "over_limit": bool(pct is not None and pct > limit),
        "breached_market_value": round(breached, 2),
        "breached_pct": round(breached / equity, 4) if equity else None,
        "per_position_budget": round(budget, 2),
        "note": "热度 = 所有持仓同时打到止损线时的组合回撤; 同板块高相关持仓应视为一笔风险",
    }


def reunderwrite_preview(r: Mapping[str, Any], equity: float, cfg: Mapping[str, Any]) -> dict:
    """遗留持仓的 "重新承保" 预案: 若以今日收盘为新起点保留, 新止损线与风险预算下的最大持股。

    机构做法: 对已越线的旧仓位, 不问成本, 只问 "以今天的价格我还会买这么多吗"。
    保留 ⇒ 按新止损距离重新定仓; 超出预算的部分即使保留观点也应减掉。
    """
    close, atr = float(r.get("close") or 0), float(r.get("atr") or 0)
    if not close or not atr:
        return {}
    k = float(class_params(r.get("asset_class", "theme_etf"), r.get("sleeve", "satellite"), cfg)["init_atr_mult"])
    dist = max(k * atr, float(cfg["min_r_pct"]) * close)
    new_stop = round_down(close - dist, tick_size(r["ts_code"]))
    budget = float(cfg["risk"]["per_position_pct"]) * equity
    lot = int(cfg["lot_size"])
    cap = int(budget / dist // lot) * lot if dist > 0 else 0
    qty = int(r.get("qty") or 0)
    return {"new_stop": new_stop, "stop_distance_pct": round(dist / close, 4), "risk_budget": round(budget, 2),
            "max_qty": cap, "reduce_qty": max(0, qty - cap), "keep_value": round(min(qty, cap) * close, 2)}


def reentry_watch(trades: list[Mapping[str, Any]], holdings: Mapping[str, Any], loader: Callable[[str], Any],
                  cfg: Mapping[str, Any], today: str, lookback_days: int = 180) -> list[dict]:
    """近期清仓 (台账最后一笔为卖出且当前不持有) 的标的, 按资产类别的再入场规则给信号。"""
    last: dict[str, Mapping[str, Any]] = {}
    for t in trades:
        last[t["ts_code"]] = t
    cutoff = (pd.Timestamp(today) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    out = []
    for code, t in last.items():
        if code in holdings or t.get("side") != "sell" or t.get("date", "") < cutoff:
            continue
        name = t.get("name", code)
        cls = asset_class(code, name, cfg)
        rule = class_params(cls, "satellite", cfg).get("reentry", "ma60")
        try:
            sig = reentry_signal(loader(code), rule)
        except Exception as e:
            sig = {"state": "NO_DATA", "error": str(e)}
        out.append({"ts_code": code, "name": name, "asset_class": cls, "last_sell": t["date"],
                    "last_sell_price": t.get("price"), **sig})
    order = {"TRIGGER": 0, "ABOVE": 1, "WAIT": 2, "NO_DATA": 3}
    out.sort(key=lambda x: (order.get(x.get("state"), 9), x["last_sell"]))
    return out


def averaging_down(trades: list[Mapping[str, Any]], holdings: Mapping[str, Mapping[str, Any]],
                   as_of: Optional[str] = None, threshold: float = 0.03,
                   breaches: Optional[Mapping[str, str]] = None) -> dict:
    """亏损加仓 (摊薄) 识别: 对仍持有的标的, 低于当前持仓成本 ≥3% 的追加买入。

    机构纪律: 加仓只加在赚钱的仓位上; 亏损中加仓会放大单一判断的风险, 且绕过了止损纪律。
    """
    items = []
    for t in trades:
        code = t.get("ts_code")
        if t.get("side") != "buy" or code not in holdings or (as_of and t.get("date", "") > as_of):
            continue
        cost = float(holdings[code].get("cost") or 0)
        px = float(t.get("price") or (float(t.get("amount", 0)) / max(int(t.get("qty") or 1), 1)))
        if cost and px < cost * (1 - threshold):
            items.append({"date": t["date"], "ts_code": code, "name": holdings[code].get("name", t.get("name", "")),
                          "price": px, "qty": int(t["qty"]), "amount": round(float(t.get("amount") or px * int(t["qty"])), 2),
                          "below_cost_pct": round(px / cost - 1, 4),
                          "after_breach": bool(breaches and breaches.get(code) and t["date"] >= breaches[code])})
    items.sort(key=lambda x: x["date"], reverse=True)
    ab = [i for i in items if i["after_breach"]]
    return {"count": len(items), "amount": round(sum(i["amount"] for i in items), 2),
            "after_breach_count": len(ab), "after_breach_amount": round(sum(i["amount"] for i in ab), 2),
            "codes": sorted({i["ts_code"] for i in items}), "items": items[:30]}


# ═══════════════════════════════════════════════════════
#  执行纪律 (替代 position_deviation_engine 中写死的 80 分)
# ═══════════════════════════════════════════════════════

def _update_discipline_log(log: dict, rows: list[dict], today: str) -> dict:
    """记录每次触发 (RED / 分批) 及其执行结果。键 = code|触发日|类型。"""
    log = dict(log or {})
    for r in rows:
        code = r.get("ts_code")
        if r.get("status") == "RED" and r.get("first_breach"):
            k = f"{code}|{r['first_breach']}|exit"
            e = log.setdefault(k, {"ts_code": code, "trigger": r["first_breach"], "type": "exit", "resolved": None})
            e["days_open"] = r.get("days_since_breach", 0)
        if r.get("status") == "ACTION" and r.get("pending_partial"):
            p = r["pending_partial"]
            k = f"{code}|{p['since']}|partial{p['stage']}"
            log.setdefault(k, {"ts_code": code, "trigger": p["since"], "type": f"partial{p['stage']}", "resolved": None})
    live = {(r.get("ts_code"), r.get("status")) for r in rows}
    held = {r.get("ts_code") for r in rows}
    for k, e in log.items():
        if e.get("resolved"):
            continue
        if e["type"] == "exit" and (e["ts_code"] not in held):
            e["resolved"] = today
        elif e["type"].startswith("partial") and (e["ts_code"], "ACTION") not in live:
            e["resolved"] = today
    return log


def discipline_from_rows(rows: list[dict], state: Mapping[str, Any]) -> dict:
    log = (state or {}).get("discipline_log", {}) or {}
    events = list(log.values())
    on_time = late = overridden = 0
    for e in events:
        if not e.get("resolved"):
            continue
        if e.get("override"):
            overridden += 1
            continue
        lag = len(pd.bdate_range(e["trigger"], e["resolved"])) - 1
        if lag <= 2:
            on_time += 1
        else:
            late += 1
    overdue = [r for r in rows if r.get("status") == "RED" and (r.get("days_since_breach") or 0) >= 1]
    pending_partial = [r for r in rows if r.get("status") == "ACTION"]
    denom = on_time + late + overridden + len(overdue)
    score = round(100 * on_time / denom) if denom else None
    return {
        "score": score,
        "on_time": on_time, "late": late, "overridden": overridden, "overdue": len(overdue),
        "pending_partial": len(pending_partial),
        "legacy": sum(1 for r in rows if r.get("status") == "LEGACY"),
        "note": "触发后 T+1 内卖出记为按时; 由成交台账/持仓变化自动核对" if denom else "跟踪期内尚无触发事件",
    }


def get_discipline_score() -> Optional[int]:
    """供 position_deviation_engine 使用 (读日终缓存); 无触发事件时返回 None (调用方保留原逻辑)。"""
    try:
        return (load_state().get("last_discipline") or {}).get("score")
    except Exception as e:
        logger.debug("执行纪律分不可用: %s", e)
        return None


# ═══════════════════════════════════════════════════════
#  人工决策 (留痕)
# ═══════════════════════════════════════════════════════

def set_sleeve(ts_code: str, sleeve: str, reason: str = "") -> dict:
    if sleeve not in ("core", "satellite"):
        raise ValueError("sleeve 只能是 core 或 satellite")
    with _LOCK:
        st = load_state()
        st["positions"].setdefault(ts_code, {})["sleeve"] = sleeve
        _audit(st, ts_code, "set_sleeve", f"{sleeve} {reason}".strip())
        save_state(st)
    return st["positions"][ts_code]


def rebaseline(ts_code: str, reason: str, *, bars_loader: Optional[Callable[[str], Any]] = None) -> dict:
    """遗留持仓重新基准化: 以最新收盘为新起点重新计算 R 与止损线 (必须填写理由)。"""
    if not reason or len(reason.strip()) < 4:
        raise ValueError("重新基准化必须填写理由 (≥4 字), 将写入审计日志")
    bars = (bars_loader or default_bars_loader)(ts_code)
    if bars is None or len(bars) == 0:
        raise ValueError("缺少行情, 无法确定基准价")
    from services.trailing_stop import normalize_bars
    b = normalize_bars(bars)
    date, price = b.index[-1].strftime("%Y-%m-%d"), float(b["close"].iloc[-1])
    with _LOCK:
        st = load_state()
        st["positions"].setdefault(ts_code, {})["rebaseline"] = {
            "date": date, "price": price, "reason": reason.strip(),
            "at": datetime.now().isoformat(timespec="seconds")}
        st["positions"][ts_code].pop("acked_stages", None)
        for e in (st.get("discipline_log") or {}).values():
            if e.get("ts_code") == ts_code and not e.get("resolved"):
                e["resolved"], e["override"] = date, reason.strip()
        _audit(st, ts_code, "rebaseline", f"{date} @ {price}: {reason.strip()}")
        save_state(st)
    return st["positions"][ts_code]


def set_anchor(ts_code: str, date: str, reason: str) -> dict:
    """人工设定建仓日 (通达信只能导出近 60 天成交时使用); 必须写理由, 入审计。"""
    try:
        d = pd.Timestamp(date).strftime("%Y-%m-%d")
    except Exception:
        raise ValueError("日期格式应为 YYYY-MM-DD")
    if d > datetime.now().strftime("%Y-%m-%d"):
        raise ValueError("建仓日不能晚于今天")
    if not reason or len(reason.strip()) < 2:
        raise ValueError("请填写依据 (如: 券商对账单 2026-06-12 首次买入)")
    with _LOCK:
        st = load_state()
        ps = st["positions"].setdefault(ts_code, {})
        ps["manual_anchor"] = {"date": d, "reason": reason.strip(), "at": datetime.now().isoformat(timespec="seconds")}
        ps.pop("published", None)          # 锚点变更 → 旧止损线下限失效
        _audit(st, ts_code, "set_anchor", f"{d}: {reason.strip()}")
        save_state(st)
    return ps


def clear_anchor(ts_code: str) -> dict:
    with _LOCK:
        st = load_state()
        ps = st["positions"].setdefault(ts_code, {})
        ps.pop("manual_anchor", None)
        ps.pop("published", None)
        _audit(st, ts_code, "clear_anchor", "恢复自动锚点")
        save_state(st)
    return ps


def ack_stage(ts_code: str, stage: int, note: str = "") -> dict:
    """台账未覆盖的减仓 (如其他账户) 手动确认已执行。"""
    with _LOCK:
        st = load_state()
        ps = st["positions"].setdefault(ts_code, {})
        acked = set(ps.get("acked_stages", []))
        acked.add(int(stage))
        ps["acked_stages"] = sorted(acked)
        _audit(st, ts_code, "ack_stage", f"S{stage} 已执行 {note}".strip())
        save_state(st)
    return ps


# ═══════════════════════════════════════════════════════
#  回合复盘
# ═══════════════════════════════════════════════════════

def build_review(*, ledger: Optional[Mapping[str, Any]] = None, store: Optional[Mapping[str, Any]] = None,
                 bars_loader: Optional[Callable[[str], Any]] = None, regime: str = "RANGE",
                 cfg: Optional[Mapping[str, Any]] = None) -> dict:
    ledger = ledger if ledger is not None else load_ledger()
    store = store if store is not None else _read_json(STORE_PATH, {}) or {}
    loader = bars_loader or default_bars_loader
    cfg = cfg or load_config()
    held = [k for k, v in (store.get("positions") or {}).items() if float(v.get("amount", 0) or 0) > 0]
    trips = closed_round_trips(ledger.get("trades", []), held_codes=held)
    out = []
    for t in trips:
        try:
            out.append(review_round_trip(t, loader(t["ts_code"]), regime=regime, cfg=cfg))
        except Exception as e:
            out.append({**t, "review": f"error: {e}"})
    ok = [x for x in out if x.get("review") == "ok"]
    gb = [x["giveback"] for x in ok if x.get("giveback") is not None]
    diff = [x["rule_minus_actual"] for x in ok if x.get("rule_minus_actual") is not None]
    wins = [x for x in out if (x.get("pnl") or 0) > 0]
    return {
        "trips": out,
        "summary": {
            "count": len(out),
            "win_rate": round(len(wins) / len(out), 3) if out else None,
            "realized_pnl": round(sum(x.get("pnl") or 0 for x in out), 2),
            "avg_giveback": round(sum(gb) / len(gb), 3) if gb else None,
            "avg_rule_minus_actual": round(sum(diff) / len(diff), 4) if diff else None,
            "rule_better": sum(1 for d in diff if d > 0),
            "rule_worse": sum(1 for d in diff if d < 0),
        },
    }


# ═══════════════════════════════════════════════════════
#  预警 (每日收盘后)
# ═══════════════════════════════════════════════════════

_SEVERITY = {"RED": ("critical", "🛑"), "ACTION": ("warning", "💰"), "YELLOW": ("info", "⚠️"),
             "LEGACY": ("warning", "📌")}


def scan_and_alert(report: Optional[dict] = None, *, push: bool = True) -> list[dict]:
    """同一标的同一状态同一触发日只推送一次。"""
    report = report or build_report()
    with _LOCK:
        st = load_state()
        sent = st.setdefault("alerts", {})
        fired = []
        for r in report.get("positions", []):
            status = r.get("status")
            if status not in _SEVERITY:
                continue
            marker = r.get("first_breach") or (r.get("pending_partial") or {}).get("since") or r.get("as_of")
            key = f"{status}|{marker}"
            if sent.get(r["ts_code"]) == key:
                continue
            sev, icon = _SEVERITY[status]
            title = f"跟踪止盈 · {r['name']} {status}"
            detail = f"{r['ts_code']} 收盘 {r.get('close')} · {r.get('action')}"
            fired.append({"rule_id": f"trailing_{status.lower()}", "severity": sev, "icon": icon,
                          "title": title, "detail": detail, "value": r.get("close") or 0})
            sent[r["ts_code"]] = key
        dd_alert = _dds.alert(report.get("drawdown"), sent)
        if dd_alert:
            fired.append(dd_alert)
        if fired:
            save_state(st)
    if not fired:
        return []
    try:
        from services import db as ac_db
        for a in fired:
            ac_db.save_alert(rule_id=a["rule_id"], severity=a["severity"],
                             title=f'{a["icon"]} {a["title"]}', detail=a["detail"], value=a["value"])
    except Exception as e:
        logger.warning("跟踪止盈预警落库失败: %s", e)
    if push:
        try:
            from services.alert_monitor import _push_all_channels
            threading.Thread(target=_push_all_channels, args=(fired,), daemon=True).start()
        except Exception as e:
            logger.warning("跟踪止盈预警推送失败: %s", e)
    return fired


def daily_job() -> dict:
    """收盘后定时任务: 扫描导入文件夹 → 同步持仓行情 → 计算并日终提交 → 推送。"""
    store = _read_json(STORE_PATH, {}) or {}
    codes = [k for k, v in (store.get("positions") or {}).items() if float(v.get("amount", 0) or 0) > 0]
    try:
        from services.trade_import import scan_import_folder
        scanned = scan_import_folder()
    except Exception as e:
        scanned = {"error": str(e)}
    sync = sync_prices(codes) if codes else {}
    try:
        led_codes = sorted({t["ts_code"] for t in load_ledger().get("trades", [])} - set(codes))
        if led_codes:
            sync_prices(led_codes)            # 已清仓标的: 组合净值回溯需要其行情
    except Exception as e:
        logger.warning("历史标的行情同步失败: %s", e)
    report = build_report(store=store, persist=True)        # 日终: 计算 + 提交 (唯一写入方)
    fired = scan_and_alert(report)
    try:
        from services.cache_service import cache_manager
        cache_manager.set_json("trailing_stop_report_full", report, ttl_seconds=6 * 3600)
    except Exception:
        pass
    logger.info("跟踪止盈日终: %s · 预警 %d 条 · 同步失败 %s", report.get("summary"), len(fired),
                (sync or {}).get("failed"))
    return {"summary": report.get("summary"), "alerts": len(fired), "sync": sync, "imports": scanned}
