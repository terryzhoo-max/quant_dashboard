"""持仓跟踪止盈引擎: 阶段 / 棘轮 / 触发 / 分批 / 遗留突破 / 复盘"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.trailing_stop import (  # noqa: E402
    DEFAULT_CONFIG, PositionInput, asset_class, evaluate_position, merge_config, review_round_trip,
    wilder_atr,
)


def make_bars(closes, start="2026-06-01", band=0.01):
    idx = pd.bdate_range(start, periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c.shift(1).fillna(c), "high": c * (1 + band), "low": c * (1 - band), "close": c})


def trend_up_then_down():
    flat = [10.0] * 40                                   # 建仓前 40 日用于 ATR 预热
    up = list(np.linspace(10.0, 14.0, 40))               # 上涨 40%
    down = list(np.linspace(14.0, 12.0, 15))             # 回落
    return make_bars(flat + up + down)


def pos(**kw):
    base = dict(ts_code="588000.SH", name="科创50ETF", qty=30000, cost=10.0,
                anchor_date="2026-07-27", anchor_quality="exact")
    base.update(kw)
    return PositionInput(**base)


def test_stage_progression_and_trigger():
    bars = trend_up_then_down()
    anchor = bars.index[40].strftime("%Y-%m-%d")
    r = evaluate_position(pos(anchor_date=anchor), bars, regime="BULL")
    assert r["stage"] == 2 and r["asset_class"] == "theme_etf"
    assert r["params"]["init_k"] == 2.0 and r["params"]["trail_k"] == 5.0 and r["params"]["trail_start_r"] == 3.0
    assert r["status"] == "RED" and r["first_breach"] is not None
    assert r["sell_qty"] == 30000
    assert r["breach_stop"] > 10.0                   # 跟踪止盈线已高于成本: 锁住了利润


def test_stop_is_a_ratchet_never_moves_down():
    bars = trend_up_then_down()
    anchor = bars.index[40].strftime("%Y-%m-%d")
    stops = [evaluate_position(pos(anchor_date=anchor), bars, regime="BULL", as_of=d.strftime("%Y-%m-%d"))["stop"]
             for d in bars.index[42:]]
    assert all(b >= a - 1e-12 for a, b in zip(stops, stops[1:]))


def test_partial_take_profit_pending_until_sell_seen():
    closes = [10.0] * 40 + list(np.linspace(10.0, 11.6, 20))    # 进入 S2, 未回落
    bars = make_bars(closes)
    anchor = bars.index[40].strftime("%Y-%m-%d")
    r = evaluate_position(pos(anchor_date=anchor), bars, regime="BULL")
    assert r["stage"] >= 2 and r["status"] == "ACTION"
    assert r["sell_qty"] == 10000                    # 1/3, 按 100 股取整
    s2 = r["stage_dates"][2]
    r2 = evaluate_position(pos(anchor_date=anchor, qty=20000, sells_after=((s2, 10000),)), bars, regime="BULL")
    assert r2["pending_partial"] is None or r2["pending_partial"]["stage"] == 3
    r3 = evaluate_position(pos(anchor_date=anchor, qty=29000, sells_after=((s2, 1000),)), bars, regime="BULL")
    assert r3["status"] == "ACTION"                 # 零星卖出 1000 股不算执行了 1/3 止盈
    assert r2["status"] in ("GREEN", "YELLOW", "ACTION")
    assert r2["pending_partial"] is None or r2["pending_partial"]["stage"] == 3


def test_legacy_breach_before_tracking_needs_decision():
    closes = [10.0] * 40 + list(np.linspace(10.0, 7.0, 20))     # 建仓后一路下跌
    bars = make_bars(closes)
    anchor = bars.index[40].strftime("%Y-%m-%d")
    r = evaluate_position(pos(anchor_date=anchor, tracking_since=bars.index[-1].strftime("%Y-%m-%d")), bars)
    assert r["status"] == "LEGACY" and r["sell_qty"] == 0
    r2 = evaluate_position(pos(anchor_date=anchor, tracking_since=anchor), bars)
    assert r2["status"] == "RED"


def test_rebaseline_restarts_from_new_basis():
    closes = [10.0] * 40 + list(np.linspace(10.0, 7.0, 20)) + [7.0] * 10
    bars = make_bars(closes)
    new_anchor = bars.index[60].strftime("%Y-%m-%d")
    r = evaluate_position(pos(anchor_date=new_anchor, basis_price=7.0, tracking_since=new_anchor), bars)
    assert r["status"] in ("GREEN", "YELLOW") and r["first_breach"] is None
    assert r["stop"] < 7.0


def test_stock_uses_wide_calibrated_initial_stop():
    rng = np.random.default_rng(0)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, 60)))
    bars = make_bars(list(closes), band=0.03)
    anchor = bars.index[40].strftime("%Y-%m-%d")
    cost = float(bars["close"].iloc[40])
    r = evaluate_position(PositionInput("300476.SZ", "胜宏科技", 600, cost, anchor), bars)
    assert r["asset_class"] == "stock" and r["params"]["init_k"] == 5.0
    assert r["init_stop"] < cost * 0.92             # 个股 8% 硬止损已被校准否决 (约 1.3 ATR, 过紧)


def test_core_sleeve_is_looser_and_has_no_partial():
    closes = [10.0] * 40 + list(np.linspace(10.0, 11.6, 20))
    bars = make_bars(closes)
    anchor = bars.index[40].strftime("%Y-%m-%d")
    sat = evaluate_position(pos(anchor_date=anchor), bars, regime="BULL")
    core = evaluate_position(pos(anchor_date=anchor, sleeve="core"), bars, regime="BULL")
    assert core["k_trail"] > sat["k_trail"]
    assert core["pending_partial"] is None and core["status"] != "ACTION"


def test_regime_adjustment_off_by_default_but_configurable():
    bars = trend_up_then_down()
    a = bars.index[40].strftime("%Y-%m-%d")
    bull = evaluate_position(pos(anchor_date=a), bars, regime="BULL")["k_trail"]
    bear = evaluate_position(pos(anchor_date=a), bars, regime="BEAR")["k_trail"]
    assert bull == bear == 5.0                      # 校准: 环境调整无增益, 默认关闭
    cfg = merge_config({"aiae_tighten_step": 0.5, "regime_trail_adj": {"BEAR": -1.0}})
    assert evaluate_position(pos(anchor_date=a), bars, regime="BEAR", aiae_regime=4, cfg=cfg)["k_trail"] == 3.5


def test_no_data():
    assert evaluate_position(pos(), pd.DataFrame())["status"] == "NO_DATA"
    assert evaluate_position(pos(), make_bars([10.0] * 5))["status"] == "NO_DATA"


def test_asset_classes():
    cfg = DEFAULT_CONFIG
    assert asset_class("510300.SH", "沪深300ETF", cfg) == "broad_etf"
    assert asset_class("588000.SH", "科创50ETF华夏", cfg) == "theme_etf"
    assert asset_class("159995.SZ", "芯片ETF华夏", cfg) == "theme_etf"
    assert asset_class("688981.SH", "中芯国际", cfg) == "stock"


def test_atr_close_only_fallback():
    bars = make_bars([10.0 + (i % 2) * 0.2 for i in range(40)])[["close"]]
    atr = wilder_atr(bars, 20)
    assert atr.dropna().iloc[-1] == pytest.approx(0.25, rel=0.05)


def test_merge_config_deep():
    cfg = merge_config({"classes": {"theme_etf": {"trail_atr_mult": 6.0}}, "_comment": "x"})
    assert cfg["classes"]["theme_etf"]["trail_atr_mult"] == 6.0
    assert cfg["classes"]["theme_etf"]["init_atr_mult"] == 2.0 and cfg["classes"]["stock"]["init_atr_mult"] == 5.0


def test_review_round_trip_giveback_and_rule_exit():
    bars = trend_up_then_down()
    trip = {"ts_code": "588000.SH", "name": "科创50ETF", "entry_date": bars.index[40].strftime("%Y-%m-%d"),
            "exit_date": bars.index[-1].strftime("%Y-%m-%d"), "buy_qty": 1000, "avg_buy": 10.0,
            "avg_sell": 12.0, "ret": 0.2}
    r = review_round_trip(trip, bars, regime="BULL")
    assert r["mfe_pct"] == pytest.approx(0.4)
    assert r["giveback"] == pytest.approx(0.5)       # 涨 4 元回吐 2 元
    assert r["rule_exit_date"] <= trip["exit_date"]
    assert r["rule_ret"] > r["ret"]                  # 规则在回落途中更早锁利


def test_snapshot_anchor_already_below_initial_stop_is_legacy():
    closes = [10.0] * 40 + list(np.linspace(10.0, 7.0, 20))
    bars = make_bars(closes)
    today = bars.index[-1].strftime("%Y-%m-%d")
    r = evaluate_position(pos(anchor_date=today, anchor_quality="unknown", tracking_since=today), bars)
    assert r["status"] == "LEGACY" and r["sell_qty"] == 0


def test_etf_share_split_is_back_adjusted_not_a_crash():
    # 1 拆 2: 收盘 2.00 → 次日 1.01 (pre_close 1.00, 涨 1%), 未复权数据会伪造 −50%
    idx = pd.bdate_range("2026-06-01", periods=60)
    close = np.r_[np.full(40, 2.0), np.full(20, 1.01)]
    pre = np.r_[2.0, close[:-1]]
    pre[40] = 1.0
    raw = pd.DataFrame({"trade_date": idx.strftime("%Y%m%d"), "open": close, "high": close * 1.005,
                        "low": close * 0.995, "close": close, "pre_close": pre})
    from services.trailing_stop import normalize_bars
    b = normalize_bars(raw)
    assert b["close"].iloc[0] == pytest.approx(1.0) and b["close"].iloc[-1] == pytest.approx(1.01)
    assert b["raw_close"].iloc[0] == 2.0
    r = evaluate_position(PositionInput("159516.SZ", "半导体设备ETF", 10000, 1.0, idx[30].strftime("%Y-%m-%d"),
                                        tracking_since="2026-06-01"), raw)
    assert r["first_breach"] is None and r["status"] != "RED"


def test_point_in_time_regime_keeps_published_stop_from_dropping():
    bars = trend_up_then_down()
    a = bars.index[40].strftime("%Y-%m-%d")
    # 校准后默认不按环境调整倍数; 若用户开启 (BULL 放宽), 历史各日仍须用当日环境
    cfg = merge_config({"regime_trail_adj": {"BULL": 1.5, "BEAR": -1.5}})
    mid, nxt = bars.index[75], bars.index[76]
    r_mid = evaluate_position(pos(anchor_date=a), bars, regime="BEAR", cfg=cfg, as_of=mid.strftime("%Y-%m-%d"))
    hist = pd.Series({bars.index[0]: "BEAR", nxt: "BULL"})
    r_next = evaluate_position(pos(anchor_date=a), bars, regime="BULL", cfg=cfg, regime_hist=hist,
                               as_of=nxt.strftime("%Y-%m-%d"))
    assert r_next["stop"] >= r_mid["stop"]
    naive = evaluate_position(pos(anchor_date=a), bars, regime="BULL", cfg=cfg, as_of=nxt.strftime("%Y-%m-%d"))
    assert naive["stop"] < r_mid["stop"]            # 旧实现: 用今天的倍数改写历史 → 止损线下移


def test_published_floor_survives_split_adjustment():
    bars = trend_up_then_down()
    a = bars.index[40].strftime("%Y-%m-%d")
    d = bars.index[70]
    r = evaluate_position(pos(anchor_date=a), bars, regime="BEAR", as_of=d.strftime("%Y-%m-%d"))
    ratio = r["stop"] / r["close"]
    r2 = evaluate_position(pos(anchor_date=a, published_floor=(d.strftime("%Y-%m-%d"), ratio)), bars,
                           regime="BULL", as_of=bars.index[72].strftime("%Y-%m-%d"))
    assert r2["stop"] >= r["stop"] - 0.002


def test_next_fill_skips_locked_limit_down():
    from services.trailing_stop import next_fill
    idx = pd.bdate_range("2026-06-01", periods=5)
    c = np.array([10.0, 9.0, 8.1, 7.29, 7.5])
    b = pd.DataFrame({"open": [10, 9.5, 8.1, 7.29, 7.0], "high": [10.1, 9.6, 8.1, 7.29, 7.6],
                      "low": [9.9, 9.0, 8.1, 7.29, 6.9], "close": c, "pre_close": np.r_[10.0, c[:-1]]}, index=idx)
    d, px = next_fill(b, idx[1], "002156.SZ")        # 次两日一字跌停, 第 5 日开盘才能成交
    assert d == idx[4].strftime("%Y-%m-%d") and px == 7.0
