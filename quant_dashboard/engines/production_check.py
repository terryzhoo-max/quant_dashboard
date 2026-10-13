"""
AlphaCore · 生产就绪检查 (Production Readiness Check)
======================================================
一键验证全系统关键路径。部署前 / 每日启动时运行。

用法:
  python engines/production_check.py
  python engines/production_check.py --code-only
"""
import argparse
import json
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ═══════════════════════════════════════════════════════
#  1. 引擎导入链
# ═══════════════════════════════════════════════════════

def check_aiae_params():
    import engines.aiae_params as AP
    assert AP.V5_ENABLED, "V5_ENABLED is False"
    version_parts = str(AP.VERSION).split(".")
    assert version_parts and version_parts[0].isdigit(), f"invalid VERSION={AP.VERSION}"
    assert int(version_parts[0]) == 5, f"unsupported major VERSION={AP.VERSION}"

    thresholds = [float(value) for value in AP.V5_REGIME_THRESHOLDS]
    assert len(thresholds) == 4, f"expected 4 V5 thresholds, got {len(thresholds)}"
    assert all(
        left < right for left, right in zip(thresholds, thresholds[1:])
    ), f"V5 thresholds are not strictly increasing: {thresholds}"
    assert set(AP.POSITION_MATRIX) == {
        "erp_gt6", "erp_4_6", "erp_2_4", "erp_lt2"
    }, "V5 position matrix ERP tiers are incomplete"
    assert all(len(row) == 5 for row in AP.POSITION_MATRIX.values()), (
        "V5 position matrix must cover all 5 regimes"
    )
    return "pass", f"V{AP.VERSION}, V5 contract valid, thresholds={thresholds}"


def check_aiae_engine():
    from engines.aiae_engine import get_aiae_engine
    e = get_aiae_engine()
    assert hasattr(e, 'classify_regime'), "missing classify_regime"
    assert hasattr(e, 'get_position_from_matrix'), "missing get_position_from_matrix"
    return "pass", "classify_regime + get_position_from_matrix OK"


def check_backtest_engine():
    from engines.aiae_backtest_v4 import AIAEBacktestV4
    assert callable(AIAEBacktestV4), "AIAEBacktestV4 is not callable"
    return "pass", "AIAEBacktestV4 importable"


def check_sub_engines():
    missing = []
    for name in ['mean_reversion_engine', 'dividend_trend_engine',
                 'momentum_rotation_engine', 'dual_momentum_engine']:
        try:
            __import__(f'engines.{name}')
        except Exception as e:
            missing.append(f"{name}: {e}")
    if missing:
        return "fail", "; ".join(missing)
    return "pass", "MR + Dividend + Momentum + GEM all importable"


def check_drift_monitor():
    from engines.drift_monitor import check_regime_transition
    # Verify the function exists and is callable
    assert callable(check_regime_transition)
    return "pass", "5-dim drift monitor (incl. regime_transition)"


# ═══════════════════════════════════════════════════════
#  2. V5 信号链路
# ═══════════════════════════════════════════════════════

def check_v5_regime_classify():
    from engines.aiae_engine import get_aiae_engine
    e = get_aiae_engine()
    # 4 个关键时点
    cases = [
        (21.0, 1, "R1 极低估"),
        (23.5, 2, "R2 低估"),
        (25.0, 3, "R3 中性"),
        (27.0, 4, "R4 偏高"),
        (29.0, 5, "R5 过热"),
    ]
    errors = []
    for val, expected, label in cases:
        r = e.classify_regime(25.0, None, aiae_simple=val)
        if r != expected:
            errors.append(f"{label}: got R{r}, expected R{expected}")
    if errors:
        return "fail", "; ".join(errors)
    return "pass", "5/5 regime points correct"


