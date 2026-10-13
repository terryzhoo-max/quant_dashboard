"""Backtest MR presets must be hydrated from the production runtime API."""

from pathlib import Path


def test_backtest_loads_mr_presets_from_runtime_api():
    source = Path("static/js/backtest.js").read_text(encoding="utf-8")

    assert "/api/v1/params/strategy-config" in source
    assert "applyRuntimeMrParams" in source
    assert "bias_buy * 10" in source
    assert "stop_loss * 100" in source
    assert "MR 参数同步失败" in source
