"""Fail-closed industry eligibility policy shared by API and health checks.

The Alpha score remains a research ranking.  This module is the only place
that converts that ranking into an execution eligibility decision.
"""

import math
from statistics import median
from typing import Any, Iterable, Mapping

from services.strategy_params import (
    get_position_cap,
    get_industry_execution_rules,
    get_runtime_metadata,
    get_score_gate,
    get_single_position_cap,
    get_stop_loss,
)


VALID_REGIMES = {"BEAR", "RANGE", "BULL", "CRASH"}


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date_key(value: Any) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else None


def _aiae_lock_reason(market_snapshot: Mapping[str, Any]) -> str:
    reason = str(market_snapshot.get("aiae_reason") or "").lower()
    return {
        "missing": "AIAE_CONTEXT_MISSING",
        "stale": "AIAE_STALE",
        "decision_locked": "AIAE_DECISION_LOCKED",
        "timestamp_missing_or_invalid": "AIAE_TIMESTAMP_INVALID",
    }.get(reason, "AIAE_UNUSABLE")


def build_industry_liquidity_profile(
    amount_values: Iterable[Any] | None,
    *,
    rules: Mapping[str, Any] | None = None,
) -> dict:
    """Convert Tushare ETF amount values into an auditable CNY capacity gate."""
    contract = dict(rules or get_industry_execution_rules())
    lookback = int(contract["liquidity_lookback_days"])
    min_valid = int(contract["min_valid_amount_days"])
    raw_values = (
        list(amount_values)[-lookback:] if amount_values is not None else []
    )
    valid_values = [
        value
        for raw in raw_values
        if (value := _finite_number(raw)) is not None and value > 0
    ]
    multiplier = 1000.0 if contract["amount_unit"] == "thousand_cny" else 1.0
    median_cny = median(valid_values) * multiplier if valid_values else None
    latest = _finite_number(raw_values[-1]) if raw_values else None
    latest_cny = latest * multiplier if latest is not None and latest > 0 else None
    floor_cny = float(contract["min_median_turnover_cny"])
    participation = float(contract["max_participation_rate"])
    data_complete = len(raw_values) >= lookback and len(valid_values) >= min_valid
    adv_pass = data_complete and median_cny is not None and median_cny >= floor_cny
    return {
        "lookback_days": lookback,
        "valid_amount_days": len(valid_values),
        "median_turnover_cny": round(median_cny, 2) if median_cny is not None else None,
        "latest_turnover_cny": round(latest_cny, 2) if latest_cny is not None else None,
        "capacity_at_participation_cny": (
            round(median_cny * participation, 2) if median_cny is not None else None
        ),
        "min_median_turnover_cny": floor_cny,
        "max_participation_rate": participation,
        "data_complete": data_complete,
        "median_turnover_pass": adv_pass,
        "pretrade_quote_required": contract["pretrade_quote_required"] is True,
    }


