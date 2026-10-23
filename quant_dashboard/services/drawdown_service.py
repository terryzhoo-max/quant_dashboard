"""
AlphaCore · 组合回撤 (MDD) 编排层
=================================

职责划分 (生产架构):
  services/drawdown.py           纯计算: 净值重建 · 回撤读数 · 前瞻 · 分档状态机 (无 I/O, 可单测)
  services/drawdown_service.py   编排: 策略参数解析 · 时点一致性 (发布/重述) · 刹车执行进度 ·
                                 降仓清单 · 行动项 · 预警 · 基准重设 (本文件)
  services/trailing_stop_service 日终唯一写入方: 在 commit_eod 中调用 publish() 落盘, 写合规缓存

时点一致性: 每个收盘日发布的档位写入 state.drawdown.published (不可变日志)。之后若导入更早的台账、
补齐行情, 重放得到的历史档位可能改变 —— 不静默改写, 而是在报告中披露 "重述" (原发布 vs 重算)。
"""
from __future__ import annotations

import copy
import math
from datetime import datetime
from typing import Any, Callable, Mapping, Optional

import pandas as pd

from services import drawdown as ddmod
from services.logger import get_logger

logger = get_logger("alphacore.drawdown")

PUBLISH_KEEP = 400
STALE_DAYS = 3          # 合规层: 刹车数据超过 3 个交易日未更新 → 视为过期


def resolve_policy(cfg: Optional[Mapping[str, Any]]) -> dict:
    pol = copy.deepcopy(ddmod.DEFAULT_POLICY)
    for k, v in ((cfg or {}).get("drawdown") or {}).items():
        if not str(k).startswith("_"):
            pol[k] = v
    return pol


def marked_equity(store: Mapping[str, Any], invested_value: float) -> tuple[float, Optional[float], str]:
    """同一时点的总资产 = 最新收盘持仓市值 + 现金。券商快照的总资产是快照日的, 与最新收盘市值相加会错配。"""
    if store.get("cash") is not None:
        cash = float(store.get("cash") or 0)
        return invested_value + cash, cash, "marked"
    bta = float(store.get("broker_total_asset") or 0)
    bmv = sum(float(p.get("broker_market_value") or 0) for p in (store.get("positions") or {}).values())
    if bta and bmv:
        cash = bta - bmv
        return invested_value + cash, cash, "marked"
    if bta:
        return bta, None, "broker_snapshot"
    return invested_value, 0.0, "holdings_only"


# ═══════════════════════════════════════════════════════
#  组装
# ═══════════════════════════════════════════════════════

def section(*, holdings: Mapping[str, Any], trades: list[Mapping[str, Any]], loader: Callable[[str], Any],
            store: Mapping[str, Any], state: Mapping[str, Any], cfg: Mapping[str, Any],
            equity: float, invested_value: float, rows: Optional[list[dict]] = None) -> dict:
    pol = resolve_policy(cfg)
    dstate = state.get("drawdown") or {}
    try:
        out = ddmod.monitor({k: float(v.get("amount") or 0) for k, v in holdings.items()}, list(trades), loader,
                            snapshot_date=store.get("import_date"), equity=equity, invested_value=invested_value,
                            baseline=dstate.get("baseline"), policy=pol)
    except Exception as e:                                   # 风控模块失败不能拖垮整页, 但必须显式暴露
        logger.warning("组合回撤计算失败: %s", e)
        return {"status": "error", "error": str(e), "missing_prices": []}
    nav = out.pop("_nav", None)
    out["budget"] = {"max_dd": pol["tiers"][-1]["dd"], "note": "回撤预算 = 末档触发线; 预算内的仓位上限由前瞻模拟反算"}
    b = out.get("brake") or {}
    if b:
        pub = dstate.get("published") or {}
        b["progress"] = execution_progress(b, trades, min(pub) if pub else None)
        if b.get("reduce_value") and rows:
            b["plan"] = derisk_plan(rows, float(b["reduce_value"]), equity, invested_value, int(cfg.get("lot_size", 100)))
        out["restatement"] = restatement(nav, dstate.get("published") or {}, pol)
    return out


