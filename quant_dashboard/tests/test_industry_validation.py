"""Point-in-time industry validation and promotion-gate contracts."""

import copy
from datetime import datetime, timezone

import pandas as pd

from services.industry_validation import (
    build_universe_fingerprint,
    build_policy_fingerprint,
    evaluate_validation_artifact,
    point_in_time_universe_coverage,
    resolve_universe_codes,
    load_industry_validation_status,
    simulate_candidate_trade,
    summarize_portfolio_periods,
    wilson_lower_bound,
)
from services.strategy_params import DEFAULT_RUNTIME_CONFIG


def _runtime():
    return copy.deepcopy(DEFAULT_RUNTIME_CONFIG)


def _complete_universe():
    return {"schema_version": 1, "complete_history": True, "members": []}


def _passing_artifact(runtime):
    return {
        "schema_version": 1,
        "model_id": "industry-alpha-v1",
        "generated_at": "2026-09-06T08:00:00+00:00",
        "data_end_date": "2026-09-04",
        "policy_fingerprint": build_policy_fingerprint(runtime),
        "methodology": {
            "point_in_time_universe": True,
            "universe_fingerprint": build_universe_fingerprint(_complete_universe()),
            "historical_aiae_used": False,
            "entry": "next_session_open",
        },
        "holdout": {
            "signals": 60,
            "win_rate": 0.60,
            "profit_factor": 1.50,
            "avg_excess_return": 0.01,
            "max_drawdown": -0.12,
            "by_regime": {
                "BEAR": {"signals": 20, "win_rate": 0.60, "profit_factor": 1.4, "avg_excess_return": 0.01, "portfolio": {"periods": 15, "positive_period_rate": 0.60, "wilson_lower_95": 0.36, "profit_factor": 1.4, "avg_excess_return": 0.01, "max_drawdown": -0.10}},
                "RANGE": {"signals": 20, "win_rate": 0.60, "profit_factor": 1.4, "avg_excess_return": 0.01, "portfolio": {"periods": 15, "positive_period_rate": 0.60, "wilson_lower_95": 0.36, "profit_factor": 1.4, "avg_excess_return": 0.01, "max_drawdown": -0.10}},
                "BULL": {"signals": 20, "win_rate": 0.60, "profit_factor": 1.4, "avg_excess_return": 0.01, "portfolio": {"periods": 15, "positive_period_rate": 0.60, "wilson_lower_95": 0.36, "profit_factor": 1.4, "avg_excess_return": 0.01, "max_drawdown": -0.10}},
            },
        },
    }


def test_promotion_is_recomputed_and_never_trusts_artifact_passed_flag():
    runtime = _runtime()
    artifact = _passing_artifact(runtime)
    artifact["passed"] = True
    artifact["holdout"]["win_rate"] = 0.20

    status = evaluate_validation_artifact(
        artifact,
        runtime_config=runtime,
        now=datetime(2026, 9, 6, 12, tzinfo=timezone.utc),
        universe_history=_complete_universe(),
    )

    assert status["ready"] is False
    assert "OOS_WIN_RATE_BELOW_GATE" in status["reasons"]


def test_complete_fresh_evidence_can_promote_the_exact_policy_fingerprint():
    runtime = _runtime()

    status = evaluate_validation_artifact(
        _passing_artifact(runtime),
        runtime_config=runtime,
        now=datetime(2026, 9, 6, 12, tzinfo=timezone.utc),
        universe_history=_complete_universe(),
    )

    assert status["ready"] is True
    assert status["stage"] == "promoted"
    assert status["reasons"] == []


def test_policy_fingerprint_mismatch_and_survivorship_bias_fail_closed():
    runtime = _runtime()
    artifact = _passing_artifact(runtime)
    artifact["policy_fingerprint"] = "old-policy"
    artifact["methodology"]["point_in_time_universe"] = False

    status = evaluate_validation_artifact(
        artifact,
        runtime_config=runtime,
        now=datetime(2026, 9, 6, 12, tzinfo=timezone.utc),
        universe_history={"schema_version": 1, "complete_history": False, "members": []},
    )

    assert status["ready"] is False
    assert "POLICY_FINGERPRINT_MISMATCH" in status["reasons"]
    assert "POINT_IN_TIME_UNIVERSE_UNAVAILABLE" in status["reasons"]


