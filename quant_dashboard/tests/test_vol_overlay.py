"""
波动率自适应仓位 (Vol Overlay V2) 单元测试
==========================================
覆盖:
  - services/vol_regime.py      市场尾部刹车 (时点安全 / 刹车触发 / 新鲜度保守处理)
  - services/portfolio_vol.py   组合波动预算 (单票上限 / 跳空上限 / 目标波动 / 减仓草案)
  - services/aiae_safety.py     apply_vol_overlay (有效上限 / 不复利 / 锁定不改)
  - engines/compliance_engine   vol_budget 规则
  - services/strategy_params    vol_targeting 配置校验
全部使用合成数据, 不读磁盘行情, 不依赖网络。
"""

import copy
import math
import unittest
from datetime import date

import numpy as np
import pandas as pd

from services import vol_regime as vr
from services import portfolio_vol as pv
from services.aiae_safety import apply_vol_overlay


def _gbm(n, daily_vol, seed=0, start="2018-01-01", s0=100.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, daily_vol, n)
    idx = pd.bdate_range(start, periods=n)
    return pd.Series(s0 * np.exp(np.cumsum(r)), index=idx)


def _calm_then_storm(calm_n=900, storm_n=60, calm_vol=0.011, storm_vol=0.045, seed=1):
    rng = np.random.default_rng(seed)
    r = np.concatenate([rng.normal(0, calm_vol, calm_n), rng.normal(0, storm_vol, storm_n)])
    idx = pd.bdate_range("2016-01-01", periods=len(r))
    return pd.Series(100 * np.exp(np.cumsum(r)), index=idx)


class TestMarketVolOverlay(unittest.TestCase):
    def test_split_jump_is_filtered(self):
        close = _gbm(300, 0.01)
        close.iloc[150:] = close.iloc[150:] / 2.0  # 1:2 拆分未复权
        r = vr.clean_log_returns(close)
        self.assertLess(r.abs().max(), 0.21)
        self.assertEqual(len(r), 298)

    def test_normal_vol_keeps_factor_at_one(self):
        frame = vr.compute_vol_factor_frame(_gbm(1200, 0.011, seed=3))
        self.assertFalse(frame.empty)
        self.assertTrue((frame["factor"] == 1.0).all())
        self.assertEqual(set(frame["regime"]), {"normal"})

    def test_extreme_vol_engages_brake_within_bounds(self):
        frame = vr.compute_vol_factor_frame(_calm_then_storm())
        last = frame.iloc[-1]
        self.assertTrue(bool(last["crash"]))
        self.assertLess(last["factor"], 1.0)
        self.assertGreaterEqual(last["factor"], vr.DEFAULT_MARKET_VOL_CONFIG["floor"])
        self.assertIn(last["regime"], {"elevated", "high_vol", "extreme"})

    def test_ceiling_never_lifts_cap_in_calm_markets(self):
        frame = vr.compute_vol_factor_frame(_gbm(1200, 0.004, seed=5))
        self.assertLessEqual(frame["factor"].max(), 1.0)

    def test_point_in_time_prefix_invariance(self):
        """第 t 行的系数不能因为追加未来数据而改变 (无前视)."""
        close = _calm_then_storm(seed=7)
        full = vr.compute_vol_factor_frame(close)
        part = vr.compute_vol_factor_frame(close.iloc[:-40])
        common = part.index
        np.testing.assert_allclose(full.loc[common, "factor"].values, part["factor"].values)

    def test_slow_recovery_when_configured(self):
        close = pd.concat([
            _calm_then_storm(seed=11),
            _gbm(80, 0.011, seed=12, start="2019-09-01", s0=1.0),
        ])
        close = close[~close.index.duplicated()]
        cfg = {"up_confirm_days": 5, "max_up_step_per_day": 0.01, "up_deadband": 0.0}
        fast = vr.compute_vol_factor_frame(close)
        slow = vr.compute_vol_factor_frame(close, cfg)
        self.assertGreaterEqual(fast["factor"].iloc[-20:].mean(), slow["factor"].iloc[-20:].mean())
        self.assertLessEqual(slow["factor"].diff().max(), 0.01 + 1e-9)

    def test_insufficient_history_returns_empty(self):
        self.assertTrue(vr.compute_vol_factor_frame(_gbm(50, 0.01)).empty)