def brief(d: Optional[Mapping[str, Any]]) -> Optional[dict]:
    b = (d or {}).get("brake")
    if not b:
        return None
    return {k: b.get(k) for k in ("tier", "cap_pct", "no_add", "dd", "label", "basis", "invested_pct", "reduce_value")}


# ═══════════════════════════════════════════════════════
#  时点一致性: 发布日志 / 重述披露
# ═══════════════════════════════════════════════════════

def publish(state: dict, d: Optional[Mapping[str, Any]], as_of: str) -> None:
    """日终提交时调用 (调用方持锁)。同一 as_of 重复提交覆盖, 幂等。"""
    b = (d or {}).get("brake")
    if not b:
        return
    log = state.setdefault("drawdown", {}).setdefault("published", {})
    log[as_of] = {"tier": b.get("tier"), "dd": b.get("dd"), "cap_pct": b.get("cap_pct"),
                  "basis": b.get("basis"), "at": datetime.now().isoformat(timespec="seconds")}
    for k in sorted(log)[:-PUBLISH_KEEP]:
        log.pop(k, None)


def restatement(nav: Optional[pd.Series], published: Mapping[str, Any], pol: Mapping[str, Any]) -> list[dict]:
    """把最近 10 个已发布交易日的档位与 "按当前数据重放" 的结果对比; 不一致即披露。"""
    if nav is None or not len(published):
        return []
    out = []
    days = [d for d in sorted(published)[-10:] if pd.Timestamp(d) in nav.index]
    for d in days:
        p = published[d]
        if p.get("basis") == "baseline":
            continue
        re = ddmod.replay_tiers(nav[nav.index <= pd.Timestamp(d)], pol)
        if re["tier"] != p.get("tier"):
            out.append({"date": d, "published_tier": p.get("tier"), "restated_tier": re["tier"],
                        "published_dd": p.get("dd"),
                        "restated_dd": round(float(nav[:d].iloc[-1] / nav[:d].max() - 1), 4)})
    return out


# ═══════════════════════════════════════════════════════
#  刹车执行进度: 触发后实际卖了多少 / 有没有违规买入
# ═══════════════════════════════════════════════════════

def execution_progress(b: Mapping[str, Any], trades: list[Mapping[str, Any]],
                       live_since: Optional[str] = None) -> Optional[dict]:
    """live_since: 刹车首次发布日 (系统启用日)。之前的买入是回放出来的 "若当时已启用" 情形, 不算违规。"""
    if not b.get("tier"):
        return None
    start = None                     # 本轮刹车起点: 最近一次回到 0 档之后的第一次下探
    for e in reversed(b.get("events") or []):
        if e.get("to") == 0:
            break
        if e.get("dir") == "down":
            start = e["date"]
    if not start:
        return None
    after = [t for t in trades if t.get("date", "") > start]       # 收盘判定, 次日起执行
    amt = lambda t: float(t.get("amount") or (float(t.get("price") or 0) * float(t.get("qty") or 0)))
    sold = sum(amt(t) for t in after if t.get("side") == "sell")
    buys = [t for t in after if t.get("side") == "buy"]
    bought = sum(amt(t) for t in buys)
    remaining = float(b.get("reduce_value") or 0)
    executed = max(0.0, sold - bought)
    need = executed + remaining
    live = [t for t in buys if live_since and t["date"] > live_since]
    row = lambda t: {"date": t["date"], "ts_code": t.get("ts_code"), "name": t.get("name"),
                     "qty": t.get("qty"), "amount": round(amt(t), 2)}
    return {
        "since": start, "sold": round(sold, 2), "bought": round(bought, 2), "executed": round(executed, 2),
        "remaining": round(remaining, 2), "pct": round(executed / need, 3) if need > 0 else 1.0,
        "live_since": live_since,
        "violations": [row(t) for t in live][-10:], "violation_count": len(live),
        "violation_amount": round(sum(amt(t) for t in live), 2),
        "pre_live_buys": len(buys) - len(live), "pre_live_amount": round(bought - sum(amt(t) for t in live), 2),
        "note": "按台账成交统计 (收盘判定日之后); 系统启用前的买入为回放, 不计违规",
    }


