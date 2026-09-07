"""Institutional industry eligibility policy contracts."""

from services.industry_policy import (
    build_industry_abstention_plan,
    build_industry_decision_context,
    build_industry_liquidity_profile,
    evaluate_industry_candidate,
)


def _quality(**overrides):
    data = {
        "decision_locked": False,
        "is_usable": True,
        "reasons": [],
        "expected_trade_date": "20260904",
    }
    data.update(overrides)
    return data


def _market(**overrides):
    data = {
        "status": "ok",
        "latest_date": "20260904",
        "regime": "BEAR",
        "aiae_usable": True,
        "aiae_decision_locked": False,
        "aiae_reason": None,
        "aiae_cap": 53,
        "audit_cap": 95,
    }
    data.update(overrides)
    return data


def _candidate(**overrides):
    data = {
        "alpha_score": 80.0,
        "trend_strength": {
            "above_ma20": True,
            "above_ma60": True,
            "ma20_slope": 0.2,
        },
        "risk_alerts": [],
        "execution_quality": {
            "lookback_days": 20,
            "valid_amount_days": 20,
            "median_turnover_cny": 100_000_000,
            "latest_turnover_cny": 120_000_000,
            "capacity_at_participation_cny": 2_000_000,
            "min_median_turnover_cny": 50_000_000,
            "max_participation_rate": 0.02,
            "data_complete": True,
            "median_turnover_pass": True,
            "pretrade_quote_required": True,
        },
    }
    data.update(overrides)
    return data


def test_bear_regime_uses_canonical_gate_and_single_industry_cap():
    context = build_industry_decision_context(
        _quality(), _market(), model_validation_ready=True
    )
    result = evaluate_industry_candidate(_candidate(), context)

    assert context["score_gate"] == 75
    assert context["single_position_cap"] == 12
    assert context["effective_total_cap"] == 35
    assert context["stop_loss_pct"] == 5
    assert result["policy_qualified"] is True
    assert result["advice_action"] == "eligible_buy"
    assert result["position_cap"] == "单行业上限12%"
    assert result["execution"]["allowed"] is True
    assert result["execution"]["order_release_allowed"] is False
    assert result["execution"]["pretrade_quote_required"] is True


def test_score_below_current_regime_gate_is_watch_only():
    context = build_industry_decision_context(
        _quality(), _market(), model_validation_ready=True
    )
    result = evaluate_industry_candidate(
        _candidate(alpha_score=74.9), context
    )

    assert result["policy_qualified"] is False
    assert result["advice_action"] == "watch"
    assert "SCORE_BELOW_REGIME_GATE" in result["veto_reasons"]


def test_policy_qualified_candidate_stays_non_executable_until_model_validation():
    context = build_industry_decision_context(
        _quality(), _market(), model_validation_ready=False
    )
    result = evaluate_industry_candidate(_candidate(), context)

    assert context["decision_locked"] is True
    assert context["hard_locked"] is False
    assert context["decision_lock_reasons"] == ["MODEL_VALIDATION_PENDING"]
    assert result["policy_qualified"] is True
    assert result["advice_action"] == "candidate_eligible"
    assert result["position_cap"] == "0%（待样本外验证）"
    assert result["execution"]["proposed_single_position_cap"] == 12


def test_validation_evidence_reasons_are_exposed_without_becoming_operational_gates():
    context = build_industry_decision_context(
        _quality(),
        _market(),
        model_validation_status={
            "ready": False,
            "stage": "shadow",
            "reasons": [
                "VALIDATION_DATA_STALE",
                "POINT_IN_TIME_UNIVERSE_UNAVAILABLE",
            ],
            "holdout": {"signals": 18, "win_rate": 0.5},
        },
    )

    assert context["hard_locked"] is False
    assert context["model_validation_ready"] is False
    assert context["model_validation"]["stage"] == "shadow"
    assert context["decision_lock_reasons"] == [
        "MODEL_VALIDATION_PENDING",
        "VALIDATION_DATA_STALE",
        "POINT_IN_TIME_UNIVERSE_UNAVAILABLE",
    ]


