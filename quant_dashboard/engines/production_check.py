"""
AlphaCore V5.0 · 生产就绪检查 (Production Readiness Check)
============================================================
一键验证全系统关键路径。部署前 / 每日启动时运行。

用法: python engines/production_check.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
WARN = 0
FAIL = 0


def _check(name, fn):
    global PASS, WARN, FAIL
    try:
        ok, msg = fn()
        if ok == "pass":
            PASS += 1
            print(f"  [PASS] {name}: {msg}")
        elif ok == "warn":
            WARN += 1
            print(f"  [WARN] {name}: {msg}")
        else:
            FAIL += 1
            print(f"  [FAIL] {name}: {msg}")
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL] {name}: {e}")


# ═══════════════════════════════════════════════════════
#  1. 引擎导入链
# ═══════════════════════════════════════════════════════

def check_aiae_params():
    import engines.aiae_params as AP
    assert AP.V5_ENABLED, "V5_ENABLED is False"
    assert AP.VERSION == "5.0", f"VERSION={AP.VERSION}"
    return "pass", f"V{AP.VERSION}, V5_ENABLED=True"


def check_aiae_engine():
    from engines.aiae_engine import get_aiae_engine
    e = get_aiae_engine()
    assert hasattr(e, 'classify_regime'), "missing classify_regime"
    assert hasattr(e, 'get_position_from_matrix'), "missing get_position_from_matrix"
    return "pass", "classify_regime + get_position_from_matrix OK"


def check_backtest_engine():
    from engines.aiae_backtest_v4 import AIAEBacktestV4
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
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = {
        'strategy.html': ['22.8'],
        'decision.html': ['24%'],
        'static/js/decision/hub_core.js': ['22.8'],
    }
    issues = []
    for fname, markers in files.items():
        path = os.path.join(base, fname)
        if not os.path.exists(path):
            issues.append(f"{fname}: not found")
            continue
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        for marker in markers:
            if marker not in content:
                issues.append(f"{fname}: missing V5 marker '{marker}'")
    if issues:
        return "warn", "; ".join(issues)
    return "pass", "V5 markers found in all frontend files"


# ═══════════════════════════════════════════════════════
#  Run all checks
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  AlphaCore V5.0 Production Readiness Check")
    print("=" * 60)

    print("\n[1/5] Engine Import Chain")
    _check("aiae_params", check_aiae_params)
    _check("aiae_engine", check_aiae_engine)
    _check("backtest_v4", check_backtest_engine)
    _check("sub_engines", check_sub_engines)
    _check("drift_monitor", check_drift_monitor)

    print("\n[2/5] V5 Signal Pipeline")
    _check("regime_classify", check_v5_regime_classify)
    _check("position_matrix", check_v5_position_matrix)

    print("\n[3/5] Data Integrity")
    _check("history_parquet", check_history_parquet)
    _check("backtest_results", check_backtest_results)

    print("\n[4/5] Quota Consistency")
    _check("alloc_matrix", check_sub_strategy_alloc)
    _check("dividend_aiae", check_dividend_aiae_integration)

    print("\n[5/5] Frontend V5 Sync")
    _check("frontend_sync", check_frontend_v5_sync)

    print("\n" + "=" * 60)
    total = PASS + WARN + FAIL
    if FAIL > 0:
        print(f"  RESULT: {FAIL} FAILED / {WARN} WARN / {PASS} PASS (of {total})")
        print("  STATUS: NOT READY FOR PRODUCTION")
    elif WARN > 0:
        print(f"  RESULT: {WARN} WARN / {PASS} PASS (of {total})")
        print("  STATUS: READY WITH WARNINGS")
    else:
        print(f"  RESULT: {PASS}/{total} PASSED")
        print("  STATUS: PRODUCTION READY")
    print("=" * 60)
