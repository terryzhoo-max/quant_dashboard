"""Point-in-time validation and fail-closed promotion for industry signals.

The validation artifact is evidence, not authority.  Runtime promotion is
recomputed from the current versioned contract every time the artifact is
loaded, so a stale ``passed`` field can never unlock execution.
"""

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

from services.industry_tracker import (
    compute_alpha_score,
    compute_price_percentile,
    compute_risk_alerts,
    compute_sector_heat_score,
)
from services.strategy_params import load_runtime_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_SCHEMA_VERSION = 1
_write_lock = threading.Lock()


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _validation_rules(runtime_config: Mapping[str, Any]) -> Mapping[str, Any]:
    return runtime_config["strategies"]["momentum"]["validation"]


def build_policy_fingerprint(runtime_config: Mapping[str, Any] | None = None) -> str:
    """Hash only inputs that change reconstructed signals or trade outcomes."""
    runtime = runtime_config or load_runtime_config()
    momentum = runtime["strategies"]["momentum"]
    validation = momentum["validation"]
    payload = {
        "regime": runtime["regime"],
        "score_gates": momentum["score_gates"],
        "stop_losses": momentum["stop_losses"],
        "model_id": validation["model_id"],
        "factor_version": validation["factor_version"],
        "rebalance_days": validation["rebalance_days"],
        "holding_days": validation["holding_days"],
        "min_history_days": validation["min_history_days"],
        "round_trip_cost_bps": validation["round_trip_cost_bps"],
        "entry": "next_session_open",
        "exit": "stop_or_ma60_or_horizon_close",
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_universe_history(manifest: Mapping[str, Any]) -> None:
    """Validate membership history without inferring unknown effective dates."""
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") not in {1, 2}:
        raise ValueError("unsupported industry universe history schema")
    if not isinstance(manifest.get("complete_history"), bool):
        raise ValueError("complete_history must be boolean")
    if manifest["schema_version"] == 2:
        source = manifest.get("source")
        coverage = manifest.get("coverage")
        if not isinstance(source, Mapping) or not source.get("provider"):
            raise ValueError("schema 2 universe requires source provenance")
        if not isinstance(source.get("snapshot_sha256"), str) or len(source["snapshot_sha256"]) != 64:
            raise ValueError("schema 2 universe requires a source snapshot hash")
        if not isinstance(coverage, Mapping) or coverage.get("mode") != "prospective":
            raise ValueError("schema 2 universe requires prospective coverage")
        if _as_date(coverage.get("complete_from")) is None:
            raise ValueError("schema 2 universe requires complete_from")
        if coverage.get("complete_through") is not None and _as_date(coverage.get("complete_through")) is None:
            raise ValueError("invalid complete_through")
    members = manifest.get("members")
    if not isinstance(members, list):
        raise ValueError("members must be a list")
    seen: set[str] = set()
    for member in members:
        if not isinstance(member, Mapping):
            raise ValueError("universe member must be an object")
        code = str(member.get("code") or "").strip()
        if not code or code in seen:
            raise ValueError("universe member codes must be non-empty and unique")
        seen.add(code)
        start = _as_date(member.get("membership_from"))
        end = _as_date(member.get("membership_to"))
        listed = _as_date(member.get("instrument_list_date"))
        delisted = _as_date(member.get("instrument_delist_date"))
        if manifest["complete_history"] and start is None:
            raise ValueError("complete universe history requires membership_from")
        if member.get("membership_from") is not None and start is None:
            raise ValueError(f"invalid membership_from for {code}")
        if member.get("membership_to") is not None and end is None:
            raise ValueError(f"invalid membership_to for {code}")
        if start is not None and end is not None and end < start:
            raise ValueError(f"membership_to preced membership_from for {code}")
        if member.get("instrument_list_date") is not None and listed is None:
            raise ValueError(f"invalid instrument_list_date for {code}")
        if member.get("instrument_delist_date") is not None and delisted is None:
            raise ValueError(f"invalid instrument_delist_date for {code}")
        if listed is not None and delisted is not None and delisted < listed:
            raise ValueError(f"instrument_delist_date preced instrument_list_date for {code}")
        if start is not None and listed is not None and start < listed:
            raise ValueError(f"membership starts before instrument listing for {code}")


def build_universe_fingerprint(manifest: Mapping[str, Any]) -> str:
    validate_universe_history(manifest)
    payload = {
        "schema_version": manifest["schema_version"],
        "as_of": manifest.get("as_of"),
        "source": manifest.get("source"),
        "complete_history": manifest["complete_history"],
        "history_start": manifest.get("history_start"),
        "coverage": manifest.get("coverage"),
        "policy": manifest.get("policy"),
        "members": [
            {
                "code": member.get("code"),
                "instrument_first_trade_date": member.get("instrument_first_trade_date"),
                "instrument_list_date": member.get("instrument_list_date"),
                "instrument_delist_date": member.get("instrument_delist_date"),
                "instrument_status": member.get("instrument_status"),
                "membership_from": member.get("membership_from"),
                "membership_to": member.get("membership_to"),
                "membership_source": member.get("membership_source"),
            }
            for member in sorted(manifest["members"], key=lambda item: str(item.get("code")))
        ],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_universe_codes(manifest: Mapping[str, Any], as_of: Any) -> set[str]:
    """Return only memberships whose effective dates are explicitly known."""
    validate_universe_history(manifest)
    target = _as_date(as_of)
    if target is None:
        raise ValueError("as_of must be an ISO date")
    resolved: set[str] = set()
    for member in manifest["members"]:
        start = _as_date(member.get("membership_from"))
        end = _as_date(member.get("membership_to"))
        listed = _as_date(member.get("instrument_list_date"))
        delisted = _as_date(member.get("instrument_delist_date"))
        if start is None:
            continue
        membership_active = start <= target and (end is None or target <= end)
        instrument_active = (listed is None or listed <= target) and (delisted is None or target <= delisted)
        if membership_active and instrument_active:
            resolved.add(str(member["code"]))
    return resolved


def point_in_time_universe_coverage(
    manifest: Mapping[str, Any], start: Any, end: Any | None = None
) -> bool:
    """Return whether every membership decision is known throughout the requested interval."""
    validate_universe_history(manifest)
    requested_start = _as_date(start)
    requested_end = _as_date(end if end is not None else start)
    if requested_start is None or requested_end is None or requested_end < requested_start:
        raise ValueError("invalid universe coverage interval")
    if manifest.get("complete_history") is True:
        history_start = _as_date(manifest.get("history_start"))
        return history_start is None or history_start <= requested_start
    coverage = manifest.get("coverage")
    if not isinstance(coverage, Mapping):
        return False
    complete_from = _as_date(coverage.get("complete_from"))
    complete_through = _as_date(coverage.get("complete_through"))
    return bool(
        complete_from is not None
        and complete_from <= requested_start
        and (complete_through is None or requested_end <= complete_through)
    )


def load_industry_universe_history(
    *,
    path: Path | str | None = None,
    runtime_config: Mapping[str, Any] | None = None,
) -> dict:
    runtime = runtime_config or load_runtime_config()
    if path is None:
        configured = Path(str(_validation_rules(runtime)["universe_history_path"]))
        target = configured if configured.is_absolute() else PROJECT_ROOT / configured
    else:
        target = Path(path)
    with target.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    validate_universe_history(manifest)
    return manifest


def _gate(
    results: dict[str, dict],
    reasons: list[str],
    name: str,
    actual: Any,
    threshold: Any,
    passed: bool,
    reason: str,
) -> None:
    results[name] = {
        "actual": actual,
        "threshold": threshold,
        "passed": bool(passed),
    }
    if not passed:
        reasons.append(reason)


def evaluate_validation_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    runtime_config: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    universe_history: Mapping[str, Any] | None = None,
) -> dict:
    """Re-evaluate all promotion gates against current policy and time."""
    runtime = runtime_config or load_runtime_config()
    rules = _validation_rules(runtime)
    promotion = rules["promotion"]
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    reasons: list[str] = []
    gates: dict[str, dict] = {}
    evidence = artifact if isinstance(artifact, Mapping) else {}

    _gate(
        gates,
        reasons,
        "schema_version",
        evidence.get("schema_version"),
        ARTIFACT_SCHEMA_VERSION,
        evidence.get("schema_version") == ARTIFACT_SCHEMA_VERSION,
        "VALIDATION_ARTIFACT_SCHEMA_INVALID",
    )
    _gate(
        gates,
        reasons,
        "model_id",
        evidence.get("model_id"),
        rules["model_id"],
        evidence.get("model_id") == rules["model_id"],
        "VALIDATION_MODEL_ID_MISMATCH",
    )
    current_fingerprint = build_policy_fingerprint(runtime)
    _gate(
        gates,
        reasons,
        "policy_fingerprint",
        evidence.get("policy_fingerprint"),
        current_fingerprint,
        evidence.get("policy_fingerprint") == current_fingerprint,
        "POLICY_FINGERPRINT_MISMATCH",
    )

    generated_at = _as_utc(evidence.get("generated_at"))
    artifact_age_days = (
        max(0.0, (current_time - generated_at).total_seconds() / 86400)
        if generated_at is not None
        else None
    )
    _gate(
        gates,
        reasons,
        "artifact_freshness",
        round(artifact_age_days, 2) if artifact_age_days is not None else None,
        rules["max_artifact_age_days"],
        artifact_age_days is not None
        and artifact_age_days <= float(rules["max_artifact_age_days"]),
        "VALIDATION_ARTIFACT_STALE",
    )

    data_end = _as_date(evidence.get("data_end_date"))
    data_lag_days = (
        max(0, (current_time.date() - data_end).days) if data_end is not None else None
    )
    _gate(
        gates,
        reasons,
        "data_freshness",
        data_lag_days,
        rules["max_data_lag_days"],
        data_lag_days is not None
        and data_lag_days <= int(rules["max_data_lag_days"]),
        "VALIDATION_DATA_STALE",
    )

    methodology = evidence.get("methodology")
    methodology = methodology if isinstance(methodology, Mapping) else {}
    if universe_history is None:
        try:
            universe_history = load_industry_universe_history(runtime_config=runtime)
        except (OSError, ValueError, json.JSONDecodeError):
            universe_history = None
    universe_fingerprint = None
    universe_complete = False
    if isinstance(universe_history, Mapping):
        try:
            universe_fingerprint = build_universe_fingerprint(universe_history)
            coverage_start = methodology.get("universe_coverage_start") or rules["validation_start"]
            coverage_end = methodology.get("universe_coverage_end") or evidence.get("data_end_date")
            universe_complete = bool(
                coverage_end
                and point_in_time_universe_coverage(
                    universe_history, coverage_start, coverage_end
                )
            )
        except ValueError:
            universe_fingerprint = None
    _gate(
        gates,
        reasons,
        "universe_fingerprint",
        methodology.get("universe_fingerprint"),
        universe_fingerprint,
        universe_fingerprint is not None
        and methodology.get("universe_fingerprint") == universe_fingerprint,
        "UNIVERSE_FINGERPRINT_MISMATCH",
    )
    point_in_time = (
        methodology.get("point_in_time_universe") is True and universe_complete
    )
    require_pit = promotion["require_point_in_time_universe"] is True
    _gate(
        gates,
        reasons,
        "point_in_time_universe",
        point_in_time,
        require_pit,
        point_in_time or not require_pit,
        "POINT_IN_TIME_UNIVERSE_UNAVAILABLE",
    )
    common_reasons = list(reasons)

    holdout = evidence.get("holdout")
    holdout = holdout if isinstance(holdout, Mapping) else {}
    signals = _finite(holdout.get("signals"))
    win_rate = _finite(holdout.get("win_rate"))
    profit_factor = _finite(holdout.get("profit_factor"))
    avg_excess = _finite(holdout.get("avg_excess_return"))
    max_drawdown = _finite(holdout.get("max_drawdown"))
    _gate(gates, reasons, "oos_signals", signals, promotion["min_oos_signals"], signals is not None and signals >= promotion["min_oos_signals"], "OOS_SAMPLE_TOO_SMALL")
    _gate(gates, reasons, "oos_win_rate", win_rate, promotion["min_oos_win_rate"], win_rate is not None and win_rate >= promotion["min_oos_win_rate"], "OOS_WIN_RATE_BELOW_GATE")
    _gate(gates, reasons, "profit_factor", profit_factor, promotion["min_profit_factor"], profit_factor is not None and profit_factor >= promotion["min_profit_factor"], "OOS_PROFIT_FACTOR_BELOW_GATE")
    _gate(gates, reasons, "avg_excess_return", avg_excess, promotion["min_avg_excess_return"], avg_excess is not None and avg_excess >= promotion["min_avg_excess_return"], "OOS_EXCESS_RETURN_BELOW_GATE")
    _gate(gates, reasons, "max_drawdown", max_drawdown, -float(promotion["max_drawdown"]), max_drawdown is not None and max_drawdown >= -float(promotion["max_drawdown"]), "OOS_DRAWDOWN_ABOVE_LIMIT")

    by_regime = holdout.get("by_regime")
    by_regime = by_regime if isinstance(by_regime, Mapping) else {}
    regime_statuses: dict[str, dict] = {}
    for state in promotion["required_regimes"]:
        state_reason_start = len(reasons)
        state_metrics = by_regime.get(state)
        state_metrics = state_metrics if isinstance(state_metrics, Mapping) else {}
        count = _finite(state_metrics.get("signals"))
        _gate(
            gates,
            reasons,
            f"regime_{state.lower()}_signals",
            count,
            promotion["min_regime_signals"],
            count is not None and count >= promotion["min_regime_signals"],
            f"OOS_{state}_SAMPLE_TOO_SMALL",
        )
        state_win_rate = _finite(state_metrics.get("win_rate"))
        _gate(
            gates,
            reasons,
            f"regime_{state.lower()}_win_rate",
            state_win_rate,
            promotion["min_regime_win_rate"],
            state_win_rate is not None
            and state_win_rate >= promotion["min_regime_win_rate"],
            f"OOS_{state}_WIN_RATE_BELOW_GATE",
        )
        state_profit_factor = _finite(state_metrics.get("profit_factor"))
        _gate(
            gates,
            reasons,
            f"regime_{state.lower()}_profit_factor",
            state_profit_factor,
            promotion["min_regime_profit_factor"],
            state_profit_factor is not None
            and state_profit_factor >= promotion["min_regime_profit_factor"],
            f"OOS_{state}_PROFIT_FACTOR_BELOW_GATE",
        )
        state_excess = _finite(state_metrics.get("avg_excess_return"))
        _gate(
            gates,
            reasons,
            f"regime_{state.lower()}_avg_excess_return",
            state_excess,
            promotion["min_regime_avg_excess_return"],
            state_excess is not None
            and state_excess >= promotion["min_regime_avg_excess_return"],
            f"OOS_{state}_EXCESS_RETURN_BELOW_GATE",
        )
        portfolio = state_metrics.get("portfolio")
        portfolio = portfolio if isinstance(portfolio, Mapping) else {}
        portfolio_periods = _finite(portfolio.get("periods"))
        _gate(
            gates,
            reasons,
            f"regime_{state.lower()}_portfolio_periods",
            portfolio_periods,
            promotion["min_regime_periods"],
            portfolio_periods is not None
            and portfolio_periods >= promotion["min_regime_periods"],
            f"OOS_{state}_PORTFOLIO_PERIODS_TOO_SMALL",
        )
        positive_rate = _finite(portfolio.get("positive_period_rate"))
        _gate(
            gates,
            reasons,
            f"regime_{state.lower()}_positive_period_rate",
            positive_rate,
            promotion["min_regime_positive_period_rate"],
            positive_rate is not None
            and positive_rate >= promotion["min_regime_positive_period_rate"],
            f"OOS_{state}_POSITIVE_PERIOD_RATE_BELOW_GATE",
        )
        wilson_lower = _finite(portfolio.get("wilson_lower_95"))
        _gate(
            gates,
            reasons,
            f"regime_{state.lower()}_wilson_lower_95",
            wilson_lower,
            promotion["min_regime_wilson_lower_95"],
            wilson_lower is not None
            and wilson_lower >= promotion["min_regime_wilson_lower_95"],
            f"OOS_{state}_WIN_RATE_CONFIDENCE_BELOW_GATE",
        )
        period_profit_factor = _finite(portfolio.get("profit_factor"))
        _gate(
            gates,
            reasons,
            f"regime_{state.lower()}_period_profit_factor",
            period_profit_factor,
            promotion["min_regime_period_profit_factor"],
            period_profit_factor is not None
            and period_profit_factor >= promotion["min_regime_period_profit_factor"],
            f"OOS_{state}_PERIOD_PROFIT_FACTOR_BELOW_GATE",
        )
        period_excess = _finite(portfolio.get("avg_excess_return"))
        _gate(
            gates,
            reasons,
            f"regime_{state.lower()}_period_avg_excess_return",
            period_excess,
            promotion["min_regime_period_avg_excess_return"],
            period_excess is not None
            and period_excess >= promotion["min_regime_period_avg_excess_return"],
            f"OOS_{state}_PERIOD_EXCESS_RETURN_BELOW_GATE",
        )
        period_drawdown = _finite(portfolio.get("max_drawdown"))
        _gate(
            gates,
            reasons,
            f"regime_{state.lower()}_period_max_drawdown",
            period_drawdown,
            -float(promotion["max_regime_period_drawdown"]),
            period_drawdown is not None
            and period_drawdown >= -float(promotion["max_regime_period_drawdown"]),
            f"OOS_{state}_PERIOD_DRAWDOWN_ABOVE_LIMIT",
        )
        state_reasons = list(dict.fromkeys(reasons[state_reason_start:]))
        lifecycle = rules["regime_lifecycle"][state]
        statistical_ready = not state_reasons
        execution_ready = (
            lifecycle == "enabled" and not common_reasons and statistical_ready
        )
        lifecycle_reason = {
            "disabled": f"{state}_REGIME_DISABLED_BY_POLICY",
            "shadow": f"{state}_REGIME_SHADOW_ONLY",
        }.get(lifecycle)
        regime_statuses[state] = {
            "lifecycle": lifecycle,
            "statistical_ready": statistical_ready,
            "execution_ready": execution_ready,
            "reasons": list(dict.fromkeys(
                common_reasons + state_reasons + ([lifecycle_reason] if lifecycle_reason else [])
            )),
            "metrics": dict(state_metrics),
        }

    for state, lifecycle in rules["regime_lifecycle"].items():
        if state in regime_statuses:
            continue
        regime_statuses[state] = {
            "lifecycle": lifecycle,
            "statistical_ready": False,
            "execution_ready": False,
            "reasons": [f"{state}_REGIME_DISABLED_BY_POLICY"],
            "metrics": dict(by_regime.get(state) or {}),
        }

    reasons = list(dict.fromkeys(reasons))
    ready = not reasons
    return {
        "ready": ready,
        "stage": "promoted" if ready else ("shadow" if evidence else "missing"),
        "model_id": rules["model_id"],
        "factor_version": rules["factor_version"],
        "policy_fingerprint": current_fingerprint,
        "generated_at": evidence.get("generated_at"),
        "data_end_date": evidence.get("data_end_date"),
        "artifact_age_days": round(artifact_age_days, 2) if artifact_age_days is not None else None,
        "data_lag_days": data_lag_days,
        "reasons": reasons,
        "gates": gates,
        "holdout": dict(holdout),
        "methodology": dict(methodology),
        "universe_complete": universe_complete,
        "regime_statuses": regime_statuses,
        "limitations": list(evidence.get("limitations") or []),
    }


def _artifact_path(
    runtime_config: Mapping[str, Any], path: Path | str | None = None
) -> Path:
    if path is not None:
        return Path(path)
    configured = Path(str(_validation_rules(runtime_config)["artifact_path"]))
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


def load_industry_validation_status(
    *, path: Path | str | None = None, now: datetime | None = None
) -> dict:
    """Load evidence from disk and fail closed on missing or malformed files."""
    runtime = load_runtime_config()
    target = _artifact_path(runtime, path)
    try:
        with target.open("r", encoding="utf-8") as handle:
            artifact = json.load(handle)
    except FileNotFoundError:
        return {
            **evaluate_validation_artifact({}, runtime_config=runtime, now=now),
            "stage": "missing",
            "reasons": ["VALIDATION_ARTIFACT_MISSING"],
            "artifact_path": str(target),
        }
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {
            **evaluate_validation_artifact({}, runtime_config=runtime, now=now),
            "stage": "invalid",
            "reasons": ["VALIDATION_ARTIFACT_INVALID"],
            "artifact_path": str(target),
        }
    status = evaluate_validation_artifact(artifact, runtime_config=runtime, now=now)
    status["artifact_path"] = str(target)
    return status


def simulate_candidate_trade(
    frame: pd.DataFrame,
    *,
    signal_index: int,
    holding_days: int,
    stop_loss: float,
    round_trip_cost_bps: float,
    ma_exit_days: int | None = 60,
) -> dict | None:
    """Enter only after the signal close and simulate observable close exits."""
    prices = frame.sort_values("trade_date").reset_index(drop=True)
    entry_index = signal_index + 1
    if signal_index < 0 or entry_index >= len(prices):
        return None
    last_index = min(len(prices) - 1, entry_index + int(holding_days) - 1)
    if last_index < entry_index:
        return None
    entry_row = prices.iloc[entry_index]
    raw_open = _finite(entry_row.get("open"))
    adjusted_close = _finite(entry_row.get("close"))
    raw_close = _finite(entry_row.get("raw_close"))
    if (
        raw_open is not None
        and adjusted_close is not None
        and raw_close is not None
        and raw_close > 0
    ):
        # The qfq store preserves raw OHLC but provides an adjusted ``close``.
        # Convert the next open with the same day's observable adjustment factor.
        entry_price = raw_open * adjusted_close / raw_close
        entry_price_basis = "adjusted_open"
    else:
        entry_price = raw_open or adjusted_close
        entry_price_basis = "open" if raw_open is not None else "close_fallback"
    if entry_price is None or entry_price <= 0:
        return None

    exit_index = last_index
    exit_reason = "HORIZON"
    stop_price = entry_price * (1 - float(stop_loss))
    for index in range(entry_index, last_index + 1):
        close_price = _finite(prices.iloc[index].get("close"))
        if close_price is None:
            continue
        if close_price <= stop_price:
            exit_index = index
            exit_reason = "STOP_LOSS"
            break
        if ma_exit_days is not None and index + 1 >= ma_exit_days:
            ma_value = pd.to_numeric(
                prices.loc[index - ma_exit_days + 1:index, "close"], errors="coerce"
            ).mean()
            if math.isfinite(float(ma_value)) and close_price < float(ma_value):
                exit_index = index
                exit_reason = f"MA{ma_exit_days}_BREAK"
                break

    exit_price = _finite(prices.iloc[exit_index].get("close"))
    if exit_price is None or exit_price <= 0:
        return None
    gross_return = exit_price / entry_price - 1
    net_return = gross_return - float(round_trip_cost_bps) / 10000
    to_date = lambda value: pd.Timestamp(value).strftime("%Y-%m-%d")
    return {
        "signal_date": to_date(prices.iloc[signal_index]["trade_date"]),
        "entry_date": to_date(entry_row["trade_date"]),
        "exit_date": to_date(prices.iloc[exit_index]["trade_date"]),
        "entry_price": round(entry_price, 8),
        "entry_price_basis": entry_price_basis,
        "exit_price": round(exit_price, 8),
        "exit_reason": exit_reason,
        "gross_return": round(gross_return, 8),
        "net_return": round(net_return, 8),
        "holding_sessions": int(exit_index - entry_index + 1),
    }


def _classify_regime(close_values: np.ndarray, rules: Mapping[str, Any]) -> str:
    close = np.asarray(close_values, dtype=float)
    ma_period = int(rules["ma_period"])
    slope_days = int(rules["slope_days"])
    ret3 = close[-1] / close[-4] - 1 if len(close) >= 4 else 0.0
    if ret3 < float(rules["crash_return_3d"]):
        return "CRASH"
    ma = close[-ma_period:].mean() if len(close) >= ma_period else close.mean()
    ma_series = np.asarray([
        close[max(0, i - ma_period + 1):i + 1].mean()
        for i in range(max(0, len(close) - slope_days - 1), len(close))
    ])
    slope = float(np.polyfit(np.arange(len(ma_series)), ma_series, 1)[0]) if len(ma_series) >= 2 else 0.0
    ret5 = close[-1] / close[-6] - 1 if len(close) >= 6 else 0.0
    ret20 = close[-1] / close[-21] - 1 if len(close) >= 21 else 0.0
    if close[-1] > ma and slope > 0 and ret20 > float(rules["bull_return_20d_min"]):
        return "BULL"
    if close[-1] > ma or ret5 > float(rules["rebound_return_5d_min"]):
        return "RANGE"
    return "BEAR"


def _candidate_at(history: pd.DataFrame) -> dict:
    trend = 0.0
    if len(history) >= 5:
        trend = float((history["close"].iloc[-1] / history["close"].iloc[-5] - 1) * 100)
    heat = compute_sector_heat_score(history, trend)
    price_percentile = compute_price_percentile(history)
    alpha = compute_alpha_score(history, heat["heat_score"], trend, price_percentile)
    alerts = compute_risk_alerts(
        heat["vol_ratio"],
        price_percentile,
        trend,
        heat["heat_score"],
        heat["crowd_score"],
    )
    return {"alpha_score": alpha["alpha_score"], "trend_strength": alpha["trend_strength"], "risk_alerts": alerts}


def _candidate_passes(candidate: Mapping[str, Any], gate: float) -> bool:
    trend = candidate.get("trend_strength") or {}
    return bool(
        _finite(candidate.get("alpha_score")) is not None
        and float(candidate["alpha_score"]) >= gate
        and trend.get("above_ma20") is True
        and trend.get("above_ma60") is True
        and (_finite(trend.get("ma20_slope")) or 0.0) >= 0
        and not any(
            isinstance(alert, Mapping) and alert.get("level") == "danger"
            for alert in candidate.get("risk_alerts") or []
        )
    )


def wilson_lower_bound(wins: int, total: int, z: float = 1.959963984540054) -> float | None:
    """Two-sided 95% Wilson lower bound for a binomial success rate."""
    if total <= 0 or wins < 0 or wins > total:
        return None
    rate = wins / total
    denominator = 1 + z * z / total
    centre = rate + z * z / (2 * total)
    margin = z * math.sqrt((rate * (1 - rate) + z * z / (4 * total)) / total)
    return round(max(0.0, (centre - margin) / denominator), 6)


def summarize_portfolio_periods(trades: list[Mapping[str, Any]]) -> dict:
    """Collapse correlated same-date signals into one equal-weight portfolio period."""
    if not trades:
        return {
            "periods": 0,
            "positive_periods": 0,
            "positive_period_rate": None,
            "wilson_lower_95": None,
            "avg_return": None,
            "avg_excess_return": None,
            "profit_factor": None,
            "total_return": None,
            "max_drawdown": None,
            "average_names": None,
        }
    frame = pd.DataFrame(trades)
    periods = frame.groupby("signal_date", sort=True).agg(
        net_return=("net_return", "mean"),
        excess_return=("excess_return", "mean"),
        names=("signal_date", "size"),
    )
    returns = periods["net_return"].astype(float)
    excess = periods["excess_return"].astype(float)
    positive = int((returns > 0).sum())
    gains = returns[returns > 0].sum()
    losses = abs(returns[returns <= 0].sum())
    profit_factor = float(gains / losses) if losses > 0 else (999.0 if gains > 0 else 0.0)
    compounded = np.concatenate(([1.0], (1 + returns).cumprod().to_numpy(dtype=float)))
    peaks = np.maximum.accumulate(compounded)
    drawdown = compounded / peaks - 1
    return {
        "periods": int(len(periods)),
        "positive_periods": positive,
        "positive_period_rate": round(positive / len(periods), 6),
        "wilson_lower_95": wilson_lower_bound(positive, len(periods)),
        "avg_return": round(float(returns.mean()), 8),
        "avg_excess_return": round(float(excess.mean()), 8),
        "profit_factor": round(min(profit_factor, 999.0), 6),
        "total_return": round(float(compounded[-1] - 1), 8),
        "max_drawdown": round(float(drawdown.min()), 8),
        "average_names": round(float(periods["names"].mean()), 4),
    }


def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {
            "signals": 0, "wins": 0, "win_rate": None,
            "avg_return": None, "median_return": None,
            "profit_factor": None, "payoff_ratio": None,
            "avg_excess_return": None, "max_drawdown": None,
            "portfolio": summarize_portfolio_periods([]), "by_regime": {},
        }
    returns = np.asarray([trade["net_return"] for trade in trades], dtype=float)
    excess = np.asarray([trade["excess_return"] for trade in trades], dtype=float)
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    profit_factor = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else (999.0 if len(wins) else 0.0)
    payoff = float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) and losses.mean() != 0 else None
    portfolio = summarize_portfolio_periods(trades)
    result = {
        "signals": int(len(trades)),
        "wins": int((returns > 0).sum()),
        "win_rate": round(float((returns > 0).mean()), 6),
        "avg_return": round(float(returns.mean()), 8),
        "median_return": round(float(np.median(returns)), 8),
        "profit_factor": round(min(profit_factor, 999.0), 6),
        "payoff_ratio": round(payoff, 6) if payoff is not None else None,
        "avg_excess_return": round(float(excess.mean()), 8),
        "max_drawdown": portfolio["max_drawdown"],
        "portfolio": portfolio,
        "by_regime": {},
    }
    for state in ("BEAR", "RANGE", "BULL", "CRASH"):
        subset = [trade for trade in trades if trade["regime"] == state]
        if subset:
            state_returns = np.asarray([trade["net_return"] for trade in subset])
            state_excess = np.asarray([trade["excess_return"] for trade in subset])
            state_wins = state_returns[state_returns > 0]
            state_losses = state_returns[state_returns <= 0]
            state_profit_factor = (
                float(state_wins.sum() / abs(state_losses.sum()))
                if len(state_losses) and state_losses.sum() != 0
                else (999.0 if len(state_wins) else 0.0)
            )
            result["by_regime"][state] = {
                "signals": len(subset),
                "win_rate": round(float((state_returns > 0).mean()), 6),
                "avg_return": round(float(state_returns.mean()), 8),
                "profit_factor": round(min(state_profit_factor, 999.0), 6),
                "avg_excess_return": round(float(state_excess.mean()), 8),
                "portfolio": summarize_portfolio_periods(subset),
            }
    return result