def test_disabled_current_regime_is_an_explicit_hard_lock():
    context = build_industry_decision_context(
        _quality(),
        _market(regime="BEAR"),
        model_validation_status={
            "ready": True,
            "reasons": [],
            "regime_statuses": {
                "BEAR": {
                    "lifecycle": "disabled",
                    "statistical_ready": False,
                    "execution_ready": False,
                    "reasons": ["OOS_BEAR_SAMPLE_TOO_SMALL"],
                }
            },
        },
    )

    assert context["hard_locked"] is True
    assert "REGIME_MODEL_DISABLED" in context["decision_lock_reasons"]
    assert context["regime_model_validation"]["lifecycle"] == "disabled"


def test_aiae_unusable_is_a_hard_lock():
    context = build_industry_decision_context(
        _quality(),
        _market(
            aiae_usable=False,
            aiae_decision_locked=True,
            aiae_reason="stale",
            aiae_cap=None,
        ),
        model_validation_ready=True,
    )
    result = evaluate_industry_candidate(_candidate(), context)

    assert context["hard_locked"] is True
    assert "AIAE_STALE" in context["decision_lock_reasons"]
    assert result["advice_action"] == "data_locked"
    assert result["position_cap"] == "0%"


def test_regime_data_older_than_industry_data_is_a_hard_lock():
    context = build_industry_decision_context(
        _quality(), _market(latest_date="20260903"), model_validation_ready=True
    )

    assert context["hard_locked"] is True
    assert "REGIME_DATA_STALE" in context["decision_lock_reasons"]


def test_danger_alert_is_a_hard_candidate_veto():
    context = build_industry_decision_context(
        _quality(), _market(), model_validation_ready=True
    )
    result = evaluate_industry_candidate(
        _candidate(risk_alerts=[{"level": "danger", "metric": "crowd"}]),
        context,
    )

    assert result["policy_qualified"] is False
    assert result["advice_action"] == "avoid"
    assert "DANGER_RISK_ALERT" in result["veto_reasons"]


def test_crash_regime_never_allows_new_industry_positions():
    context = build_industry_decision_context(
        _quality(), _market(regime="CRASH", aiae_cap=20), model_validation_ready=True
    )
    result = evaluate_industry_candidate(_candidate(alpha_score=100), context)

    assert context["hard_locked"] is True
    assert "REGIME_CRASH_LOCK" in context["decision_lock_reasons"]
    assert result["advice_action"] == "data_locked"


def test_liquidity_profile_converts_tushare_thousand_cny_and_sizes_capacity():
    profile = build_industry_liquidity_profile([100_000.0] * 20)

    assert profile["median_turnover_cny"] == 100_000_000
    assert profile["latest_turnover_cny"] == 100_000_000
    assert profile["capacity_at_participation_cny"] == 2_000_000
    assert profile["data_complete"] is True
    assert profile["median_turnover_pass"] is True
    assert profile["pretrade_quote_required"] is True


def test_candidate_is_vetoed_when_median_turnover_is_below_execution_floor():
    context = build_industry_decision_context(
        _quality(), _market(), model_validation_ready=True
    )
    profile = build_industry_liquidity_profile([2_500.0] * 20)
    result = evaluate_industry_candidate(
        _candidate(execution_quality=profile), context
    )

    assert result["policy_qualified"] is False
    assert result["execution"]["allowed"] is False
    assert result["execution"]["order_release_allowed"] is False
    assert result["execution"]["capacity_at_participation_cny"] == 50_000
    assert "MEDIAN_TURNOVER_20D_BELOW_MINIMUM" in result["veto_reasons"]


def test_candidate_fails_closed_when_liquidity_history_is_incomplete():
    context = build_industry_decision_context(
        _quality(), _market(), model_validation_ready=True
    )
    profile = build_industry_liquidity_profile([100_000.0] * 19 + [None])
    result = evaluate_industry_candidate(
        _candidate(execution_quality=profile), context
    )

    assert profile["data_complete"] is False
    assert "LIQUIDITY_DATA_INCOMPLETE" in result["veto_reasons"]
    assert result["execution"]["allowed"] is False


