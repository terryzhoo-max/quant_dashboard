"""Append-only forward shadow evidence contracts."""

import json

import pandas as pd

from services.industry_forward_monitor import (
    append_ledger_record,
    get_forward_monitor_status,
    read_forward_ledger,
    record_daily_snapshot,
    settle_snapshot,
)


def _snapshot():
    return {
        "record_type": "snapshot",
        "observed_at": "2026-09-07T15:45:00+08:00",
        "trade_date": "2026-09-04",
        "market_regime": "BULL",
        "spec_fingerprint": "spec-v1",
        "universe_fingerprint": "universe-v1",
        "lifecycle": "shadow",
        "candidates": [{"code": "A.SH", "challenger_score": 88.0}],
        "execution_allowed": False,
    }


def _prices(periods):
    dates = pd.bdate_range("2026-09-04", periods=periods)
    close = [100.0 + index for index in range(periods)]
    return pd.DataFrame({
        "trade_date": dates,
        "open": close,
        "close": close,
        "raw_close": close,
    })


def test_ledger_hash_chain_detects_historical_tampering(tmp_path):
    path = tmp_path / "forward.jsonl"
    first = append_ledger_record(path, _snapshot())
    append_ledger_record(path, {
        "record_type": "heartbeat",
        "observed_at": "2026-09-08T15:45:00+08:00",
        "trade_date": "2026-09-08",
    })

    healthy = read_forward_ledger(path)
    assert healthy["integrity_ok"] is True
    assert len(healthy["records"]) == 2
    assert healthy["records"][1]["prev_hash"] == first["record_hash"]

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["market_regime"] = "BEAR"
    lines[0] = json.dumps(tampered, ensure_ascii=False, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    damaged = read_forward_ledger(path)
    assert damaged["integrity_ok"] is False
    assert "RECORD_HASH_MISMATCH" in damaged["errors"]


def test_daily_snapshot_is_idempotent_for_trade_date_and_spec(tmp_path):
    path = tmp_path / "forward.jsonl"

    first = record_daily_snapshot(path, _snapshot())
    repeated = record_daily_snapshot(path, _snapshot())

    assert first["appended"] is True
    assert repeated["appended"] is False
    assert repeated["record"]["record_hash"] == first["record"]["record_hash"]
    assert len(read_forward_ledger(path)["records"]) == 1


def test_snapshot_never_allows_execution_even_if_caller_requests_it(tmp_path):
    path = tmp_path / "forward.jsonl"
    unsafe = _snapshot()
    unsafe["execution_allowed"] = True

    result = record_daily_snapshot(path, unsafe)

    assert result["record"]["execution_allowed"] is False


def test_settlement_waits_for_full_forward_horizon_and_uses_next_open():
    snapshot = {**_snapshot(), "record_hash": "signal-hash"}
    spec = {"holding_days": 20, "round_trip_cost_bps": 20}

    immature = settle_snapshot(
        snapshot,
        {"A.SH": _prices(20)},
        _prices(20),
        spec,
        stop_loss=0.08,
    )
    matured = settle_snapshot(
        snapshot,
        {"A.SH": _prices(21)},
        _prices(21),
        spec,
        stop_loss=0.08,
    )

    assert immature == []
    assert len(matured) == 1
    assert matured[0]["signal_record_hash"] == "signal-hash"
    assert matured[0]["entry_date"] == "2026-09-07"
    assert matured[0]["exit_date"] == "2026-10-02"
    assert matured[0]["execution_allowed"] is False


def test_forward_status_reports_preregistered_maturity_gate(tmp_path):
    status = get_forward_monitor_status(tmp_path / "forward.jsonl")

    assert status["maturity_target_periods"] == 8
    assert status["maturity_periods"] == 0
    assert status["maturity_ratio"] == 0.0
    assert status["evidence_mature"] is False
    assert status["execution_allowed"] is False
