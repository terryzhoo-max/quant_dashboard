"""Production modules imported by the API must not write user-home config."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
STARTUP_MODULES = (
    "data/data_manager.py",
    "engines/aiae_engine.py",
    "engines/dividend_trend_engine.py",
    "engines/dual_momentum_engine.py",
    "engines/erp_timing_engine.py",
    "engines/hf_proxy_engine.py",
    "engines/momentum_rotation_engine.py",
    "strategies/aiae_backtest_engine.py",
    "strategies/backtest_engine.py",
    "strategies/erp_backtest_data.py",
)


def test_api_startup_modules_do_not_call_tushare_set_token_at_import_time():
    for relative_path in STARTUP_MODULES:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        top_level_calls = [
            line for line in source.splitlines()
            if line.startswith(("ts.set_token(", "_ts.set_token("))
        ]
        assert not top_level_calls, f"{relative_path}: {top_level_calls}"