def test_abstention_plan_ranks_watchlist_without_granting_execution():
    context = build_industry_decision_context(
        _quality(),
        _market(regime="BEAR"),
        model_validation_status={
            "ready": False,
            "reasons": ["OOS_BEAR_SAMPLE_TOO_SMALL"],
            "regime_statuses": {
                "BEAR": {
                    "lifecycle": "disabled",
                    "statistical_ready": False,
                    "execution_ready": False,
                    "reasons": ["OOS_BEAR_SAMPLE_TOO_SMALL"],
                }
            },
        },
    )
    leading = {
        "ts_code": "LEAD.SH",
        "name": "领先观察",
        **_candidate(alpha_score=56.9),
    }
    trend_repair = {
        "ts_code": "TREND.SH",
        "name": "趋势修复",
        **_candidate(
            alpha_score=74.0,
            trend_strength={
                "above_ma20": False,
                "above_ma60": False,
                "ma20_slope": -0.1,
            },
        ),
    }
    risk_veto = {
        "ts_code": "RISK.SH",
        "name": "风险否决",
        **_candidate(
            alpha_score=90.0,
            risk_alerts=[{"level": "danger", "metric": "crowding"}],
        ),
    }
    evaluated = []
    for item in (risk_veto, trend_repair, leading):
        enriched = dict(item)
        enriched.update(evaluate_industry_candidate(enriched, context))
        evaluated.append(enriched)

    plan = build_industry_abstention_plan(evaluated, context)

    assert plan["action"] == "NO_TRADE"
    assert plan["execution_allowed"] is False
    assert plan["decision_lock_reasons"] == ["REGIME_MODEL_DISABLED"]
    assert [item["code"] for item in plan["watchlist"]] == [
        "LEAD.SH",
        "TREND.SH",
        "RISK.SH",
    ]
    assert plan["watchlist"][0]["readiness_tier"] == "LEADING_WATCH"
    assert plan["watchlist"][0]["score_gap"] == -18.1
    assert plan["watchlist"][0]["remaining_conditions"] == [
        "SCORE_BELOW_REGIME_GATE"
    ]
    assert plan["watchlist"][1]["readiness_tier"] == "TREND_REPAIR"
    assert plan["watchlist"][2]["readiness_tier"] == "RISK_VETO"
    assert all(item["execution_allowed"] is False for item in plan["watchlist"])


def test_abstention_plan_only_calls_small_score_gap_near_trigger():
    context = build_industry_decision_context(
        _quality(), _market(), model_validation_ready=False
    )
    item = {
        "ts_code": "NEAR.SH",
        "name": "临近触发",
        **_candidate(alpha_score=72.0),
    }
    item.update(evaluate_industry_candidate(item, context))

    plan = build_industry_abstention_plan([item], context)

    assert plan["watchlist"][0]["readiness_tier"] == "NEAR_TRIGGER"
    assert plan["watchlist"][0]["passed_checks"] == 6
    assert plan["watchlist"][0]["total_checks"] == 7
    assert plan["watchlist"][0]["execution_allowed"] is False


def test_abstention_plan_demotes_an_illiquid_high_score_candidate():
    context = build_industry_decision_context(
        _quality(), _market(), model_validation_ready=False
    )
    liquid = {
        "ts_code": "LIQUID.SH",
        "name": "可成交观察",
        **_candidate(alpha_score=72.0),
    }
    illiquid = {
        "ts_code": "THIN.SH",
        "name": "低流动性",
        **_candidate(
            alpha_score=90.0,
            execution_quality=build_industry_liquidity_profile([2_500.0] * 20),
        ),
    }
    evaluated = []
    for item in (illiquid, liquid):
        enriched = dict(item)
        enriched.update(evaluate_industry_candidate(enriched, context))
        evaluated.append(enriched)

    plan = build_industry_abstention_plan(evaluated, context)

    assert plan["watchlist"][0]["code"] == "LIQUID.SH"
    assert plan["watchlist"][1]["readiness_tier"] == "LIQUIDITY_CONSTRAINED"
    assert plan["watchlist"][1]["capacity_at_participation_cny"] == 50_000
