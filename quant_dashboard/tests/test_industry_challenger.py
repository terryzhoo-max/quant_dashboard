"""Pre-registered BULL-only industry challenger contracts."""

import copy
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from services.industry_challenger import (
    build_challenger_fingerprint,
    evaluate_challenger_artifact,
    rank_challenger_candidates,
    split_challenger_trades,
    validate_challenger_spec,
)
from services.industry_validation import build_universe_fingerprint


def _spec():
    return {
        "schema_version": 1,
        "spec_revision": 1,
        "model_id": "industry-bull-rs-v1",
        "lifecycle": "shadow",
        "frozen_at": "2026-09-06T15:00:00+00:00",
        "backtest_start": "2020-01-01",
        "design_data_end": "2023-12-31",
        "validation_start": "2024-01-01",
        "validation_end": "2025-12-31",
        "confirmation_start": "2026-01-01",
        "allowed_regimes": ["BULL"],
        "rebalance_days": 20,
        "holding_days": 20,
        "min_history_days": 120,
        "top_n": 2,
        "round_trip_cost_bps": 20,
        "filters": {
            "min_return_20d": 0.0,
            "min_return_60d": 0.0,
            "max_annualized_volatility_20d": 0.60,
        },
        "weights": {"rps_20d": 0.50, "rps_60d": 0.30, "low_volatility": 0.20},
        "promotion": {
            "min_confirmation_periods": 8,
            "min_positive_period_rate": 0.55,
            "min_wilson_lower_95": 0.30,
            "min_profit_factor": 1.20,
            "min_avg_excess_return": 0.0,
            "max_drawdown": 0.15,
            "require_point_in_time_universe": True,
            "max_artifact_age_days": 35,
            "max_data_lag_days": 10,
        },
        "artifact_path": "config/industry_challenger_validation.json",
        "forward_ledger_path": "data_lake/industry_challenger_forward.jsonl",
    }


def _frame(daily_return, *, periods=150):
    dates = pd.bdate_range("2025-01-01", periods=periods)
    close = 100 * np.cumprod(np.repeat(1 + daily_return, periods))
    return pd.DataFrame({
        "trade_date": dates,
        "open": close,
        "close": close,
        "raw_close": close,
        "amount": np.repeat(1_000_000.0, periods),
    })


def _complete_universe():
    return {
        "schema_version": 1,
        "complete_history": True,
        "members": [
            {"code": code, "membership_from": "2020-01-01", "membership_to": None}
            for code in ("STRONG", "MEDIUM", "WEAK")
        ],
    }


def _passing_artifact(spec):
    universe = _complete_universe()
    return {
        "schema_version": 1,
        "model_id": spec["model_id"],
        "generated_at": "2026-09-06T08:00:00+00:00",
        "data_end_date": "2026-09-04",
        "spec_fingerprint": build_challenger_fingerprint(spec),
        "universe_fingerprint": build_universe_fingerprint(universe),
        "methodology": {
            "point_in_time_universe": True,
            "confirmation_touched_by_optimization": False,
        },
        "confirmation": {
            "periods": 10,
            "positive_period_rate": 0.60,
            "wilson_lower_95": 0.312674,
            "profit_factor": 1.50,
            "avg_excess_return": 0.01,
            "max_drawdown": -0.10,
        },
    }


def test_challenger_spec_rejects_temporal_leakage_and_bad_weights():
    spec = _spec()
    validate_challenger_spec(spec)

    leaked = copy.deepcopy(spec)
    leaked["design_data_end"] = "2024-06-01"
    with pytest.raises(ValueError):
        validate_challenger_spec(leaked)

    bad_weights = copy.deepcopy(spec)
    bad_weights["weights"]["rps_20d"] = 0.8
    with pytest.raises(ValueError):
        validate_challenger_spec(bad_weights)


def test_challenger_ranking_selects_positive_relative_strength_without_future_rows():
    frames = {
        "STRONG": _frame(0.003),
        "MEDIUM": _frame(0.001),
        "WEAK": _frame(-0.001),
    }
    signal_date = frames["STRONG"]["trade_date"].iloc[-11]
    baseline = rank_challenger_candidates(frames, signal_date, _spec())

    mutated = {code: frame.copy() for code, frame in frames.items()}
    mutated["WEAK"].loc[mutated["WEAK"]["trade_date"] > signal_date, "close"] *= 100
    after_future_mutation = rank_challenger_candidates(mutated, signal_date, _spec())

    assert [item["code"] for item in baseline] == ["STRONG", "MEDIUM"]
    assert [item["code"] for item in after_future_mutation] == ["STRONG", "MEDIUM"]
    assert all(item["return_20d"] > 0 and item["return_60d"] > 0 for item in baseline)


def test_challenger_split_keeps_confirmation_strictly_untouched():
    trades = [
        {"signal_date": "2023-12-01"},
        {"signal_date": "2024-01-01"},
        {"signal_date": "2025-12-31"},
        {"signal_date": "2026-01-01"},
    ]

    split = split_challenger_trades(trades, _spec())

    assert [t["signal_date"] for t in split["design"]] == ["2023-12-01"]
    assert [t["signal_date"] for t in split["validation"]] == ["2024-01-01", "2025-12-31"]
    assert [t["signal_date"] for t in split["confirmation"]] == ["2026-01-01"]


def test_shadow_lifecycle_never_becomes_executable_even_when_evidence_passes():
    spec = _spec()
    universe = _complete_universe()

    status = evaluate_challenger_artifact(
        _passing_artifact(spec),
        spec=spec,
        universe_history=universe,
        now=datetime(2026, 9, 6, 12, tzinfo=timezone.utc),
    )

    assert status["evidence_ready"] is True
    assert status["lifecycle"] == "shadow"
    assert status["execution_ready"] is False
    assert "CHALLENGER_SHADOW_ONLY" in status["reasons"]


def test_challenger_recomputes_confirmation_gates_instead_of_trusting_passed_flag():
    spec = _spec()
    artifact = _passing_artifact(spec)
    artifact["passed"] = True
    artifact["confirmation"]["positive_period_rate"] = 0.20

    status = evaluate_challenger_artifact(
        artifact,
        spec=spec,
        universe_history=_complete_universe(),
        now=datetime(2026, 9, 6, 12, tzinfo=timezone.utc),
    )

    assert status["evidence_ready"] is False
    assert status["execution_ready"] is False
    assert "CHALLENGER_CONFIRMATION_WIN_RATE_BELOW_GATE" in status["reasons"]
