"""Fail-closed safety rules shared by AIAE producers and consumers."""

import math
from typing import Any, Mapping, Tuple


AIAE_MIN_QUALITY_SCORE = 50
AIAE_FAILED_QUALITY_SCORE = 0


def resolve_aiae_safety(report: Mapping[str, Any] | None) -> Tuple[float, bool]:
    """Return a validated ``(quality_score, decision_locked)`` pair.

    Only an explicit successful report with a valid quality score and an
    explicit unlocked flag may permit decisions. All missing, malformed, or
    degraded reports fail closed.
    """
    if not isinstance(report, Mapping) or report.get("status") != "success":
        return AIAE_FAILED_QUALITY_SCORE, True

    raw_score = report.get("data_quality_score")
    if isinstance(raw_score, bool):
        return AIAE_FAILED_QUALITY_SCORE, True

    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return AIAE_FAILED_QUALITY_SCORE, True

    if not math.isfinite(score):
        return AIAE_FAILED_QUALITY_SCORE, True

    score = max(0.0, min(100.0, score))
    if score.is_integer():
        score = int(score)

    explicitly_unlocked = report.get("decision_locked") is False
    locked = not explicitly_unlocked or score < AIAE_MIN_QUALITY_SCORE
    return score, locked


def build_aiae_context(report: Mapping[str, Any] | None) -> dict:
    """Normalize an AIAE engine report into the shared consumer contract."""
    safe_report = report if isinstance(report, Mapping) else {}
    current = safe_report.get("current")
    current = current if isinstance(current, Mapping) else {}
    position = safe_report.get("position")
    position = position if isinstance(position, Mapping) else {}
    quality_score, report_locked = resolve_aiae_safety(safe_report)

    raw_cap = position.get("matrix_position")
    try:
        cap = float(raw_cap)
        cap_valid = math.isfinite(cap) and 0 <= cap <= 100
    except (TypeError, ValueError):
        cap = None
        cap_valid = False
    if cap_valid and cap.is_integer():
        cap = int(cap)

    position_unlocked = position.get("decision_locked") is False
    locked = report_locked or not position_unlocked or not cap_valid
    regime_info = current.get("regime_info")
    regime_info = regime_info if isinstance(regime_info, Mapping) else {}
    slope = current.get("slope")
    slope = slope if isinstance(slope, Mapping) else {}

    return {
        "status": safe_report.get("status", "error"),
        "updated_at": safe_report.get("updated_at"),
        "regime": current.get("regime"),
        "regime_cn": regime_info.get("cn"),
        "regime_info": dict(regime_info),
        "cap": cap if cap_valid else None,
        "aiae_v1": current.get("regime_basis_value", current.get("aiae_v1")),
        "slope": slope.get("slope", 0),
        "slope_direction": slope.get("direction", "flat"),
        "margin_heat": current.get("margin_heat"),
        "fund_position": current.get("fund_position"),
        "fund_position_source": current.get("fund_position_source"),
        "fund_position_date": current.get("fund_position_date"),
        "regime_basis_value": current.get("regime_basis_value"),
        "regime_thresholds": current.get("regime_thresholds"),
        "regime_mode": current.get("regime_mode"),
        "data_quality_score": quality_score,
        "decision_locked": locked,
    }


def apply_vol_overlay(context: Mapping[str, Any], overlay: Mapping[str, Any] | None) -> dict:
    """Return a copy of an AIAE context whose ``cap`` is the volatility-adjusted cap.

    ``base_cap`` keeps the raw AIAE matrix position; ``cap`` becomes
    ``min(95, base_cap × factor)``. Locked or invalid contexts are returned
    unchanged (they never emit tactics anyway). The overlay is recorded under
    ``vol_overlay`` so every consumer can show why the cap moved.
    """
    ctx = dict(context or {})
    if ctx.get("decision_locked") is not False or ctx.get("cap") is None:
        return ctx
    from services.vol_regime import apply_vol_overlay_to_cap

    base_cap = ctx.get("base_cap", ctx["cap"])
    effective = apply_vol_overlay_to_cap(base_cap, overlay)
    if effective is None:
        return ctx
    if isinstance(effective, float) and effective.is_integer():
        effective = int(effective)
    ov = dict(overlay or {})
    ctx["base_cap"] = base_cap
    ctx["cap"] = effective
    ctx["vol_overlay"] = {
        "status": ov.get("status", "unknown"),
        "factor": ov.get("factor", 1.0),
        "brake_on": bool(ov.get("brake_on", False)),
        "sigma_hat": ov.get("sigma_hat"),
        "baseline": ov.get("baseline"),
        "ratio": ov.get("ratio"),
        "trigger_ratio": ov.get("trigger_ratio"),
        "trade_date": ov.get("trade_date"),
        "reason": ov.get("reason", ""),
    }
    return ctx
