"""Canonical CSI300 regime snapshot for all strategy consumers."""

import math
import time
from datetime import datetime, timedelta
from typing import Any, Mapping

import pandas as pd
import tushare as ts

from config import POSITION_CONFIG, TUSHARE_TOKEN
from mean_reversion_engine import _classify_regime_from_series
from services.cache_service import cache_manager
from services.cache_store import get_cache_ttl
from services.health_status import evaluate_aiae_context, get_aiae_max_age_sec
from services.strategy_params import (
    get_position_cap,
    get_runtime_metadata,
    get_score_gate,
    get_single_position_cap,
    get_stop_loss,
)


_CACHE_KEY = "market_regime_base_v2"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _build_regime_base(index_frame: pd.DataFrame) -> dict:
    if index_frame is None or len(index_frame) < 30:
        raise ValueError("CSI300 数据不足")
    required = {"trade_date", "close"}
    if not required.issubset(index_frame.columns):
        raise ValueError("CSI300 数据字段不完整")

    frame = index_frame.copy().sort_values("trade_date").reset_index(drop=True)
    close = pd.to_numeric(frame["close"], errors="coerce")
    if close.isna().any() or (close <= 0).any():
        raise ValueError("CSI300 收盘价无效")

    close_values = close.to_numpy(dtype=float)
    info = _classify_regime_from_series(close_values)
    regime = str(info["regime"]).upper()
    latest = float(close_values[-1])
    ret5 = float(info["ret5"])
    ret20 = float(info["ret20"])
    if "pct_chg" in frame.columns:
        pct = pd.to_numeric(frame["pct_chg"], errors="coerce") / 100
    else:
        pct = close.pct_change()
    vol20 = float(pct.iloc[-20:].std() * (252**0.5) * 100) if len(pct) >= 20 else 20.0
    ret60 = float((close_values[-1] / close_values[-61] - 1) * 100) if len(close_values) >= 61 else 0.0
    ma_label = f"MA{info.get('ma_period', 120)}"
    ma120 = float(info["ma120"])

    desc_map = {
        "BULL": f"CSI300 ({latest:.0f}) 站上{ma_label} ({ma120:.0f})且均线向上，允许提高风险预算。",
        "RANGE": f"CSI300 ({latest:.0f}) 处于震荡结构，采用均衡风险预算。",
        "BEAR": f"CSI300 ({latest:.0f}) 跌破{ma_label} ({ma120:.0f})，压低仓位并提高门槛。",
        "CRASH": f"CSI300 ({latest:.0f}) 触发极端风险状态，禁止新建仓。",
    }
    if regime == "RANGE" and not info["above_ma120"]:
        desc_map["RANGE"] = (
            f"CSI300 ({latest:.0f}) 仍低于{ma_label} ({ma120:.0f})，"
            f"近5日反弹{ret5:+.1f}%，仅保留受限风险预算。"
        )

    return {
        "status": "ok",
        "as_of": datetime.now().strftime("%Y-%m-%d"),
        "latest_date": str(frame["trade_date"].iloc[-1]).replace("-", "")[:8],
        "csi300": round(latest, 2),
        "ma60": round(float(info["ma60"]), 2),
        "ma120": round(ma120, 2),
        "above_ma120": bool(info["above_ma120"]),
        "ma120_rising": float(info["slope5"]) > 0,
        "ma120_slope5": round(float(info["slope5"]), 4),
        "ret5d": round(ret5, 2),
        "ret20d": round(ret20, 2),
        "ret60d": round(ret60, 2),
        "vol20d": round(vol20, 1),
        "regime": regime,
        "regime_cn": info["regime_cn"],
        "regime_color": info["regime_color"],
        "regime_icon": info["regime_icon"],
        "regime_desc": desc_map.get(regime, ""),
    }