class TestOverlayFreshness(unittest.TestCase):
    cfg = dict(vr.DEFAULT_MARKET_VOL_CONFIG)

    def test_fresh_snapshot_is_used_as_is(self):
        ov = vr.evaluate_overlay({"factor": 0.9, "trade_date": "2026-10-20"}, self.cfg, today=date(2026, 10, 22))
        self.assertEqual(ov["status"], "ok")
        self.assertEqual(ov["factor"], 0.9)

    def test_stale_snapshot_is_capped_conservatively(self):
        ov = vr.evaluate_overlay({"factor": 1.0, "trade_date": "2026-09-04"}, self.cfg, today=date(2026, 10, 22))
        self.assertEqual(ov["status"], "stale")
        self.assertEqual(ov["factor"], self.cfg["stale_factor_cap"])
        ov2 = vr.evaluate_overlay({"factor": 0.6, "trade_date": "2026-09-04"}, self.cfg, today=date(2026, 10, 22))
        self.assertEqual(ov2["factor"], 0.6)  # 已经更低时不放松

    def test_missing_snapshot_fails_conservative_not_neutral(self):
        ov = vr.evaluate_overlay({}, self.cfg, today=date(2026, 10, 22))
        self.assertEqual(ov["status"], "missing")
        self.assertLess(ov["factor"], 1.0)

    def test_disabled_is_explicit_neutral(self):
        ov = vr.evaluate_overlay({}, dict(self.cfg, enabled=False))
        self.assertEqual(ov["status"], "disabled")
        self.assertEqual(ov["factor"], 1.0)

    def test_apply_to_cap(self):
        self.assertEqual(vr.apply_vol_overlay_to_cap(60, {"factor": 0.8}), 48.0)
        self.assertEqual(vr.apply_vol_overlay_to_cap(100, {"factor": 1.0}), 95.0)  # 审计红线
        self.assertEqual(vr.apply_vol_overlay_to_cap(60, None), 60.0)
        self.assertIsNone(vr.apply_vol_overlay_to_cap("abc", {"factor": 0.8}))
        self.assertEqual(vr.apply_vol_overlay_to_cap(60, {"factor": float("nan")}), 60.0)


class TestApplyVolOverlayToContext(unittest.TestCase):
    def _ctx(self, **kw):
        base = {"decision_locked": False, "cap": 60, "regime": 3}
        base.update(kw)
        return base

    def test_effective_cap_and_base_cap(self):
        out = apply_vol_overlay(self._ctx(), {"status": "ok", "factor": 0.75, "brake_on": True})
        self.assertEqual(out["base_cap"], 60)
        self.assertEqual(out["cap"], 45)
        self.assertTrue(out["vol_overlay"]["brake_on"])

    def test_reapplying_does_not_compound(self):
        once = apply_vol_overlay(self._ctx(), {"status": "ok", "factor": 0.75})
        twice = apply_vol_overlay(once, {"status": "ok", "factor": 0.75})
        self.assertEqual(twice["cap"], 45)

    def test_locked_context_untouched(self):
        ctx = self._ctx(decision_locked=True)
        out = apply_vol_overlay(ctx, {"status": "ok", "factor": 0.5})
        self.assertEqual(out["cap"], 60)
        self.assertNotIn("base_cap", out)


