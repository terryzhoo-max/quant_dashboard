"""Audit and API must consume runtime MR lifecycle evidence."""

import asyncio
from unittest.mock import patch

from engines import audit_engine
from routers.params_api import get_strategy_config


def _validated_lifecycle():
    return {
        state: {
            "status": "validated",
            "configured_status": "validated",
            "validated_at": "2026-10-13T09:00:00+08:00",
            "data_through": "2026-10-12",
            "validation_run_id": f"run-{state.lower()}",
            "next_validate_after": "2026-12-12T09:00:00+08:00",
            "allow_new_entries": True,
            "reason": "lifecycle_validated",
        }
        for state in ("BEAR", "RANGE", "BULL")
    }


def test_strategy_config_api_exposes_effective_mr_lifecycle():
    lifecycle = _validated_lifecycle()
    with patch("routers.params_api.get_all_mr_lifecycle", return_value=lifecycle):
        payload = asyncio.run(get_strategy_config())

    assert payload["mr"]["lifecycle"] == lifecycle


def test_audit_uses_runtime_lifecycle_not_legacy_mr_artifact():
    with patch(
        "services.strategy_params.get_all_mr_lifecycle",
        return_value=_validated_lifecycle(),
    ):
        result = audit_engine.audit_strategy_health()

    checks = [check for check in result["checks"] if check["name"] == "均值回归"]
    assert len(checks) == 1
    assert checks[0]["status"] == "pass"
    assert checks[0]["score"] == 100
    assert "runtime lifecycle" in checks[0]["meta"]
    assert "均值回归" not in audit_engine.OPTIMIZATION_FILES


def test_audit_fails_when_any_regime_is_stale():
    lifecycle = _validated_lifecycle()
    lifecycle["BEAR"].update({
        "status": "stale",
        "allow_new_entries": False,
        "reason": "validation_expired",
    })
    with patch(
        "services.strategy_params.get_all_mr_lifecycle",
        return_value=lifecycle,
    ):
        result = audit_engine.audit_strategy_health()

    check = next(check for check in result["checks"] if check["name"] == "均值回归")
    assert check["status"] == "fail"
    assert check["score"] == 40


def _run_audit(lifecycle, caps=None):
    caps = caps if caps is not None else {"BEAR": 0, "RANGE": 80, "BULL": 35, "CRASH": 0}
    runtime = {"strategies": {"mr": {"position_caps": caps}}}
    with patch(
        "services.strategy_params.get_all_mr_lifecycle", return_value=lifecycle
    ), patch(
        "services.strategy_params.load_runtime_config", return_value=runtime
    ):
        result = audit_engine.audit_strategy_health()
    return result, next(c for c in result["checks"] if c["name"] == "均值回归")


def test_audit_treats_gated_unvalidated_regimes_as_controlled_disable():
    """insufficient_evidence with entries blocked is fail-closed, not a failure."""
    lifecycle = _validated_lifecycle()
    lifecycle["BEAR"].update({"status": "rejected", "allow_new_entries": False})
    for state in ("RANGE", "BULL"):
        lifecycle[state].update({
            "status": "insufficient_evidence",
            "allow_new_entries": False,
        })
    result, check = _run_audit(lifecycle)

    assert check["status"] == "warn"
    assert check["score"] == 70
    assert "闸门关闭" in check["detail"]
    assert (result.get("circuit_breaker") or {}).get("reason") != "核心路径联锁"


def test_audit_fails_when_unvalidated_regime_still_allows_entries():
    lifecycle = _validated_lifecycle()
    lifecycle["RANGE"].update({
        "status": "insufficient_evidence",
        "allow_new_entries": True,
    })
    _, check = _run_audit(lifecycle)

    assert check["status"] == "fail"
    assert check["score"] == 20

