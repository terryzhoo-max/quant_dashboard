"""产业追踪接口必须对不可信数据 fail closed。"""

import asyncio

import pandas as pd

from engines import momentum_rotation_engine
from routers import industry


def test_momentum_fetch_uses_isolated_raw_namespace(monkeypatch, tmp_path):
    raw_dir = tmp_path / "momentum_prices_raw"
    monkeypatch.setattr(
        momentum_rotation_engine, "MOMENTUM_RAW_PRICE_DIR", str(raw_dir)
    )

    class FakePro:
        @staticmethod
        def fund_daily(**_kwargs):
            return pd.DataFrame(
                {
                    "trade_date": ["20260903", "20260904"],
                    "close": [1.0, 1.01],
                }
            )

    code, frame, _ = momentum_rotation_engine._fetch_single_mom_etf(
        {"code": "RAW.SH", "name": "Raw ETF", "type": "offense"},
        "20260901",
        "20260904",
        60,
        FakePro(),
    )

    assert code == "RAW.SH"
    assert frame is not None
    assert (raw_dir / "RAW.SH.parquet").exists()


def test_industry_detail_never_falls_back_to_static_constituents(monkeypatch):
    class EmptyDataManager:
        def get_industry_price_payload(self, _code):
            return pd.DataFrame()

    monkeypatch.setattr(industry, "FactorDataManager", EmptyDataManager)
    monkeypatch.setattr(
        industry,
        "get_etf_constituent_snapshot",
        lambda _code: {
            "etf_code": "ETF.SH",
            "instrument_name": "真实ETF名称",
            "tracking_index_name": "真实跟踪指数",
            "is_verified": False,
            "top_constituents": [],
            "issues": ["INDEX_WEIGHT_UNAVAILABLE"],
        },
    )

    response = asyncio.run(industry.get_industry_detail("ETF.SH"))

    snapshot = response["data"]["metrics"]["constituent_snapshot"]
    assert response["status"] == "success"
    assert response["data"]["metrics"]["constituents"] == []
    assert snapshot["is_verified"] is False
    assert snapshot["issues"] == ["INDEX_WEIGHT_UNAVAILABLE"]


def test_tracking_endpoint_overrides_all_advice_when_data_is_locked(monkeypatch):
    dates = pd.bdate_range(end="2026-09-04", periods=80)
    prices = pd.DataFrame(
        {
            "trade_date": dates,
            "close": [1.0 + i / 100 for i in range(len(dates))],
            "amount": [1_000_000.0] * len(dates),
            "vol": [100_000.0] * len(dates),
        }
    )

    class FakeDataManager:
        def check_industry_data_quality(self, _codes, **_kwargs):
            return {
                "decision_locked": True,
                "is_usable": False,
                "reasons": ["STALE_DATA: 1/16"],
                "items": {},
                "checked_count": 16,
                "expected_trade_date": "20260904",
            }

        def get_industry_price_payload(self, _code):
            return prices.copy()

    class FakeIndustryEngine:
        @staticmethod
        def get_industry_rotation(base_date=None):
            return {}

    monkeypatch.setattr(industry, "FactorDataManager", FakeDataManager)
    monkeypatch.setattr(industry, "IndustryEngine", FakeIndustryEngine)
    monkeypatch.setattr(industry, "_tracking_cache_set", lambda *_args, **_kwargs: None)

    response = asyncio.run(industry.get_industry_tracking())

    assert response["status"] == "success"
    assert response["decision_locked"] is True
    assert response["decision_lock_reasons"] == ["STALE_DATA: 1/16"]
    assert response["data"]["sector_heatmap"]
    assert all(
        item["advice_action"] == "data_locked"
        and item["position_cap"] == "0%"
        and item["decision_locked"] is True
        for item in response["data"]["sector_heatmap"]
    )


