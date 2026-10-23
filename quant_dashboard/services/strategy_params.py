"""Versioned production strategy parameters and atomic CI publication."""

import copy
import json
import math
import os
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CONFIG_PATH = PROJECT_ROOT / "config" / "strategy_runtime.json"
REGIMES = ("BEAR", "RANGE", "BULL", "CRASH")
MR_REGIMES = ("BEAR", "RANGE", "BULL")
MR_LIFECYCLE_STATUSES = {
    "validated",
    "stale",
    "rejected",
    "insufficient_evidence",
}
RUNTIME_TIMEZONE = ZoneInfo("Asia/Shanghai")

with RUNTIME_CONFIG_PATH.open("r", encoding="utf-8") as _default_file:
    DEFAULT_RUNTIME_CONFIG = json.load(_default_file)

_cache_lock = threading.RLock()
_publish_lock = threading.Lock()
_cached_config = None
_cached_mtime_ns = None


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _validate_range(value: Any, name: str, lower: float, upper: float) -> None:
    number = _number(value, name)
    if number < lower or number > upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")


def _parse_runtime_datetime(value: Any, name: str = "runtime datetime") -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=RUNTIME_TIMEZONE)
    return parsed


def _validate_mr_lifecycle(mr: Mapping[str, Any]) -> None:
    lifecycle = mr.get("lifecycle")
    if not isinstance(lifecycle, Mapping) or set(lifecycle) != set(MR_REGIMES):
        raise ValueError("mr.lifecycle must cover BEAR, RANGE, and BULL")
    for state in MR_REGIMES:
        entry = lifecycle.get(state)
        if not isinstance(entry, Mapping):
            raise ValueError(f"mr.lifecycle.{state} must be an object")
        status = entry.get("status")
        if status not in MR_LIFECYCLE_STATUSES:
            raise ValueError(f"mr.lifecycle.{state}.status is invalid")
        for key in ("validated_at", "next_validate_after"):
            _parse_runtime_datetime(
                entry.get(key), f"mr.lifecycle.{state}.{key}"
            )
        try:
            datetime.fromisoformat(str(entry.get("data_through"))).date()
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"mr.lifecycle.{state}.data_through must be an ISO date"
            ) from exc
        run_id = entry.get("validation_run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError(
                f"mr.lifecycle.{state}.validation_run_id must be non-empty"
            )


_VOL_MARKET_RANGES = {
    "trigger_ratio": (1.0, 5.0),
    "alpha": (0.1, 2.0),
    "floor": (0.2, 1.0),
    "ceiling": (1.0, 1.5),
    "ewma_lambda": (0.80, 0.995),
    "slow_window": (20, 250),
    "baseline_window": (120, 2520),
    "max_data_age_days": (1, 60),
    "stale_factor_cap": (0.2, 1.0),
}
_VOL_PORTFOLIO_RANGES = {
    "target_vol": (0.05, 0.60),
    "vol_window": (60, 756),
    "shrinkage": (0.0, 1.0),
    "k_stock": (0.005, 0.20),
    "k_etf": (0.01, 0.50),
    "static_cap_stock": (1.0, 30.0),
    "static_cap_etf": (1.0, 60.0),
    "gap_loss_budget": (0.002, 0.10),
    "gap_limit_days": (1, 5),
}


def _validate_vol_targeting(section: Any) -> None:
    """Optional section; when present every numeric knob must stay in a sane range."""
    if section is None:
        return
    if not isinstance(section, Mapping):
        raise ValueError("vol_targeting must be an object")
    for part, ranges in (("market", _VOL_MARKET_RANGES), ("portfolio", _VOL_PORTFOLIO_RANGES)):
        block = section.get(part)
        if block is None:
            continue
        if not isinstance(block, Mapping):
            raise ValueError(f"vol_targeting.{part} must be an object")
        for key, (lower, upper) in ranges.items():
            if key in block:
                _validate_range(block[key], f"vol_targeting.{part}.{key}", lower, upper)
        for flag in ("enabled", "enforce_in_compliance"):
            if flag in block and not isinstance(block[flag], bool):
                raise ValueError(f"vol_targeting.{part}.{flag} must be boolean")
    market = section.get("market") or {}
    if "floor" in market and "ceiling" in market and float(market["floor"]) > float(market["ceiling"]):
        raise ValueError("vol_targeting.market.floor must not exceed ceiling")


