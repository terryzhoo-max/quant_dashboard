"""Industry momentum surfaces must never fabricate market observations."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from dashboard_modules import sector_heatmap
from engines.industry_engine import IndustryEngine


class _PriceStore:
    def __init__(self, payload):
        self.payload = payload

    def get_price_payload(self, _code):
        return self.payload.copy()


def _engine_with_payload(payload):
    engine = IndustryEngine.__new__(IndustryEngine)
    engine.dm = _PriceStore(payload)
    engine.industry_map = None
    return engine


def test_sector_heatmap_returns_empty_when_every_market_fetch_fails(monkeypatch):
    monkeypatch.setattr(
        sector_heatmap.ts,
        "pro_bar",
        lambda **_kwargs: pd.DataFrame(),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        result = asyncio.run(
            sector_heatmap.compute_sector_heatmap(executor, {}, {})
        )

    assert result == []


def test_sector_performance_preserves_observed_zero_returns():
    payload = pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-08-31", periods=5, freq="D"),
            "close": [1.0] * 5,
        }
    )

    result = _engine_with_payload(payload).get_sector_performance(
        days=5, base_date="2026-09-07"
    )

    assert result
    assert all(item["trend_5d"] == 0.0 for item in result)
    assert all(item["data_status"] == "observed" for item in result)


def test_sector_performance_marks_missing_data_instead_of_zero():
    result = _engine_with_payload(pd.DataFrame()).get_sector_performance(
        days=5, base_date="2026-09-07"
    )

    assert result
    assert all(item["trend_5d"] is None for item in result)
    assert all(item["data_status"] == "missing" for item in result)


def test_browser_fallback_contains_no_synthetic_industry_quotes():
    ui_source = (
        Path(__file__).parents[1] / "static" / "js" / "ui_utils.js"
    ).read_text(encoding="utf-8")

    assert "sector_heatmap: []" in ui_source
    assert '{ name: "医药生物", change:' not in ui_source