# ═══════════════════════════════════════════════════════
#  降仓清单
# ═══════════════════════════════════════════════════════

def _sell_lot(code: str, lot: int) -> tuple[int, int]:
    """(最小申报量, 递增单位): 科创板 ≥200 股、1 股递增; 其余 100 股整手。"""
    return (200, 1) if code.startswith(("688", "689")) else (lot, lot)


def _round_sell(code: str, want: float, avail: int, lot: int, up: bool = False) -> int:
    mn, step = _sell_lot(code, lot)
    if want <= 0:
        return 0
    q = (math.ceil if up else math.floor)(want / step) * step
    if q < mn:
        q = mn if up else 0                     # 向下取整不足最小申报 → 不卖; 向上 → 补到最小申报
    if q <= 0:
        return 0
    if q >= avail or avail - q < mn:            # 余量不足一笔最小申报 → 一并卖出, 不留零股
        return avail
    return int(q)


def derisk_plan(rows: list[dict], reduce_value: float, equity: float, invested_value: float, lot: int = 100) -> dict:
    """回撤刹车降仓清单 —— 规则已判定的先卖, 健康仓位最后按市值等比:
    ① 已触发止损 (RED) 全部 → ② 跟踪前已越线 (LEGACY), 越线越深越先 → ③ 超单票风险预算的部分 → ④ 其余等比。
    数量遵守交易规则: 主板/创业板/ETF 100 股整手; 科创板 ≥200 股、1 股递增; 不留不足一手的零股。"""
    left = reduce_value
    used: dict[str, int] = {}
    lines: dict[str, dict] = {}
    live = [r for r in rows if r.get("close") and r.get("qty") and r.get("status") != "NO_DATA"]
    avail = lambda r: int(r["qty"]) - used.get(r["ts_code"], 0)

    def add(r: Mapping[str, Any], q: int, step: int, reason: str) -> None:
        nonlocal left
        q = min(q, avail(r))
        if q <= 0:
            return
        code, px = r["ts_code"], float(r["close"])
        used[code] = used.get(code, 0) + q
        left -= q * px
        ln = lines.setdefault(code, {"step": step, "ts_code": code, "name": r.get("name"), "qty": 0, "price": px,
                                     "value": 0.0, "status": r.get("status"), "reasons": []})
        ln["qty"] += q
        ln["value"] = round(ln["qty"] * px, 2)
        ln["remaining_qty"] = int(r["qty"]) - ln["qty"]
        if reason not in ln["reasons"]:
            ln["reasons"].append(reason)

    def sell_upto(r: Mapping[str, Any], q_max: int, step: int, reason: str) -> None:
        if left <= 0:
            return
        need = _round_sell(r["ts_code"], left / float(r["close"]), avail(r), lot, up=True)
        add(r, min(q_max, need), step, reason)

    for r in sorted((r for r in live if r.get("status") == "RED"), key=lambda r: -(r.get("market_value") or 0)):
        add(r, avail(r), 1, "已触发止损, 规则本就要求卖出")       # RED 无论刹车与否都要卖
    depth = lambda r: (float(r["close"]) / float(r["breach_stop"]) - 1) if r.get("breach_stop") else 0.0
    for r in sorted((r for r in live if r.get("status") == "LEGACY"), key=depth):
        sell_upto(r, avail(r), 2, f"跟踪前已越线 (低于止损线 {abs(depth(r)):.0%})")
    for r in live:
        if r.get("risk_excess_qty") and r.get("status") not in ("RED", "LEGACY") and left > 0:
            q = _round_sell(r["ts_code"], float(r["risk_excess_qty"]), avail(r), lot, up=True)
            add(r, q, 3, "超出单票风险预算")
    rest = [r for r in live if r.get("status") not in ("RED", "LEGACY") and avail(r) > 0]
    rest_mv = sum(avail(r) * float(r["close"]) for r in rest)
    if left > 0 and rest_mv > 0:
        f = min(1.0, left / rest_mv)
        reason = f"其余持仓等比减 {f:.0%} (保持结构)"
        for r in rest:                                        # 先向下取整, 再按缺口从大到小补足
            add(r, _round_sell(r["ts_code"], avail(r) * f, avail(r), lot), 4, reason)
        for r in sorted(rest, key=lambda r: -avail(r) * float(r["close"])):   # 缺口: 每只最多再补一笔最小单位
            if left <= 0:
                break
            mn, stp = _sell_lot(r["ts_code"], lot)
            unit = stp if used.get(r["ts_code"]) else mn
            want = min(left / float(r["close"]), unit)
            add(r, _round_sell(r["ts_code"], max(want, unit), avail(r), lot, up=True), 4, reason)
    items = sorted(lines.values(), key=lambda x: (x["step"], -x["value"]))
    for i in items:
        i["reason"] = " · ".join(i.pop("reasons"))
    total = round(sum(i["value"] for i in items), 2)
    return {
        "items": items, "total": total, "target": round(reduce_value, 2),
        "after_invested_pct": round((invested_value - total) / equity * 100, 1) if equity else None,
        "note": ("收盘价估算; 下一交易日开盘起执行, 开盘跌停的顺延, 金额大可分 1–3 个交易日; "
                 "跌破止损的先卖, 不按比例砍健康仓位"),
    }


