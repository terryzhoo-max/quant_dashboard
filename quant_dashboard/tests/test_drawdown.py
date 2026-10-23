"""组合回撤监控: 剔除资金进出的净值 / 回撤读数 / 前瞻 / 分档刹车重放"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import drawdown as dd  # noqa: E402


def _px(vals, start="2026-09-01"):
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(vals, index=idx, dtype=float)


def test_nav_is_flow_neutral_when_adding_money():
    # 价格 10 → 8 (−20%), 期间在 9.0 加仓一倍: 总市值几乎不变, 但净值必须体现 −20%
    p = _px([10, 9.5, 9.0, 8.5, 8.0])
    trades = [{"date": p.index[2].strftime("%Y-%m-%d"), "ts_code": "A", "side": "buy", "qty": 1000}]
    H = dd.holdings_history(p.index, {"A": 2000}, trades, p.index[-1].strftime("%Y-%m-%d"))
    assert list(H["A"]) == [1000, 1000, 2000, 2000, 2000]
    ns = dd.nav_series(H, pd.DataFrame({"A": p}))
    assert ns["nav"].iloc[-1] == pytest.approx(0.8)
    assert ns["mv"].iloc[-1] == pytest.approx(16000)       # 市值 16000 > 期初 10000, 但实际亏 20%


def test_holdings_roll_forward_after_snapshot():
    p = _px([10, 10, 10, 10])
    trades = [{"date": p.index[3].strftime("%Y-%m-%d"), "ts_code": "A", "side": "sell", "qty": 500}]
    H = dd.holdings_history(p.index, {"A": 1000}, trades, p.index[1].strftime("%Y-%m-%d"))
    assert list(H["A"]) == [1000, 1000, 1000, 500]


def test_dd_stats():
    nav = _px([1.0, 1.2, 0.9, 1.0])
    s = dd.dd_stats(nav)
    assert s["mdd"] == pytest.approx(-0.25) and s["current_dd"] == pytest.approx(1.0 / 1.2 - 1, abs=1e-4)
    assert s["days_underwater"] == 2 and s["recovery_needed"] == pytest.approx(0.2, abs=1e-3)


def test_replay_tiers_with_hysteresis():
    # 1.0 → 0.86 (−14%: 一档) → 0.78 (−22%: 二档) → 0.86 (收复 36% < 1/2: 仍二档) → 0.90 (收复 55%: 回一档)
    nav = _px([1.0, 0.95, 0.86, 0.80, 0.78, 0.82, 0.86, 0.90])
    b = dd.replay_tiers(nav)
    assert [e["to"] for e in b["events"]] == [1, 2, 1]
    assert b["tier"] == 1 and b["cap_pct"] == 75 and b["no_add"] is True
    assert dd.replay_tiers(nav.iloc[:7])["tier"] == 2
    b2 = dd.replay_tiers(nav.iloc[:5])
    assert b2["tier"] == 2 and b2["cap_pct"] == 50 and b2["next_trigger_dd"] == -0.28
    assert b2["rerisk_at_dd"] == pytest.approx((0.78 + (1 - 0.78) / 2) - 1, abs=1e-4)
    b3 = dd.replay_tiers(nav, {**dd.DEFAULT_POLICY, "rerisk_recover": 1 / 3})
    assert [e["to"] for e in b3["events"]] == [1, 2, 1]


def test_tier_logic_matches_calibration_backtest():
    """生产状态机必须与校准时的回测逻辑一致 (同一组参数下档位轨迹相同)。"""
    rng = np.random.default_rng(3)
    nav = _px(np.cumprod(1 + rng.normal(-0.002, 0.03, 300)), "2025-01-01")
    tiers = dd.DEFAULT_POLICY["tiers"]
    hwm, tier, trough, path = -1, 0, None, []
    for v in nav:
        hwm = max(hwm, v)
        d = v / hwm - 1
        lvl = tier
        while lvl < len(tiers) and d <= -tiers[lvl]["dd"]:
            lvl += 1
        if lvl > tier:
            tier, trough = lvl, v
        elif tier > 0:
            trough = min(trough, v)
            if v >= trough + dd.DEFAULT_POLICY["rerisk_recover"] * (hwm - trough) or v >= hwm:
                tier, trough = tier - 1, v
        path.append(tier)
    assert dd.replay_tiers(nav)["tier"] == path[-1]


def test_forecast_and_budget_exposure():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.0005, 0.03, 250))           # 年化波动 ≈ 47%
    f = dd.forecast_mdd(r, sims=600)
    assert -0.8 < f["mdd_p95"] < f["mdd_median"] < 0
    assert 0 < f["max_exposure_for_budget"] < 1
    calm = dd.forecast_mdd(pd.Series(rng.normal(0.0003, 0.004, 250)), sims=400)
    assert calm["max_exposure_for_budget"] == 1.0


def test_gz_exposure():
    assert dd.gz_exposure(_px([1.0, 0.9]), 0.25, 2.0) == pytest.approx(2 * (0.9 - 0.75) / 0.9, abs=1e-3)
    assert dd.gz_exposure(_px([1.0, 0.7]), 0.25, 2.0) == 0.0


def test_monitor_end_to_end_and_baseline():
    p = _px(list(np.linspace(10, 7, 40)), "2026-08-03")
    bars = pd.DataFrame({"close": p, "high": p, "low": p, "open": p})
    trades = [{"date": p.index[20].strftime("%Y-%m-%d"), "ts_code": "A", "side": "buy", "qty": 1000}]
    m = dd.monitor({"A": 2000}, trades, lambda c: bars if c == "A" else None,
                   snapshot_date=p.index[-1].strftime("%Y-%m-%d"), equity=14000, invested_value=14000)
    assert m["status"] == "ok" and m["brake"]["tier"] >= 1 and m["brake"]["reduce_value"] > 0
    m2 = dd.monitor({"A": 2000}, trades, lambda c: bars if c == "A" else None,
                    snapshot_date=p.index[-1].strftime("%Y-%m-%d"), equity=14000, invested_value=14000,
                    baseline={"date": p.index[-2].strftime("%Y-%m-%d"), "reason": "x"})
    assert m2["brake"]["basis"] == "baseline" and m2["brake"]["dd"] > m["brake"]["dd"]


def test_service_actions_and_baseline_audit(tmp_path, monkeypatch):
    from services import trailing_stop_service as svc
    monkeypatch.setattr(svc, "STATE_PATH", str(tmp_path / "state.json"))
    acts = svc._drawdown_actions({"brake": {"tier": 2, "cap_pct": 50, "dd": -0.226, "label": "二档", "invested_pct": 99.0,
                                            "reduce_value": 690000, "rerisk_at_dd": -0.15, "basis": "realized",
                                            "events": [{"date": "2026-10-19", "to": 2}]}})
    assert acts[0]["type"] == "DRAWDOWN" and acts[0]["priority"] == 1 and "22.6%" in acts[0]["detail"]
    assert svc._drawdown_actions({"brake": {"tier": 0, "invested_pct": 95},
                                  "forecast": {"max_exposure_for_budget": 0.4, "ann_vol": 0.47,
                                               "mdd_p95": -0.59, "budget_dd": 0.28}})[0]["type"] == "DD_BUDGET"
    with pytest.raises(ValueError):
        svc.set_drawdown_baseline("2026-10-01", "")
    svc.set_drawdown_baseline("2026-10-01", "追加资金重新承保")
    st = svc.load_state()
    assert st["drawdown"]["baseline"]["date"] == "2026-10-01" and st["audit"][-1]["action"] == "drawdown_baseline"
    assert svc.clear_drawdown_baseline()["cleared"] is True


def test_forecast_is_drift_neutral_and_vol_floored():
    rng = np.random.default_rng(5)
    up = pd.Series(rng.normal(0.004, 0.02, 250))            # 过去一年强趋势
    raw = dd.forecast_mdd(up, sims=500, demean=False, ewma_lambda=None)
    neutral = dd.forecast_mdd(up, sims=500)
    assert neutral["mdd_median"] < raw["mdd_median"]        # 不外推趋势 → 回撤估计更保守
    calm_then_wild = pd.Series(np.r_[rng.normal(0, 0.01, 200), rng.normal(0, 0.04, 50)])
    f = dd.forecast_mdd(calm_then_wild, sims=500)
    assert "EWMA 放大" in f["assumptions"]["vol"] and f["ann_vol"] > calm_then_wild.std() * np.sqrt(250)


def test_synth_prices_hit_trade_anchors():
    proxy = _px(list(np.linspace(1.0, 0.8, 10)))
    trades = [{"ts_code": "X", "date": proxy.index[2].strftime("%Y-%m-%d"), "price": 100, "qty": 100},
              {"ts_code": "X", "date": proxy.index[7].strftime("%Y-%m-%d"), "price": 70, "qty": 100}]
    sp = dd.synth_prices(["X"], trades, proxy)["X"]
    assert sp.iloc[2] == pytest.approx(100) and sp.iloc[7] == pytest.approx(70)
    assert sp.iloc[0] == pytest.approx(100 * proxy.iloc[0] / proxy.iloc[2])   # 首锚点前按代理外推


def test_derisk_plan_sells_breached_first_and_respects_lots():
    from services.trailing_stop_service import derisk_plan
    rows = [
        {"ts_code": "588000.SH", "name": "ETF遗留", "status": "LEGACY", "qty": 100000, "close": 1.0,
         "breach_stop": 1.1, "market_value": 100000},
        {"ts_code": "688019.SH", "name": "科创股", "status": "GREEN", "qty": 900, "close": 100.0, "market_value": 90000},
        {"ts_code": "002463.SZ", "name": "主板股", "status": "GREEN", "qty": 1000, "close": 50.0, "market_value": 50000},
    ]
    p = derisk_plan(rows, 130000, equity=240000, invested_value=240000)
    it = {i["ts_code"]: i for i in p["items"]}
    assert it["588000.SH"]["qty"] == 100000 and it["588000.SH"]["step"] == 2      # 已越线的整只先卖
    assert it["688019.SH"]["qty"] >= 200                                          # 科创板 ≥200 股
    assert it.get("002463.SZ", {"qty": 0})["qty"] % 100 == 0                      # 主板整手
    assert p["total"] >= 130000 and p["total"] < 130000 + 100 * 200               # 不足额也不大幅超卖
    small = derisk_plan(rows, 50000, equity=240000, invested_value=240000)
    assert [i["ts_code"] for i in small["items"]] == ["588000.SH"] and small["items"][0]["qty"] == 50000


def test_calibration_simulator_matches_production_state_machine():
    """校准器与生产状态机同一逻辑: 满仓 (无档位) 时等于买入持有; 档位轨迹与 replay_tiers 一致。"""
    from strategies.drawdown_calibration import simulate
    rng = np.random.default_rng(11)
    c = 10 * np.cumprod(1 + rng.normal(-0.001, 0.025, 400))
    o = c * (1 + rng.normal(0, 0.003, 400))
    pc = np.r_[c[0], c[:-1]]
    nav, ex = simulate(o, c, pc, 0.1, [], 0.5)
    assert nav[-1] == pytest.approx(c[-1] / c[0], rel=1e-9) and (ex == 1).all()
    tiers = [(t["dd"], t["cap"] / 100) for t in dd.DEFAULT_POLICY["tiers"]]
    _, ex = simulate(o, c, pc, 0.1, tiers, dd.DEFAULT_POLICY["rerisk_recover"])
    book = pd.Series(c / c[0], index=pd.bdate_range("2024-01-01", periods=400))
    for t in range(2, 400, 7):                               # 第 t 日执行的仓位 = 第 t−1 日收盘的档位上限
        assert ex[t] == pytest.approx(dd.replay_tiers(book.iloc[:t])["cap_pct"] / 100)


# ═══════════════ 编排层 (services/drawdown_service.py) ═══════════════

def test_marked_equity_uses_same_timestamp():
    from services.drawdown_service import marked_equity
    store = {"broker_total_asset": 1_000_000, "positions": {"A": {"broker_market_value": 990_000}}}
    eq, cash, basis = marked_equity(store, 900_000)          # 快照后持仓跌到 90 万
    assert basis == "marked" and cash == 10_000 and eq == 910_000
    assert marked_equity({"cash": 5.0}, 100.0) == (105.0, 5.0, "marked")
    assert marked_equity({"broker_total_asset": 1e6, "positions": {}}, 5e5)[2] == "broker_snapshot"


def test_publish_and_restatement():
    from services import drawdown_service as ds
    nav = _px([1.0, 0.95, 0.86, 0.80, 0.78])
    state = {}
    b = dd.replay_tiers(nav)
    ds.publish(state, {"brake": {**b, "dd": -0.22, "basis": "realized"}}, nav.index[-1].strftime("%Y-%m-%d"))
    ds.publish(state, {"brake": {**b, "dd": -0.22, "basis": "realized"}}, nav.index[-1].strftime("%Y-%m-%d"))
    assert len(state["drawdown"]["published"]) == 1                                  # 同日幂等
    assert ds.restatement(nav, state["drawdown"]["published"], dd.DEFAULT_POLICY) == []
    nav2 = nav.copy(); nav2.iloc[1:] = [0.99, 0.97, 0.95, 0.93]                        # 补齐数据后历史净值改变
    r = ds.restatement(nav2, state["drawdown"]["published"], dd.DEFAULT_POLICY)
    assert r and r[0]["published_tier"] == 2 and r[0]["restated_tier"] == 0
    assert any(a["type"] == "RESTATE" for a in ds.actions({"restatement": r}))


def test_execution_progress_counts_sells_and_flags_buys():
    from services.drawdown_service import execution_progress
    b = {"tier": 2, "reduce_value": 300_000, "events": [
        {"date": "2026-09-01", "to": 1, "dir": "down"}, {"date": "2026-09-05", "to": 0, "dir": "up"},
        {"date": "2026-10-08", "to": 1, "dir": "down"}, {"date": "2026-10-19", "to": 2, "dir": "down"}]}
    trades = [{"date": "2026-10-08", "side": "sell", "amount": 99_999},               # 触发当日: 不计
              {"date": "2026-10-09", "side": "sell", "amount": 200_000},
              {"date": "2026-10-12", "side": "buy", "amount": 50_000, "ts_code": "X", "qty": 100}]
    p = execution_progress(b, trades)
    assert p["since"] == "2026-10-08" and p["executed"] == 150_000 and p["remaining"] == 300_000
    assert p["pct"] == pytest.approx(1 / 3, abs=1e-3)
    assert p["violation_count"] == 0 and p["pre_live_buys"] == 1                   # 系统启用前: 回放, 不算违规
    p2 = execution_progress(b, trades, live_since="2026-10-10")
    assert p2["violation_count"] == 1 and p2["violations"][0]["ts_code"] == "X"


def test_alert_fires_once_per_tier_change():
    from services.drawdown_service import alert
    sent = {}
    d = {"brake": {"tier": 2, "dd": -0.22, "label": "二档", "cap_pct": 50, "events": [{"date": "2026-10-19"}]}}
    assert alert(d, sent)["severity"] == "critical"
    assert alert(d, sent) is None
    d2 = {"brake": {"tier": 1, "dd": -0.10, "label": "一档", "cap_pct": 75, "events": [{"date": "2026-11-02"}]}}
    assert alert(d2, sent)["icon"] == "🔓"
