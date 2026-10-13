"""Regression tests for the production readiness gate."""

from pathlib import Path

from engines import production_check as pc


PROJECT_ROOT = Path(__file__).parents[1]


def test_current_v5_parameter_contract_is_accepted():
    status, message = pc.check_aiae_params()

    assert status == "pass"
    assert "V5.2" in message


def test_frontend_fallback_thresholds_match_backend_contract():
    status, message = pc.check_frontend_v5_sync()

    assert status == "pass", message
    assert "thresholds" in message.lower()


def test_code_only_groups_exclude_runtime_data_checks():
    groups = pc.build_check_groups(code_only=True)
    names = [name for _, checks in groups for name, _ in checks]

    assert "history_parquet" not in names
    assert "backtest_results" not in names
    assert "frontend_sync" in names


def test_main_returns_failure_exit_code_when_any_check_fails(monkeypatch):
    monkeypatch.setattr(
        pc,
        "run_checks",
        lambda groups, emit=print: {"pass": 2, "warn": 0, "fail": 1},
    )

    assert pc.main(["--code-only"]) == 1


def test_ci_runs_code_only_production_readiness_gate():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "python engines/production_check.py --code-only" in workflow
