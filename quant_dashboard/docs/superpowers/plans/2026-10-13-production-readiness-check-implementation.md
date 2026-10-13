# Production Readiness Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AlphaCore production readiness check validate current runtime contracts, support CI without production data, and return a failing process status when readiness fails.

**Architecture:** Refactor the script into named code/data check groups plus a testable `run_checks()`/`main()` entry point. Replace display-text markers with a backend-to-frontend threshold contract, while keeping the full server-side data checks available by default.

**Tech Stack:** Python 3.12, pytest, GitHub Actions

---

## File Structure

- Create `tests/test_production_check.py`: regression tests for version, frontend contract, check selection, and exit status.
- Modify `engines/production_check.py`: structured check groups, meaningful frontend validation, `--code-only`, and exit codes.
- Modify `.github/workflows/ci.yml`: execute the code-only readiness gate after unit tests.

### Task 1: Lock the Correct Contracts with Failing Tests

**Files:**
- Create: `tests/test_production_check.py`
- Test: `tests/test_production_check.py`

- [ ] Write tests asserting that the current V5.2 parameter center passes without an exact duplicated version constant.
- [ ] Write a test asserting that the frontend fallback thresholds equal `V5_REGIME_THRESHOLDS` and that `decision.html` loads `hub_core.js`.
- [ ] Write tests asserting that code-only selection excludes data checks and that a failed check produces exit code 1.
- [ ] Run `python -m pytest tests/test_production_check.py -q` and confirm failures are caused by the missing structured runner/current hard-coded checks.

### Task 2: Implement the Structured Readiness Runner

**Files:**
- Modify: `engines/production_check.py`
- Test: `tests/test_production_check.py`

- [ ] Replace exact `VERSION == "5.0"` with validation of the enabled V5 contract: semantic major version 5, four finite strictly increasing thresholds, and five position-matrix states.
- [ ] Replace display-text marker searches with parsing and comparing `_DEFAULT_REGIME_THRESHOLDS`, plus the `decision.html` script reference check.
- [ ] Define code and data check groups and implement `run_checks(code_only=False)` returning pass/warn/fail counts.
- [ ] Implement `main(argv=None)` with `--code-only`; return 1 on any failure and 0 otherwise; invoke it through `raise SystemExit(main())`.
- [ ] Run `python -m pytest tests/test_production_check.py -q` and confirm all focused tests pass.

### Task 3: Add the CI Gate and Verify the Repository

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_production_check.py`

- [ ] Add `python engines/production_check.py --code-only` after unit tests.
- [ ] Run `python engines/production_check.py --code-only` and require exit 0.
- [ ] Run `python engines/production_check.py` and record its real server-data readiness result.
- [ ] Run `python -m pytest tests -q` and require the full non-integration suite to pass.
- [ ] Run `git diff --check` and inspect `git diff` for scope control.