class TestPortfolioVolBudget(unittest.TestCase):
    cfg = dict(pv.DEFAULT_PORTFOLIO_VOL_CONFIG)

    @staticmethod
    def _loader_from(series_map):
        return lambda code: series_map.get(code)

    def test_single_asset_vol_and_max_equity(self):
        close = _gbm(400, 0.40 / math.sqrt(252), seed=21)
        res = pv.compute_portfolio_vol(
            {"510300.SH": {"name": "300ETF", "broker_market_value": 900}}, 1000,
            self._loader_from({"510300.SH": close}), dict(self.cfg, target_vol=0.15),
        )
        self.assertEqual(res["status"], "ok")
        self.assertAlmostEqual(res["sleeve_vol"], 0.40, delta=0.05)
        self.assertAlmostEqual(res["max_equity_pct"], 15 / (res["sleeve_vol"] * 100) * 100, delta=0.5)
        self.assertGreater(res["equity_excess_pp"], 0)

    def test_gap_cap_for_20cm_board(self):
        cap, rule = pv.name_cap_pct("688981.SH", "中芯国际", 0.30, self.cfg)
        self.assertEqual(rule, "gap")
        self.assertAlmostEqual(cap, 0.02 / (1 - 0.8 ** 2) * 100, places=1)

    def test_vol_cap_for_high_vol_stock(self):
        cap, rule = pv.name_cap_pct("002463.SZ", "沪电股份", 0.75, self.cfg)
        self.assertEqual(rule, "vol")
        self.assertAlmostEqual(cap, 4.0, places=1)

    def test_etf_has_no_gap_rule(self):
        cap, rule = pv.name_cap_pct("588000.SH", "科创50ETF", 0.20, self.cfg)
        self.assertEqual(rule, "static")
        self.assertEqual(cap, 25.0)

    def test_concentrated_basket_has_about_one_bet_and_trim_hits_target(self):
        rng = np.random.default_rng(31)
        common = rng.normal(0, 0.03, 400)
        idx = pd.bdate_range("2024-01-01", periods=400)
        series, positions = {}, {}
        for i in range(6):
            r = common + rng.normal(0, 0.005, 400)
            code = f"68800{i}.SH"
            series[code] = pd.Series(100 * np.exp(np.cumsum(r)), index=idx)
            positions[code] = {"name": f"S{i}", "broker_market_value": 160}
        res = pv.compute_portfolio_vol(positions, 1000, self._loader_from(series), self.cfg)
        self.assertLess(res["effective_bets"], 1.5)
        self.assertEqual(res["breach_count"], 6)
        self.assertLessEqual(res["after_trim"]["portfolio_vol"], self.cfg["target_vol"] + 1e-3)
        self.assertTrue(all(p["to_pct"] <= p["from_pct"] for p in res["trim_plan"]))

    def test_missing_prices_use_proxy_and_flag_partial(self):
        res = pv.compute_portfolio_vol(
            {"300476.SZ": {"name": "胜宏科技", "broker_market_value": 500}}, 1000,
            self._loader_from({}), self.cfg,
        )
        self.assertEqual(res["status"], "partial")
        self.assertEqual(res["positions"][0]["vol_source"], "proxy")

    def test_empty_portfolio(self):
        self.assertEqual(pv.compute_portfolio_vol({}, 1000, cfg=self.cfg)["status"], "empty")

    def test_summarize(self):
        self.assertIsNone(pv.summarize({"status": "empty"}))
        s = pv.summarize({"status": "ok", "max_equity_pct": 30, "invested_pct": 90})
        self.assertEqual(s["max_equity_pct"], 30)


class TestComplianceVolBudget(unittest.TestCase):
    def test_rule_paths(self):
        from engines.compliance_engine import _check_vol_budget

        ok, _ = _check_vol_budget({}, [], {"vol_budget": {
            "invested_pct": 30, "max_equity_pct": 33, "portfolio_vol": 0.14, "target_vol": 0.15}})
        self.assertTrue(ok)
        ok, detail = _check_vol_budget({}, [], {"vol_budget": {
            "invested_pct": 98, "max_equity_pct": 33, "portfolio_vol": 0.44, "target_vol": 0.15}})
        self.assertFalse(ok)
        self.assertIn("超出波动预算", detail)
        ok, _ = _check_vol_budget({}, [], {"vol_budget": {"cap": 85}})
        self.assertTrue(ok)  # 数据不完整 → 跳过


class TestVolTargetingConfigValidation(unittest.TestCase):
    def test_rejects_out_of_range_values(self):
        from services.strategy_params import DEFAULT_RUNTIME_CONFIG, validate_runtime_config

        good = copy.deepcopy(DEFAULT_RUNTIME_CONFIG)
        good["vol_targeting"] = {"market": {"trigger_ratio": 2.0, "floor": 0.5, "ceiling": 1.0},
                                 "portfolio": {"target_vol": 0.15, "enforce_in_compliance": False}}
        validate_runtime_config(good)
        for part, key, bad in (("market", "floor", 0.0), ("market", "trigger_ratio", 0.5),
                               ("portfolio", "target_vol", 2.0),
                               ("portfolio", "enforce_in_compliance", "yes")):
            cfg = copy.deepcopy(good)
            cfg["vol_targeting"][part][key] = bad
            with self.assertRaises(ValueError):
                validate_runtime_config(cfg)


