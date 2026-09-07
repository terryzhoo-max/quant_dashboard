"""Authoritative ETF master data and prospective PIT industry-universe freezes."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MASTER_PATH = PROJECT_ROOT / "data_lake" / "industry_etf_master.json"
MANIFEST_PATH = PROJECT_ROOT / "config" / "industry_universe_history.json"
_write_lock = threading.Lock()


def _iso_date(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    try:
        parsed = datetime.strptime(text[:8], "%Y%m%d").date() if "-" not in text[:10] else date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"invalid date: {value}") from exc
    return parsed.isoformat()


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique_rows(frame: pd.DataFrame, label: str) -> dict[str, dict]:
    if "ts_code" not in frame.columns:
        raise ValueError(f"{label} missing ts_code")
    rows: dict[str, dict] = {}
    for raw in frame.to_dict("records"):
        code = str(raw.get("ts_code") or "").strip()
        if not code:
            raise ValueError(f"{label} contains empty ts_code")
        if code in rows:
            raise ValueError(f"{label} contains duplicate ts_code: {code}")
        rows[code] = raw
    return rows


def _normalized_status(value: Any) -> str:
    status = str(value or "").strip()
    return "P" if status == "I" else status


def build_etf_master(
    etf_basic: pd.DataFrame,
    fund_basic: pd.DataFrame,
    *,
    retrieved_at: str | None = None,
) -> dict:
    """Merge ETF identity with lifecycle fields and produce a deterministic snapshot."""
    etf_rows = _unique_rows(etf_basic, "etf_basic")
    fund_rows = _unique_rows(fund_basic, "fund_basic")
    records: list[dict] = []
    for code in sorted(etf_rows):
        etf = etf_rows[code]
        fund = fund_rows.get(code, {})
        etf_status = _normalized_status(etf.get("list_status"))
        fund_status = _normalized_status(fund.get("status"))
        status = etf_status or fund_status
        if status not in {"L", "D", "P"}:
            raise ValueError(f"unsupported listing status for {code}")
        etf_list_date = _iso_date(etf.get("list_date"))
        fund_list_date = _iso_date(fund.get("list_date"))
        if etf_list_date and fund_list_date and etf_list_date != fund_list_date:
            raise ValueError(f"listing date mismatch for {code}")
        list_date = etf_list_date or fund_list_date
        if list_date is None and status != "P":
            raise ValueError(f"listing date missing for {code}")
        records.append({
            "code": code,
            "exchange_name": str(etf.get("csname") or etf.get("extname") or fund.get("name") or ""),
            "exchange": str(etf.get("exchange") or ""),
            "manager": str(etf.get("mgr_name") or ""),
            "index_code": str(etf.get("index_code") or ""),
            "index_name": str(etf.get("index_name") or ""),
            "setup_date": _iso_date(etf.get("setup_date") or fund.get("found_date")),
            "instrument_list_date": list_date,
            "instrument_delist_date": _iso_date(fund.get("delist_date")),
            "instrument_status": status,
            "fund_status": fund_status or None,
            "status_conflict": bool(etf_status and fund_status and etf_status != fund_status),
        })
    observed_at = retrieved_at or datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "provider": "tushare_pro",
        "datasets": ["etf_basic", "fund_basic"],
        "primary_origin": "Shanghai and Shenzhen stock exchange public disclosures",
        "retrieved_at": observed_at,
        "record_count": len(records),
        "snapshot_sha256": _canonical_hash(records),
        "records": records,
    }


def build_prospective_manifest(
    master: Mapping[str, Any],
    core_etfs: Sequence[Mapping[str, Any]],
    *,
    effective_from: str,
    as_of: str | None = None,
) -> dict:
    """Freeze today's research policy prospectively without backdating selection."""
    effective = _iso_date(effective_from)
    if effective is None:
        raise ValueError("effective_from is required")
    records = master.get("records")
    if not isinstance(records, list) or master.get("snapshot_sha256") != _canonical_hash(records):
        raise ValueError("ETF master snapshot integrity check failed")
    master_by_code = {str(row.get("code") or ""): row for row in records}
    members: list[dict] = []
    seen: set[str] = set()
    for item in core_etfs:
        code = str(item.get("code") or "").strip()
        if not code or code in seen:
            raise ValueError("core ETF codes must be non-empty and unique")
        seen.add(code)
        source = master_by_code.get(code)
        if source is None:
            raise ValueError(f"missing core ETF in master: {code}")
        listed = _iso_date(source.get("instrument_list_date"))
        delisted = _iso_date(source.get("instrument_delist_date"))
        if (
            listed is None
            or listed > effective
            or (delisted is not None and delisted < effective)
            or source.get("instrument_status") != "L"
            or source.get("status_conflict") is True
        ):
            raise ValueError(f"core ETF is not tradable on policy freeze date: {code}")
        members.append({
            "code": code,
            "name": str(item.get("name") or ""),
            "instrument_name": str(source.get("exchange_name") or ""),
            "tracking_index_code": str(source.get("index_code") or ""),
            "tracking_index_name": str(source.get("index_name") or ""),
            "instrument_list_date": listed,
            "instrument_delist_date": delisted,
            "instrument_status": str(source.get("instrument_status") or ""),
            "membership_from": effective,
            "membership_to": None,
            "membership_source": "pre_registered_policy_freeze",
        })
    current_as_of = _iso_date(as_of or datetime.now(timezone.utc).date().isoformat())
    return {
        "schema_version": 2,
        "as_of": current_as_of,
        "source": {
            "provider": master.get("provider"),
            "datasets": list(master.get("datasets") or []),
            "primary_origin": master.get("primary_origin"),
            "retrieved_at": master.get("retrieved_at"),
            "snapshot_sha256": master.get("snapshot_sha256"),
            "master_path": "data_lake/industry_etf_master.json",
        },
        "complete_history": False,
        "history_start": effective,
        "coverage": {
            "mode": "prospective",
            "complete_from": effective,
            "complete_through": None,
        },
        "policy": {
            "revision": 1,
            "frozen_at": effective,
            "selection_method": "manual_pre_registered_core_etf_set",
            "automatic_membership_changes": False,
        },
        "notes": [
            "Research-universe membership is complete prospectively from the policy freeze date.",
            "No membership is backfilled before the freeze date; retrospective validation remains locked.",
        ],
        "members": members,
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with _write_lock:
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()


def fetch_tushare_etf_master(*, client: Any = None, retrieved_at: str | None = None) -> dict:
    """Fetch all live, delisted and pending ETFs plus exchange-fund lifecycle metadata."""
    if client is None:
        import tushare as ts
        from config import TUSHARE_TOKEN

        ts.set_token(TUSHARE_TOKEN)
        client = ts.pro_api()
    etf_frames = [
        client.etf_basic(
            list_status=status,
            fields="ts_code,csname,extname,index_code,index_name,setup_date,list_date,list_status,exchange,mgr_name",
        )
        for status in ("L", "D", "P")
    ]
    fund_frames = [
        client.fund_basic(
            market="E", status=status,
            fields="ts_code,name,found_date,list_date,delist_date,status",
        )
        for status in ("L", "D", "I")
    ]
    return build_etf_master(
        pd.concat(etf_frames, ignore_index=True),
        pd.concat(fund_frames, ignore_index=True),
        retrieved_at=retrieved_at,
    )


def refresh_industry_universe(
    *,
    effective_from: str,
    master_path: Path | str = MASTER_PATH,
    manifest_path: Path | str = MANIFEST_PATH,
    client: Any = None,
    retrieved_at: str | None = None,
    core_etfs: Sequence[Mapping[str, Any]] | None = None,
) -> dict:
    """Refresh authoritative master data and persist a separately frozen policy manifest."""
    from data.core_etf_config import CORE_ETFS

    selected = list(core_etfs) if core_etfs is not None else CORE_ETFS
    master = fetch_tushare_etf_master(client=client, retrieved_at=retrieved_at)
    manifest = build_prospective_manifest(
        master, selected, effective_from=effective_from,
        as_of=(retrieved_at or datetime.now(timezone.utc).isoformat())[:10],
    )
    _atomic_write_json(Path(master_path), master)
    _atomic_write_json(Path(manifest_path), manifest)
    return {"master": master, "manifest": manifest}


def refresh_existing_industry_universe(
    *,
    master_path: Path | str = MASTER_PATH,
    manifest_path: Path | str = MANIFEST_PATH,
    client: Any = None,
    retrieved_at: str | None = None,
) -> dict:
    """Refresh source data while preserving the pre-registered policy freeze date."""
    with Path(manifest_path).open("r", encoding="utf-8") as handle:
        existing = json.load(handle)
    coverage = existing.get("coverage")
    effective_from = coverage.get("complete_from") if isinstance(coverage, Mapping) else None
    if _iso_date(effective_from) is None:
        raise ValueError("existing universe has no valid policy freeze date")
    from data.core_etf_config import CORE_ETFS

    existing_members = existing.get("members")
    if not isinstance(existing_members, list):
        raise ValueError("existing universe has no member registry")
    existing_codes = {str(item.get("code") or "") for item in existing_members}
    configured_codes = {str(item.get("code") or "") for item in CORE_ETFS}
    if existing_codes != configured_codes:
        raise ValueError("core ETF set changed; new policy revision required")
    frozen_members = [
        {"code": item["code"], "name": item.get("name") or ""}
        for item in existing_members
    ]
    return refresh_industry_universe(
        effective_from=effective_from,
        master_path=master_path,
        manifest_path=manifest_path,
        client=client,
        retrieved_at=retrieved_at,
        core_etfs=frozen_members,
    )


def get_industry_universe_status(
    *,
    master_path: Path | str = MASTER_PATH,
    manifest_path: Path | str = MANIFEST_PATH,
    as_of: Any | None = None,
    validation_start: Any = "2020-01-01",
) -> dict:
    """Report master integrity separately from retrospective PIT completeness."""
    from services.industry_validation import (
        build_universe_fingerprint,
        point_in_time_universe_coverage,
        resolve_universe_codes,
        validate_universe_history,
    )

    with Path(master_path).open("r", encoding="utf-8") as handle:
        master = json.load(handle)
    with Path(manifest_path).open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    records = master.get("records")
    master_hash_ok = bool(
        isinstance(records, list)
        and master.get("record_count") == len(records)
        and master.get("snapshot_sha256") == _canonical_hash(records)
    )
    validate_universe_history(manifest)
    source = manifest.get("source") if isinstance(manifest.get("source"), Mapping) else {}
    lineage_ok = bool(
        master_hash_ok
        and source.get("snapshot_sha256") == master.get("snapshot_sha256")
    )
    current_date = _iso_date(as_of or datetime.now(timezone.utc).date().isoformat())
    coverage = manifest.get("coverage") if isinstance(manifest.get("coverage"), Mapping) else {}
    current_covered = point_in_time_universe_coverage(manifest, current_date)
    historical_covered = point_in_time_universe_coverage(
        manifest, validation_start, current_date
    )
    active = resolve_universe_codes(manifest, current_date) if current_covered else set()
    member_codes = {str(member.get("code") or "") for member in manifest["members"]}
    reasons: list[str] = []
    if not master_hash_ok:
        reasons.append("ETF_MASTER_INTEGRITY_FAILED")
    if not lineage_ok:
        reasons.append("UNIVERSE_MASTER_LINEAGE_MISMATCH")
    if not current_covered:
        reasons.append("CURRENT_UNIVERSE_DATE_NOT_COVERED")
    if not historical_covered:
        reasons.append("UNIVERSE_HISTORY_BEFORE_FREEZE_UNAVAILABLE")
    return {
        "status": "prospective" if lineage_ok and current_covered else "locked",
        "integrity_ok": lineage_ok,
        "master_record_count": master.get("record_count"),
        "master_status_conflicts": sum(
            1 for record in (records or []) if record.get("status_conflict") is True
        ),
        "master_retrieved_at": master.get("retrieved_at"),
        "master_snapshot_sha256": master.get("snapshot_sha256"),
        "universe_fingerprint": build_universe_fingerprint(manifest),
        "member_count": len(member_codes),
        "active_member_count": len(active),
        "inactive_members": sorted(member_codes - active),
        "coverage_mode": coverage.get("mode"),
        "prospective_complete_from": coverage.get("complete_from"),
        "prospective_complete_through": coverage.get("complete_through"),
        "current_as_of": current_date,
        "current_date_covered": current_covered,
        "historical_validation_start": _iso_date(validation_start),
        "historical_validation_covered": historical_covered,
        "reasons": reasons,
        "execution_allowed": False,
    }
