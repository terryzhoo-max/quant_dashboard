"""Regression tests for runtime failures confirmed by the production audit."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import runpy
from unittest.mock import MagicMock

import pandas as pd
import pytest


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("engines.aiae_engine", "AIAEEngine"),
        ("engines.aiae_jp_engine", "AIAEJPEngine"),
        ("engines.aiae_us_engine", "AIAEUSEngine"),
    ],
)
def test_aiae_report_failure_returns_fallback_and_logs_traceback(
    monkeypatch, module_name, class_name
):
    module = __import__(module_name, fromlist=[class_name])
    engine_class = getattr(module, class_name)
    engine = object.__new__(engine_class)
    expected_error = "forced data-source failure"

    failing_executor = MagicMock()
    failing_executor.submit.side_effect = ValueError(expected_error)
    debug_logger = MagicMock()

    monkeypatch.setattr(module, "_bg_executor", failing_executor)
    monkeypatch.setattr(module, "_logger", debug_logger, raising=False)
    monkeypatch.setattr(
        engine,
        "_fallback_report",
        lambda reason: {"status": "fallback", "message": reason},
    )

    report = engine.generate_report()

    assert report == {"status": "fallback", "message": expected_error}
    debug_logger.debug.assert_called_once_with("Traceback", exc_info=True)


def test_erp_backtest_uses_400_day_macro_history(monkeypatch):
    from models.schemas import BacktestRequest
    from routers import industry

    backtester = MagicMock()
    backtester.fetch_tushare_data.return_value = pd.DataFrame(
        {"close": [100.0, 101.0]}
    )
    backtester.run_vectorized.return_value = {"equity_curve": [100.0, 101.0]}
    backtester.run_monte_carlo.return_value = {"bankruptcy_probability": 0.0}

    macro_data = pd.DataFrame({"erp": [3.0, 3.1]})
    prepare_macro = MagicMock(return_value=macro_data)
    build_signals = MagicMock(return_value=pd.Series([0, 1]))

    monkeypatch.setattr(industry, "AlphaBacktester", lambda **_kwargs: backtester)
    monkeypatch.setattr(industry, "prepare_erp_backtest_data", prepare_macro)
    monkeypatch.setattr(industry, "erp_timing_strategy_vectorized", build_signals)

    request = BacktestRequest(
        strategy="erp",
        ts_code="510300.SH",
        start_date="20200101",
        end_date="20201231",
    )
    response = asyncio.run(industry.run_backtest_api(request))

    expected_macro_start = (
        datetime.strptime(request.start_date, "%Y%m%d") - timedelta(days=400)
    ).strftime("%Y%m%d")
    assert response["status"] == "success", response
    prepare_macro.assert_called_once_with(expected_macro_start, request.end_date)
    build_signals.assert_called_once()


@pytest.mark.parametrize(
    ("fetch_name", "cache_name"),
    [
        ("fetch_jpx_margin", "_load_margin_cache"),
        ("fetch_jpx_foreign_flow", "_load_foreign_cache"),
    ],
)
def test_jpx_fetch_failure_returns_cache_and_logs_traceback(
    monkeypatch, fetch_name, cache_name
):
    from data import jpx_data_fetcher

    cached = {"source": "test_cache"}
    debug_logger = MagicMock()

    monkeypatch.setattr(
        jpx_data_fetcher,
        "_find_xls_links",
        MagicMock(side_effect=ValueError("forced JPX failure")),
    )
    monkeypatch.setattr(jpx_data_fetcher.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(jpx_data_fetcher, cache_name, MagicMock(return_value=cached))
    monkeypatch.setattr(jpx_data_fetcher, "_logger", debug_logger, raising=False)

    result = getattr(jpx_data_fetcher, fetch_name)()

    assert result == cached
    debug_logger.debug.assert_called_once_with("Traceback", exc_info=True)


def test_etf_data_checker_can_read_with_pandas_available(
    monkeypatch, tmp_path, capsys
):
    from core_etf_config import CORE_ETF_CODES

    price_dir = tmp_path / "data_lake" / "daily_prices"
    price_dir.mkdir(parents=True)
    (price_dir / f"{CORE_ETF_CODES[0]}.parquet").touch()
    script = Path(__file__).parents[1] / "_dev_tools" / "check_etf_data.py"

    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(script), run_name="__main__")

    output = capsys.readouterr().out
    assert "name 'pd' is not defined" not in output