def test_artifact_and_underlying_market_data_have_independent_freshness_gates():
    runtime = _runtime()
    artifact = _passing_artifact(runtime)
    artifact["generated_at"] = "2026-07-01T00:00:00+00:00"
    artifact["data_end_date"] = "2026-06-04"

    status = evaluate_validation_artifact(
        artifact,
        runtime_config=runtime,
        now=datetime(2026, 9, 6, 12, tzinfo=timezone.utc),
        universe_history=_complete_universe(),
    )

    assert "VALIDATION_ARTIFACT_STALE" in status["reasons"]
    assert "VALIDATION_DATA_STALE" in status["reasons"]


def test_missing_artifact_is_an_explicit_fail_closed_state(tmp_path):
    status = load_industry_validation_status(path=tmp_path / "missing.json")

    assert status["ready"] is False
    assert status["stage"] == "missing"
    assert status["reasons"] == ["VALIDATION_ARTIFACT_MISSING"]


def test_point_in_time_universe_resolution_never_infers_unknown_membership_dates():
    manifest = {
        "schema_version": 1,
        "complete_history": False,
        "members": [
            {"code": "OLD.SH", "membership_from": "2020-01-01", "membership_to": "2022-12-31"},
            {"code": "LIVE.SH", "membership_from": "2021-06-01", "membership_to": None},
            {"code": "UNKNOWN.SH", "membership_from": None, "membership_to": None},
        ],
    }

    assert resolve_universe_codes(manifest, "2022-06-01") == {"OLD.SH", "LIVE.SH"}
    assert resolve_universe_codes(manifest, "2024-01-01") == {"LIVE.SH"}
    assert "UNKNOWN.SH" not in resolve_universe_codes(manifest, "2024-01-01")


def test_prospective_universe_is_complete_only_from_its_frozen_date():
    manifest = {
        "schema_version": 2,
        "complete_history": False,
        "coverage": {
            "mode": "prospective",
            "complete_from": "2026-09-06",
            "complete_through": None,
        },
        "source": {"provider": "test", "snapshot_sha256": "a" * 64},
        "members": [],
    }

    assert point_in_time_universe_coverage(manifest, "2020-01-01", "2026-09-04") is False
    assert point_in_time_universe_coverage(manifest, "2026-09-06", "2026-09-07") is True


def test_universe_resolution_enforces_instrument_and_membership_intervals():
    manifest = {
        "schema_version": 2,
        "complete_history": False,
        "coverage": {
            "mode": "prospective",
            "complete_from": "2026-09-01",
            "complete_through": None,
        },
        "source": {"provider": "test", "snapshot_sha256": "b" * 64},
        "members": [
            {
                "code": "LIVE.SH",
                "instrument_list_date": "2026-08-01",
                "instrument_delist_date": None,
                "membership_from": "2026-09-01",
                "membership_to": None,
            },
            {
                "code": "LATE.SH",
                "instrument_list_date": "2026-09-10",
                "instrument_delist_date": None,
                "membership_from": "2026-09-10",
                "membership_to": None,
            },
            {
                "code": "DELISTED.SH",
                "instrument_list_date": "2020-01-01",
                "instrument_delist_date": "2026-09-05",
                "membership_from": "2026-09-01",
                "membership_to": None,
            },
        ],
    }

    assert resolve_universe_codes(manifest, "2026-09-04") == {"LIVE.SH", "DELISTED.SH"}
    assert resolve_universe_codes(manifest, "2026-09-07") == {"LIVE.SH"}
    assert resolve_universe_codes(manifest, "2026-09-11") == {"LIVE.SH", "LATE.SH"}


