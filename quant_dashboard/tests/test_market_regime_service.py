"""The market regime snapshot must expose one canonical parameter set."""

from datetime import datetime, timezone

import pandas as pd

from services.market_regime import build_market_regime_snapshot


def _index_frame():
    dates = pd.bdate_range(end="2026-09-04", periods=180)
    closes = [3000 + i * 4 for i in range(len(dates))]
    return pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y%m%d"),
            "close": closes,
            "pct_chg": pd.Series(closes).pct_change().fillna(0) * 100,
        }
    )


def test_snapshot_uses_runtime_parameters_and_strict_minimum_cap():
    now = datetime(2026, 9, 6, tzinfo=timezone.utc).timestamp()
    snapshot = build_market_regime_snapshot(
        _index_frame(),
        {
            "status": "success",
            "data_quality_score": 90,
            "decision_locked": False,
            "updated_at": now,
            "cap": 53,
        },
        now_ts=now,
        aiae_max_age_sec=86_400,
    )

    assert snapshot["status"] == "ok"
    assert snapshot["regime"] == "BULL"
    assert snapshot["score_gate"] == 65
    assert snapshot["regime_cap"] == 85
    assert snapshot["single_position_cap"] == 20
    assert snapshot["aiae_cap"] == 53
    assert snapshot["pos_cap"] == 53
    assert snapshot["aiae_usable"] is True
    assert snapshot["runtime"]["revision"] >= 2


def test_snapshot_does_not_silently_ignore_stale_aiae():
    now = datetime(2026, 9, 6, tzinfo=timezone.utc).timestamp()
    snapshot = build_market_regime_snapshot(
        _index_frame(),
        {
            "status": "success",
            "data_quality_score": 90,
            "decision_locked": False,
            "updated_at": now - 90_000,
            "cap": 53,
        },
        now_ts=now,
        aiae_max_age_sec=86_400,
    )

    assert snapshot["aiae_usable"] is False
    assert snapshot["aiae_reason"] == "stale"
    assert snapshot["aiae_cap"] is None
    assert snapshot["decision_locked"] is True
