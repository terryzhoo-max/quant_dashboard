"""跟踪止盈闭环: 持仓 × 台账 × 行情 → 报告 / 条件单 / 纪律 / 人工决策留痕 / 预警去重"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import trailing_stop_service as svc  # noqa: E402


def _bars(closes, start="2026-06-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"trade_date": idx.strftime("%Y%m%d"), "open": c.values, "high": (c * 1.01).values,
                         "low": (c * 0.99).values, "close": c.values})


UP_DOWN = [10.0] * 40 + list(np.linspace(10, 14, 40)) + list(np.linspace(14, 12, 15))
UP = [10.0] * 40 + list(np.linspace(10, 11.6, 20))
DOWN = [10.0] * 40 + list(np.linspace(10, 7, 20))
BARS = {"588000.SH": _bars(UP_DOWN), "159995.SZ": _bars(UP), "300476.SZ": _bars(DOWN)}


def _iso(series_len, i):
    return pd.bdate_range("2026-06-01", periods=series_len)[i].strftime("%Y-%m-%d")


def _fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(svc, "SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    store = {"import_date": "2026-10-22", "positions": {
        "588000.SH": {"name": "科创50ETF", "amount": 30000, "cost": 10.0},
        "159995.SZ": {"name": "芯片ETF", "amount": 30000, "cost": 10.0},
        "300476.SZ": {"name": "胜宏科技", "amount": 600, "cost": 10.0},
        "999999.SZ": {"name": "无行情", "amount": 100, "cost": 1.0},
    }}
    ledger = {"trades": [
        {"date": _iso(95, 40), "time": "10:00:00", "ts_code": "588000.SH", "side": "buy", "qty": 30000, "amount": 300000, "key": "a"},
        {"date": _iso(60, 40), "time": "10:00:00", "ts_code": "159995.SZ", "side": "buy", "qty": 30000, "amount": 300000, "key": "b"},
        {"date": _iso(60, 40), "time": "10:00:00", "ts_code": "300476.SZ", "side": "buy", "qty": 600, "amount": 6000, "key": "c"},
    ], "imports": []}
    return store, ledger


def _report(store, ledger, state=None, today="2026-10-22"):
    return svc.build_report(store=store, ledger=ledger, state=state if state is not None else svc.load_state(),
                            bars_loader=lambda c: BARS.get(c), regime="BULL", aiae_regime=3, today=today,
                            persist=False)


def test_report_statuses_orders_and_anchor(tmp_path, monkeypatch):
    store, ledger = _fixture(tmp_path, monkeypatch)
    rep = _report(store, ledger, state={"positions": {}, "audit": [], "tracking_since": "2026-06-01"})
    by = {r["ts_code"]: r for r in rep["positions"]}
    assert by["588000.SH"]["status"] == "RED"
    assert by["588000.SH"]["anchor_quality"] == "exact"
    assert by["159995.SZ"]["status"] == "ACTION" and by["159995.SZ"]["sell_qty"] == 10000
    assert by["300476.SZ"]["status"] == "RED"            # 跟踪期内跌破个股硬止损
    assert by["999999.SZ"]["status"] == "NO_DATA"
    assert [r["status"] for r in rep["positions"]][:2] == ["RED", "RED"]   # 风险优先排序
    types = {(o["ts_code"], o["type"]) for o in rep["orders"]}
    assert ("588000.SH", "次日开盘卖出") in types
    assert ("159995.SZ", "股价≤ 兜底价 全部卖出") in types
    assert rep["discipline"]["overdue"] == 2


def test_first_run_marks_pre_existing_breaches_as_legacy(tmp_path, monkeypatch):
    store, ledger = _fixture(tmp_path, monkeypatch)
    rep = _report(store, ledger, state={"positions": {}, "audit": []})
    by = {r["ts_code"]: r for r in rep["positions"]}
    assert by["300476.SZ"]["status"] == "LEGACY" and by["588000.SH"]["status"] == "LEGACY"
    assert not any(o["ts_code"] == "300476.SZ" for o in rep["orders"])


def test_rebaseline_requires_reason_and_is_audited(tmp_path, monkeypatch):
    store, ledger = _fixture(tmp_path, monkeypatch)
    try:
        svc.rebaseline("300476.SZ", "", bars_loader=lambda c: BARS[c])
        raise AssertionError("should require reason")
    except ValueError:
        pass
    svc.rebaseline("300476.SZ", "AI 算力 PCB 订单景气未变, 保留观察仓", bars_loader=lambda c: BARS[c])
    st = svc.load_state()
    assert st["positions"]["300476.SZ"]["rebaseline"]["price"] == 7.0
    assert st["audit"][-1]["action"] == "rebaseline"
    rep = _report(store, ledger, state=st)
    r = {x["ts_code"]: x for x in rep["positions"]}["300476.SZ"]
    assert r["anchor_quality"] == "rebaselined" and r["status"] in ("GREEN", "YELLOW")


def test_sell_in_ledger_clears_partial_and_discipline_on_time(tmp_path, monkeypatch):
    store, ledger = _fixture(tmp_path, monkeypatch)
    svc.save_state({"positions": {}, "audit": [], "tracking_since": "2026-06-01"})
    rep = _report(store, ledger, state=svc.load_state())
    svc.commit_eod(rep, regime="BULL", today=rep["as_of"])          # 日终提交: 记录分批止盈触发
    s2 = {r["ts_code"]: r for r in rep["positions"]}["159995.SZ"]["pending_partial"]["since"]
    ledger["trades"].append({"date": s2, "time": "14:00:00", "ts_code": "159995.SZ", "side": "sell",
                             "qty": 10000, "amount": 110000, "key": "d"})
    store["positions"]["159995.SZ"]["amount"] = 20000
    rep2 = _report(store, ledger, state=svc.load_state(), today=s2)
    r = {x["ts_code"]: x for x in rep2["positions"]}["159995.SZ"]
    assert r["status"] != "ACTION" or r["pending_partial"]["stage"] == 3
    assert rep2["discipline"]["on_time"] >= 1


def test_sleeve_and_alert_dedupe(tmp_path, monkeypatch):
    store, ledger = _fixture(tmp_path, monkeypatch)
    svc.set_sleeve("588000.SH", "core", "长期底仓")
    assert svc.load_state()["positions"]["588000.SH"]["sleeve"] == "core"
    rep = _report(store, ledger, state={"positions": {}, "audit": [], "tracking_since": "2026-06-01"})
    saved = []
    import types
    import services
    stub = types.SimpleNamespace(save_alert=lambda **kw: saved.append(kw))
    monkeypatch.setitem(sys.modules, "services.db", stub)
    monkeypatch.setattr(services, "db", stub, raising=False)
    first = svc.scan_and_alert(rep, push=False)
    second = svc.scan_and_alert(rep, push=False)
    assert len(first) >= 2 and second == [] and len(saved) == len(first)


def test_review_from_ledger(tmp_path, monkeypatch):
    ledger = {"trades": [
        {"date": _iso(95, 40), "ts_code": "588000.SH", "name": "科创50ETF", "side": "buy", "qty": 1000, "amount": 10000.0, "key": "x"},
        {"date": _iso(95, 94), "ts_code": "588000.SH", "name": "科创50ETF", "side": "sell", "qty": 1000, "amount": 12000.0, "key": "y"},
    ]}
    rev = svc.build_review(ledger=ledger, store={"positions": {}}, bars_loader=lambda c: BARS.get(c), regime="BULL")
    t = rev["trips"][0]
    assert t["review"] == "ok" and t["giveback"] == 0.5 and t["rule_minus_actual"] > 0
    assert rev["summary"]["rule_better"] == 1


def test_heat_budget_and_reunderwrite(tmp_path, monkeypatch):
    store, ledger = _fixture(tmp_path, monkeypatch)
    store["broker_total_asset"] = 1_000_000
    rep = _report(store, ledger, state={"positions": {}, "audit": []})          # 首次运行 → 越线即 LEGACY
    by = {r["ts_code"]: r for r in rep["positions"]}
    h = rep["heat"]
    assert h["per_position_budget"] == 20000 and h["breached_pct"] > 0
    ru = by["300476.SZ"]["reunderwrite"]                                       # 个股: 5×ATR 新止损
    assert ru["new_stop"] < by["300476.SZ"]["close"] and ru["max_qty"] % 100 == 0
    act = by["159995.SZ"]                                                       # 盈利仓位: 有开放风险
    assert act["open_risk"] > 0 and act["risk_pct"] == round(act["open_risk"] / 1_000_000, 4)


def test_averaging_down_flags_adds_after_breach(tmp_path, monkeypatch):
    store, ledger = _fixture(tmp_path, monkeypatch)
    ledger["trades"].append({"date": _iso(60, 55), "ts_code": "300476.SZ", "side": "buy", "qty": 100,
                             "price": 8.0, "amount": 800.0, "key": "z"})
    rep = _report(store, ledger, state={"positions": {}, "audit": [], "tracking_since": "2026-06-01"})
    ad = rep["averaging_down"]
    assert ad["count"] == 1 and ad["items"][0]["below_cost_pct"] == -0.2
    assert ad["after_breach_count"] == 1                                       # 跌破止损后仍加仓


def test_reentry_watch_signals(tmp_path, monkeypatch):
    store, ledger = _fixture(tmp_path, monkeypatch)
    BARS["512480.SH"] = _bars([10.0] * 60 + list(np.linspace(10, 12, 20)))      # 创 20 日新高
    ledger["trades"] += [
        {"date": _iso(80, 30), "ts_code": "512480.SH", "name": "半导体ETF", "side": "buy", "qty": 1000, "amount": 10000, "key": "r1"},
        {"date": _iso(80, 50), "ts_code": "512480.SH", "name": "半导体ETF", "side": "sell", "qty": 1000, "amount": 9500, "key": "r2"},
    ]
    try:
        rep = _report(store, ledger, state={"positions": {}, "audit": []})
    finally:
        BARS.pop("512480.SH")
    re_ = {x["ts_code"]: x for x in rep["reentry"]}
    assert re_["512480.SH"]["state"] == "TRIGGER" and re_["512480.SH"]["rule"] == "20 日新高"


def test_infer_anchor_from_cost_and_priority():
    bars = BARS["588000.SH"]                      # 10 → 14 → 12
    d = svc.infer_anchor_from_cost(bars, 13.0, before=_iso(95, 90))
    assert d is not None and d < _iso(95, 90)
    rec_pre = {"anchor_date": _iso(95, 90), "anchor_quality": "pre_window"}
    assert svc.resolve_anchor(rec_pre, {}, bars, 13.0, "2026-10-22")[1] == "inferred_cost"
    assert svc.resolve_anchor(rec_pre, {}, bars, 99.0, "2026-10-22")[:2] == (_iso(95, 90), "pre_window")
    manual = {"manual_anchor": {"date": "2026-06-15"}}
    assert svc.resolve_anchor(rec_pre, manual, bars, 13.0, "2026-10-22")[:2] == ("2026-06-15", "manual")
    exact = {"anchor_date": "2026-07-01", "anchor_quality": "exact"}
    assert svc.resolve_anchor(exact, {}, bars, 13.0, "2026-10-22")[:2] == ("2026-07-01", "exact")


def test_set_anchor_requires_reason_and_is_audited(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    try:
        svc.set_anchor("300476.SZ", "2026-06-15", "")
        raise AssertionError("reason required")
    except ValueError:
        pass
    svc.set_anchor("300476.SZ", "2026-06-15", "对账单 6/15 首次买入")
    st = svc.load_state()
    assert st["positions"]["300476.SZ"]["manual_anchor"]["date"] == "2026-06-15"
    assert st["audit"][-1]["action"] == "set_anchor"
    svc.clear_anchor("300476.SZ")
    assert "manual_anchor" not in svc.load_state()["positions"]["300476.SZ"]


def test_ledger_freshness_reminds_before_60_day_window():
    assert svc.ledger_freshness({"imports": []}, "2026-10-22")["import_due"] is True
    led = {"imports": [{"at": "2026-09-01T10:00:00"}]}
    f = svc.ledger_freshness(led, "2026-10-22")
    assert f["import_due"] is True and f["days_since_import"] == 51
    assert svc.ledger_freshness({"imports": [{"at": "2026-10-20T10:00:00"}]}, "2026-10-22")["import_due"] is False


def test_stale_price_data_flagged(tmp_path, monkeypatch):
    store, ledger = _fixture(tmp_path, monkeypatch)
    rep = _report(store, ledger, state={"positions": {}, "audit": []}, today="2026-12-31")
    assert "999999.SZ" in rep["price_sync_needed"]               # 无行情
    r = {x["ts_code"]: x for x in rep["positions"]}["588000.SH"]
    assert r["data_lag_days"] > 1 and "行情滞后" in r["action"]
    assert "588000.SH" in rep["price_sync_needed"]



def test_read_is_pure_and_eod_commit_is_single_writer(tmp_path, monkeypatch):
    store, ledger = _fixture(tmp_path, monkeypatch)
    st0 = {"positions": {}, "audit": [], "tracking_since": "2026-06-01"}
    svc.save_state(st0)
    kw = dict(store=store, ledger=ledger, bars_loader=lambda c: BARS.get(c), regime="BULL", aiae_regime=3,
              today="2026-10-22")
    before = open(svc.STATE_PATH, encoding="utf-8").read()
    svc.build_report(**kw)                                           # 纯计算: 不写盘
    assert open(svc.STATE_PATH, encoding="utf-8").read() == before
    rep = svc.get_report(**kw)                                       # 新收盘 → 补跑日终提交一次
    assert rep["eod"]["committed_now"] is True
    st = svc.load_state()
    assert st["last_eod"]["as_of"] == rep["as_of"] and st["positions"]["588000.SH"]["published"]
    assert os.path.exists(svc.snapshot_path(rep["as_of"]))
    again = svc.get_report(**kw)                                     # 同一收盘再次读取: 只读
    assert again["eod"]["committed_now"] is False
    assert rep["meta"]["schema_version"] == 2 and rep["meta"]["config_hash"]


def test_day_over_day_diff_and_actions(tmp_path, monkeypatch):
    prev = {"as_of": "2026-10-21", "positions": [
        {"ts_code": "A", "name": "甲", "status": "GREEN", "stop": 10.0, "qty": 100},
        {"ts_code": "B", "name": "乙", "status": "GREEN", "stop": 5.0, "qty": 100}]}
    cur = {"as_of": "2026-10-22", "positions": [
        {"ts_code": "A", "name": "甲", "status": "RED", "stop": 10.2, "qty": 100},
        {"ts_code": "C", "name": "丙", "status": "GREEN", "stop": 1.0, "qty": 100}]}
    d = svc.diff_snapshots(prev, cur)
    types = [i["type"] for i in d["items"]]
    assert types[0] == "status" and "closed" in types and "new" in types and "stop" in types
    store, ledger = _fixture(tmp_path, monkeypatch)
    rep = _report(store, ledger, state={"positions": {}, "audit": [], "tracking_since": "2026-06-01"})
    acts = rep["actions"]
    assert acts[0]["type"] == "EXIT" and acts == sorted(acts, key=lambda a: (a["priority"], -(a.get("value") or 0)))
    assert any(a["type"] == "TRIM" for a in acts)


def test_correlation_risk_effective_bets():
    rows = [{"ts_code": "588000.SH", "market_value": 100, "status": "GREEN"},
            {"ts_code": "159995.SZ", "market_value": 100, "status": "GREEN"}]
    same = svc.correlation_risk(rows, lambda c: BARS["588000.SH"])  # 同一序列 → 相关 1
    assert same["avg_corr"] == 1.0 and same["n_eff"] == 1.0
