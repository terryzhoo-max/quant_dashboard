"""产业追踪 P0 数据契约测试。"""

from datetime import datetime
import json

import pandas as pd

from data import data_manager as data_manager_module
from data.data_manager import FactorDataManager


def _configure_temp_store(monkeypatch, tmp_path):
    data_dir = tmp_path / "data_lake"
    daily_dir = data_dir / "daily_prices"
    industry_dir = data_dir / "industry_prices_qfq"
    financial_dir = data_dir / "financials"
    data_dir.mkdir()
    daily_dir.mkdir()
    industry_dir.mkdir()
    financial_dir.mkdir()

    monkeypatch.setattr(data_manager_module, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(data_manager_module, "DAILY_PRICE_DIR", str(daily_dir))
    monkeypatch.setattr(data_manager_module, "INDUSTRY_DAILY_PRICE_DIR", str(industry_dir))
    monkeypatch.setattr(data_manager_module, "FINA_INDICATOR_DIR", str(financial_dir))

    calendar = ["20260615", "20260616", "20260903", "20260904"]
    (data_dir / "trading_calendar.json").write_text(
        json.dumps(calendar), encoding="utf-8"
    )
    return daily_dir, industry_dir


def _write_prices(directory, code, dates, closes):
    pd.DataFrame(
        {
            "trade_date": dates,
            "close": closes,
            "amount": [1_000_000.0] * len(dates),
            "vol": [100_000.0] * len(dates),
        }
    ).to_parquet(directory / f"{code}.parquet")


def test_industry_quality_checks_every_code_and_locks_on_one_stale_series(
    monkeypatch, tmp_path
):
    _, industry_dir = _configure_temp_store(monkeypatch, tmp_path)
    _write_prices(industry_dir, "FRESH.SH", ["20260903", "20260904"], [1.0, 1.01])
    _write_prices(industry_dir, "STALE.SH", ["20260615", "20260616"], [1.0, 1.01])

    quality = FactorDataManager().check_industry_data_quality(
        ["FRESH.SH", "STALE.SH"],
        as_of=datetime(2026, 9, 6, 16, 0),
        min_history_rows=2,
    )

    assert quality["checked_count"] == 2
    assert quality["expected_trade_date"] == "20260904"
    assert quality["decision_locked"] is True
    assert quality["stale_codes"] == ["STALE.SH"]
    assert quality["items"]["FRESH.SH"]["is_usable"] is True
    assert quality["items"]["STALE.SH"]["stale_trading_days"] >= 1


def test_industry_quality_locks_on_unexplained_adjusted_price_jump(
    monkeypatch, tmp_path
):
    _, industry_dir = _configure_temp_store(monkeypatch, tmp_path)
    _write_prices(industry_dir, "SPLIT.SH", ["20260903", "20260904"], [1.0, 0.5])

    quality = FactorDataManager().check_industry_data_quality(
        ["SPLIT.SH"],
        as_of=datetime(2026, 9, 6, 16, 0),
        min_history_rows=2,
        max_abs_return=0.35,
    )

    assert quality["decision_locked"] is True
    assert quality["anomalous_codes"] == ["SPLIT.SH"]
    assert quality["items"]["SPLIT.SH"]["max_abs_return"] == 0.5
    assert "PRICE_JUMP" in quality["items"]["SPLIT.SH"]["issues"]


def test_industry_quality_locks_on_recent_calendar_gap(monkeypatch, tmp_path):
    _, industry_dir = _configure_temp_store(monkeypatch, tmp_path)
    calendar_path = tmp_path / "data_lake" / "trading_calendar.json"
    calendar_path.write_text(
        json.dumps(["20260831", "20260901", "20260902", "20260903", "20260904"]),
        encoding="utf-8",
    )
    _write_prices(
        industry_dir,
        "GAP.SH",
        [20260831, 20260901, 20260902, 20260904],
        [1.0, 1.01, 1.02, 1.03],
    )

    quality = FactorDataManager().check_industry_data_quality(
        ["GAP.SH"],
        as_of=datetime(2026, 9, 6, 16, 0),
        min_history_rows=4,
    )

    assert quality["decision_locked"] is True
    assert quality["incomplete_codes"] == ["GAP.SH"]
    assert quality["items"]["GAP.SH"]["latest_trade_date"] == "20260904"
    assert quality["items"]["GAP.SH"]["coverage_ratio"] == 0.75


def test_industry_sync_writes_only_to_qfq_namespace(monkeypatch, tmp_path):
    daily_dir, industry_dir = _configure_temp_store(monkeypatch, tmp_path)
    captured = {}

    def fake_pro_bar(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame(
            {
                "ts_code": [kwargs["ts_code"]],
                "trade_date": ["20260904"],
                "close": [1.0],
            }
        )

    monkeypatch.setattr(data_manager_module.ts, "pro_bar", fake_pro_bar)

    FactorDataManager().sync_industry_prices(
        ["SAFE.SH"], start_date="20260901", end_date="20260904"
    )

    assert (industry_dir / "SAFE.SH.parquet").exists()
    assert not (daily_dir / "SAFE.SH.parquet").exists()
    assert captured["asset"] == "FD"
    assert captured["adj"] == "qfq"


def test_historical_as_of_does_not_treat_later_cached_rows_as_future_data(
    monkeypatch, tmp_path
):
    _, industry_dir = _configure_temp_store(monkeypatch, tmp_path)
    calendar_path = tmp_path / "data_lake" / "trading_calendar.json"
    calendar_path.write_text(
        json.dumps(["20260901", "20260902", "20260903", "20260904"]),
        encoding="utf-8",
    )
    _write_prices(
        industry_dir,
        "HISTORY.SH",
        ["20260901", "20260902", "20260903", "20260904"],
        [1.0, 1.01, 1.02, 1.03],
    )

    quality = FactorDataManager().check_industry_data_quality(
        ["HISTORY.SH"],
        as_of=datetime(2026, 9, 3, 23, 59),
        min_history_rows=2,
    )

    assert quality["expected_trade_date"] == "20260903"
    assert quality["decision_locked"] is False
    assert "FUTURE_DATA" not in quality["items"]["HISTORY.SH"]["issues"]


def test_industry_sync_reconstructs_split_continuous_close_from_pct_chg(
    monkeypatch, tmp_path
):
    _, industry_dir = _configure_temp_store(monkeypatch, tmp_path)

    def fake_pro_bar(**kwargs):
        return pd.DataFrame(
            {
                "ts_code": [kwargs["ts_code"]] * 3,
                "trade_date": ["20260902", "20260903", "20260904"],
                "close": [2.0, 1.0, 1.01],
                # 9/3 是 1:2 份额拆分，真实收益为 0%；9/4 上涨 1%。
                "pct_chg": [0.0, 0.0, 1.0],
                "amount": [1_000_000.0] * 3,
            }
        )

    monkeypatch.setattr(data_manager_module.ts, "pro_bar", fake_pro_bar)
    FactorDataManager().sync_industry_prices(
        ["SPLIT.SH"], start_date="20260901", end_date="20260904"
    )

    stored = pd.read_parquet(industry_dir / "SPLIT.SH.parquet").sort_values(
        "trade_date"
    )
    adjusted_returns = stored["close"].pct_change().dropna()
    assert adjusted_returns.abs().max() < 0.02
    assert stored["raw_close"].tolist() == [2.0, 1.0, 1.01]
    assert stored["close"].iloc[-1] == 1.01
    assert set(stored["price_basis"]) == {"pct_chg_split_adjusted"}