def validate_runtime_config(config: Mapping[str, Any]) -> None:
    """Validate the complete runtime parameter document or raise ValueError."""
    if not isinstance(config, Mapping):
        raise ValueError("runtime config must be an object")
    _validate_vol_targeting(config.get("vol_targeting"))
    if config.get("schema_version") != 1:
        raise ValueError("unsupported runtime config schema")
    revision = config.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision must be a positive integer")

    regime = config.get("regime", {})
    _validate_range(regime.get("ma_period"), "regime.ma_period", 20, 300)
    _validate_range(regime.get("slope_days"), "regime.slope_days", 1, 60)
    _validate_range(regime.get("crash_return_3d"), "regime.crash_return_3d", -0.50, -0.01)
    _validate_range(regime.get("bull_return_20d_min"), "regime.bull_return_20d_min", -0.10, 0.30)
    _validate_range(regime.get("rebound_return_5d_min"), "regime.rebound_return_5d_min", 0.0, 0.30)

    strategies = config.get("strategies", {})
    for strategy in ("mr", "momentum", "gem", "dividend"):
        caps = strategies.get(strategy, {}).get("position_caps", {})
        for state in REGIMES:
            _validate_range(caps.get(state), f"{strategy}.position_caps.{state}", 0, 100)

    for strategy in ("mr", "momentum"):
        losses = strategies.get(strategy, {}).get("stop_losses", {})
        for state in REGIMES:
            _validate_range(losses.get(state), f"{strategy}.stop_losses.{state}", 0, 0.50)

    momentum = strategies.get("momentum", {})
    single_caps = momentum.get("single_position_caps", {})
    for state in REGIMES:
        _validate_range(
            single_caps.get(state),
            f"momentum.single_position_caps.{state}",
            0,
            100,
        )
        if float(single_caps[state]) > float(momentum["position_caps"][state]):
            raise ValueError(
                f"momentum.single_position_caps.{state} must not exceed total position cap"
            )
    for state in ("BEAR", "RANGE", "BULL"):
        _validate_range(
            momentum.get("score_gates", {}).get(state),
            f"momentum.score_gates.{state}",
            0,
            100,
        )
    _validate_range(
        momentum.get("score_gates", {}).get("CRASH"),
        "momentum.score_gates.CRASH",
        100,
        1000,
    )
    validation = momentum.get("validation", {})
    execution = momentum.get("execution", {})
    if execution.get("amount_unit") != "thousand_cny":
        raise ValueError("momentum.execution.amount_unit must be thousand_cny")
    _validate_range(
        execution.get("liquidity_lookback_days"),
        "momentum.execution.liquidity_lookback_days",
        5,
        120,
    )
    _validate_range(
        execution.get("min_valid_amount_days"),
        "momentum.execution.min_valid_amount_days",
        5,
        120,
    )
    if int(execution["min_valid_amount_days"]) > int(
        execution["liquidity_lookback_days"]
    ):
        raise ValueError(
            "momentum.execution.min_valid_amount_days must not exceed lookback"
        )
    _validate_range(
        execution.get("min_median_turnover_cny"),
        "momentum.execution.min_median_turnover_cny",
        1_000_000,
        100_000_000_000,
    )
    _validate_range(
        execution.get("max_participation_rate"),
        "momentum.execution.max_participation_rate",
        0.001,
        0.10,
    )
    if not isinstance(execution.get("pretrade_quote_required"), bool):
        raise ValueError(
            "momentum.execution.pretrade_quote_required must be boolean"
        )
    _validate_range(
        execution.get("constituent_max_age_days"),
        "momentum.execution.constituent_max_age_days",
        1,
        120,
    )
    _validate_range(
        execution.get("constituent_top_n"),
        "momentum.execution.constituent_top_n",
        1,
        20,
    )
    weight_bounds = execution.get("constituent_weight_sum_bounds_pct")
    if not isinstance(weight_bounds, list) or len(weight_bounds) != 2:
        raise ValueError(
            "momentum.execution.constituent_weight_sum_bounds_pct must have two values"
        )
    _validate_range(
        weight_bounds[0],
        "momentum.execution.constituent_weight_sum_bounds_pct.lower",
        50,
        100,
    )
    _validate_range(
        weight_bounds[1],
        "momentum.execution.constituent_weight_sum_bounds_pct.upper",
        100,
        150,
    )
    if float(weight_bounds[0]) >= float(weight_bounds[1]):
        raise ValueError(
            "momentum.execution constituent weight lower bound must be below upper"
        )
    if not isinstance(validation.get("model_id"), str) or not validation["model_id"]:
        raise ValueError("momentum.validation.model_id must be non-empty")
    if not isinstance(validation.get("factor_version"), str) or not validation["factor_version"]:
        raise ValueError("momentum.validation.factor_version must be non-empty")
    artifact_path = validation.get("artifact_path")
    if not isinstance(artifact_path, str) or not artifact_path.endswith(".json"):
        raise ValueError("momentum.validation.artifact_path must be a JSON path")
    universe_path = validation.get("universe_history_path")
    if not isinstance(universe_path, str) or not universe_path.endswith(".json"):
        raise ValueError("momentum.validation.universe_history_path must be a JSON path")
    for date_key in ("validation_start", "holdout_start"):
        try:
            datetime.fromisoformat(str(validation.get(date_key)))
        except (TypeError, ValueError):
            raise ValueError(f"momentum.validation.{date_key} must be an ISO date")
    if validation["holdout_start"] <= validation["validation_start"]:
        raise ValueError("momentum.validation.holdout_start must follow validation_start")
    _validate_range(validation.get("rebalance_days"), "momentum.validation.rebalance_days", 5, 63)
    _validate_range(validation.get("holding_days"), "momentum.validation.holding_days", 5, 63)
    _validate_range(validation.get("min_history_days"), "momentum.validation.min_history_days", 60, 1250)
    _validate_range(validation.get("round_trip_cost_bps"), "momentum.validation.round_trip_cost_bps", 0, 200)
    _validate_range(validation.get("max_artifact_age_days"), "momentum.validation.max_artifact_age_days", 1, 365)
    _validate_range(validation.get("max_data_lag_days"), "momentum.validation.max_data_lag_days", 1, 90)
    lifecycle = validation.get("regime_lifecycle")
    if not isinstance(lifecycle, Mapping) or set(lifecycle) != set(REGIMES):
        raise ValueError("momentum.validation.regime_lifecycle must cover all regimes")
    allowed_lifecycle = {"disabled", "shadow", "enabled"}
    if any(value not in allowed_lifecycle for value in lifecycle.values()):
        raise ValueError("momentum.validation.regime_lifecycle contains invalid state")
    promotion = validation.get("promotion", {})
    _validate_range(promotion.get("min_oos_signals"), "momentum.validation.promotion.min_oos_signals", 1, 100000)
    _validate_range(promotion.get("min_oos_win_rate"), "momentum.validation.promotion.min_oos_win_rate", 0, 1)
    _validate_range(promotion.get("min_profit_factor"), "momentum.validation.promotion.min_profit_factor", 0, 100)
    _validate_range(promotion.get("min_avg_excess_return"), "momentum.validation.promotion.min_avg_excess_return", -1, 1)
    _validate_range(promotion.get("max_drawdown"), "momentum.validation.promotion.max_drawdown", 0, 1)
    _validate_range(promotion.get("min_regime_signals"), "momentum.validation.promotion.min_regime_signals", 1, 100000)
    _validate_range(promotion.get("min_regime_win_rate"), "momentum.validation.promotion.min_regime_win_rate", 0, 1)
    _validate_range(promotion.get("min_regime_profit_factor"), "momentum.validation.promotion.min_regime_profit_factor", 0, 100)
    _validate_range(promotion.get("min_regime_avg_excess_return"), "momentum.validation.promotion.min_regime_avg_excess_return", -1, 1)
    _validate_range(promotion.get("min_regime_periods"), "momentum.validation.promotion.min_regime_periods", 1, 10000)
    _validate_range(promotion.get("min_regime_positive_period_rate"), "momentum.validation.promotion.min_regime_positive_period_rate", 0, 1)
    _validate_range(promotion.get("min_regime_wilson_lower_95"), "momentum.validation.promotion.min_regime_wilson_lower_95", 0, 1)
    _validate_range(promotion.get("min_regime_period_profit_factor"), "momentum.validation.promotion.min_regime_period_profit_factor", 0, 100)
    _validate_range(promotion.get("min_regime_period_avg_excess_return"), "momentum.validation.promotion.min_regime_period_avg_excess_return", -1, 1)
    _validate_range(promotion.get("max_regime_period_drawdown"), "momentum.validation.promotion.max_regime_period_drawdown", 0, 1)
    required_regimes = promotion.get("required_regimes")
    if not isinstance(required_regimes, list) or not required_regimes:
        raise ValueError("momentum.validation.promotion.required_regimes must be non-empty")
    if any(state not in REGIMES for state in required_regimes):
        raise ValueError("momentum.validation.promotion.required_regimes contains invalid regime")
    if not isinstance(promotion.get("require_point_in_time_universe"), bool):
        raise ValueError("momentum.validation.promotion.require_point_in_time_universe must be boolean")

    mr = strategies.get("mr", {})
    _validate_mr_lifecycle(mr)
    for state in MR_REGIMES:
        params = mr.get("regimes", {}).get(state, {}).get("params", {})
        if "stop_loss" in params:
            raise ValueError(f"mr.regimes.{state}.params.stop_loss duplicates mr.stop_losses")
        params_with_stop = dict(params)
        params_with_stop["stop_loss"] = mr.get("stop_losses", {}).get(state)
        _validate_mr_params(params_with_stop)
        _validate_range(mr.get("score_gates", {}).get(state), f"mr.score_gates.{state}", 0, 100)
    _validate_range(mr.get("score_gates", {}).get("CRASH"), "mr.score_gates.CRASH", 100, 1000)

    _validate_erp_params(strategies.get("erp", {}).get("params", {}))


