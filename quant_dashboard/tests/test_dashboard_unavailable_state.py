"""The dashboard's browser fallback must be a fail-closed unavailable state."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from dashboard_modules import fetch_macro


ROOT = Path(__file__).parents[1]


def _source(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_browser_fallback_contains_no_simulated_market_or_trade_data():
    source = _source("static/js/ui_utils.js")

    forbidden = (
        "20.15",
        "151.4",
        "5.22",
        "某AI行业龙头",
        "车规半导体标的",
        'consensus: "3/5 看多"',
        'status_text: "发现极值猎物"',
        'cap: 65',
    )
    assert all(token not in source for token in forbidden)


def test_browser_fallback_is_explicitly_unavailable_and_locked():
    source = _source("static/js/ui_utils.js")

    assert "_meta_unavailable: true" in source
    assert "decision_locked: true" in source
    assert "available: false" in source
    assert "sector_heatmap: []" in source
    assert "buy_zone: []" in source
    assert "danger_zone: []" in source


def test_renderers_clear_numeric_surfaces_for_unavailable_payloads():
    source = _source("static/js/renderers.js")
    orchestrator = _source("static/js/script.js")

    assert "renderAIAEUnavailable" in source
    assert "renderPositionHubUnavailable" in source
    assert "isUnavailable" in source
    assert "vix.available === false" in orchestrator


def test_fetch_failures_publish_machine_readable_unavailable_reasons():
    source = _source("static/js/data_fetch.js")

    assert "DASHBOARD_WARMING_UP" in source
    assert "DASHBOARD_API_UNREACHABLE" in source


def test_vix_all_sources_failed_raises_instead_of_using_default(monkeypatch):
    monkeypatch.setattr(fetch_macro, "_load_vix_disk", lambda **_kwargs: None)
    monkeypatch.setattr(fetch_macro, "_fetch_vix_tradingview", lambda: (None, None))
    monkeypatch.setattr(fetch_macro, "_fetch_vix_yfinance", lambda: (None, None))
    monkeypatch.setattr(fetch_macro, "_fetch_vix_cnbc", lambda: None)
    monkeypatch.setattr(fetch_macro, "fred_get_series", lambda *_args, **_kwargs: pd.Series(dtype=float))
    monkeypatch.setitem(sys.modules, "fredapi", SimpleNamespace(Fred=lambda **_kwargs: object()))

    with pytest.raises(RuntimeError, match="VIX_DATA_UNAVAILABLE"):
        fetch_macro.fetch_vix_for_dashboard()


def test_cny_all_sources_failed_raises_instead_of_using_default(monkeypatch):
    monkeypatch.setattr(fetch_macro, "_load_cny_disk", lambda **_kwargs: None)
    monkeypatch.setattr(
        fetch_macro.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="CNY_DATA_UNAVAILABLE"):
        fetch_macro.fetch_cny_for_dashboard()


def test_dashboard_builder_never_substitutes_a_neutral_aiae_regime():
    source = _source("services/dashboard_builder.py")

    assert "aiae_cap = 65" not in source
    assert 'raise RuntimeError("AIAE_CONTEXT_UNUSABLE")' in source
    assert '"margin_heat": _full_aiae_ctx.get("margin_heat") or 2.0' not in source
    assert '"fund_position": _full_aiae_ctx.get("fund_position") or 80' not in source
