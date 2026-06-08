import pytest
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dashboard_modules.fetch_macro import (
    fetch_vix_for_dashboard,
    fetch_cny_for_dashboard,
    fetch_macro_data,
    _fetch_vix_tradingview,
    _fetch_vix_yfinance
)

def test_fetch_vix_for_dashboard():
    latest, prev = fetch_vix_for_dashboard()
    assert isinstance(latest, float)
    assert isinstance(prev, float)
    assert latest > 0
    assert prev > 0

def test_fetch_cny_for_dashboard():
    cny = fetch_cny_for_dashboard()
    assert isinstance(cny, float)
    assert 5.0 < cny < 9.0  # reasonable bounds for USD/CNY

@pytest.mark.asyncio
async def test_fetch_macro_data_async():
    with ThreadPoolExecutor(max_workers=2) as executor:
        latest_vix, prev_vix, latest_cny = await fetch_macro_data(executor)
        assert isinstance(latest_vix, float)
        assert isinstance(prev_vix, float)
        assert isinstance(latest_cny, float)
        assert latest_vix > 0
        assert prev_vix > 0
        assert 5.0 < latest_cny < 9.0