def check_v5_position_matrix():
    from engines.aiae_engine import get_aiae_engine
    e = get_aiae_engine()
    # R1+ERP>6% should cap at 80%, not 95%
    pos = e.get_position_from_matrix(1, 'erp_gt6', aiae_value=20.0)
    if pos > 80:
        return "fail", f"R1+ERP>6%={pos}%, expected <=80%"
    # R5+ERP<2% should be 0%
    pos5 = e.get_position_from_matrix(5, 'erp_lt2', aiae_value=30.0)
    if pos5 != 0:
        return "fail", f"R5+ERP<2%={pos5}%, expected 0%"
    return "pass", f"R1 cap={pos}%, R5 floor={pos5}%"


# ═══════════════════════════════════════════════════════
#  3. 数据完整性
# ═══════════════════════════════════════════════════════

def check_history_parquet():
    import pandas as pd
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data_lake', 'aiae_true_history.parquet')
    if not os.path.exists(path):
        return "fail", "aiae_true_history.parquet not found"
    df = pd.read_parquet(path)
    n = len(df)
    if n < 130:
        return "warn", f"only {n} months (expected >=130)"
    return "pass", f"{n} months, {df['month'].iloc[0]}~{df['month'].iloc[-1]}"


def check_backtest_results():
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'aiae_backtest_v4_results.json')
    if not os.path.exists(path):
        return "fail", "aiae_backtest_v4_results.json not found"
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    n_strat = len(data.get('strategies', {}))
    has_v5 = any('V5' in k for k in data.get('strategies', {}))
    if not has_v5:
        return "warn", f"{n_strat} strategies but no V5"
    return "pass", f"{n_strat} strategies, V5 present"


# ═══════════════════════════════════════════════════════
#  4. 配额一致性
# ═══════════════════════════════════════════════════════

def check_sub_strategy_alloc():
    from engines.aiae_params import SUB_STRATEGY_ALLOC
    errors = []
    for regime, alloc in SUB_STRATEGY_ALLOC.items():
        total = sum(alloc.values())
        if total != 100:
            errors.append(f"R{regime}: sum={total}")
        if 'div' not in alloc:
            errors.append(f"R{regime}: missing 'div' key")
    if errors:
        return "fail", "; ".join(errors)
    return "pass", "5 regimes, all sum=100, all keys present"