# ═══════════════════════════════════════════════════════
#  行动项 / 预警
# ═══════════════════════════════════════════════════════

def actions(d: Mapping[str, Any]) -> list[dict]:
    b = d.get("brake") or {}
    acts: list[dict] = []
    if b.get("tier"):
        ev = (b.get("events") or [{}])[-1]
        detail = (f"剔除资金进出的组合净值自高点回撤 {abs(b['dd']):.1%} ({ev.get('date')} 触发), "
                  f"仓位上限 {b['cap_pct']}%, 当前 {b.get('invested_pct')}%。")
        if b.get("reduce_value"):
            pl = b.get("plan") or {}
            detail += (f" 需降仓约 ¥{b['reduce_value']:,.0f}: 降仓清单 {len(pl.get('items') or [])} 笔, "
                       f"执行后仓位约 {pl.get('after_invested_pct')}% (先卖已越线的, 不按比例砍健康仓位)。")
        pg = b.get("progress") or {}
        if pg.get("violation_count"):
            detail += f" ⚠ 刹车生效后仍有 {pg['violation_count']} 笔买入 (¥{pg['violation_amount']:,.0f})。"
        elif pg.get("pre_live_buys"):
            detail += (f" 回放: 若刹车在 {pg['since']} 已启用, 其后 {pg['pre_live_buys']} 笔加仓 "
                       f"(¥{pg['pre_live_amount']:,.0f}) 本会被拦截。")
        detail += f" 禁止新增买入; 回撤收窄到 {abs(b.get('rerisk_at_dd') or 0):.1%} 以内恢复一档。"
        if b.get("basis") != "baseline":
            detail += " 若对当前仓位另有承保理由, 可「重设回撤基准」(留痕), 但这等于放弃本次刹车。"
        acts.append({"priority": 1 if b.get("reduce_value") else 2, "type": "DRAWDOWN",
                     "value": b.get("reduce_value") or 0,
                     "title": f"组合回撤刹车 · {b.get('label')}" + (f" · 降仓 ¥{b['reduce_value']:,.0f}" if b.get("reduce_value") else ""),
                     "detail": detail})
    for r in d.get("restatement") or []:
        acts.append({"priority": 5, "type": "RESTATE",
                     "title": f"回撤档位重述: {r['date']} 已发布 {r['published_tier']} 档 → 重算 {r['restated_tier']} 档",
                     "detail": "台账或行情更新改变了历史净值; 已发布结论保留在审计日志中, 当前刹车按重算结果执行"})
    fc = d.get("forecast") or {}
    mx = fc.get("max_exposure_for_budget")
    inv = b.get("invested_pct")
    if mx is not None and inv is not None and inv / 100 > mx + 0.05 and not b.get("tier"):
        acts.append({"priority": 4, "type": "DD_BUDGET",
                     "title": f"回撤预算: 当前结构下仓位宜 ≤ {mx:.0%}",
                     "detail": (f"按近一年波动 {fc.get('ann_vol', 0):.0%} 模拟, 满仓一年内 95% 情形最大回撤 "
                                f"{fc.get('mdd_p95', 0):.0%}; 回撤预算 {fc.get('budget_dd', 0):.0%} 对应仓位上限 {mx:.0%}")})
    return acts