def test_tracking_stays_locked_until_execution_policy_is_validated(monkeypatch):
    dates = pd.bdate_range(end="2026-09-04", periods=80)
    prices = pd.DataFrame(
        {
            "trade_date": dates,
            "close": [1.0 + i / 100 for i in range(len(dates))],
            "amount": [1_000_000.0] * len(dates),
            "vol": [100_000.0] * len(dates),
        }
    )

    class HealthyDataManager:
        def check_industry_data_quality(self, _codes, **_kwargs):
            return {
                "decision_locked": False,
                "is_usable": True,
                "reasons": [],
                "items": {},
                "checked_count": 16,
                "usable_count": 16,
                "expected_trade_date": "20260904",
            }

        def get_industry_price_payload(self, _code):
            return prices.copy()

    class FakeIndustryEngine:
        @staticmethod
        def get_industry_rotation(base_date=None):
            return {}

    monkeypatch.setattr(industry, "FactorDataManager", HealthyDataManager)
    monkeypatch.setattr(industry, "IndustryEngine", FakeIndustryEngine)
    monkeypatch.setattr(
        industry,
        "get_market_regime_snapshot",
        lambda: {
            "status": "ok",
            "latest_date": "20260904",
            "regime": "BEAR",
            "aiae_usable": True,
            "aiae_decision_locked": False,
            "aiae_reason": None,
            "aiae_cap": 53,
            "audit_cap": 95,
        },
    )
    monkeypatch.setattr(industry, "_tracking_cache_set", lambda *_args, **_kwargs: None)

    response = asyncio.run(industry.get_industry_tracking())

    assert response["decision_locked"] is True
    assert response["decision_lock_reasons"] == ["REGIME_MODEL_DISABLED"]
    assert response["data"]["execution_context"]["hard_locked"] is True
    assert response["data"]["execution_context"]["regime_model_validation"][
        "lifecycle"
    ] == "disabled"
    assert response["data"]["eligible_buy_count"] == 0
    assert response["data"]["abstention_plan"]["action"] == "NO_TRADE"
    assert response["data"]["abstention_plan"]["execution_allowed"] is False
    assert response["data"]["abstention_plan"]["watchlist"]
    assert all(
        item["execution_allowed"] is False
        for item in response["data"]["abstention_plan"]["watchlist"]
    )
    assert all(
        item["advice_action"] != "eligible_buy"
        and item["execution"]["allowed"] is False
        and item["execution"]["order_release_allowed"] is False
        and item["eligibility_checks"]["liquidity_data_complete"] is True
        and item["eligibility_checks"]["liquidity_median_turnover_pass"] is True
        and item["execution"]["capacity_at_participation_cny"] == 20_000_000
        for item in response["data"]["sector_heatmap"]
    )


def test_historical_tracking_never_uses_current_market_regime(monkeypatch):
    dates = pd.bdate_range(end="2026-09-04", periods=80)
    prices = pd.DataFrame(
        {
            "trade_date": dates,
            "close": [1.0 + i / 100 for i in range(len(dates))],
            "amount": [1_000_000.0] * len(dates),
            "vol": [100_000.0] * len(dates),
        }
    )

    class HealthyDataManager:
        def check_industry_data_quality(self, _codes, **_kwargs):
            return {
                "decision_locked": False,
                "is_usable": True,
                "reasons": [],
                "items": {},
                "checked_count": 16,
                "usable_count": 16,
                "expected_trade_date": "20260903",
            }

        def get_industry_price_payload(self, _code):
            return prices.copy()

    class FakeIndustryEngine:
        @staticmethod
        def get_industry_rotation(base_date=None):
            return {}

    monkeypatch.setattr(industry, "FactorDataManager", HealthyDataManager)
    monkeypatch.setattr(industry, "IndustryEngine", FakeIndustryEngine)
    monkeypatch.setattr(
        industry,
        "get_market_regime_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("current regime must not be used")),
    )
    monkeypatch.setattr(industry, "_tracking_cache_set", lambda *_args, **_kwargs: None)

    response = asyncio.run(industry.get_industry_tracking(date="2026-09-03"))

    assert response["decision_locked"] is True
    assert response["decision_lock_reasons"] == ["HISTORICAL_QUERY_RESEARCH_ONLY"]
    assert response["data"]["eligible_buy_count"] == 0
