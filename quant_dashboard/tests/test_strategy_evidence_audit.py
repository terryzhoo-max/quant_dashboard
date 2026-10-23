"""Auxiliary strategy audit must check evidence that covers the LIVE parameters."""

import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta
from unittest.mock import patch

from engines import audit_engine

LIVE_ERP = {
    "buy_threshold": 55, "sell_threshold": 40, "erp_window": 1008, "stop_loss": 0,
    "w_erp_abs": 0.2, "w_erp_pct": 0.3, "w_m1": 0.35, "w_vol": 0.08, "w_credit": 0.07,
}
LIVE_DIV = {
    "BEAR": {"ma_trend": 90, "rsi_buy": 30, "rsi_sell": 70, "bias_buy": -3.0, "bias_sell": 4.5, "ma_defend": 40},
    "RANGE": {"ma_trend": 60, "rsi_buy": 35, "rsi_sell": 75, "bias_buy": -2.0, "bias_sell": 5.5, "ma_defend": 30},
    "BULL": {"ma_trend": 60, "rsi_buy": 40, "rsi_sell": 80, "bias_buy": -1.5, "bias_sell": 7.0, "ma_defend": 20},
}


def _days_ago(n, fmt="%Y-%m-%d"):
    return (datetime.now() - timedelta(days=n)).strftime(fmt)


def _with_file(name, payload, fn):
    with tempfile.TemporaryDirectory() as root:
        rel = audit_engine.OPTIMIZATION_FILES[name]
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        with patch.object(audit_engine, "PROJECT_ROOT", root):
            return fn()


def _erp(best, oos_end_days_ago=30, alpha=0.05):
    payload = {
        "meta": {"out_sample": f"20240101 → {_days_ago(oos_end_days_ago, '%Y%m%d')}"},
        "best_params": best,
        "best_out_sample": {"alpha": alpha},
    }
    with patch("services.strategy_params.get_erp_params", return_value=dict(LIVE_ERP)):
        return _with_file("ERP择时", payload, lambda: audit_engine._audit_erp_evidence(180, 360, 0.15))


def test_erp_evidence_for_different_params_is_not_applicable():
    check = _erp({**LIVE_ERP, "buy_threshold": 75})
    assert check["status"] == "fail"
    assert check["score"] == 30
    assert "buy_threshold" in check["detail"]


def test_erp_evidence_matching_live_params_and_fresh_passes():
    check = _erp(dict(LIVE_ERP))
    assert check["status"] == "pass"
    assert check["score"] == 100


def test_erp_negative_oos_alpha_caps_at_warn():
    check = _erp(dict(LIVE_ERP), alpha=-0.05)
    assert check["status"] == "warn"
    assert check["score"] == 70


def _dividend(params, data_through_days_ago=10, wins=2):
    payload = {
        "data_through": _days_ago(data_through_days_ago),
        "params": params,
        "win_count": wins,
        "total_count": 4,
    }
    fake = types.ModuleType("engines.dividend_trend_engine")
    fake.REGIME_PARAMS = LIVE_DIV
    with patch.dict(sys.modules, {"engines.dividend_trend_engine": fake}):
        return _with_file("红利趋势", payload, lambda: audit_engine._audit_dividend_evidence(90, 180, 0.15))


def test_dividend_evidence_bound_and_fresh_passes():
    check = _dividend(LIVE_DIV)
    assert check["status"] == "pass"
    assert check["score"] == 100


def test_dividend_evidence_with_drifted_params_fails():
    drifted = {**LIVE_DIV, "RANGE": {**LIVE_DIV["RANGE"], "ma_trend": 120}}
    check = _dividend(drifted)
    assert check["status"] == "fail"
    assert check["score"] == 30


def test_dividend_stale_evidence_fails():
    check = _dividend(LIVE_DIV, data_through_days_ago=211)
    assert check["status"] == "fail"
    assert check["score"] < 60


def test_dividend_no_regime_gain_caps_at_warn():
    check = _dividend(LIVE_DIV, wins=0)
    assert check["status"] == "warn"
    assert check["score"] == 70


def _momentum(status):
    with patch("services.industry_validation.load_industry_validation_status", return_value=status):
        return audit_engine._audit_momentum_evidence(60, 90, 0.20)


def test_momentum_stale_validation_fails():
    check = _momentum({
        "stage": "shadow", "ready": False, "data_end_date": "2026-09-04",
        "data_lag_days": 49, "artifact_age_days": 47.0,
        "reasons": ["VALIDATION_ARTIFACT_STALE", "VALIDATION_DATA_STALE"],
    })
    assert check["status"] == "fail"
    assert check["score"] == 40


def test_momentum_fresh_but_not_promoted_is_controlled_warn():
    check = _momentum({
        "stage": "shadow", "ready": False, "data_end_date": "2026-10-20",
        "data_lag_days": 3, "artifact_age_days": 2.0,
        "reasons": ["HOLDOUT_WIN_RATE_BELOW_THRESHOLD"],
    })
    assert check["status"] == "warn"
    assert check["score"] == 70


def test_momentum_promoted_passes():
    check = _momentum({
        "stage": "promoted", "ready": True, "data_end_date": "2026-10-20",
        "data_lag_days": 3, "artifact_age_days": 2.0, "reasons": [],
    })
    assert check["status"] == "pass"
    assert check["score"] == 100
