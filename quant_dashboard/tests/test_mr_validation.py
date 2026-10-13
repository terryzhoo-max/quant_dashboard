"""Frozen out-of-sample validation for mean-reversion parameters."""

from datetime import date

import numpy as np
import pandas as pd

from services.mr_validation import (
    _lag_positions,
    classify_regimes,
    compare_incumbent_and_challenger,
    compare_regime,
)


def _parameter_set():
    return {
        state: {
            "N_trend": 20,
            "rsi_period": 6,
            "rsi_buy": 45,
            "rsi_sell": 65,
            "bias_buy": -1.0,
            "stop_loss": 0.08,
        }
        for state in ("BEAR", "RANGE", "BULL")
    }


def _market(days=260):
    index = pd.bdate_range("2026-01-01", periods=days)
    phase = np.arange(days, dtype=float)
    benchmark = pd.Series(100 + phase * 0.08 + np.sin(phase / 8), index=index)
    prices = pd.DataFrame({
        "AAA": 50 + phase * 0.04 + np.sin(phase / 4) * 2,
        "BBB": 80 + phase * 0.03 + np.cos(phase / 5) * 3,
    }, index=index)
    return prices, benchmark


def test_regime_labels_do_not_change_when_future_prices_are_appended():
    _, benchmark = _market()
    prefix = benchmark.iloc[:180]

    prefix_labels = classify_regimes(prefix)
    extended_labels = classify_regimes(benchmark).iloc[:180]

    assert prefix_labels.tolist() == extended_labels.tolist()


def test_validation_compares_candidates_on_identical_window_and_costs():
    prices, benchmark = _market()
    incumbent = _parameter_set()
    challenger = _parameter_set()
    challenger["BULL"]["rsi_buy"] = 40

    result = compare_incumbent_and_challenger(
        prices=prices,
        benchmark=benchmark,
        incumbent=incumbent,
        challenger=challenger,
        oos_start=date(2026, 3, 28),
        cost_rate=0.001,
    )

    assert result["incumbent"]["oos_start"] == result["challenger"]["oos_start"]
    assert result["incumbent"]["data_through"] == result["challenger"]["data_through"]
    assert result["incumbent"]["cost_rate"] == result["challenger"]["cost_rate"] == 0.001


def test_positions_are_executed_one_day_after_signal():
    desired = pd.DataFrame({"AAA": [0.0, 1.0, 1.0, 0.0]})

    executed = _lag_positions(desired)

    assert executed["AAA"].tolist() == [0.0, 0.0, 1.0, 1.0]


def test_insufficient_regime_evidence_cannot_be_published():
    metrics = {
        "regime_days": 59,
        "trades": 20,
        "sharpe": 2.0,
        "max_dd": -5.0,
        "calmar": 2.0,
        "coverage": 50.0,
    }

    decision = compare_regime(metrics, metrics)

    assert decision == {
        "decision": "INSUFFICIENT_EVIDENCE",
        "reason": "regime_days",
    }
