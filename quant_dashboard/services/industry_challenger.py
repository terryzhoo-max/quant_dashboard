"""Pre-registered BULL-only relative-strength challenger in shadow mode."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

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


SPEC_PATH = PROJECT_ROOT / "config" / "industry_challenger_spec.json"
_write_lock = threading.Lock()


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _instant(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _range(value: Any, name: str, lower: float, upper: float) -> None:
    number = _finite(value)
    if number is None or number < lower or number > upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")


def validate_challenger_spec(spec: Mapping[str, Any]) -> None:
    if not isinstance(spec, Mapping) or spec.get("schema_version") != 1:
        raise ValueError("unsupported challenger schema")
    if not isinstance(spec.get("spec_revision"), int) or spec["spec_revision"] < 1:
        raise ValueError("spec_revision must be positive")
    if spec.get("lifecycle") not in {"shadow", "disabled", "enabled"}:
        raise ValueError("invalid challenger lifecycle")
    dates = {
        key: _date(spec.get(key))
        for key in (
            "backtest_start",
            "design_data_end",
            "validation_start",
            "validation_end",
            "confirmation_start",
        )
    }
    if any(value is None for value in dates.values()):
        raise ValueError("challenger split dates must be ISO dates")
    if not (
        dates["backtest_start"] <= dates["design_data_end"]
        < dates["validation_start"] <= dates["validation_end"]
        < dates["confirmation_start"]
    ):
        raise ValueError("challenger temporal split leaks future observations")
    if _instant(spec.get("frozen_at")) is None:
        raise ValueError("frozen_at must be an ISO timestamp")
    if spec.get("allowed_regimes") != ["BULL"]:
        raise ValueError("challenger must remain BULL-only")
    _range(spec.get("rebalance_days"), "rebalance_days", 5, 63)
    _range(spec.get("holding_days"), "holding_days", 5, 63)
    _range(spec.get("min_history_days"), "min_history_days", 60, 1250)
    _range(spec.get("top_n"), "top_n", 1, 5)
    _range(spec.get("round_trip_cost_bps"), "round_trip_cost_bps", 0, 200)
    filters = spec.get("filters")
    if not isinstance(filters, Mapping):
        raise ValueError("filters must be an object")
    _range(filters.get("min_return_20d"), "min_return_20d", -0.5, 1)
    _range(filters.get("min_return_60d"), "min_return_60d", -0.8, 2)
    _range(filters.get("max_annualized_volatility_20d"), "max_annualized_volatility_20d", 0.05, 2)
    weights = spec.get("weights")
    expected_weights = {"rps_20d", "rps_60d", "low_volatility"}
    if not isinstance(weights, Mapping) or set(weights) != expected_weights:
        raise ValueError("challenger weights are incomplete")
    for key, value in weights.items():
        _range(value, f"weights.{key}", 0, 1)
    if not math.isclose(sum(float(value) for value in weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("challenger weights must sum to 1")
    promotion = spec.get("promotion")
    if not isinstance(promotion, Mapping):
        raise ValueError("promotion must be an object")
    _range(promotion.get("min_confirmation_periods"), "min_confirmation_periods", 1, 1000)
    _range(promotion.get("min_positive_period_rate"), "min_positive_period_rate", 0, 1)
    _range(promotion.get("min_wilson_lower_95"), "min_wilson_lower_95", 0, 1)
    _range(promotion.get("min_profit_factor"), "min_profit_factor", 0, 100)
    _range(promotion.get("min_avg_excess_return"), "min_avg_excess_return", -1, 1)
    _range(promotion.get("max_drawdown"), "max_drawdown", 0, 1)
    _range(promotion.get("max_artifact_age_days"), "max_artifact_age_days", 1, 365)
    _range(promotion.get("max_data_lag_days"), "max_data_lag_days", 1, 90)
    if not isinstance(promotion.get("require_point_in_time_universe"), bool):
        raise ValueError("require_point_in_time_universe must be boolean")
    if not isinstance(spec.get("artifact_path"), str) or not spec["artifact_path"].endswith(".json"):
        raise ValueError("artifact_path must be JSON")
    if not isinstance(spec.get("forward_ledger_path"), str) or not spec["forward_ledger_path"].endswith(".jsonl"):
        raise ValueError("forward_ledger_path must be JSONL")


def load_challenger_spec(path: Path | str | None = None) -> dict:
    target = Path(path) if path is not None else SPEC_PATH
    with target.open("r", encoding="utf-8") as handle:
        spec = json.load(handle)
    validate_challenger_spec(spec)
    return spec


def build_challenger_fingerprint(spec: Mapping[str, Any]) -> str:
    validate_challenger_spec(spec)
    payload = {
        key: spec[key]
        for key in (
            "schema_version", "spec_revision", "model_id", "backtest_start",
            "design_data_end", "validation_start", "validation_end",
            "confirmation_start", "allowed_regimes", "rebalance_days",
            "holding_days", "min_history_days", "top_n",
            "round_trip_cost_bps", "filters", "weights",
        )
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def rank_challenger_candidates(
    price_frames: Mapping[str, pd.DataFrame], signal_date: Any, spec: Mapping[str, Any]
) -> list[dict]:
    """Rank only data observable on signal_date; future rows are ignored."""
    validate_challenger_spec(spec)
    target = pd.Timestamp(signal_date)
    records: list[dict] = []
    min_history = int(spec["min_history_days"])
    filters = spec["filters"]
    for code, source in price_frames.items():
        frame = source.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        history = frame[frame["trade_date"] <= target].sort_values("trade_date")
        if len(history) < max(min_history, 61):
            continue
        close = pd.to_numeric(history["close"], errors="coerce").dropna()
        if len(close) < max(min_history, 61) or close.iloc[-1] <= 0:
            continue
        return_20d = float(close.iloc[-1] / close.iloc[-21] - 1)
        return_60d = float(close.iloc[-1] / close.iloc[-61] - 1)
        daily = close.pct_change().tail(20).dropna()
        annual_volatility = float(daily.std(ddof=1) * math.sqrt(252)) if len(daily) >= 10 else math.inf
        ma20 = float(close.tail(20).mean())
        ma60 = float(close.tail(60).mean())
        ma20_prior = float(close.iloc[-25:-5].mean())
        slope = ma20 / ma20_prior - 1 if ma20_prior > 0 else -math.inf
        if not (
            return_20d > float(filters["min_return_20d"])
            and return_60d > float(filters["min_return_60d"])
            and annual_volatility <= float(filters["max_annualized_volatility_20d"])
            and close.iloc[-1] > ma20
            and close.iloc[-1] > ma60
            and slope >= 0
        ):
            continue
        records.append({
            "code": str(code),
            "return_20d": return_20d,
            "return_60d": return_60d,
            "annualized_volatility_20d": annual_volatility,
            "above_ma20": True,
            "above_ma60": True,
            "ma20_slope_5d": slope,
        })
    if not records:
        return []
    ranked = pd.DataFrame(records)
    ranked["rps_20d"] = ranked["return_20d"].rank(method="average", pct=True) * 100
    ranked["rps_60d"] = ranked["return_60d"].rank(method="average", pct=True) * 100
    ranked["low_volatility_score"] = ranked["annualized_volatility_20d"].rank(
        method="average", ascending=False, pct=True
    ) * 100
    weights = spec["weights"]
    ranked["challenger_score"] = (
        ranked["rps_20d"] * float(weights["rps_20d"])
        + ranked["rps_60d"] * float(weights["rps_60d"])
        + ranked["low_volatility_score"] * float(weights["low_volatility"])
    )
    ranked = ranked.sort_values(
        ["challenger_score", "return_20d", "code"], ascending=[False, False, True]
    ).head(int(spec["top_n"]))
    numeric = [
        "return_20d", "return_60d", "annualized_volatility_20d",
        "ma20_slope_5d", "rps_20d", "rps_60d",
        "low_volatility_score", "challenger_score",
    ]
    result = ranked.to_dict("records")
    for item in result:
        for key in numeric:
            item[key] = round(float(item[key]), 8)
    return result


def split_challenger_trades(trades: list[dict], spec: Mapping[str, Any]) -> dict[str, list[dict]]:
    validate_challenger_spec(spec)
    design_end = pd.Timestamp(spec["design_data_end"])
    validation_start = pd.Timestamp(spec["validation_start"])
    validation_end = pd.Timestamp(spec["validation_end"])
    confirmation_start = pd.Timestamp(spec["confirmation_start"])
    result = {"design": [], "validation": [], "confirmation": []}
    for trade in trades:
        signal_date = pd.Timestamp(trade["signal_date"])
        if signal_date <= design_end:
            result["design"].append(trade)
        elif validation_start <= signal_date <= validation_end:
            result["validation"].append(trade)
        elif signal_date >= confirmation_start:
            result["confirmation"].append(trade)
    return result


def evaluate_challenger_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    spec: Mapping[str, Any] | None = None,
    universe_history: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict:
    spec = dict(spec or load_challenger_spec())
    validate_challenger_spec(spec)
    evidence = artifact if isinstance(artifact, Mapping) else {}
    universe = universe_history or load_industry_universe_history()
    promotion = spec["promotion"]
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    reasons: list[str] = []
    gates: dict[str, dict] = {}

    def gate(name: str, actual: Any, threshold: Any, passed: bool, reason: str) -> None:
        gates[name] = {"actual": actual, "threshold": threshold, "passed": bool(passed)}
        if not passed:
            reasons.append(reason)

    gate("schema", evidence.get("schema_version"), 1, evidence.get("schema_version") == 1, "CHALLENGER_ARTIFACT_SCHEMA_INVALID")
    gate("model_id", evidence.get("model_id"), spec["model_id"], evidence.get("model_id") == spec["model_id"], "CHALLENGER_MODEL_ID_MISMATCH")
    fingerprint = build_challenger_fingerprint(spec)
    gate("spec_fingerprint", evidence.get("spec_fingerprint"), fingerprint, evidence.get("spec_fingerprint") == fingerprint, "CHALLENGER_SPEC_FINGERPRINT_MISMATCH")
    universe_fingerprint = build_universe_fingerprint(universe)
    gate("universe_fingerprint", evidence.get("universe_fingerprint"), universe_fingerprint, evidence.get("universe_fingerprint") == universe_fingerprint, "CHALLENGER_UNIVERSE_FINGERPRINT_MISMATCH")
    generated = _instant(evidence.get("generated_at"))
    age = max(0.0, (current - generated).total_seconds() / 86400) if generated else None
    gate("artifact_freshness", round(age, 2) if age is not None else None, promotion["max_artifact_age_days"], age is not None and age <= promotion["max_artifact_age_days"], "CHALLENGER_ARTIFACT_STALE")
    data_end = _date(evidence.get("data_end_date"))
    lag = max(0, (current.date() - data_end).days) if data_end else None
    gate("data_freshness", lag, promotion["max_data_lag_days"], lag is not None and lag <= promotion["max_data_lag_days"], "CHALLENGER_DATA_STALE")
    methodology = evidence.get("methodology") if isinstance(evidence.get("methodology"), Mapping) else {}
    coverage_start = methodology.get("universe_coverage_start") or spec["backtest_start"]
    coverage_end = methodology.get("universe_coverage_end") or evidence.get("data_end_date")
    coverage_complete = bool(
        coverage_end
        and point_in_time_universe_coverage(universe, coverage_start, coverage_end)
    )
    pit = methodology.get("point_in_time_universe") is True and coverage_complete
    require_pit = promotion["require_point_in_time_universe"] is True
    gate("point_in_time_universe", pit, require_pit, pit or not require_pit, "CHALLENGER_POINT_IN_TIME_UNIVERSE_UNAVAILABLE")
    untouched = methodology.get("confirmation_touched_by_optimization") is False
    gate("confirmation_untouched", untouched, True, untouched, "CHALLENGER_CONFIRMATION_CONTAMINATED")

    confirmation = evidence.get("confirmation") if isinstance(evidence.get("confirmation"), Mapping) else {}
    checks = [
        ("periods", "min_confirmation_periods", ">=", "CHALLENGER_CONFIRMATION_SAMPLE_TOO_SMALL"),
        ("positive_period_rate", "min_positive_period_rate", ">=", "CHALLENGER_CONFIRMATION_WIN_RATE_BELOW_GATE"),
        ("wilson_lower_95", "min_wilson_lower_95", ">=", "CHALLENGER_CONFIRMATION_CONFIDENCE_BELOW_GATE"),
        ("profit_factor", "min_profit_factor", ">=", "CHALLENGER_CONFIRMATION_PROFIT_FACTOR_BELOW_GATE"),
        ("avg_excess_return", "min_avg_excess_return", ">=", "CHALLENGER_CONFIRMATION_EXCESS_BELOW_GATE"),
    ]
    for metric, threshold_key, _operator, reason in checks:
        actual = _finite(confirmation.get(metric))
        threshold = float(promotion[threshold_key])
        gate(f"confirmation_{metric}", actual, threshold, actual is not None and actual >= threshold, reason)
    drawdown = _finite(confirmation.get("max_drawdown"))
    gate("confirmation_max_drawdown", drawdown, -float(promotion["max_drawdown"]), drawdown is not None and drawdown >= -float(promotion["max_drawdown"]), "CHALLENGER_CONFIRMATION_DRAWDOWN_ABOVE_LIMIT")

    evidence_reasons = list(dict.fromkeys(reasons))
    evidence_ready = not evidence_reasons
    lifecycle = spec["lifecycle"]
    execution_ready = evidence_ready and lifecycle == "enabled"
    if lifecycle == "shadow":
        reasons.append("CHALLENGER_SHADOW_ONLY")
    elif lifecycle == "disabled":
        reasons.append("CHALLENGER_DISABLED")
    return {
        "model_id": spec["model_id"],
        "spec_revision": spec["spec_revision"],
        "lifecycle": lifecycle,
        "evidence_ready": evidence_ready,
        "execution_ready": execution_ready,
        "stage": "enabled" if execution_ready else lifecycle,
        "reasons": list(dict.fromkeys(reasons)),
        "evidence_reasons": evidence_reasons,
        "gates": gates,
        "generated_at": evidence.get("generated_at"),
        "data_end_date": evidence.get("data_end_date"),
        "data_lag_days": lag,
        "design": dict(evidence.get("design") or {}),
        "validation": dict(evidence.get("validation") or {}),
        "confirmation": dict(confirmation),
        "latest_snapshot": dict(evidence.get("latest_snapshot") or {}),
    }


def _artifact_path(spec: Mapping[str, Any]) -> Path:
    configured = Path(spec["artifact_path"])
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


def load_challenger_status() -> dict:
    spec = load_challenger_spec()
    target = _artifact_path(spec)
    try:
        with target.open("r", encoding="utf-8") as handle:
            artifact = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {
            "model_id": spec["model_id"], "lifecycle": spec["lifecycle"],
            "evidence_ready": False, "execution_ready": False, "stage": "missing",
            "reasons": ["CHALLENGER_ARTIFACT_MISSING"], "artifact_path": str(target),
        }
    status = evaluate_challenger_artifact(artifact, spec=spec)
    status["artifact_path"] = str(target)
    return status


def run_challenger_validation(
    price_frames: Mapping[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    *,
    spec: Mapping[str, Any] | None = None,
    universe_history: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict:
    spec = dict(spec or load_challenger_spec())
    validate_challenger_spec(spec)
    universe = universe_history or load_industry_universe_history()
    runtime = load_runtime_config()
    benchmark = benchmark.copy()
    benchmark["trade_date"] = pd.to_datetime(benchmark["trade_date"])
    benchmark = benchmark.sort_values("trade_date").drop_duplicates("trade_date").reset_index(drop=True)
    normalized: dict[str, pd.DataFrame] = {}
    for code, source in price_frames.items():
        frame = source.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        normalized[code] = frame.sort_values("trade_date").drop_duplicates("trade_date").reset_index(drop=True)
    first = max(
        int(spec["min_history_days"]) - 1,
        int(benchmark["trade_date"].searchsorted(pd.Timestamp(spec["backtest_start"]))),
    )
    last = len(benchmark) - int(spec["holding_days"]) - 1
    latest_date = benchmark["trade_date"].iloc[-1]
    complete_universe = point_in_time_universe_coverage(
        universe, spec["backtest_start"], latest_date
    )
    trades: list[dict] = []
    for bench_index in range(first, max(first, last + 1), int(spec["rebalance_days"])):
        signal_date = benchmark.iloc[bench_index]["trade_date"]
        regime = _classify_regime(
            pd.to_numeric(benchmark.loc[:bench_index, "close"], errors="coerce").dropna().values,
            runtime["regime"],
        )
        if regime not in spec["allowed_regimes"]:
            continue
        date_covered = point_in_time_universe_coverage(universe, signal_date)
        allowed = resolve_universe_codes(universe, signal_date) if date_covered else set(normalized)
        ranked = rank_challenger_candidates(
            {code: normalized[code] for code in allowed if code in normalized},
            signal_date,
            spec,
        )
        benchmark_trade = simulate_candidate_trade(
            benchmark, signal_index=bench_index, holding_days=int(spec["holding_days"]),
            stop_loss=1.0, round_trip_cost_bps=0, ma_exit_days=None,
        )
        if benchmark_trade is None:
            continue
        for candidate in ranked:
            frame = normalized[candidate["code"]]
            matches = np.flatnonzero(frame["trade_date"].values == signal_date.to_datetime64())
            if len(matches) != 1:
                continue
            trade = simulate_candidate_trade(
                frame,
                signal_index=int(matches[0]),
                holding_days=int(spec["holding_days"]),
                stop_loss=float(runtime["strategies"]["momentum"]["stop_losses"]["BULL"]),
                round_trip_cost_bps=float(spec["round_trip_cost_bps"]),
                ma_exit_days=60,
            )
            if trade is None:
                continue
            trade.update(candidate)
            trade["regime"] = regime
            trade["benchmark_return"] = benchmark_trade["gross_return"]
            trade["excess_return"] = round(trade["net_return"] - benchmark_trade["gross_return"], 8)
            trades.append(trade)
    split = split_challenger_trades(trades, spec)
    now = generated_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    latest_regime = _classify_regime(
        pd.to_numeric(benchmark["close"], errors="coerce").dropna().values,
        runtime["regime"],
    )
    latest_covered = point_in_time_universe_coverage(universe, latest_date)
    latest_allowed = resolve_universe_codes(universe, latest_date) if latest_covered else set()
    latest_candidates = (
        rank_challenger_candidates(
            {code: normalized[code] for code in latest_allowed if code in normalized},
            latest_date,
            spec,
        )
        if latest_regime in spec["allowed_regimes"] and latest_covered else []
    )
    artifact = {
        "schema_version": 1,
        "model_id": spec["model_id"],
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "data_end_date": latest_date.strftime("%Y-%m-%d"),
        "spec_fingerprint": build_challenger_fingerprint(spec),
        "universe_fingerprint": build_universe_fingerprint(universe),
        "methodology": {
            "point_in_time_universe": complete_universe,
            "universe_coverage_start": spec["backtest_start"],
            "universe_coverage_end": latest_date.strftime("%Y-%m-%d"),
            "confirmation_touched_by_optimization": False,
            "selection": "BULL-only absolute momentum + cross-sectional relative strength + low volatility",
            "portfolio": f"top-{spec['top_n']} equal weight by rebalance period",
        },
        "design": summarize_portfolio_periods(split["design"]),
        "validation": summarize_portfolio_periods(split["validation"]),
        "confirmation": summarize_portfolio_periods(split["confirmation"]),
        "latest_snapshot": {
            "date": latest_date.strftime("%Y-%m-%d"),
            "regime": latest_regime,
            "candidates": latest_candidates,
            "universe_coverage_complete": latest_covered,
            "execution_allowed": False,
        },
        "trades": trades,
    }
    status = evaluate_challenger_artifact(
        artifact, spec=spec, universe_history=universe, now=now
    )
    artifact["passed"] = status["evidence_ready"]
    artifact["promotion_reasons"] = status["reasons"]
    artifact["promotion_gates"] = status["gates"]
    return artifact


def write_challenger_artifact(artifact: Mapping[str, Any]) -> Path:
    spec = load_challenger_spec()
    target = _artifact_path(spec)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with _write_lock:
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(artifact, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink()
    return target


def run_local_challenger_validation(*, write: bool = True) -> dict:
    from core_etf_config import CORE_ETF_CODES

    industry_dir = PROJECT_ROOT / "data_lake" / "industry_prices_qfq"
    benchmark_path = PROJECT_ROOT / "data_lake" / "daily_prices" / "000300.SH.parquet"
    frames = {
        code: pd.read_parquet(industry_dir / f"{code}.parquet")
        for code in CORE_ETF_CODES
        if (industry_dir / f"{code}.parquet").exists()
    }
    artifact = run_challenger_validation(
        frames,
        pd.read_parquet(benchmark_path),
        universe_history=load_industry_universe_history(),
    )
    if write:
        write_challenger_artifact(artifact)
    return artifact
