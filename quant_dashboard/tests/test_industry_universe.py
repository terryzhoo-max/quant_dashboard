"""Authoritative ETF master and prospective PIT-universe contracts."""

import json
import pandas as pd
import pytest

from services.industry_universe import (
    build_etf_master,
    build_prospective_manifest,
    get_industry_universe_status,
    refresh_existing_industry_universe,
)


def _etf_basic():
    return pd.DataFrame([
        {
            "ts_code": "A.SH", "csname": "行业AETF", "index_code": "IDX.A",
            "index_name": "行业A", "setup_date": "20200101", "list_date": "20200110",
            "list_status": "L", "exchange": "SH", "mgr_name": "管理人A",
        },
        {
            "ts_code": "B.SZ", "csname": "行业BETF", "index_code": "IDX.B",
            "index_name": "行业B", "setup_date": "20210101", "list_date": "20210110",
            "list_status": "D", "exchange": "SZ", "mgr_name": "管理人B",
        },
    ])


def _fund_basic():
    return pd.DataFrame([
        {"ts_code": "A.SH", "found_date": "20200101", "list_date": "20200110", "delist_date": None, "status": "L"},
        {"ts_code": "B.SZ", "found_date": "20210101", "list_date": "20210110", "delist_date": "20251231", "status": "D"},
    ])


def test_master_merges_exchange_etf_identity_with_fund_lifecycle():
    master = build_etf_master(_etf_basic(), _fund_basic(), retrieved_at="2026-09-07T00:00:00+00:00")

    assert master["record_count"] == 2
    assert len(master["snapshot_sha256"]) == 64
    b = next(row for row in master["records"] if row["code"] == "B.SZ")
    assert b["instrument_list_date"] == "2021-01-10"
    assert b["instrument_delist_date"] == "2025-12-31"
    assert b["instrument_status"] == "D"


def test_master_accepts_pending_etf_without_listing_date_but_never_invents_one():
    pending = pd.DataFrame([{
        "ts_code": "P.SZ", "csname": "待上市ETF", "index_code": "IDX.P",
        "index_name": "待上市", "setup_date": "20260901", "list_date": None,
        "list_status": "P", "exchange": "SZ", "mgr_name": "管理人P",
    }])
    issuing = pd.DataFrame([{
        "ts_code": "P.SZ", "list_date": None, "delist_date": None, "status": "I",
    }])
    master = build_etf_master(pending, issuing, retrieved_at="2026-09-07T00:00:00+00:00")

    assert master["records"][0]["instrument_status"] == "P"
    assert master["records"][0]["fund_status"] == "P"
    assert master["records"][0]["status_conflict"] is False
    assert master["records"][0]["instrument_list_date"] is None


def test_etf_specific_status_wins_transient_cross_dataset_conflict_and_is_audited():
    pending = pd.DataFrame([{
        "ts_code": "P.SZ", "csname": "待上市ETF", "list_date": None,
        "list_status": "P", "exchange": "SZ",
    }])
    generic_live = pd.DataFrame([{
        "ts_code": "P.SZ", "list_date": None, "delist_date": None, "status": "L",
    }])

    master = build_etf_master(pending, generic_live, retrieved_at="2026-09-07T00:00:00+00:00")
    row = master["records"][0]

    assert row["instrument_status"] == "P"
    assert row["fund_status"] == "L"
    assert row["status_conflict"] is True


def test_prospective_manifest_freezes_policy_date_without_backdating_membership():
    master = build_etf_master(_etf_basic(), _fund_basic(), retrieved_at="2026-09-07T00:00:00+00:00")
    manifest = build_prospective_manifest(
        master,
        [{"code": "A.SH", "name": "行业A"}],
        effective_from="2026-09-06",
        as_of="2026-09-07",
    )

    assert manifest["schema_version"] == 2
    assert manifest["complete_history"] is False
    assert manifest["coverage"]["complete_from"] == "2026-09-06"
    assert manifest["members"][0]["instrument_list_date"] == "2020-01-10"
    assert manifest["members"][0]["membership_from"] == "2026-09-06"


def test_manifest_generation_fails_closed_when_core_member_is_missing_from_master():
    master = build_etf_master(_etf_basic(), _fund_basic(), retrieved_at="2026-09-07T00:00:00+00:00")

    with pytest.raises(ValueError, match="missing core ETF"):
        build_prospective_manifest(
            master,
            [{"code": "MISSING.SH", "name": "缺失"}],
            effective_from="2026-09-06",
            as_of="2026-09-07",
        )


def test_status_distinguishes_prospective_integrity_from_missing_history(tmp_path):
    master = build_etf_master(_etf_basic(), _fund_basic(), retrieved_at="2026-09-07T00:00:00+00:00")
    manifest = build_prospective_manifest(
        master,
        [{"code": "A.SH", "name": "行业A"}],
        effective_from="2026-09-06",
        as_of="2026-09-07",
    )
    master_path = tmp_path / "master.json"
    manifest_path = tmp_path / "manifest.json"
    master_path.write_text(json.dumps(master), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    status = get_industry_universe_status(
        master_path=master_path,
        manifest_path=manifest_path,
        as_of="2026-09-07",
        validation_start="2020-01-01",
    )

    assert status["integrity_ok"] is True
    assert status["current_date_covered"] is True
    assert status["historical_validation_covered"] is False
    assert status["prospective_complete_from"] == "2026-09-06"
    assert status["execution_allowed"] is False


def test_refresh_existing_registry_preserves_policy_freeze_date(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "coverage": {"complete_from": "2026-09-06"},
        "members": [{"code": "A.SH", "name": "行业A"}],
    }), encoding="utf-8")
    captured = {}

    def fake_refresh(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr("services.industry_universe.refresh_industry_universe", fake_refresh)
    monkeypatch.setattr("data.core_etf_config.CORE_ETFS", [{"code": "A.SH", "name": "行业A"}])

    result = refresh_existing_industry_universe(
        master_path=tmp_path / "master.json",
        manifest_path=manifest_path,
    )

    assert result == {"ok": True}
    assert captured["effective_from"] == "2026-09-06"


def test_refresh_rejects_core_set_change_instead_of_backdating_it(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "coverage": {"complete_from": "2026-09-06"},
        "members": [{"code": "A.SH", "name": "行业A"}],
    }), encoding="utf-8")
    monkeypatch.setattr("data.core_etf_config.CORE_ETFS", [
        {"code": "A.SH", "name": "行业A"},
        {"code": "NEW.SH", "name": "新增行业"},
    ])

    with pytest.raises(ValueError, match="new policy revision"):
        refresh_existing_industry_universe(
            master_path=tmp_path / "master.json",
            manifest_path=manifest_path,
        )
