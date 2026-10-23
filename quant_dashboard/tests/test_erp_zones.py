"""ERP valuation zones must be point-in-time and consistent with the D2 percentile."""

import numpy as np
import pandas as pd

from engines.erp_zones import compute_erp_pit_bands, zone_episodes


def _series(n=1600, seed=3):
    rng = np.random.default_rng(seed)
    return pd.Series(5.0 + np.cumsum(rng.normal(0, 0.05, n)).clip(-2.5, 2.5))


def test_no_look_ahead():
    s = _series()
    base = compute_erp_pit_bands(s, window=1008, abs_floor=3.0)
    shocked = s.copy()
    shocked.iloc[1200:] += 3.0                      # 改变未来, 过去的区间不得变化
    after = compute_erp_pit_bands(shocked, window=1008, abs_floor=3.0)
    pd.testing.assert_frame_equal(base.iloc[:1200], after.iloc[:1200])


def test_current_pct_matches_d2_definition():
    s = _series()
    bands = compute_erp_pit_bands(s, window=1008, abs_floor=3.0)
    window = s.tail(1008)
    d2 = (window < s.iloc[-1]).mean() * 100
    assert abs(bands["pct"].iloc[-1] - d2) < 1e-9


def test_lines_are_ordered_and_floor_binds():
    s = pd.Series(np.linspace(4.0, 1.5, 1300))      # 长期泡沫: 估值持续变贵
    b = compute_erp_pit_bands(s, window=1008, abs_floor=3.0).dropna(subset=["danger"])
    assert (b["danger"] >= 3.0 - 1e-12).all()
    assert (b["danger"] <= b["under"]).all() and (b["under"] <= b["over"]).all() and (b["over"] <= b["strong"]).all()
    # 尾段 ERP < 3%: 相对分位虽在窗口内"不算最贵", 绝对下限必须判为危险
    assert b["zone"].iloc[-1] == "danger"


def test_zone_boundaries_require_double_confirmation():
    s = _series()
    b = compute_erp_pit_bands(s, window=1008, abs_floor=0.0).dropna(subset=["danger", "anchor"])
    v = s.loc[b.index]
    assert ((b["zone"] == "strong") == ((v >= b["strong"]) & (v >= b["anchor"]))).all()
    assert ((b["zone"] == "danger") == ((v < b["danger"]) & (v < b["anchor"]))).all()


def test_relatively_low_but_above_anchor_is_only_underweight():
    # 先长期在 4% 附近, 再经历 4 年 7% 的便宜期, 回落到 5% (高于长期中枢 4.x%, 但低于 4 年 P20)
    s = pd.Series([4.0] * 1500 + [7.0] * 1008 + [5.0] * 5)
    b = compute_erp_pit_bands(s, window=1008, abs_floor=3.0)
    last = b.iloc[-1]
    assert s.iloc[-1] < last["danger"] and s.iloc[-1] > last["anchor"]
    assert last["zone"] == "under"


def test_insufficient_history_has_no_zone():
    s = _series(300)
    b = compute_erp_pit_bands(s, window=1008, abs_floor=3.0)
    assert b["zone"].iloc[:251].isna().all()
    assert b["zone"].iloc[-1] is not None


def test_zone_episodes_merge_short_gaps():
    zones = ["danger", "danger", None, "danger", "neutral", "neutral", "neutral", "neutral", "danger"]
    dates = [f"d{i}" for i in range(len(zones))]
    eps = zone_episodes(zones, dates, "danger", merge_gap=3)
    assert len(eps) == 2
    assert eps[0]["start"] == "d0" and eps[0]["end"] == "d3" and eps[0]["points"] == 3
    assert eps[1]["ongoing"] is True


def test_full_window_flag_marks_only_complete_windows():
    s = _series(1300)
    b = compute_erp_pit_bands(s, window=1008, abs_floor=3.0)
    assert not b["full_window"].iloc[:1007].any()
    assert b["full_window"].iloc[1007:].all()


def test_episodes_count_trading_days_on_daily_zones():
    zones = ["danger"] * 10 + ["neutral"] * 2 + ["danger"] * 5
    dates = [f"d{i}" for i in range(len(zones))]
    eps = zone_episodes(zones, dates, "danger", merge_gap=5)
    assert len(eps) == 1 and eps[0]["points"] == 15 and eps[0]["ongoing"] is True