def _attach_policy_and_aiae(
    base: Mapping[str, Any],
    aiae_ctx: Mapping[str, Any] | None,
    *,
    now_ts: float,
    aiae_max_age_sec: int | None = None,
) -> dict:
    result = dict(base)
    regime = str(result["regime"]).upper()
    aiae_state = evaluate_aiae_context(
        aiae_ctx,
        now_ts=now_ts,
        max_age_sec=aiae_max_age_sec,
    )
    safe_ctx = aiae_ctx if isinstance(aiae_ctx, Mapping) else {}
    raw_aiae_cap = _number(safe_ctx.get("cap"))
    valid_aiae_cap = (
        raw_aiae_cap
        if aiae_state["usable"] and raw_aiae_cap is not None and 0 <= raw_aiae_cap <= 100
        else None
    )

    regime_cap = get_position_cap("momentum", regime)
    audit_cap = float(POSITION_CONFIG.get("total_cap", 95))
    single_cap = min(
        get_single_position_cap("momentum", regime),
        float(POSITION_CONFIG.get("sector_limit", 40)),
    )
    effective_cap = (
        min(regime_cap, valid_aiae_cap, audit_cap)
        if valid_aiae_cap is not None
        else 0.0
    )
    locked = (
        not aiae_state["usable"]
        or valid_aiae_cap is None
        or regime == "CRASH"
        or effective_cap <= 0
    )
    score_gate = get_score_gate("momentum", regime)
    stop_loss_pct = get_stop_loss("momentum", regime) * 100

    note_map = {
        "BULL": "顺势配置；仍受 AIAE、组合及单行业上限约束",
        "RANGE": "均衡配置；提高信号确认要求",
        "BEAR": "防御配置；提高门槛并收紧止损",
        "CRASH": "禁止新建仓",
    }
    result.update({
        "decision_locked": locked,
        "aiae_usable": aiae_state["usable"],
        "aiae_decision_locked": aiae_state["decision_locked"],
        "aiae_reason": aiae_state["reason"],
        "aiae_quality_score": aiae_state["data_quality_score"],
        "aiae_age_sec": aiae_state["age_sec"],
        "aiae_max_age_sec": aiae_state["max_age_sec"],
        "aiae_cap": valid_aiae_cap,
        "regime_cap": regime_cap,
        "audit_cap": audit_cap,
        "single_position_cap": single_cap,
        "pos_cap": effective_cap,
        "pos_source": "strict_min" if valid_aiae_cap is not None else "locked",
        "score_gate": score_gate,
        "stop_loss_pct": stop_loss_pct,
        "runtime": get_runtime_metadata(),
        "optimal_params": {
            "top_n": 3,
            "rebalance_days": 5,
            "mom_window": 30,
            "stop_loss": -stop_loss_pct,
            "pos_cap": effective_cap,
            "single_position_cap": single_cap,
            "entry_threshold": score_gate,
            "note": note_map.get(regime, ""),
        },
    })
    return result


def build_market_regime_snapshot(
    index_frame: pd.DataFrame,
    aiae_ctx: Mapping[str, Any] | None,
    *,
    now_ts: float | None = None,
    aiae_max_age_sec: int | None = None,
) -> dict:
    """Pure-ish builder used by tests and the live cached loader."""
    current_ts = time.time() if now_ts is None else now_ts
    return _attach_policy_and_aiae(
        _build_regime_base(index_frame),
        aiae_ctx,
        now_ts=current_ts,
        aiae_max_age_sec=aiae_max_age_sec,
    )


def _fetch_csi300() -> pd.DataFrame:
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    end_dt = datetime.now().strftime("%Y%m%d")
    start_dt = (datetime.now() - timedelta(days=300)).strftime("%Y%m%d")
    return pro.index_daily(
        ts_code="000300.SH",
        start_date=start_dt,
        end_date=end_dt,
        fields="trade_date,close,pct_chg",
    )


def get_market_regime_snapshot(*, force: bool = False) -> dict:
    """Load cached market metrics but re-evaluate AIAE safety on every call."""
    base = None if force else cache_manager.get_json(_CACHE_KEY)
    if not isinstance(base, Mapping) or base.get("status") != "ok":
        base = _build_regime_base(_fetch_csi300())
        cache_manager.set_json(_CACHE_KEY, base, ttl_seconds=get_cache_ttl())

    # AIAE is deliberately not embedded in the regime cache. Its lock and age
    # must be recomputed on every decision request.
    aiae_ctx = cache_manager.get_json("aiae_ctx")
    return _attach_policy_and_aiae(
        base,
        aiae_ctx,
        now_ts=time.time(),
        aiae_max_age_sec=get_aiae_max_age_sec(),
    )