def check_dividend_aiae_integration():
    """Verify dividend engine has AIAE quota code"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'dividend_trend_engine.py')
    with open(path, 'r', encoding='utf-8') as f:
        code = f.read()
    if 'SUB_STRATEGY_ALLOC' not in code:
        return "fail", "dividend_trend_engine.py missing AIAE quota integration"
    if 'aiae_cap_pct' not in code:
        return "fail", "dividend_trend_engine.py missing aiae_cap_pct variable"
    return "pass", "AIAE quota integration present in dividend engine"


# ═══════════════════════════════════════════════════════
#  5. 前端一致性
# ═══════════════════════════════════════════════════════

def check_frontend_v5_sync():
    """Validate the runtime threshold contract instead of display text."""
    from engines import aiae_params as AP

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    decision_path = os.path.join(base, "decision.html")
    hub_path = os.path.join(base, "static", "js", "decision", "hub_core.js")

    if not os.path.exists(decision_path):
        return "fail", "decision.html not found"
    if not os.path.exists(hub_path):
        return "fail", "static/js/decision/hub_core.js not found"

    with open(decision_path, "r", encoding="utf-8") as handle:
        decision_html = handle.read()
    if "static/js/decision/hub_core.js" not in decision_html:
        return "fail", "decision.html does not load hub_core.js"

    with open(hub_path, "r", encoding="utf-8") as handle:
        hub_source = handle.read()
    match = re.search(
        r"_DEFAULT_REGIME_THRESHOLDS\s*=\s*(\[[^\]]+\])",
        hub_source,
    )
    if not match:
        return "fail", "frontend default regime thresholds are not parseable"

    try:
        frontend_thresholds = [float(value) for value in json.loads(match.group(1))]
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return "fail", f"invalid frontend threshold array: {exc}"

    backend_thresholds = [float(value) for value in AP.V5_REGIME_THRESHOLDS]
    if frontend_thresholds != backend_thresholds:
        return "fail", (
            f"threshold mismatch: frontend={frontend_thresholds}, "
            f"backend={backend_thresholds}"
        )
    if "snapshot.regime_thresholds" not in hub_source:
        return "fail", "hub_core.js does not consume backend regime thresholds"

    return "pass", f"frontend/backend thresholds aligned: {backend_thresholds}"


# ═══════════════════════════════════════════════════════
#  Check groups and runner
# ═══════════════════════════════════════════════════════

ENGINE_CHECKS = (
    "Engine Import Chain",
    (
        ("aiae_params", check_aiae_params),
        ("aiae_engine", check_aiae_engine),
        ("backtest_v4", check_backtest_engine),
        ("sub_engines", check_sub_engines),
        ("drift_monitor", check_drift_monitor),
    ),
)
SIGNAL_CHECKS = (
    "V5 Signal Pipeline",
    (
        ("regime_classify", check_v5_regime_classify),
        ("position_matrix", check_v5_position_matrix),
    ),
)
DATA_CHECKS = (
    "Runtime Data Integrity",
    (
        ("history_parquet", check_history_parquet),
        ("backtest_results", check_backtest_results),
    ),
)
ALLOCATION_CHECKS = (
    "Allocation Consistency",
    (
        ("alloc_matrix", check_sub_strategy_alloc),
        ("dividend_aiae", check_dividend_aiae_integration),
    ),
)
FRONTEND_CHECKS = (
    "Frontend Runtime Contract",
    (("frontend_sync", check_frontend_v5_sync),),
)


def build_check_groups(code_only: bool = False):
    """Return deterministic check groups for CI or full server validation."""
    groups = [ENGINE_CHECKS, SIGNAL_CHECKS]
    if not code_only:
        groups.append(DATA_CHECKS)
    groups.extend((ALLOCATION_CHECKS, FRONTEND_CHECKS))
    return groups


def run_checks(groups, emit=print):
    """Run check groups and return pass/warn/fail counts."""
    summary = {"pass": 0, "warn": 0, "fail": 0}
    total_groups = len(groups)

    for index, (title, checks) in enumerate(groups, start=1):
        emit(f"\n[{index}/{total_groups}] {title}")
        for name, check_fn in checks:
            try:
                status, message = check_fn()
                if status not in summary:
                    invalid_status = status
                    status = "fail"
                    message = f"invalid check status: {invalid_status!r}; {message}"
            except Exception as exc:
                status, message = "fail", str(exc)
            summary[status] += 1
            emit(f"  [{status.upper()}] {name}: {message}")

    return summary


def _print_summary(summary, emit=print):
    total = sum(summary.values())
    emit("\n" + "=" * 60)
    if summary["fail"]:
        emit(
            f"  RESULT: {summary['fail']} FAILED / {summary['warn']} WARN / "
            f"{summary['pass']} PASS (of {total})"
        )
        emit("  STATUS: NOT READY FOR PRODUCTION")
    elif summary["warn"]:
        emit(f"  RESULT: {summary['warn']} WARN / {summary['pass']} PASS (of {total})")
        emit("  STATUS: READY WITH WARNINGS")
    else:
        emit(f"  RESULT: {summary['pass']}/{total} PASSED")
        emit("  STATUS: PRODUCTION READY")
    emit("=" * 60)


def main(argv=None):
    parser = argparse.ArgumentParser(description="AlphaCore production readiness gate")
    parser.add_argument(
        "--code-only",
        action="store_true",
        help="skip server-local runtime data checks (intended for CI)",
    )
    args = parser.parse_args(argv)

    print("=" * 60)
    print("  AlphaCore Production Readiness Check")
    print(f"  Mode: {'CODE ONLY' if args.code_only else 'FULL'}")
    print("=" * 60)

    summary = run_checks(build_check_groups(code_only=args.code_only))
    _print_summary(summary)
    return 1 if summary["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