def build_industry_decision_context(
    data_quality: Mapping[str, Any] | None,
    market_snapshot: Mapping[str, Any] | None,
    *,
    model_validation_ready: bool | None = None,
    model_validation_status: Mapping[str, Any] | None = None,
    historical_query: bool = False,
) -> dict:
    """Build one canonical decision context and fail closed on missing inputs."""
    quality = data_quality if isinstance(data_quality, Mapping) else {}
    market = market_snapshot if isinstance(market_snapshot, Mapping) else {}
    hard_reasons: list[str] = []

    data_blocked = quality.get("decision_locked", True) or not quality.get("is_usable", False)
    if data_blocked:
        hard_reasons.extend(
            str(reason) for reason in quality.get("reasons", []) if reason
        )
        if not hard_reasons:
            hard_reasons.append("INDUSTRY_DATA_UNUSABLE")

    if historical_query:
        hard_reasons.append("HISTORICAL_QUERY_RESEARCH_ONLY")

    evaluate_market = not data_blocked and not historical_query
    market_ok = evaluate_market and market.get("status") == "ok"
    if evaluate_market and not market_ok:
        hard_reasons.append("REGIME_UNAVAILABLE")

    regime = str(market.get("regime") or "UNKNOWN").upper()
    if evaluate_market and regime not in VALID_REGIMES:
        hard_reasons.append("REGIME_INVALID")

    expected_date = _date_key(quality.get("expected_trade_date"))
    regime_date = _date_key(market.get("latest_date"))
    if market_ok and expected_date and (
        regime_date is None or regime_date < expected_date
    ):
        hard_reasons.append("REGIME_DATA_STALE")

    if market_ok and market.get("aiae_usable") is not True:
        hard_reasons.append(_aiae_lock_reason(market))

    aiae_cap = _finite_number(market.get("aiae_cap"))
    if market_ok and market.get("aiae_usable") is True and (
        aiae_cap is None or not 0 <= aiae_cap <= 100
    ):
        hard_reasons.append("AIAE_CAP_INVALID")

    score_gate = None
    regime_cap = None
    single_cap = None
    stop_loss_pct = None
    runtime = {}
    if evaluate_market and regime in VALID_REGIMES:
        try:
            score_gate = get_score_gate("momentum", regime)
            regime_cap = get_position_cap("momentum", regime)
            single_cap = get_single_position_cap("momentum", regime)
            stop_loss_pct = get_stop_loss("momentum", regime) * 100
            runtime = get_runtime_metadata()
        except (KeyError, TypeError, ValueError):
            hard_reasons.append("POLICY_PARAMETER_ERROR")

    audit_cap = _finite_number(market.get("audit_cap")) if evaluate_market else None
    if evaluate_market and (audit_cap is None or not 0 <= audit_cap <= 100):
        hard_reasons.append("AUDIT_CAP_INVALID")

    effective_total_cap = 0.0
    if regime_cap is not None and aiae_cap is not None and audit_cap is not None:
        effective_total_cap = min(regime_cap, aiae_cap, audit_cap)

    if evaluate_market and regime == "CRASH":
        hard_reasons.append("REGIME_CRASH_LOCK")
    elif (
        evaluate_market
        and market.get("aiae_usable") is True
        and aiae_cap is not None
        and audit_cap is not None
        and effective_total_cap <= 0
    ):
        hard_reasons.append("ZERO_POSITION_CAP")

    if model_validation_status is not None:
        validation = dict(model_validation_status)
    elif model_validation_ready is not None:
        validation = {
            "ready": bool(model_validation_ready),
            "stage": "promoted" if model_validation_ready else "pending",
            "reasons": [],
        }
    else:
        try:
            from services.industry_validation import load_industry_validation_status

            validation = load_industry_validation_status()
        except Exception:
            validation = {
                "ready": False,
                "stage": "error",
                "reasons": ["VALIDATION_STATUS_UNAVAILABLE"],
            }
    regime_statuses = validation.get("regime_statuses")
    regime_statuses = regime_statuses if isinstance(regime_statuses, Mapping) else {}
    regime_validation = regime_statuses.get(regime)
    regime_validation = (
        dict(regime_validation) if isinstance(regime_validation, Mapping) else {}
    )
    lifecycle = regime_validation.get("lifecycle")
    if evaluate_market and lifecycle == "disabled":
        hard_reasons.append("REGIME_MODEL_DISABLED")
    model_ready = (
        regime_validation.get("execution_ready") is True
        if regime_validation
        else validation.get("ready") is True
    )

    hard_reasons = _dedupe(hard_reasons)
    lock_reasons = list(hard_reasons)
    if not hard_reasons and not model_ready:
        if lifecycle == "shadow":
            lock_reasons.append("REGIME_MODEL_SHADOW")
        lock_reasons.append("MODEL_VALIDATION_PENDING")
        lock_reasons.extend(str(reason) for reason in validation.get("reasons", []) if reason)
        lock_reasons = _dedupe(lock_reasons)

    return {
        "regime": regime,
        "regime_as_of": regime_date,
        "industry_expected_trade_date": expected_date,
        "score_gate": score_gate,
        "regime_position_cap": regime_cap,
        "aiae_position_cap": aiae_cap,
        "audit_position_cap": audit_cap,
        "effective_total_cap": effective_total_cap,
        "single_position_cap": single_cap,
        "stop_loss_pct": stop_loss_pct,
        "aiae_usable": market.get("aiae_usable") is True,
        "aiae_reason": market.get("aiae_reason"),
        "model_validation_ready": model_ready,
        "model_validation": validation,
        "regime_model_validation": regime_validation,
        "hard_locked": bool(hard_reasons),
        "decision_locked": bool(lock_reasons),
        "decision_lock_reasons": lock_reasons,
        "runtime": runtime,
    }