def test_universe_lineage_mismatch_invalidates_otherwise_passing_evidence():
    runtime = _runtime()
    universe = {"schema_version": 1, "complete_history": True, "members": []}
    artifact = _passing_artifact(runtime)
    artifact["methodology"]["universe_fingerprint"] = "old-universe"

    status = evaluate_validation_artifact(
        artifact,
        runtime_config=runtime,
        now=datetime(2026, 9, 6, 12, tzinfo=timezone.utc),
        universe_history=universe,
    )

    assert build_universe_fingerprint(universe) != "old-universe"
    assert status["ready"] is False
    assert "UNIVERSE_FINGERPRINT_MISMATCH" in status["reasons"]


def test_portfolio_period_summary_deduplicates_correlated_same_day_signals():
    trades = [
        {"signal_date": "2026-01-01", "net_return": 0.20, "excess_return": 0.10},
        {"signal_date": "2026-01-01", "net_return": 0.00, "excess_return": -0.02},
        {"signal_date": "2026-02-01", "net_return": -0.10, "excess_return": -0.04},
    ]

    summary = summarize_portfolio_periods(trades)

    assert summary["periods"] == 2
    assert summary["positive_period_rate"] == 0.5
    assert summary["profit_factor"] == 1.0
    assert summary["avg_excess_return"] == 0.0
    assert summary["max_drawdown"] == -0.1
    assert summary["average_names"] == 1.5


def test_wilson_lower_bound_penalizes_small_apparent_win_rates():
    assert wilson_lower_bound(6, 10) == 0.312674
    assert wilson_lower_bound(0, 0) is None


def test_regime_lifecycle_never_turns_shadow_or_disabled_evidence_executable():
    runtime = _runtime()
    status = evaluate_validation_artifact(
        _passing_artifact(runtime),
        runtime_config=runtime,
        now=datetime(2026, 9, 6, 12, tzinfo=timezone.utc),
        universe_history=_complete_universe(),
    )

    assert status["regime_statuses"]["BULL"]["lifecycle"] == "shadow"
    assert status["regime_statuses"]["BULL"]["statistical_ready"] is True
    assert status["regime_statuses"]["BULL"]["execution_ready"] is False
    assert status["regime_statuses"]["BEAR"]["lifecycle"] == "disabled"
    assert status["regime_statuses"]["BEAR"]["execution_ready"] is False


def test_trade_simulation_enters_next_open_and_applies_runtime_stop_without_lookahead():
    frame = pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-01", periods=8, freq="D"),
            "open": [100, 102, 101, 95, 93, 92, 94, 96],
            "close": [100, 101, 99, 94, 92, 93, 95, 97],
        }
    )

    trade = simulate_candidate_trade(
        frame,
        signal_index=0,
        holding_days=5,
        stop_loss=0.05,
        round_trip_cost_bps=20,
        ma_exit_days=None,
    )

    assert trade["signal_date"] == "2026-01-01"
    assert trade["entry_date"] == "2026-01-02"
    assert trade["entry_price"] == 102.0
    assert trade["exit_date"] == "2026-01-04"
    assert trade["exit_reason"] == "STOP_LOSS"
    assert trade["gross_return"] == round(94 / 102 - 1, 8)
    assert trade["net_return"] == round(94 / 102 - 1 - 0.002, 8)


def test_trade_simulation_converts_raw_open_to_adjusted_price_basis():
    frame = pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-01", periods=4, freq="D"),
            "open": [100, 102, 104, 106],
            "close": [50, 51, 52, 53],
            "raw_close": [100, 102, 104, 106],
        }
    )

    trade = simulate_candidate_trade(
        frame,
        signal_index=0,
        holding_days=2,
        stop_loss=0.10,
        round_trip_cost_bps=0,
        ma_exit_days=None,
    )

    assert trade["entry_price"] == 51.0
    assert trade["exit_price"] == 52.0
    assert trade["gross_return"] == round(52 / 51 - 1, 8)
