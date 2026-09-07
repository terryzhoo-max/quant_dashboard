"""Verified ETF tracking-index constituents with fail-closed lineage checks."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from services.strategy_params import get_industry_execution_rules


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = PROJECT_ROOT / "data_lake" / "industry_index_constituents.json"
MANIFEST_PATH = PROJECT_ROOT / "config" / "industry_universe_history.json"
STOCK_LIST_PATH = PROJECT_ROOT / "data_lake" / "stock_list.parquet"
_write_lock = threading.Lock()


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _iso_date(value: Any) -> str:
    text = str(value or "").strip().replace("-", "")[:8]
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid date: {value}")
    return datetime.strptime(text, "%Y%m%d").date().isoformat()


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_constituent_snapshot(
    manifest: Mapping[str, Any],
    frames_by_index: Mapping[str, pd.DataFrame],
    *,
    stock_names: Mapping[str, str],
    as_of: Any,
    retrieved_at: str | None = None,
    max_age_days: int,
    top_n: int,
    weight_sum_bounds_pct: tuple[float, float] | list[float] = (95, 105),
) -> dict:
    """Build a deterministic snapshot from official monthly index weights."""
    reference_date = date.fromisoformat(_iso_date(as_of))
    lower_weight, upper_weight = map(float, weight_sum_bounds_pct)
    members = manifest.get("members")
    if not isinstance(members, list):
        raise ValueError("industry universe manifest has no members")

    records: list[dict] = []
    for member in members:
        etf_code = str(member.get("code") or "").strip()
        index_code = str(member.get("tracking_index_code") or "").strip()
        issues: list[str] = []
        latest_date: str | None = None
        age_days: int | None = None
        weight_sum: float | None = None
        constituent_count = 0
        verified_top: list[dict] = []

        if not etf_code:
            raise ValueError("industry universe contains empty ETF code")
        if not index_code:
            issues.append("TRACKING_INDEX_MISSING")
            frame = pd.DataFrame()
        else:
            frame = frames_by_index.get(index_code, pd.DataFrame())

        required = {"con_code", "trade_date", "weight"}
        if frame is None or frame.empty:
            issues.append("INDEX_WEIGHT_UNAVAILABLE")
        elif not required.issubset(frame.columns):
            issues.append("INDEX_WEIGHT_SCHEMA_INVALID")
        else:
            work = frame[list(required)].copy()
            try:
                work["trade_date_iso"] = work["trade_date"].map(_iso_date)
            except ValueError:
                issues.append("INDEX_WEIGHT_DATE_INVALID")
                work = pd.DataFrame()
            if not work.empty:
                work = work[work["trade_date_iso"] <= reference_date.isoformat()]
            if work.empty and "INDEX_WEIGHT_DATE_INVALID" not in issues:
                issues.append("INDEX_WEIGHT_UNAVAILABLE")
            elif not work.empty:
                latest_date = str(work["trade_date_iso"].max())
                latest = work[work["trade_date_iso"] == latest_date].copy()
                latest["con_code"] = latest["con_code"].astype(str).str.strip()
                latest["weight_num"] = pd.to_numeric(latest["weight"], errors="coerce")
                if latest["con_code"].eq("").any():
                    issues.append("INDEX_CONSTITUENT_CODE_INVALID")
                if latest["con_code"].duplicated().any():
                    issues.append("INDEX_CONSTITUENT_DUPLICATE")
                if latest["weight_num"].isna().any() or (
                    latest["weight_num"] <= 0
                ).any():
                    issues.append("INDEX_WEIGHT_VALUE_INVALID")
                constituent_count = int(len(latest))
                weight_sum_value = _finite(latest["weight_num"].sum())
                weight_sum = (
                    round(weight_sum_value, 4)
                    if weight_sum_value is not None
                    else None
                )
                if constituent_count < max(5, int(top_n)):
                    issues.append("INDEX_CONSTITUENT_COUNT_TOO_SMALL")
                if weight_sum is None or not lower_weight <= weight_sum <= upper_weight:
                    issues.append("INDEX_WEIGHT_SUM_INVALID")
                age_days = (reference_date - date.fromisoformat(latest_date)).days
                if age_days < 0 or age_days > int(max_age_days):
                    issues.append("INDEX_WEIGHT_STALE")

                if not issues:
                    latest = latest.sort_values(
                        ["weight_num", "con_code"], ascending=[False, True]
                    )
                    verified_top = [
                        {
                            "code": row.con_code,
                            "name": str(stock_names.get(row.con_code) or row.con_code),
                            "weight_pct": round(float(row.weight_num), 4),
                        }
                        for row in latest.head(int(top_n)).itertuples(index=False)
                    ]

        issues = list(dict.fromkeys(issues))
        records.append(
            {
                "etf_code": etf_code,
                "policy_label": str(member.get("name") or ""),
                "instrument_name": str(member.get("instrument_name") or ""),
                "tracking_index_code": index_code,
                "tracking_index_name": str(member.get("tracking_index_name") or ""),
                "is_verified": not issues,
                "as_of": latest_date,
                "age_days": age_days,
                "constituent_count": constituent_count,
                "weight_sum_pct": weight_sum,
                "top_constituents": verified_top if not issues else [],
                "issues": issues,
            }
        )

    records.sort(key=lambda item: item["etf_code"])
    observed_at = retrieved_at or datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "provider": "tushare_pro",
        "dataset": "index_weight",
        "primary_origin": "index company public data",
        "retrieved_at": observed_at,
        "as_of": reference_date.isoformat(),
        "max_age_days": int(max_age_days),
        "top_n": int(top_n),
        "weight_sum_bounds_pct": [lower_weight, upper_weight],
        "record_count": len(records),
        "snapshot_sha256": _canonical_hash(records),
        "records": records,
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
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


def _unavailable(etf_code: str, issue: str) -> dict:
    return {
        "etf_code": etf_code,
        "is_verified": False,
        "as_of": None,
        "top_constituents": [],
        "issues": [issue],
    }


def get_constituents_for_etf(
    etf_code: str,
    *,
    path: Path | str = SNAPSHOT_PATH,
    as_of: Any | None = None,
) -> dict:
    """Return verified constituents, rechecking integrity and staleness."""
    target = Path(path)
    if not target.exists():
        return _unavailable(etf_code, "CONSTITUENT_SNAPSHOT_MISSING")
    try:
        snapshot = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _unavailable(etf_code, "CONSTITUENT_SNAPSHOT_INVALID")
    records = snapshot.get("records")
    if (
        not isinstance(records, list)
        or snapshot.get("record_count") != len(records)
        or snapshot.get("snapshot_sha256") != _canonical_hash(records)
    ):
        return _unavailable(etf_code, "CONSTITUENT_SNAPSHOT_INTEGRITY_FAILED")
    record = next(
        (item for item in records if item.get("etf_code") == etf_code), None
    )
    if not isinstance(record, Mapping):
        return _unavailable(etf_code, "CONSTITUENT_ETF_NOT_FOUND")
    result = dict(record)
    result["top_constituents"] = [
        dict(item) for item in (record.get("top_constituents") or [])
    ]
    if result.get("as_of"):
        current = date.fromisoformat(_iso_date(as_of or date.today().isoformat()))
        age_days = (current - date.fromisoformat(result["as_of"])).days
        result["age_days"] = age_days
        if age_days < 0 or age_days > int(snapshot.get("max_age_days", 0)):
            result["is_verified"] = False
            result["top_constituents"] = []
            result["issues"] = list(
                dict.fromkeys([*(result.get("issues") or []), "INDEX_WEIGHT_STALE"])
            )
    if result.get("is_verified") is not True:
        result["top_constituents"] = []
    result["provider"] = snapshot.get("provider")
    result["dataset"] = snapshot.get("dataset")
    result["retrieved_at"] = snapshot.get("retrieved_at")
    return result


def get_industry_constituent_status(
    *, path: Path | str = SNAPSHOT_PATH, as_of: Any | None = None
) -> dict:
    """Summarize current verified coverage without exposing stale weights."""
    target = Path(path)
    if not target.exists():
        return {
            "integrity_ok": False,
            "record_count": 0,
            "verified_count": 0,
            "reasons": ["CONSTITUENT_SNAPSHOT_MISSING"],
        }
    try:
        snapshot = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "integrity_ok": False,
            "record_count": 0,
            "verified_count": 0,
            "reasons": ["CONSTITUENT_SNAPSHOT_INVALID"],
        }
    records = snapshot.get("records")
    integrity_ok = bool(
        isinstance(records, list)
        and snapshot.get("record_count") == len(records)
        and snapshot.get("snapshot_sha256") == _canonical_hash(records)
    )
    if not integrity_ok:
        return {
            "integrity_ok": False,
            "record_count": len(records) if isinstance(records, list) else 0,
            "verified_count": 0,
            "reasons": ["CONSTITUENT_SNAPSHOT_INTEGRITY_FAILED"],
        }
    results = [
        get_constituents_for_etf(
            str(record.get("etf_code") or ""), path=target, as_of=as_of
        )
        for record in records
    ]
    return {
        "integrity_ok": True,
        "record_count": len(results),
        "verified_count": sum(item.get("is_verified") is True for item in results),
        "unverified_count": sum(item.get("is_verified") is not True for item in results),
        "as_of": snapshot.get("as_of"),
        "retrieved_at": snapshot.get("retrieved_at"),
        "snapshot_sha256": snapshot.get("snapshot_sha256"),
        "records": results,
        "reasons": [],
    }


def refresh_industry_constituents(
    *,
    manifest_path: Path | str = MANIFEST_PATH,
    output_path: Path | str = SNAPSHOT_PATH,
    stock_list_path: Path | str = STOCK_LIST_PATH,
    client: Any = None,
    as_of: Any | None = None,
    retrieved_at: str | None = None,
) -> dict:
    """Fetch official monthly weights for every frozen core ETF tracking index."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    rules = get_industry_execution_rules()
    reference_date = date.fromisoformat(_iso_date(as_of or date.today().isoformat()))
    if client is None:
        import tushare as ts
        from config import TUSHARE_TOKEN

        ts.set_token(TUSHARE_TOKEN)
        client = ts.pro_api()

    index_codes = sorted(
        {
            str(member.get("tracking_index_code") or "").strip()
            for member in manifest.get("members", [])
            if str(member.get("tracking_index_code") or "").strip()
        }
    )
    start_date = (reference_date - timedelta(days=150)).strftime("%Y%m%d")
    end_date = reference_date.strftime("%Y%m%d")
    frames: dict[str, pd.DataFrame] = {}
    for index_code in index_codes:
        try:
            frame = client.index_weight(
                index_code=index_code,
                start_date=start_date,
                end_date=end_date,
            )
            frames[index_code] = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
        except Exception:
            frames[index_code] = pd.DataFrame()

    stock_names: dict[str, str] = {}
    stock_path = Path(stock_list_path)
    if stock_path.exists():
        try:
            stocks = pd.read_parquet(stock_path, columns=["ts_code", "name"])
            stock_names = {
                str(row.ts_code): str(row.name)
                for row in stocks.itertuples(index=False)
                if row.ts_code and row.name
            }
        except Exception:
            stock_names = {}

    snapshot = build_constituent_snapshot(
        manifest,
        frames,
        stock_names=stock_names,
        as_of=reference_date.isoformat(),
        retrieved_at=retrieved_at,
        max_age_days=int(rules["constituent_max_age_days"]),
        top_n=int(rules["constituent_top_n"]),
        weight_sum_bounds_pct=rules["constituent_weight_sum_bounds_pct"],
    )
    _atomic_write_json(Path(output_path), snapshot)
    return snapshot
