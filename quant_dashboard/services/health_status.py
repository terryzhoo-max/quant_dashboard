"""Pure system-health evaluation used by the FastAPI health endpoint."""

import math
from datetime import datetime
from typing import Any, Mapping, Optional

from services.aiae_safety import AIAE_MIN_QUALITY_SCORE, resolve_aiae_safety


_MAX_FUTURE_CLOCK_SKEW_SEC = 300


def _timestamp_age_seconds(value: Any, now_ts: float) -> Optional[int]:
    """Convert Unix or ISO timestamps to a non-negative age in seconds."""
    if value is None or isinstance(value, bool):
        return None

    try:
        if isinstance(value, (int, float)):
            timestamp = float(value)
        else:
            raw = str(value).strip()
            try:
                timestamp = float(raw)
            except ValueError:
                try:
                    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    # AIAE engine's stable legacy format, e.g. 2026/9/6 18:21:24.
                    parsed = datetime.strptime(raw, "%Y/%m/%d %H:%M:%S")
                timestamp = parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None

    if not math.isfinite(timestamp):
        return None

    age = now_ts - timestamp
    if age < -_MAX_FUTURE_CLOCK_SKEW_SEC:
        return None
    return max(0, round(age))


def get_aiae_max_age_sec() -> int:
    """Return the market-aware AIAE freshness window."""
    from services.cache_store import get_cache_ttl

    return max(86_400, get_cache_ttl())


def evaluate_aiae_context(
    aiae_ctx: Mapping[str, Any] | None,
    *,
    now_ts: float,
    max_age_sec: int | None = None,
) -> dict:
    """Evaluate whether an AIAE cache entry is safe and fresh enough to use."""
    safe_ctx = aiae_ctx if isinstance(aiae_ctx, Mapping) else {}
    quality_score, safety_locked = resolve_aiae_safety(safe_ctx)
    max_age = max_age_sec if max_age_sec is not None else get_aiae_max_age_sec()
    age = _timestamp_age_seconds(
        safe_ctx.get("updated_at") or safe_ctx.get("ts"),
        now_ts,
    )
    fresh = age is not None and age <= max_age

    if not safe_ctx:
        reason = "missing"
    elif safety_locked:
        reason = "decision_locked"
    elif age is None:
        reason = "timestamp_missing_or_invalid"
    elif not fresh:
        reason = "stale"
    else:
        reason = None

    return {
        "present": bool(safe_ctx),
        "usable": bool(safe_ctx) and not safety_locked and fresh,
        "fresh": fresh,
        "age_sec": age,
        "max_age_sec": max_age,
        "data_quality_score": quality_score,
        "decision_locked": not (bool(safe_ctx) and not safety_locked and fresh),
        "reported_decision_locked": safety_locked,
        "reason": reason,
    }


def evaluate_system_health(
    *,
    dashboard_ready: bool,
    dashboard_updated_at: Any,
    aiae_ctx: Mapping[str, Any] | None,
    now_ts: float,
    dashboard_max_age_sec: int,
    aiae_max_age_sec: int,
) -> dict:
    """Evaluate readiness, AIAE safety, and freshness without side effects."""
    reasons = []

    dashboard_age = _timestamp_age_seconds(dashboard_updated_at, now_ts)
    dashboard_fresh = (
        dashboard_ready
        and dashboard_age is not None
        and dashboard_age <= dashboard_max_age_sec
    )
    if not dashboard_ready:
        reasons.append("dashboard_not_ready")
    elif dashboard_age is None:
        reasons.append("dashboard_timestamp_missing_or_invalid")
    elif not dashboard_fresh:
        reasons.append("dashboard_data_stale")

    aiae_state = evaluate_aiae_context(
        aiae_ctx,
        now_ts=now_ts,
        max_age_sec=aiae_max_age_sec,
    )
    quality_score = aiae_state["data_quality_score"]
    decision_locked = aiae_state["decision_locked"]
    if not aiae_state["present"]:
        reasons.append("aiae_context_missing")
    if quality_score < AIAE_MIN_QUALITY_SCORE:
        reasons.append("aiae_low_data_quality")
    if decision_locked:
        reasons.append("aiae_decision_locked")

    aiae_age = aiae_state["age_sec"]
    aiae_fresh = aiae_state["fresh"]
    if aiae_state["present"]:
        if aiae_age is None:
            reasons.append("aiae_timestamp_missing_or_invalid")
        elif not aiae_fresh:
            reasons.append("aiae_data_stale")

    if not dashboard_ready:
        status = "starting"
    elif reasons:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "reasons": reasons,
        "data_quality_score": quality_score,
        "decision_locked": decision_locked,
        "dashboard_age_sec": dashboard_age,
        "dashboard_max_age_sec": dashboard_max_age_sec,
        "dashboard_fresh": dashboard_fresh,
        "aiae_age_sec": aiae_age,
        "aiae_max_age_sec": aiae_max_age_sec,
        "aiae_fresh": aiae_fresh,
    }