class TestTomorrowPlanShowsRealRules(unittest.TestCase):
    """明日计划的文案必须与真正生效的规则一致."""

    def _ctx(self):
        from datetime import datetime
        return {
            "status": "success", "updated_at": datetime.now().isoformat(),
            "data_quality_score": 90, "decision_locked": False,
            "regime": 3, "cap": 48, "base_cap": 60, "aiae_v1": 22.0,
            "erp_tier": "neutral", "erp_val": 4.5, "erp_label": "中性",
            "regime_info": {"emoji": "⚖️", "cn": "均衡配置", "color": "#3b82f6",
                            "action": "结构性配置", "desc": "核心+卫星", "position": "50-65%", "range": "15-28%"},
            "margin_heat": 2.0, "slope": 0.5, "slope_direction": "flat", "fund_position": 78,
            "vol_overlay": {"status": "ok", "factor": 0.8, "brake_on": True, "ratio": 2.5, "trigger_ratio": 2.0},
            "vol_budget": {"target_vol": 0.15, "portfolio_vol": 0.44, "invested_pct": 98.3,
                           "max_equity_pct": 33.2, "equity_excess_pp": 65.1, "effective_bets": 1.5,
                           "breach_count": 5},
        }

    def test_plan_reports_brake_and_budget(self):
        from services.position_engine import get_tomorrow_plan, get_vix_analysis

        plan = get_tomorrow_plan(get_vix_analysis(18.0), 50, aiae_ctx=self._ctx())
        self.assertEqual(plan["mode"], "decision")
        self.assertEqual(plan["primary_regime"]["base_cap"], 60)
        self.assertEqual(plan["primary_regime"]["cap"], 48)
        self.assertIn("60%→48%", plan["directives"][0]["text"])
        self.assertIn("尾部刹车", plan["directives"][2]["text"])
        self.assertNotIn("Cap×0.75", " ".join(d["text"] for d in plan["directives"]))
        self.assertTrue(plan["validators"]["vix"]["advisory_only"])
        self.assertEqual(plan["risk_panel"]["vol_budget"]["status"], "danger")
        self.assertEqual(plan["risk_panel"]["effective_position_cap"], 33.2)
        self.assertEqual(plan["risk_panel"]["overall_risk"], "high")


class TestDecisionView(unittest.TestCase):
    """决策页面板的数据源: 上限瀑布 / 约束来源 / 结论."""

    pf = {"status": "ok", "invested_pct": 98.3, "max_equity_pct": 33.2, "target_vol": 0.15,
          "sleeve_vol": 0.45, "portfolio_vol": 0.44, "positions": [], "trim_plan": []}
    mk = {"status": "ok", "factor": 1.0, "ratio": 1.5, "trigger_ratio": 2.0}
    ctx = {"decision_locked": False, "cap": 60, "base_cap": 60, "regime": 3, "regime_cn": "中性"}

    def test_portfolio_budget_binds_and_flags_danger(self):
        v = pv.build_decision_view(self.mk, self.pf, self.ctx, enforce=False)
        self.assertEqual(v["effective_cap_pct"], 33.2)
        self.assertEqual(v["verdict"]["binding"], "portfolio_budget")
        self.assertEqual(v["verdict"]["level"], "danger")
        self.assertEqual([s["key"] for s in v["waterfall"]], ["aiae", "market", "portfolio", "effective", "actual"])
        self.assertTrue(any("默认值" in c for c in v["caveats"]))

    def test_market_brake_can_bind(self):
        pf = dict(self.pf, max_equity_pct=80, invested_pct=40)
        v = pv.build_decision_view(dict(self.mk, factor=0.6), pf, self.ctx, enforce=True)
        self.assertEqual(v["effective_cap_pct"], 36.0)
        self.assertEqual(v["verdict"]["binding"], "aiae_vol")
        self.assertEqual(v["verdict"]["level"], "ok")

    def test_room_is_not_a_buy_signal(self):
        pf = dict(self.pf, invested_pct=10)
        v = pv.build_decision_view(self.mk, pf, self.ctx, enforce=True)
        self.assertEqual(v["verdict"]["level"], "room")
        self.assertIn("信号确认", v["verdict"]["instruction"])

    def test_locked_aiae_falls_back_to_portfolio_budget(self):
        v = pv.build_decision_view(self.mk, self.pf, {"decision_locked": True, "cap": 60}, enforce=True)
        self.assertIsNone(v["waterfall"][0]["value"])
        self.assertEqual(v["effective_cap_pct"], 33.2)
        self.assertTrue(any("AIAE" in c for c in v["caveats"]))

    def test_no_portfolio_is_insufficient(self):
        v = pv.build_decision_view(self.mk, {"status": "empty"}, None, enforce=True)
        self.assertEqual(v["status"], "insufficient")
        self.assertEqual(v["verdict"]["level"], "unknown")