def _normalize_mr_params(params: Mapping[str, Any]) -> dict:
    normalized = dict(params)
    if "N_trend" not in normalized and "ma_trend" in normalized:
        normalized["N_trend"] = normalized.pop("ma_trend")
    else:
        normalized.pop("ma_trend", None)
    return normalized


def _validate_mr_params(params: Mapping[str, Any]) -> None:
    params = _normalize_mr_params(params)
    _validate_range(params.get("N_trend"), "mr.N_trend", 20, 300)
    _validate_range(params.get("rsi_period"), "mr.rsi_period", 2, 60)
    _validate_range(params.get("rsi_buy"), "mr.rsi_buy", 0, 50)
    _validate_range(params.get("rsi_sell"), "mr.rsi_sell", 50, 100)
    _validate_range(params.get("bias_buy"), "mr.bias_buy", -20, 0)
    _validate_range(params.get("stop_loss"), "mr.stop_loss", 0.01, 0.50)
    if params["rsi_buy"] >= params["rsi_sell"]:
        raise ValueError("mr.rsi_buy must be below mr.rsi_sell")


def _validate_erp_params(params: Mapping[str, Any]) -> None:
    _validate_range(params.get("buy_threshold"), "erp.buy_threshold", 1, 100)
    _validate_range(params.get("sell_threshold"), "erp.sell_threshold", 0, 99)
    _validate_range(params.get("erp_window"), "erp.erp_window", 60, 3000)
    _validate_range(params.get("stop_loss"), "erp.stop_loss", 0, 50)
    if params["buy_threshold"] <= params["sell_threshold"]:
        raise ValueError("erp.buy_threshold must exceed erp.sell_threshold")

    weight_keys = ("w_erp_abs", "w_erp_pct", "w_m1", "w_vol", "w_credit")
    weights = []
    for key in weight_keys:
        _validate_range(params.get(key), f"erp.{key}", 0, 1)
        weights.append(float(params[key]))
    if not math.isclose(sum(weights), 1.0, abs_tol=1e-8):
        raise ValueError("ERP weights must sum to 1.0")


