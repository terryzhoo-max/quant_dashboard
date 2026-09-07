"""Authoritative industry ETF constituent lineage contracts."""

import json

import pandas as pd

from services.industry_constituents import (
    build_constituent_snapshot,
    get_constituents_for_etf,
)


def _manifest():
    return {
        "members": [
            {
                "code": "ETF.SH",
                "name": "内部行业别名",
                "instrument_name": "交易所ETF名称",
                "tracking_index_code": "INDEX.CSI",
                "tracking_index_name": "真实跟踪指数",
            }
        ]
    }


def _weights(total=100.0, trade_date="20260831"):
    values = [total * ratio for ratio in (0.30, 0.25, 0.20, 0.15, 0.10)]
    return pd.DataFrame(
        {
            "index_code": ["INDEX.CSI"] * 5,
            "con_code": [f"00000{i}.SZ" for i in range(1, 6)],
            "trade_date": [trade_date] * 5,
            "weight": values,
        }
    )


def test_snapshot_uses_latest_official_index_weights_with_lineage():
    names = {f"00000{i}.SZ": f"公司{i}" for i in range(1, 6)}
    snapshot = build_constituent_snapshot(
        _manifest(),
        {"INDEX.CSI": _weights()},
        stock_names=names,
        as_of="2026-09-07",
        retrieved_at="2026-09-07T01:00:00+00:00",
        max_age_days=45,
        top_n=5,
    )

    record = snapshot["records"][0]
    assert snapshot["provider"] == "tushare_pro"
    assert snapshot["dataset"] == "index_weight"
    assert len(snapshot["snapshot_sha256"]) == 64
    assert record["is_verified"] is True
    assert record["as_of"] == "2026-08-31"
    assert record["weight_sum_pct"] == 100.0
    assert record["tracking_index_name"] == "真实跟踪指数"
    assert record["top_constituents"][0] == {
        "code": "000001.SZ",
        "name": "公司1",
        "weight_pct": 30.0,
    }


def test_invalid_weight_sum_fails_closed_and_hides_constituents():
    snapshot = build_constituent_snapshot(
        _manifest(),
        {"INDEX.CSI": _weights(total=70.0)},
        stock_names={},
        as_of="2026-09-07",
        retrieved_at="2026-09-07T01:00:00+00:00",
        max_age_days=45,
        top_n=5,
    )

    record = snapshot["records"][0]
    assert record["is_verified"] is False
    assert record["top_constituents"] == []
    assert "INDEX_WEIGHT_SUM_INVALID" in record["issues"]


def test_stale_index_weight_snapshot_fails_closed():
    snapshot = build_constituent_snapshot(
        _manifest(),
        {"INDEX.CSI": _weights(trade_date="20260131")},
        stock_names={},
        as_of="2026-09-07",
        retrieved_at="2026-09-07T01:00:00+00:00",
        max_age_days=45,
        top_n=5,
    )

    assert snapshot["records"][0]["is_verified"] is False
    assert snapshot["records"][0]["top_constituents"] == []
    assert "INDEX_WEIGHT_STALE" in snapshot["records"][0]["issues"]


def test_loader_rechecks_hash_and_never_returns_tampered_weights(tmp_path):
    snapshot = build_constituent_snapshot(
        _manifest(),
        {"INDEX.CSI": _weights()},
        stock_names={},
        as_of="2026-09-07",
        retrieved_at="2026-09-07T01:00:00+00:00",
        max_age_days=45,
        top_n=5,
    )
    snapshot["records"][0]["top_constituents"][0]["weight_pct"] = 99.0
    path = tmp_path / "constituents.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = get_constituents_for_etf(
        "ETF.SH", path=path, as_of="2026-09-07"
    )

    assert result["is_verified"] is False
    assert result["top_constituents"] == []
    assert result["issues"] == ["CONSTITUENT_SNAPSHOT_INTEGRITY_FAILED"]


def test_loader_expires_previously_valid_snapshot(tmp_path):
    snapshot = build_constituent_snapshot(
        _manifest(),
        {"INDEX.CSI": _weights()},
        stock_names={},
        as_of="2026-09-07",
        retrieved_at="2026-09-07T01:00:00+00:00",
        max_age_days=45,
        top_n=5,
    )
    path = tmp_path / "constituents.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = get_constituents_for_etf(
        "ETF.SH", path=path, as_of="2026-11-01"
    )

    assert result["is_verified"] is False
    assert result["top_constituents"] == []
    assert "INDEX_WEIGHT_STALE" in result["issues"]