class TestInstitutionalAnalytics(unittest.TestCase):
    """执行前后 / 压力情景 / 草案选择 / 风险预算再利用 / 流动性 / 估计区间."""

    @staticmethod
    def _basket(seed=41, n_days=400):
        rng = np.random.default_rng(seed)
        idx = pd.bdate_range("2024-01-01", periods=n_days)
        theme = rng.normal(0, 0.025, n_days)
        series = {"588000.SH": pd.Series(100 * np.exp(np.cumsum(theme)), index=idx),
                  "000300.SH": pd.Series(100 * np.exp(np.cumsum(theme * 0.5 + rng.normal(0, 0.006, n_days))), index=idx),
                  "512890.SH": pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.008, n_days))), index=idx)}
        positions = {"588000.SH": {"name": "科创50ETF", "broker_market_value": 300}}
        for i in range(4):
            code = f"68801{i}.SH"
            series[code] = pd.Series(100 * np.exp(np.cumsum(1.2 * theme + rng.normal(0, 0.012, n_days))), index=idx)
            positions[code] = {"name": f"S{i}", "broker_market_value": 160}
        positions["300999.SZ"] = {"name": "无行情股", "broker_market_value": 40}
        amounts = {k: pd.Series(1e9, index=idx) for k in series}
        return series, positions, amounts

    def _run(self, **cfg):
        series, positions, amounts = self._basket()
        c = dict(pv.DEFAULT_PORTFOLIO_VOL_CONFIG, **cfg)
        return pv.compute_portfolio_vol(positions, 1000, lambda k: series.get(k), c,
                                        amount_loader=lambda k: amounts.get(k))

    def test_pre_trade_reduces_risk_in_money_terms(self):
        r = self._run()
        cur, aft = r["pre_trade"]["current"], r["pre_trade"]["after"]
        self.assertLess(aft["portfolio_vol"], cur["portfolio_vol"])
        self.assertLess(aft["es_20d_95_amt"], cur["es_20d_95_amt"])
        self.assertGreater(cur["es_20d_95_amt"], cur["var_1d_95_amt"])
        self.assertLessEqual(aft["portfolio_vol"], r["target_vol"] + 1e-3)

    def test_stress_losses_are_negative_and_shrink_after_trim(self):
        r = self._run()
        keys = [x["key"] for x in r["stress"]]
        self.assertEqual(keys, ["mkt_5", "thm_20", "thm_40", "gap"])
        for x in r["stress"]:
            self.assertLess(x["current_pct"], 0)
            self.assertGreaterEqual(x["after_pct"], x["current_pct"])
        thm = {x["key"]: x for x in r["stress"]}
        self.assertAlmostEqual(thm["thm_40"]["current_pct"], 2 * thm["thm_20"]["current_pct"], delta=0.05)

    def test_recommendation_rule_prefers_structure_unless_big_saving(self):
        r = self._run()
        tc = r["trim_compare"]
        expected = "min_turnover" if tc["saving_pct"] >= 15 else "proportional"
        self.assertEqual(tc["recommended"], expected)
        r2 = self._run(min_turnover_saving=0.0)
        self.assertEqual(r2["trim_compare"]["recommended"], "min_turnover")

    def test_diversifier_frontier_uses_stress_correlation(self):
        r = self._run()
        d = [x for x in r["diversifiers"] if x["ts_code"] == "512890.SH"][0]
        adds = [f["add_pct"] for f in d["frontier"]]
        self.assertEqual(adds[0], 0.0)                     # 已在目标波动上, 不让出主题仓位就无空间
        self.assertTrue(all(b >= a for a, b in zip(adds, adds[1:])))
        loose = self._run(stress_corr_floor=-1.0)
        d2 = [x for x in loose["diversifiers"] if x["ts_code"] == "512890.SH"][0]
        self.assertGreaterEqual(d2["frontier"][1]["add_pct"], d["frontier"][1]["add_pct"])

    def test_liquidity_and_estimation_band(self):
        r = self._run()
        self.assertGreater(r["liquidity"]["covered"], 0)
        self.assertLess(r["liquidity"]["max_participation_pct"], 1)
        self.assertIsNotNone(r["vol_range"])
        self.assertLessEqual(r["vol_range"]["low"], r["portfolio_vol"])
        self.assertGreaterEqual(r["vol_range"]["high"], r["portfolio_vol"])
        est = [p for p in r["positions"] if p["ts_code"] == "300999.SZ"][0]
        self.assertTrue(est["beta_estimated"])

    def test_instruction_follows_recommended_method(self):
        r = self._run()
        v = pv.build_decision_view({"status": "ok", "factor": 1.0}, r,
                                   {"decision_locked": False, "cap": 90, "regime": 2}, enforce=False)
        word = "最小换手" if r["trim_compare"]["recommended"] == "min_turnover" else "等比缩放"
        if v["verdict"]["level"] == "danger":
            self.assertIn(word, v["verdict"]["instruction"])