def _read_config_strict(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    validate_runtime_config(config)
    return config


def load_runtime_config(*, force: bool = False, path: Path | str | None = None) -> dict:
    """Load the validated runtime config, cached by mtime in production."""
    global _cached_config, _cached_mtime_ns
    target = Path(path) if path is not None else RUNTIME_CONFIG_PATH
    if path is not None:
        return _read_config_strict(target)

    with _cache_lock:
        mtime_ns = target.stat().st_mtime_ns
        if force or _cached_config is None or mtime_ns != _cached_mtime_ns:
            _cached_config = _read_config_strict(target)
            _cached_mtime_ns = mtime_ns
        return copy.deepcopy(_cached_config)


def get_regime_rules() -> dict:
    return load_runtime_config()["regime"]


def get_position_cap(strategy: str, regime: str, *, as_ratio: bool = False,
                     apply_vol_adj: bool = True) -> float:
    """Get position cap for a strategy under a given regime.

    Vol overlay V2: when apply_vol_adj=True, multiply by the market tail-brake factor
    (services.vol_regime). The factor is 1.0 unless A-share volatility exceeds
    2x its adaptive baseline, or the volatility data is stale/missing (fail-conservative).
    Backtests must pass apply_vol_adj=False or use compute_vol_factor_frame() point-in-time.

    Args:
        strategy: Strategy name (mr/momentum/gem/dividend)
        regime: Market state (BEAR/RANGE/BULL/CRASH)
        as_ratio: True returns 0-1 decimal, False returns 0-100 percent
        apply_vol_adj: Apply vol adjustment (set False for backtests)
    """
    caps = load_runtime_config()["strategies"][strategy]["position_caps"]
    value = float(caps[regime.upper()])

    # P0-1: Volatility-adaptive position cap adjustment
    # CRASH regime (cap=0) needs no adjustment
    if apply_vol_adj and value > 0:
        try:
            from services.vol_regime import get_vol_adjustment_factor
            vol_factor = get_vol_adjustment_factor()
            if vol_factor != 1.0:
                adjusted = value * vol_factor
                # Hard ceiling: never exceed 95% (audit red-line)
                value = round(min(95.0, adjusted), 1)
        except Exception:
            # 模块本身异常 (非数据问题) 时不改变上限; 数据缺失/过期由 vol_regime 内部保守处理
            pass

    return value / 100.0 if as_ratio else value


def get_stop_loss(strategy: str, regime: str) -> float:
    losses = load_runtime_config()["strategies"][strategy]["stop_losses"]
    return float(losses[regime.upper()])


def get_single_position_cap(
    strategy: str, regime: str, *, as_ratio: bool = False
) -> float:
    caps = load_runtime_config()["strategies"][strategy]["single_position_caps"]
    value = float(caps[regime.upper()])
    return value / 100.0 if as_ratio else value


def get_score_gate(strategy: str, regime: str) -> float:
    gates = load_runtime_config()["strategies"][strategy]["score_gates"]
    return float(gates[regime.upper()])


def get_industry_validation_rules() -> dict:
    """Return the versioned validation and promotion contract."""
    return copy.deepcopy(
        load_runtime_config()["strategies"]["momentum"]["validation"]
    )


def get_industry_execution_rules() -> dict:
    """Return the versioned ETF liquidity and order-release contract."""
    return copy.deepcopy(
        load_runtime_config()["strategies"]["momentum"]["execution"]
    )


def get_mr_params(regime: str) -> dict:
    state = regime.upper()
    mr = load_runtime_config()["strategies"]["mr"]
    source_state = "RANGE" if state == "CRASH" else state
    params = _normalize_mr_params(mr["regimes"][source_state]["params"])
    params["stop_loss"] = float(mr["stop_losses"][state])
    return params


def get_all_mr_params() -> dict:
    return {state: get_mr_params(state) for state in MR_REGIMES}


def get_mr_lifecycle(
    regime: str, *, as_of: datetime | None = None
) -> dict:
    """Return the configured and effective MR parameter lifecycle."""
    state = regime.upper()
    if state == "CRASH":
        state = "RANGE"
    if state not in MR_REGIMES:
        raise ValueError(f"unsupported MR regime: {regime}")
    raw = copy.deepcopy(
        load_runtime_config()["strategies"]["mr"]["lifecycle"][state]
    )
    configured_status = raw["status"]
    effective_status = configured_status
    reason = f"lifecycle_{configured_status}"
    now = as_of or datetime.now(RUNTIME_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=RUNTIME_TIMEZONE)
    _DEGRADABLE = {"validated", "insufficient_evidence", "rejected"}
    if (
        configured_status in _DEGRADABLE
        and now
        > _parse_runtime_datetime(
            raw["next_validate_after"],
            f"mr.lifecycle.{state}.next_validate_after",
        )
    ):
        effective_status = "stale"
        reason = "validation_expired"
    raw.update({
        "configured_status": configured_status,
        "status": effective_status,
        "allow_new_entries": effective_status == "validated",
        "reason": reason,
    })
    return raw


def get_all_mr_lifecycle(*, as_of: datetime | None = None) -> dict[str, dict]:
    return {
        state: get_mr_lifecycle(state, as_of=as_of)
        for state in MR_REGIMES
    }


def get_erp_params() -> dict:
    return load_runtime_config()["strategies"]["erp"]["params"]


def get_runtime_metadata() -> dict:
    config = load_runtime_config()
    return {
        "schema_version": config["schema_version"],
        "revision": config["revision"],
        "published_at": config.get("published_at"),
        "published_by": config.get("published_by"),
    }


def record_ci_outcome(
    ci_run: Mapping[str, Any], *, path: Path | str | None = None,
) -> dict:
    """Record a non-passing CI result in lifecycle without changing params.

    For INSUFFICIENT_EVIDENCE and REJECT outcomes, updates the lifecycle
    status and timestamps so audit reflects reality rather than 'stale'.
    """
    global _cached_config, _cached_mtime_ns
    strategy = str(ci_run.get("strategy", "")).lower()
    if strategy != "mr":
        raise ValueError(f"record_ci_outcome only supports MR, got: {strategy}")

    regime = str(ci_run.get("regime", "")).upper()
    if regime not in MR_REGIMES:
        raise ValueError(f"unsupported regime: {regime}")

    status = str(ci_run.get("status", "")).upper()
    lifecycle_map = {
        "INSUFFICIENT_EVIDENCE": "insufficient_evidence",
        "REJECT": "rejected",
    }
    lifecycle_status = lifecycle_map.get(status)
    if not lifecycle_status:
        raise ValueError(f"record_ci_outcome does not handle status: {status}")

    validation = ci_run.get("validation") or {}
    data_through = str(
        validation.get("data_through", datetime.now(RUNTIME_TIMEZONE).date().isoformat())
    )
    retry_days = 30 if lifecycle_status == "insufficient_evidence" else 14

    target = Path(path) if path is not None else RUNTIME_CONFIG_PATH
    now = datetime.now(RUNTIME_TIMEZONE)
    next_va = now + timedelta(days=retry_days)

    with _publish_lock:
        current = _read_config_strict(target)
        updated = copy.deepcopy(current)
        updated["strategies"]["mr"]["lifecycle"][regime] = {
            "status": lifecycle_status,
            "validated_at": now.isoformat(),
            "data_through": data_through,
            "validation_run_id": str(ci_run.get("run_id") or "unknown"),
            "next_validate_after": next_va.isoformat(),
        }
        updated["revision"] = current["revision"] + 1
        updated["published_at"] = now.isoformat()
        updated["published_by"] = f"ci_outcome:{ci_run.get('run_id', 'unknown')}"
        validate_runtime_config(updated)
        backup_path = _atomic_write_config(target, updated)

        if target == RUNTIME_CONFIG_PATH:
            with _cache_lock:
                _cached_config = copy.deepcopy(updated)
                _cached_mtime_ns = target.stat().st_mtime_ns

    return {
        "regime": regime,
        "status": lifecycle_status,
        "next_validate_after": next_va.isoformat(),
        "backup_path": str(backup_path),
    }


def _apply_ci_update(config: dict, ci_run: Mapping[str, Any]) -> None:
    strategy = str(ci_run.get("strategy", "")).lower()

    if strategy == "mr":
        regime = str(ci_run.get("regime", "")).upper()
        if regime not in MR_REGIMES:
            raise ValueError("MR publication requires BEAR, RANGE, or BULL")
        status = str(ci_run.get("status", "")).upper()
        if status not in {"ACCEPT", "REVALIDATED"}:
            raise ValueError(f"MR CI status {status or 'missing'} is not publishable")
        validation = ci_run.get("validation")
        if not isinstance(validation, Mapping):
            raise ValueError("MR publication requires frozen OOS validation")
        expected_decision = {
            "ACCEPT": "ACCEPT_CHALLENGER",
            "REVALIDATED": "REVALIDATE_INCUMBENT",
        }[status]
        if validation.get("method") != "frozen_oos":
            raise ValueError("MR publication requires frozen_oos method")
        if validation.get("decision") != expected_decision:
            raise ValueError("MR publication status and validation decision disagree")
        try:
            oos_start = datetime.fromisoformat(str(validation["oos_start"])).date()
            data_through = datetime.fromisoformat(
                str(validation["data_through"])
            ).date()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("MR validation dates must be ISO dates") from exc
        if data_through < oos_start:
            raise ValueError("MR validation data_through precedes oos_start")

        if status == "ACCEPT":
            new_params = ci_run.get("new_params")
            if not isinstance(new_params, Mapping) or not new_params:
                raise ValueError("CI run has no publishable parameters")
            normalized = _normalize_mr_params(new_params)
            _validate_mr_params(normalized)
            stop_loss = float(normalized.pop("stop_loss"))
            config["strategies"]["mr"]["regimes"][regime]["params"] = normalized
            config["strategies"]["mr"]["stop_losses"][regime] = stop_loss

        validated_at = datetime.now(RUNTIME_TIMEZONE)
        next_validate_after = validated_at + timedelta(days=60)
        config["strategies"]["mr"]["regimes"][regime]["published_run_id"] = ci_run.get("run_id")
        config["strategies"]["mr"]["lifecycle"][regime] = {
            "status": "validated",
            "validated_at": validated_at.isoformat(),
            "data_through": data_through.isoformat(),
            "validation_run_id": str(ci_run.get("run_id") or "unknown"),
            "next_validate_after": next_validate_after.isoformat(),
        }
        config["strategies"]["mr"]["next_optimize_after"] = (
            next_validate_after.date().isoformat()
        )
        return

    if strategy == "erp":
        new_params = ci_run.get("new_params")
        if not isinstance(new_params, Mapping) or not new_params:
            raise ValueError("CI run has no publishable parameters")
        params = dict(new_params)
        _validate_erp_params(params)
        config["strategies"]["erp"]["params"] = params
        config["strategies"]["erp"]["published_run_id"] = ci_run.get("run_id")
        return

    raise ValueError(f"unsupported CI strategy: {strategy}")


def _published_run_id(config: Mapping[str, Any], ci_run: Mapping[str, Any]) -> Any:
    strategy = str(ci_run.get("strategy", "")).lower()
    if strategy == "mr":
        regime = str(ci_run.get("regime", "")).upper()
        return (
            config.get("strategies", {})
            .get("mr", {})
            .get("lifecycle", {})
            .get(regime, {})
            .get("validation_run_id")
        )
    if strategy == "erp":
        return config.get("strategies", {}).get("erp", {}).get("published_run_id")
    return None


def _atomic_write_config(path: Path, config: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    backup_path = path.with_suffix(path.suffix + ".bak")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        _read_config_strict(temp_path)
        if path.exists():
            shutil.copy2(path, backup_path)
        os.replace(temp_path, path)
        return backup_path
    finally:
        if temp_path.exists():
            temp_path.unlink()


def publish_ci_parameters(
    ci_run: Mapping[str, Any], *, path: Path | str | None = None,
) -> dict:
    """Validate and atomically publish one accepted CI parameter set."""
    global _cached_config, _cached_mtime_ns
    target = Path(path) if path is not None else RUNTIME_CONFIG_PATH

    with _publish_lock:
        current = _read_config_strict(target)
        run_id = ci_run.get("run_id")
        if run_id and _published_run_id(current, ci_run) == run_id:
            return {
                "revision": current["revision"],
                "published_at": current.get("published_at"),
                "published_by": current.get("published_by"),
                "backup_path": str(target.with_suffix(target.suffix + ".bak")),
                "already_published": True,
            }
        updated = copy.deepcopy(current)
        _apply_ci_update(updated, ci_run)
        updated["revision"] = current["revision"] + 1
        updated["published_at"] = datetime.now().isoformat()
        updated["published_by"] = f"ci:{ci_run.get('run_id', 'unknown')}"
        validate_runtime_config(updated)
        backup_path = _atomic_write_config(target, updated)

        if target == RUNTIME_CONFIG_PATH:
            with _cache_lock:
                _cached_config = copy.deepcopy(updated)
                _cached_mtime_ns = target.stat().st_mtime_ns

        return {
            "revision": updated["revision"],
            "published_at": updated["published_at"],
            "published_by": updated["published_by"],
            "backup_path": str(backup_path),
        }