def evaluate_industry_candidate(
    candidate: Mapping[str, Any], context: Mapping[str, Any]
) -> dict:
    """Apply score, trend and risk vetoes without changing the Alpha model."""
    score = _finite_number(candidate.get("alpha_score"))
    gate = _finite_number(context.get("score_gate"))
    trend = candidate.get("trend_strength")
    trend = trend if isinstance(trend, Mapping) else {}
    above_ma20 = trend.get("above_ma20") is True
    above_ma60 = trend.get("above_ma60") is True
    ma20_slope = _finite_number(trend.get("ma20_slope"))
    slope_pass = ma20_slope is not None and ma20_slope >= 0
    danger_alert = any(
        isinstance(alert, Mapping) and alert.get("level") == "danger"
        for alert in (candidate.get("risk_alerts") or [])
    )
    execution_quality = candidate.get("execution_quality")
    execution_quality = (
        execution_quality if isinstance(execution_quality, Mapping) else {}
    )
    liquidity_data_complete = execution_quality.get("data_complete") is True
    liquidity_median_turnover_pass = (
        execution_quality.get("median_turnover_pass") is True
    )

    checks = {
        "score": score,
        "score_gate": gate,
        "score_pass": score is not None and gate is not None and score >= gate,
        "above_ma20": above_ma20,
        "above_ma60": above_ma60,
        "ma20_slope": ma20_slope,
        "ma20_slope_pass": slope_pass,
        "danger_risk_alert_absent": not danger_alert,
        "liquidity_data_complete": liquidity_data_complete,
        "liquidity_median_turnover_pass": liquidity_median_turnover_pass,
    }
    vetoes: list[str] = []
    if not checks["score_pass"]:
        vetoes.append("SCORE_BELOW_REGIME_GATE")
    if not above_ma20:
        vetoes.append("BELOW_MA20")
    if not above_ma60:
        vetoes.append("BELOW_MA60")
    if not slope_pass:
        vetoes.append("MA20_SLOPE_NEGATIVE")
    if danger_alert:
        vetoes.append("DANGER_RISK_ALERT")
    if not liquidity_data_complete:
        vetoes.append("LIQUIDITY_DATA_INCOMPLETE")
    elif not liquidity_median_turnover_pass:
        vetoes.append("MEDIAN_TURNOVER_20D_BELOW_MINIMUM")

    hard_locked = context.get("hard_locked") is True
    policy_qualified = not hard_locked and not vetoes
    model_ready = context.get("model_validation_ready") is True
    stop_loss_pct = _finite_number(context.get("stop_loss_pct"))
    single_cap = _finite_number(context.get("single_position_cap")) or 0

    if hard_locked:
        action = "data_locked"
        label = "🔒 决策锁定"
        advice = "数据、Regime 或 AIAE 安全闸门未通过，禁止形成买入决策"
        buy_strategy = "等待全部硬性闸门恢复"
        position_cap = "0%"
    elif danger_alert:
        action = "avoid"
        label = "🔴 风险否决"
        advice = "触发危险级风险警报，取消候选资格"
        buy_strategy = "不新建仓，待危险信号解除后重新评估"
        position_cap = "0%"
    elif policy_qualified and not model_ready:
        action = "candidate_eligible"
        label = "🟠 条件达标·待验证"
        advice = "已通过当期策略条件，但样本外验证尚未完成，不可执行"
        buy_strategy = "保留在研究候选池，不下单"
        position_cap = "0%（待样本外验证）"
    elif policy_qualified:
        action = "eligible_buy"
        label = "🟢 盘后合格候选"
        advice = "通过盘后资格闸门；下单前仍须核验实时价格、停牌及申赎状态"
        buy_strategy = "盘前复核通过后分批建仓，并受组合、单行业及成交容量上限约束"
        position_cap = f"单行业上限{single_cap:g}%"
    else:
        action = "watch"
        label = "🔵 观察"
        advice = "研究评分保留，但未通过全部执行资格条件"
        buy_strategy = "等待评分、趋势与风险条件同时达标"
        position_cap = "0%"

    stop_loss = (
        f"收盘价较入场价回撤达到 -{stop_loss_pct:g}%，或跌破MA60"
        if policy_qualified and stop_loss_pct is not None
        else "—"
    )
    return {
        "policy_qualified": policy_qualified,
        "decision_locked": bool(context.get("decision_locked", True)),
        "decision_status": action,
        "decision_lock_reasons": list(context.get("decision_lock_reasons", [])),
        "eligibility_checks": checks,
        "veto_reasons": vetoes,
        "advice": advice,
        "advice_action": action,
        "advice_label": label,
        "buy_strategy": buy_strategy,
        "take_profit": "按周复核；跌出候选资格或组合风险预算收缩时减仓",
        "stop_loss": stop_loss,
        "position_cap": position_cap,
        "execution": {
            "allowed": action == "eligible_buy",
            "decision_basis": "end_of_day",
            "order_release_allowed": (
                action == "eligible_buy"
                and execution_quality.get("pretrade_quote_required") is not True
            ),
            "pretrade_quote_required": (
                execution_quality.get("pretrade_quote_required") is True
            ),
            "median_turnover_cny": execution_quality.get("median_turnover_cny"),
            "latest_turnover_cny": execution_quality.get("latest_turnover_cny"),
            "capacity_at_participation_cny": execution_quality.get(
                "capacity_at_participation_cny"
            ),
            "max_participation_rate": execution_quality.get(
                "max_participation_rate"
            ),
            "min_median_turnover_cny": execution_quality.get(
                "min_median_turnover_cny"
            ),
            "regime": context.get("regime"),
            "score_gate": gate,
            "score_gap": round(score - gate, 1) if score is not None and gate is not None else None,
            "effective_total_cap": context.get("effective_total_cap", 0),
            "proposed_single_position_cap": single_cap,
            "stop_loss_pct": stop_loss_pct,
            "runtime_revision": (context.get("runtime") or {}).get("revision"),
        },
    }


