"""Evaluate whether a new application container is safe to deploy.

Trading-data health and application readiness are intentionally separate:
the UI can safely expose a locked/degraded decision state as long as the
dashboard itself has finished warming up with fresh data.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any


def evaluate_deployment_readiness(health: Mapping[str, Any] | None) -> dict:
    """Return a machine-readable deployment decision for a health payload."""
    payload = health if isinstance(health, Mapping) else {}
    status = payload.get("status")
    engines = payload.get("engines")
    freshness = payload.get("freshness")
    dashboard = engines.get("dashboard", {}) if isinstance(engines, Mapping) else {}
    dashboard_freshness = (
        freshness.get("dashboard", {}) if isinstance(freshness, Mapping) else {}
    )

    dashboard_ready = (
        isinstance(dashboard, Mapping)
        and dashboard.get("status") == "ready"
        and isinstance(dashboard_freshness, Mapping)
        and dashboard_freshness.get("fresh") is True
    )
    ready = status in {"ok", "degraded"} and dashboard_ready
    reasons = payload.get("health_reasons")
    if not isinstance(reasons, list):
        reasons = []

    if ready and status == "ok":
        mode = "healthy"
    elif ready:
        mode = "safe_degraded"
    else:
        mode = "not_ready"

    return {
        "ready": ready,
        "mode": mode,
        "status": status or "invalid",
        "health_reasons": reasons,
        "dashboard_status": (
            dashboard.get("status", "missing")
            if isinstance(dashboard, Mapping)
            else "missing"
        ),
        "dashboard_fresh": bool(
            isinstance(dashboard_freshness, Mapping)
            and dashboard_freshness.get("fresh") is True
        ),
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        payload = None
    print(json.dumps(evaluate_deployment_readiness(payload), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