def alert(d: Optional[Mapping[str, Any]], sent: dict) -> Optional[dict]:
    """档位变化 (含首次进入) 推送一次; sent 为状态里的已推送标记 (调用方持锁并保存)。"""
    b = (d or {}).get("brake") or {}
    if not b:
        return None
    key = f"{b.get('tier')}|{(b.get('events') or [{}])[-1].get('date')}"
    prev = sent.get("__drawdown__")
    if prev == key or not (b.get("tier") or prev):
        return None
    sent["__drawdown__"] = key
    up = b.get("tier", 0) > int(str(prev or "0").split("|")[0] or 0)
    return {"rule_id": "drawdown_brake", "severity": "critical" if b.get("tier", 0) >= 2 else "warning",
            "icon": "🧯" if up else "🔓",
            "title": f"组合回撤 {abs(b.get('dd') or 0):.1%} · {b.get('label')}",
            "detail": (f"仓位上限 {b.get('cap_pct')}% (当前 {b.get('invested_pct')}%)"
                       + (f", 需降仓约 ¥{b['reduce_value']:,.0f}" if b.get("reduce_value") else "")),
            "value": b.get("dd") or 0}


# ═══════════════════════════════════════════════════════
#  基准重设 (人工推翻, 留痕)
# ═══════════════════════════════════════════════════════

def set_baseline(date: str, reason: str) -> dict:
    from services import trailing_stop_service as ts
    if not reason or len(reason.strip()) < 4:
        raise ValueError("重设回撤基准必须写明理由 (≥4 字)")
    datetime.strptime(date, "%Y-%m-%d")
    with ts._LOCK:
        st = ts.load_state()
        st.setdefault("drawdown", {})["baseline"] = {"date": date, "reason": reason.strip(),
                                                      "at": datetime.now().isoformat(timespec="seconds")}
        ts._audit(st, "*", "drawdown_baseline", f"回撤基准重设为 {date}: {reason.strip()}")
        ts.save_state(st)
    return st["drawdown"]["baseline"]


def clear_baseline() -> dict:
    from services import trailing_stop_service as ts
    with ts._LOCK:
        st = ts.load_state()
        old = (st.get("drawdown") or {}).pop("baseline", None)
        if old:
            ts._audit(st, "*", "drawdown_baseline_clear", f"撤销回撤基准 {old.get('date')}, 恢复按实盘高水位计算")
            ts.save_state(st)
    return {"cleared": bool(old)}


def is_stale(brief_: Optional[Mapping[str, Any]], today: Optional[str] = None) -> Optional[int]:
    """合规层用: 刹车数据距今的交易日数 (超过 STALE_DAYS 视为过期)。"""
    if not brief_ or not brief_.get("as_of"):
        return None
    today = today or datetime.now().strftime("%Y-%m-%d")
    return max(0, len(pd.bdate_range(brief_["as_of"], today)) - 1)
