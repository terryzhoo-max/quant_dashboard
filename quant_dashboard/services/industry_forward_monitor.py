"""Append-only, hash-chained forward evidence for the industry challenger."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from services.industry_challenger import (
    build_challenger_fingerprint,
    load_challenger_spec,
    rank_challenger_candidates,
)
from services.industry_validation import (
    PROJECT_ROOT,
    _classify_regime,
    build_universe_fingerprint,
    load_industry_universe_history,
    point_in_time_universe_coverage,
    resolve_universe_codes,
    simulate_candidate_trade,
    summarize_portfolio_periods,
)
from services.strategy_params import load_runtime_config


LEDGER_SCHEMA_VERSION = 1
_ledger_lock = threading.RLock()


def _canonical_record(record: Mapping[str, Any]) -> bytes:
    payload = {key: value for key, value in record.items() if key != "record_hash"}
    return json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _record_hash(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_record(record)).hexdigest()


def read_forward_ledger(path: Path | str) -> dict:
    target = Path(path)
    if not target.exists():
        return {"integrity_ok": True, "records": [], "errors": [], "path": str(target)}
    records: list[dict] = []
    errors: list[str] = []
    previous = "GENESIS"
    try:
        with target.open("r", encoding="utf-8") as handle:
            for expected_sequence, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("schema_version") != LEDGER_SCHEMA_VERSION:
                    errors.append("LEDGER_SCHEMA_INVALID")
                if record.get("sequence") != expected_sequence:
                    errors.append("LEDGER_SEQUENCE_INVALID")
                if record.get("prev_hash") != previous:
                    errors.append("PREVIOUS_HASH_MISMATCH")
                if record.get("record_hash") != _record_hash(record):
                    errors.append("RECORD_HASH_MISMATCH")
                records.append(record)
                previous = str(record.get("record_hash") or "")
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        errors.append("LEDGER_PARSE_ERROR")
    return {
        "integrity_ok": not errors,
        "records": records,
        "errors": list(dict.fromkeys(errors)),
        "path": str(target),
    }


def append_ledger_record(path: Path | str, payload: Mapping[str, Any]) -> dict:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _ledger_lock:
        state = read_forward_ledger(target)
        if not state["integrity_ok"]:
            raise ValueError("forward ledger integrity check failed")
        previous = state["records"][-1]["record_hash"] if state["records"] else "GENESIS"
        record = dict(payload)
        record.pop("record_hash", None)
        record.update({
            "schema_version": LEDGER_SCHEMA_VERSION,
            "sequence": len(state["records"]) + 1,
            "prev_hash": previous,
        })
        record["record_hash"] = _record_hash(record)
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record


def record_daily_snapshot(path: Path | str, snapshot: Mapping[str, Any]) -> dict:
    """Record one immutable snapshot per trade date and model specification."""
    if snapshot.get("record_type") != "snapshot":
        raise ValueError("daily record must be a snapshot")
    safe = dict(snapshot)
    safe["execution_allowed"] = False
    with _ledger_lock:
        state = read_forward_ledger(path)
        if not state["integrity_ok"]:
            raise ValueError("forward ledger integrity check failed")
        for record in state["records"]:
            if (
                record.get("record_type") == "snapshot"
                and record.get("trade_date") == safe.get("trade_date")
                and record.get("spec_fingerprint") == safe.get("spec_fingerprint")
            ):
                return {"appended": False, "record": record}
        return {"appended": True, "record": append_ledger_record(path, safe)}


def _normalized(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"])
    return result.sort_values("trade_date").drop_duplicates("trade_date").reset_index(drop=True)


def settle_snapshot(
    snapshot: Mapping[str, Any],
    price_frames: Mapping[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    spec: Mapping[str, Any],
    *,
    stop_loss: float,
) -> list[dict]:
    """Create settlements only after the complete forward horizon exists."""
    signal_date = pd.Timestamp(snapshot["trade_date"])
    holding_days = int(spec["holding_days"])
    benchmark = _normalized(benchmark)
    bench_matches = np.flatnonzero(benchmark["trade_date"].values == signal_date.to_datetime64())
    if len(bench_matches) != 1 or int(bench_matches[0]) + holding_days >= len(benchmark):
        return []
    benchmark_trade = simulate_candidate_trade(
        benchmark,
        signal_index=int(bench_matches[0]),
        holding_days=holding_days,
        stop_loss=1.0,
        round_trip_cost_bps=0,
        ma_exit_days=None,
    )
    if benchmark_trade is None:
        return []
    settlements: list[dict] = []
    for candidate in snapshot.get("candidates") or []:
        code = str(candidate.get("code") or "")
        if code not in price_frames:
            continue
        frame = _normalized(price_frames[code])
        matches = np.flatnonzero(frame["trade_date"].values == signal_date.to_datetime64())
        if len(matches) != 1 or int(matches[0]) + holding_days >= len(frame):
            continue
        trade = simulate_candidate_trade(
            frame,
            signal_index=int(matches[0]),
            holding_days=holding_days,
            stop_loss=float(stop_loss),
            round_trip_cost_bps=float(spec["round_trip_cost_bps"]),
            ma_exit_days=60,
        )
        if trade is None:
            continue
        settlements.append({
            "record_type": "settlement",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "trade_date": snapshot["trade_date"],
            "signal_date": trade["signal_date"],
            "signal_record_hash": snapshot["record_hash"],
            "code": code,
            "entry_date": trade["entry_date"],
            "exit_date": trade["exit_date"],
            "exit_reason": trade["exit_reason"],
            "net_return": trade["net_return"],
            "benchmark_return": benchmark_trade["gross_return"],
            "excess_return": round(
                trade["net_return"] - benchmark_trade["gross_return"], 8
            ),
            "execution_allowed": False,
        })
    return settlements


def _ledger_path(spec: Mapping[str, Any], path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = Path(str(spec["forward_ledger_path"]))
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


def get_forward_monitor_status(path: Path | str | None = None) -> dict:
    spec = load_challenger_spec()
    universe = load_industry_universe_history()
    target = _ledger_path(spec, path)
    state = read_forward_ledger(target)
    records = state["records"]
    snapshots = [record for record in records if record.get("record_type") == "snapshot"]
    settlements = [record for record in records if record.get("record_type") == "settlement"]
    settled_keys = {
        (record.get("signal_record_hash"), record.get("code")) for record in settlements
    }
    total_signals = sum(len(record.get("candidates") or []) for record in snapshots)
    open_signals = sum(
        1
        for snapshot in snapshots
        for candidate in snapshot.get("candidates") or []
        if (snapshot.get("record_hash"), candidate.get("code")) not in settled_keys
    )
    forward_portfolio = summarize_portfolio_periods(settlements)
    maturity_target = int(spec["promotion"]["min_confirmation_periods"])
    maturity_periods = int(forward_portfolio["periods"])
    coverage = universe.get("coverage") if isinstance(universe.get("coverage"), Mapping) else {}
    return {
        "status": "ok" if state["integrity_ok"] else "locked",
        "integrity_ok": state["integrity_ok"],
        "integrity_errors": state["errors"],
        "ledger_path": str(target),
        "snapshot_days": len(snapshots),
        "no_signal_days": sum(1 for record in snapshots if not record.get("candidates")),
        "total_signals": total_signals,
        "open_signals": open_signals,
        "settled_signals": len(settlements),
        "last_trade_date": snapshots[-1].get("trade_date") if snapshots else None,
        "last_regime": snapshots[-1].get("market_regime") if snapshots else None,
        "forward_portfolio": forward_portfolio,
        "maturity_target_periods": maturity_target,
        "maturity_periods": maturity_periods,
        "maturity_ratio": round(min(1.0, maturity_periods / maturity_target), 6),
        "evidence_mature": maturity_periods >= maturity_target,
        "universe_schema_version": universe.get("schema_version"),
        "universe_coverage_mode": coverage.get("mode"),
        "universe_complete_from": coverage.get("complete_from"),
        "universe_complete_through": coverage.get("complete_through"),
        "last_snapshot_universe_covered": (
            point_in_time_universe_coverage(universe, snapshots[-1]["trade_date"])
            if snapshots else None
        ),
        "execution_allowed": False,
    }


def run_forward_monitor(path: Path | str | None = None) -> dict:
    """Append today's closed-session snapshot and settle any matured signals."""
    from core_etf_config import CORE_ETF_CODES

    spec = load_challenger_spec()
    universe = load_industry_universe_history()
    runtime = load_runtime_config()
    target = _ledger_path(spec, path)
    state = read_forward_ledger(target)
    if not state["integrity_ok"]:
        raise ValueError("forward ledger integrity check failed")
    industry_dir = PROJECT_ROOT / "data_lake" / "industry_prices_qfq"
    benchmark_path = PROJECT_ROOT / "data_lake" / "daily_prices" / "000300.SH.parquet"
    frames = {
        code: _normalized(pd.read_parquet(industry_dir / f"{code}.parquet"))
        for code in CORE_ETF_CODES
        if (industry_dir / f"{code}.parquet").exists()
    }
    benchmark = _normalized(pd.read_parquet(benchmark_path))
    trade_date = benchmark["trade_date"].iloc[-1]
    regime = _classify_regime(
        pd.to_numeric(benchmark["close"], errors="coerce").dropna().values,
        runtime["regime"],
    )
    date_covered = point_in_time_universe_coverage(universe, trade_date)
    allowed = resolve_universe_codes(universe, trade_date) if date_covered else set()
    candidates = (
        rank_challenger_candidates(
            {code: frames[code] for code in allowed if code in frames}, trade_date, spec
        )
        if regime in spec["allowed_regimes"]
        else []
    )
    snapshot_result = record_daily_snapshot(target, {
        "record_type": "snapshot",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "trade_date": trade_date.strftime("%Y-%m-%d"),
        "market_regime": regime,
        "spec_fingerprint": build_challenger_fingerprint(spec),
        "universe_fingerprint": build_universe_fingerprint(universe),
        "universe_coverage_complete": date_covered,
        "universe_lock_reasons": [] if date_covered else ["UNIVERSE_DATE_NOT_COVERED"],
        "lifecycle": spec["lifecycle"],
        "candidates": candidates,
        "execution_allowed": False,
    })
    refreshed = read_forward_ledger(target)
    settled_keys = {
        (record.get("signal_record_hash"), record.get("code"))
        for record in refreshed["records"]
        if record.get("record_type") == "settlement"
    }
    appended_settlements = 0
    stop_loss = runtime["strategies"]["momentum"]["stop_losses"]["BULL"]
    for snapshot in (
        record for record in refreshed["records"] if record.get("record_type") == "snapshot"
    ):
        for settlement in settle_snapshot(
            snapshot, frames, benchmark, spec, stop_loss=stop_loss
        ):
            key = (settlement["signal_record_hash"], settlement["code"])
            if key in settled_keys:
                continue
            append_ledger_record(target, settlement)
            settled_keys.add(key)
            appended_settlements += 1
    status = get_forward_monitor_status(target)
    status["snapshot_appended"] = snapshot_result["appended"]
    status["settlements_appended"] = appended_settlements
    return status