def run_industry_validation(
    price_frames: Mapping[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    *,
    runtime_config: Mapping[str, Any] | None = None,
    point_in_time_universe: bool = False,
    universe_history: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict:
    """Reconstruct fixed signals using only information observable at each date."""
    runtime = runtime_config or load_runtime_config()
    validation = _validation_rules(runtime)
    momentum = runtime["strategies"]["momentum"]
    benchmark = benchmark.copy()
    benchmark["trade_date"] = pd.to_datetime(benchmark["trade_date"])
    benchmark = benchmark.sort_values("trade_date").drop_duplicates("trade_date").reset_index(drop=True)
    start = pd.Timestamp(validation["validation_start"])
    holdout_start = pd.Timestamp(validation["holdout_start"])
    holding_days = int(validation["holding_days"])
    min_history = max(int(validation["min_history_days"]), int(runtime["regime"]["ma_period"]))
    normalized: dict[str, pd.DataFrame] = {}
    for code, frame in price_frames.items():
        item = frame.copy()
        item["trade_date"] = pd.to_datetime(item["trade_date"])
        normalized[code] = item.sort_values("trade_date").drop_duplicates("trade_date").reset_index(drop=True)

    first_position = max(min_history - 1, int(benchmark["trade_date"].searchsorted(start)))
    final_position = len(benchmark) - holding_days - 1
    trades: list[dict] = []
    signal_dates = 0
    latest_date = benchmark["trade_date"].iloc[-1]
    manifest_complete = bool(
        isinstance(universe_history, Mapping)
        and point_in_time_universe_coverage(universe_history, start, latest_date)
    )
    if isinstance(universe_history, Mapping):
        validate_universe_history(universe_history)
    for bench_index in range(first_position, max(first_position, final_position + 1), int(validation["rebalance_days"])):
        signal_date = benchmark.iloc[bench_index]["trade_date"]
        regime = _classify_regime(
            pd.to_numeric(benchmark.loc[:bench_index, "close"], errors="coerce").dropna().values,
            runtime["regime"],
        )
        benchmark_trade = simulate_candidate_trade(
            benchmark,
            signal_index=bench_index,
            holding_days=holding_days,
            stop_loss=1.0,
            round_trip_cost_bps=0,
            ma_exit_days=None,
        )
        if benchmark_trade is None:
            continue
        signal_dates += 1
        gate = float(momentum["score_gates"][regime])
        date_covered = bool(
            isinstance(universe_history, Mapping)
            and point_in_time_universe_coverage(universe_history, signal_date)
        )
        eligible_codes = resolve_universe_codes(universe_history, signal_date) if date_covered else set(normalized)
        for code in sorted(eligible_codes):
            frame = normalized.get(code)
            if frame is None:
                continue
            positions = np.flatnonzero(frame["trade_date"].values == signal_date.to_datetime64())
            if len(positions) != 1:
                continue
            index = int(positions[0])
            if index + 1 < min_history:
                continue
            candidate = _candidate_at(frame.iloc[:index + 1])
            if not _candidate_passes(candidate, gate):
                continue
            trade = simulate_candidate_trade(
                frame,
                signal_index=index,
                holding_days=holding_days,
                stop_loss=float(momentum["stop_losses"][regime]),
                round_trip_cost_bps=float(validation["round_trip_cost_bps"]),
                ma_exit_days=60,
            )
            if trade is None:
                continue
            trade.update({
                "code": code,
                "regime": regime,
                "alpha_score": candidate["alpha_score"],
                "score_gate": gate,
                "benchmark_return": benchmark_trade["gross_return"],
                "excess_return": round(trade["net_return"] - benchmark_trade["gross_return"], 8),
            })
            trades.append(trade)

    reference = [trade for trade in trades if pd.Timestamp(trade["signal_date"]) < holdout_start]
    holdout = [trade for trade in trades if pd.Timestamp(trade["signal_date"]) >= holdout_start]
    now = generated_at or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    artifact = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_id": validation["model_id"],
        "factor_version": validation["factor_version"],
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "data_start_date": benchmark["trade_date"].min().strftime("%Y-%m-%d") if not benchmark.empty else None,
        "data_end_date": benchmark["trade_date"].max().strftime("%Y-%m-%d") if not benchmark.empty else None,
        "policy_fingerprint": build_policy_fingerprint(runtime),
        "runtime_revision": runtime["revision"],
        "methodology": {
            "design": "fixed-policy expanding-window shadow validation",
            "entry": "next_session_open",
            "exit": "stop_or_ma60_or_horizon_close",
            "rebalance_days": validation["rebalance_days"],
            "holding_days": holding_days,
            "round_trip_cost_bps": validation["round_trip_cost_bps"],
            "point_in_time_instrument_availability": True,
            "point_in_time_universe": bool(point_in_time_universe and manifest_complete),
            "universe_history_complete": manifest_complete,
            "universe_coverage_start": start.strftime("%Y-%m-%d"),
            "universe_coverage_end": latest_date.strftime("%Y-%m-%d"),
            "universe_source": universe_history.get("source") if isinstance(universe_history, Mapping) else None,
            "universe_as_of": universe_history.get("as_of") if isinstance(universe_history, Mapping) else None,
            "universe_fingerprint": build_universe_fingerprint(universe_history) if isinstance(universe_history, Mapping) else None,
            "historical_aiae_used": False,
            "parameters_optimized_on_holdout": False,
        },
        "limitations": [
            "AIAE is an operational live gate and is not backfilled into history.",
            "The available ETF list is today's research universe; delisted and formerly eligible industries are absent.",
        ],
        "coverage": {
            "instrument_count": len(normalized),
            "sampled_signal_dates": signal_dates,
            "trade_count": len(trades),
            "holdout_start": validation["holdout_start"],
        },
        "reference": _metrics(reference),
        "holdout": _metrics(holdout),
        "trades": trades,
    }
    status = evaluate_validation_artifact(
        artifact,
        runtime_config=runtime,
        now=now,
        universe_history=universe_history,
    )
    artifact["passed"] = status["ready"]
    artifact["promotion_reasons"] = status["reasons"]
    artifact["promotion_gates"] = status["gates"]
    return artifact


def write_validation_artifact(
    artifact: Mapping[str, Any], *, path: Path | str | None = None
) -> Path:
    runtime = load_runtime_config()
    target = _artifact_path(runtime, path)
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


def run_local_industry_validation(*, write: bool = True) -> dict:
    """Run the audit on local qfq ETF data and the local CSI300 benchmark."""
    from core_etf_config import CORE_ETF_CODES

    industry_dir = PROJECT_ROOT / "data_lake" / "industry_prices_qfq"
    benchmark_path = PROJECT_ROOT / "data_lake" / "daily_prices" / "000300.SH.parquet"
    frames = {
        code: pd.read_parquet(industry_dir / f"{code}.parquet")
        for code in CORE_ETF_CODES
        if (industry_dir / f"{code}.parquet").exists()
    }
    if not benchmark_path.exists():
        raise FileNotFoundError(f"benchmark data missing: {benchmark_path}")
    universe_history = load_industry_universe_history()
    benchmark = pd.read_parquet(benchmark_path)
    benchmark_end = pd.to_datetime(benchmark["trade_date"]).max()
    validation_start = _validation_rules(load_runtime_config())["validation_start"]
    artifact = run_industry_validation(
        frames,
        benchmark,
        point_in_time_universe=point_in_time_universe_coverage(
            universe_history, validation_start, benchmark_end
        ),
        universe_history=universe_history,
    )
    if write:
        write_validation_artifact(artifact)
    return artifact