class TestV3Architecture(unittest.TestCase):
    """V3: 历史回放 / 风险归因分桶 / 行情新鲜度 / 单票超限结论 / 指纹."""

    @staticmethod
    def _fat_tail_basket(seed=51, n=420, stale_tail=0):
        rng = np.random.default_rng(seed)
        idx = pd.bdate_range("2025-01-01", periods=n)
        theme = rng.standard_t(3, n) * 0.015
        series = {"588000.SH": pd.Series(100 * np.exp(np.cumsum(theme)), index=idx),
                  "000300.SH": pd.Series(100 * np.exp(np.cumsum(0.5 * theme + rng.normal(0, 0.005, n))), index=idx)}
        positions = {"588000.SH": {"name": "科创50ETF", "broker_market_value": 300}}
        for i, code in enumerate(("688011.SH", "300011.SZ", "600011.SH")):
            s = pd.Series(100 * np.exp(np.cumsum(1.2 * theme + rng.normal(0, 0.012, n))), index=idx)
            series[code] = s.iloc[:-stale_tail] if (stale_tail and i == 0) else s
            positions[code] = {"name": f"S{i}", "broker_market_value": 200}
        return series, positions, idx

    def _run(self, **kw):
        series, positions, idx = self._fat_tail_basket(**kw)
        return pv.compute_portfolio_vol(positions, 1000, lambda k: series.get(k),
                                        dict(pv.DEFAULT_PORTFOLIO_VOL_CONFIG), asof=idx[-1].date())

    def test_replay_reports_fat_tails_and_shrinks_after_trim(self):
        r = self._run()
        rp = r["replay"]
        self.assertIsNotNone(rp)
        self.assertEqual(rp["window"], 250)
        cur, aft = rp["current"], rp["after"]
        self.assertLess(cur["max_drawdown_pct"], 0)
        self.assertGreater(aft["max_drawdown_pct"], cur["max_drawdown_pct"])   # 回撤更浅
        self.assertLess(aft["es_1d_95_amt"], cur["es_1d_95_amt"])
        self.assertGreaterEqual(cur["es_1d_95_amt"], cur["var_1d_95_amt"])
        self.assertGreater(rp["tail_multiplier"], 1.0)                       # t(3) 尾部厚于正态
        self.assertEqual(len(rp["path"]["dates"]), len(rp["path"]["current"]))
        self.assertEqual(rp["path"]["dates"][-1], rp["end"])

    def test_replay_fills_gaps_with_theme_beta(self):
        r = self._run(stale_tail=15)
        self.assertGreater(r["replay"]["fill_share"], 0)
        self.assertLess(r["replay"]["fill_share"], 0.05)

    def test_buckets_partition_weight_and_risk(self):
        r = self._run()
        b = {x["key"]: x for x in r["risk_by_bucket"]}
        self.assertEqual(set(b), {"star", "chinext", "main", "etf"})
        self.assertAlmostEqual(sum(x["weight_pct"] for x in b.values()), r["invested_pct"], delta=0.05)
        self.assertAlmostEqual(sum(x["risk_share"] for x in b.values()), 1.0, delta=0.01)

    def test_stale_prices_are_flagged_not_silently_used(self):
        r = self._run(stale_tail=15)
        dq = r["data_quality"]
        self.assertEqual(dq["stale_names"], ["S0"])
        self.assertGreater(dq["stale_weight"], 0)
        p = [x for x in r["positions"] if x["ts_code"] == "688011.SH"][0]
        self.assertTrue(p["price_stale"])
        fresh = self._run()
        self.assertEqual(fresh["data_quality"]["stale_names"], [])

    def test_gap_scenario_follows_config(self):
        series, positions, idx = self._fat_tail_basket()
        r3 = pv.compute_portfolio_vol(positions, 1000, lambda k: series.get(k),
                                      dict(pv.DEFAULT_PORTFOLIO_VOL_CONFIG, gap_limit_days=3))
        g = [x for x in r3["stress"] if x["key"] == "gap"][0]
        self.assertIn("3连跌停", g["name"])
        expected = -(0.3 * 0.10 + 0.2 * (1 - 0.8 ** 3) * 2 + 0.2 * (1 - 0.9 ** 3)) * 100
        self.assertAlmostEqual(g["current_pct"], expected, places=1)

    def test_single_name_breach_escalates_verdict_inside_budget(self):
        pf = {"status": "ok", "invested_pct": 30, "max_equity_pct": 33, "target_vol": 0.15,
              "sleeve_vol": 0.45, "breach_count": 2, "cap_excess_amount": 52000}
        v = pv.build_decision_view({"status": "ok", "factor": 1.0}, pf,
                                   {"decision_locked": False, "cap": 60}, enforce=True)
        self.assertEqual(v["verdict"]["level"], "warning")
        self.assertIn("单票上限", v["verdict"]["text"])
        self.assertIn("5.2万", v["verdict"]["instruction"])

    def test_meta_and_schema(self):
        r = self._run()
        self.assertEqual(r["meta"]["schema"], pv.SCHEMA_VERSION)
        self.assertGreaterEqual(r["meta"]["elapsed_ms"], 0)
        pos = {"510300.SH": {"broker_market_value": 100}}
        cfg = dict(pv.DEFAULT_PORTFOLIO_VOL_CONFIG)
        a = pv._fingerprint(pos, 1000, cfg, date(2026, 10, 22))
        self.assertEqual(a, pv._fingerprint(pos, 1000, cfg, date(2026, 10, 22)))
        self.assertNotEqual(a, pv._fingerprint({"510300.SH": {"broker_market_value": 101}}, 1000, cfg, date(2026, 10, 22)))
        self.assertNotEqual(a, pv._fingerprint(pos, 1000, dict(cfg, target_vol=0.2), date(2026, 10, 22)))

    def test_store_path_caches_by_fingerprint(self):
        from unittest import mock
        series, positions, idx = self._fat_tail_basket()
        store = {"positions": positions, "broker_total_asset": 1000, "import_date": "2026-10-22"}
        pv.clear_cache()
        with mock.patch.object(pv, "default_price_loader", lambda k: series.get(k)), \
             mock.patch.object(pv, "default_amount_loader", lambda k: None):
            a = pv.compute_from_store(store)
            b = pv.compute_from_store(store)
            c = pv.compute_from_store(store, use_cache=False)
        self.assertEqual(a["meta"]["cache"], "miss")
        self.assertEqual(b["meta"]["cache"], "hit")
        self.assertEqual(c["meta"]["cache"], "miss")
        self.assertEqual(a["meta"]["fingerprint"], b["meta"]["fingerprint"])
        self.assertEqual(a["portfolio_vol"], b["portfolio_vol"])
        self.assertIsNotNone(a["data_quality"]["positions_age_days"])
        pv.clear_cache()

    def test_trim_terminates_with_tiny_step(self):
        w = np.array([0.5, 0.5]); cov = np.array([[0.16, 0.12], [0.12, 0.16]])
        x = pv._min_turnover_trim(w, np.array([1.0, 1.0]), cov, 0.10, 1e-6)
        self.assertLessEqual(math.sqrt(float(x @ cov @ x)), 0.10 + 1e-3)


if __name__ == "__main__":
    unittest.main()