def build_industry_abstention_plan(
    candidates: list[Mapping[str, Any]],
    context: Mapping[str, Any],
    *,
    top_n: int = 3,
) -> dict:
    """Build a non-executable monitoring packet when no industry may be bought.

    Candidate readiness is deliberately separate from the global model lock.  A
    security can lead the research ranking while the packet remains NO_TRADE.
    This function consumes already-evaluated candidates and never upgrades a
    candidate's execution permission.
    """
    check_names = (
        "score_pass",
        "above_ma20",
        "above_ma60",
        "ma20_slope_pass",
        "danger_risk_alert_absent",
        "liquidity_data_complete",
        "liquidity_median_turnover_pass",
    )
    rows: list[dict] = []
    for candidate in candidates:
        checks = candidate.get("eligibility_checks")
        checks = checks if isinstance(checks, Mapping) else {}
        vetoes = _dedupe(
            [str(reason) for reason in candidate.get("veto_reasons", [])]
        )
        execution = candidate.get("execution")
        execution = execution if isinstance(execution, Mapping) else {}
        score = _finite_number(
            candidate.get("research_score", candidate.get("alpha_score"))
        )
        gate = _finite_number(checks.get("score_gate"))
        if gate is None:
            gate = _finite_number(context.get("score_gate"))
        gap = _finite_number(execution.get("score_gap"))
        if gap is None and score is not None and gate is not None:
            gap = score - gate
        passed_checks = sum(checks.get(name) is True for name in check_names)
        danger = "DANGER_RISK_ALERT" in vetoes or checks.get(
            "danger_risk_alert_absent"
        ) is False
        liquidity_veto = any(
            reason in {
                "LIQUIDITY_DATA_INCOMPLETE",
                "MEDIAN_TURNOVER_20D_BELOW_MINIMUM",
            }
            for reason in vetoes
        )
        only_score_missing = vetoes == ["SCORE_BELOW_REGIME_GATE"]
        if danger:
            tier = "RISK_VETO"
        elif liquidity_veto:
            tier = "LIQUIDITY_CONSTRAINED"
        elif only_score_missing and gap is not None and gap >= -5:
            tier = "NEAR_TRIGGER"
        elif only_score_missing:
            tier = "LEADING_WATCH"
        else:
            tier = "TREND_REPAIR"

        tier_rank = {
            "NEAR_TRIGGER": 0,
            "LEADING_WATCH": 1,
            "TREND_REPAIR": 2,
            "LIQUIDITY_CONSTRAINED": 3,
            "RISK_VETO": 4,
        }[tier]
        rows.append(
            {
                "code": str(candidate.get("ts_code") or candidate.get("code") or ""),
                "name": str(candidate.get("name") or "未知行业"),
                "research_score": round(score, 1) if score is not None else None,
                "score_gate": round(gate, 1) if gate is not None else None,
                "score_gap": round(gap, 1) if gap is not None else None,
                "passed_checks": passed_checks,
                "total_checks": len(check_names),
                "readiness_tier": tier,
                "remaining_conditions": vetoes,
                "execution_allowed": False,
                "median_turnover_cny": execution.get("median_turnover_cny"),
                "capacity_at_participation_cny": execution.get(
                    "capacity_at_participation_cny"
                ),
                "min_median_turnover_cny": execution.get(
                    "min_median_turnover_cny"
                ),
                "data_as_of": candidate.get("data_as_of"),
                "_danger": danger,
                "_tier_rank": tier_rank,
            }
        )

    rows.sort(
        key=lambda row: (
            row["_tier_rank"],
            -row["passed_checks"],
            -(row["score_gap"] if row["score_gap"] is not None else -math.inf),
            -(row["research_score"] if row["research_score"] is not None else -math.inf),
            row["code"],
        )
    )
    watchlist = []
    for row in rows[: max(0, int(top_n))]:
        clean_row = dict(row)
        clean_row.pop("_danger", None)
        clean_row.pop("_tier_rank", None)
        watchlist.append(clean_row)

    eligible_count = sum(
        isinstance(candidate.get("execution"), Mapping)
        and candidate["execution"].get("allowed") is True
        for candidate in candidates
    )
    locked = context.get("decision_locked") is True
    no_trade = locked or eligible_count == 0
    return {
        "action": "NO_TRADE" if no_trade else "EXECUTION_CANDIDATES_PRESENT",
        "execution_allowed": not no_trade,
        "regime": context.get("regime"),
        "regime_as_of": context.get("regime_as_of"),
        "decision_lock_reasons": list(context.get("decision_lock_reasons", [])),
        "eligible_buy_count": eligible_count,
        "watchlist": watchlist,
        "disclaimer": "研究观察清单，不构成买入建议；仅 execution.allowed=true 才具备执行资格。",
    }
