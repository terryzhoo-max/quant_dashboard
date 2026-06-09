"""
AlphaCore V27.0 Decision Intelligence Hub (Facade)
====================================================
O1 Refactor: 2949L -> ~700L (78% reduction)

All core logic split into dashboard_modules.decision.* subpackage.
This file serves as:
  1. Backward-compatible facade (all external imports unchanged)
  2. Home for aggregation functions that depend on multiple submodules
"""

import copy
import math
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from services.logger import get_logger

logger = get_logger("ac.decision")

try:
    from engines.erp_params import D1_SIGMOID_CENTER as _ERP_CENTER, D1_SIGMOID_K as _ERP_K
except ImportError:
    _ERP_CENTER, _ERP_K = 4.0, 1.5


# ==============================================================
#  Re-export from submodules (backward compatibility)
# ==============================================================

from dashboard_modules.decision.conflicts import (  # noqa: F401,F403
    _signal_direction, _signal_conviction, _CONFLICT_RULES, compute_conflict_matrix,
)

from dashboard_modules.decision.jcs import (  # noqa: F401,F403
    _JCS_WEIGHTS, _JCS_WEIGHTS_V4, _REGIME_CN_MAP, _REGIME_CAP_MAP,
    _recalc_vix_score, _recalc_hub_composite, _compute_jcs_with_weights,
    _compute_jcs_v26, compute_jcs,
)

from dashboard_modules.decision.temperature import (  # noqa: F401,F403
    _GLOBAL_REGIMES, _GLOBAL_GAUGE_BANDS, _REGIME_CAP_LOOKUP,
    _build_global_temperature,
)

from dashboard_modules.decision.snapshot import (  # noqa: F401,F403
    _parse_erp_value, _build_snapshot_from_cache,
)

from dashboard_modules.decision.action_plan import (  # noqa: F401,F403
    _get_current_position, _apply_position_gap_note,
    generate_action_plan, generate_alerts,
)

from dashboard_modules.decision.scenarios import (  # noqa: F401,F403
    SCENARIOS, _SHOCK_NODES, _SHOCK_EDGES, _SHOCK_SOURCES, _SNAPSHOT_DELTA_MAP,
    _build_adjacency, propagate_shock, apply_shock_to_snapshot,
    run_shock_simulation, simulate_scenario,
)

from dashboard_modules.decision.position_path import (  # noqa: F401,F403
    _POSITION_RULES, generate_position_path,
    _estimate_volatility, _estimate_daily_volume,
    estimate_execution_cost, estimate_position_path_costs,
)

from dashboard_modules.decision.events import (  # noqa: F401,F403
    _EVENT_LOG_PATH, _SNAPSHOT_PATH, _MAX_EVENTS, _EVENT_COOLDOWNS,
    _check_event_cooldown, _load_last_snapshot, _save_last_snapshot,
    _load_event_log, _save_event_log,
    detect_market_events, get_recent_events,
)

from dashboard_modules.decision.risk_matrix import (  # noqa: F401,F403
    compute_risk_matrix,
)

from dashboard_modules.decision.accuracy import (  # noqa: F401,F403
    _get_index_close, _get_t5_trade_date, backfill_signal_accuracy,
)

from dashboard_modules.decision.contagion import (  # noqa: F401,F403
    _CONTAGION_INDICES, compute_contagion_matrix,
)


# ==============================================================
#  Aggregation functions (depend on multiple submodules)
# ==============================================================

def get_hub_data() -> dict:
    """决策中枢全量数据 (供 API 返回)"""
    snapshot = _build_snapshot_from_cache()

    conflicts = compute_conflict_matrix(snapshot)
    jcs = compute_jcs(snapshot)
    action_plan = generate_action_plan(snapshot, jcs, conflicts)

    # V19.0: 全球市场温度
    global_temp = _build_global_temperature()

    # V21.2: 数据新鲜度元数据 — 前端据此显示各引擎最后更新时间
    from services.cache_service import cache_manager
    _now_ts = datetime.now().timestamp()
    _freshness = {}

    # ── 各引擎缓存状态 + 数据日期提取 ──
    _engine_defs = [
        ("dashboard", "dashboard_data", "Dashboard"),
        ("aiae", "aiae_ctx", "AIAE"),
        ("strategy", "strategy_results", "策略引擎"),
        ("global", "aiae_global_report_data", "全球对比"),
    ]
    _dates_seen = []
    for _fk, _ck, _label in _engine_defs:
        _cached = cache_manager.get_json(_ck)
        if _cached:
            # 提取数据日期 (各引擎存储位置不同)
            _dd = None
            if _fk == "dashboard":
                # dashboard_data 不含 trade_date, 但内嵌 ERP 信号有日期
                _erp_snap = (_cached.get("data", {}).get("macro_cards", {})
                             .get("erp", {}))
                # 从 erp_pct 值存在推断数据有效, 日期从 strategy 补
            elif _fk == "aiae":
                _dd = _cached.get("trade_date") or _cached.get("date")
            elif _fk == "strategy":
                # strategy_results.erp_timing.current_snapshot.trade_date
                _erp_t = _cached.get("erp_timing", {})
                if isinstance(_erp_t, dict):
                    _dd = (_erp_t.get("data", _erp_t).get("current_snapshot", {})
                           .get("trade_date"))
                if not _dd:
                    _mr = _cached.get("mr", {})
                    if isinstance(_mr, dict):
                        _dd = (_mr.get("data", {}).get("market_overview", {})
                               .get("trade_date"))
            elif _fk == "global":
                _dd = (_cached.get("generated_at", "")[:10]
                       if isinstance(_cached.get("generated_at"), str) else None)

            _freshness[_fk] = {"label": _label, "status": "ok", "age_min": 0, "data_date": _dd}
            if _dd:
                _dates_seen.append(_dd)
        else:
            _freshness[_fk] = {"label": _label, "status": "stale", "age_min": -1, "data_date": None}

    # 权威日期源: ERP Timing 引擎的 current_snapshot.trade_date (数据交易日)
    if not _dates_seen:
        try:
            from erp_timing_engine import get_erp_engine
            _erp_sig = get_erp_engine().compute_signal()
            _erp_td = _erp_sig.get("current_snapshot", {}).get("trade_date")
            if _erp_td:
                _erp_td = str(_erp_td)[:10]
                _dates_seen.append(_erp_td)
                if "strategy" in _freshness:
                    _freshness["strategy"]["data_date"] = _erp_td
        except Exception:
            pass

    # ── 跨引擎日期一致性检查 ──
    _unique_dates = list(set(_dates_seen))
    _date_consistent = len(_unique_dates) <= 1
    _primary_date = _unique_dates[0] if _unique_dates else None

    # 用 last_update 时间戳计算各引擎数据年龄
    _last_upd = cache_manager.get_json("last_update")
    if _last_upd and isinstance(_last_upd, (int, float)):
        _age = max(0, int((_now_ts - _last_upd) / 60))  # V22.0 O3: 防时钟偏差产生负值
        for _fk2 in _freshness:
            if _freshness[_fk2]["status"] == "ok":
                _freshness[_fk2]["age_min"] = _age

    # V22.0: 信号半衰期 — 各引擎数据年龄映射为可靠性系数 (放射性衰变模型)
    # 半衰期定义: 经过此天数后, 信号可靠性降至 50%
    _DECAY_HALF_LIVES = {
        "aiae": 15,   # 月频数据, 缓慢衰减
        "erp": 3,     # 日频, 中等衰减 (ERP 信号本身是慢变量)
        "vix": 1,     # 实时数据, 快速衰减
        "mr": 2,      # 日频, 中等衰减
    }
    _DECAY_FRESHNESS_MAP = {
        "aiae": "aiae",
        "erp": "strategy",
        "vix": "dashboard",
        "mr": "strategy",
    }
    _signal_decay = {}
    for _eng_key, _hl_days in _DECAY_HALF_LIVES.items():
        _fk = _DECAY_FRESHNESS_MAP.get(_eng_key, _eng_key)
        _f = _freshness.get(_fk, {})
        _age_min = _f.get("age_min", -1)
        if _age_min >= 0:
            _age_days = _age_min / (60 * 24)
            _reliability = round(0.5 ** (_age_days / _hl_days), 3)
            _signal_decay[_eng_key] = {
                "age_min": _age_min,
                "half_life_hours": _hl_days * 24,
                "reliability": _reliability,
                "label": {"aiae": "AIAE", "erp": "ERP", "vix": "VIX", "mr": "MR"}.get(_eng_key, _eng_key),
            }
        else:
            _signal_decay[_eng_key] = {
                "age_min": -1,
                "half_life_hours": _hl_days * 24,
                "reliability": 0.0,
                "label": {"aiae": "AIAE", "erp": "ERP", "vix": "VIX", "mr": "MR"}.get(_eng_key, _eng_key),
            }

    # V22.0: 合规检查 (在 return 前计算, 内联到 dict)
    _compliance = {"status": "unknown", "summary": "合规检查不可用", "checks": []}
    try:
        from engines.compliance_engine import run_compliance_check
        _pos_target = action_plan.get("position_target", 55)
        _pos_current = snapshot.get("suggested_position", 55)
        _direction = "increase" if _pos_target > _pos_current + 3 \
            else ("decrease" if _pos_target < _pos_current - 3 else "hold")
        _ctx = {"direction": _direction, "jcs_level": jcs.get("level"), "jcs_score": jcs.get("score")}
        _compliance = run_compliance_check(snapshot, context=_ctx)
    except Exception as e:
        logger.debug("合规检查异常: %s", e)

    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "snapshot": snapshot,
        "conflicts": conflicts,
        "jcs": jcs,
        "action_plan": action_plan,
        "alerts": generate_alerts(snapshot),
        "scenarios": {k: {"name": v["name"], "desc": v["desc"], "icon": v["icon"], "severity": v["severity"]}
                      for k, v in SCENARIOS.items()},
        "global_temperature": global_temp,
        "data_freshness": _freshness,
        "signal_decay": _signal_decay,
        "data_date": _primary_date,
        "date_consistent": _date_consistent,
        "compliance": _compliance,
        # V27.1: 权重后端统一下发 (消除前后端硬编码不同步问题)
        "engine_meta": {
            k: {"weight": round(w * 100, 1)}
            for k, w in _JCS_WEIGHTS.items()
        },
    }


def log_daily_decision():
    """每日收盘快照写入 SQLite (由 warmup_pipeline 调用)"""
    from services import db as ac_db

    snapshot = _build_snapshot_from_cache()
    if not snapshot.get("aiae_regime"):
        logger.warning("决策快照跳过: 缓存数据不完整")
        return

    jcs = compute_jcs(snapshot)
    conflicts = compute_conflict_matrix(snapshot)

    data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "aiae_regime": snapshot.get("aiae_regime"),
        "aiae_v1": snapshot.get("aiae_v1"),
        "erp_score": snapshot.get("erp_score"),
        "erp_val": snapshot.get("erp_val"),
        "vix_val": snapshot.get("vix_val"),
        "mr_regime": snapshot.get("mr_regime"),
        "hub_composite": snapshot.get("hub_composite"),
        "jcs_score": jcs["score"],
        "jcs_level": jcs["level"],
        "suggested_position": snapshot.get("suggested_position"),
        "conflict_count": conflicts["conflict_count"],
        "degraded_modules": ",".join(snapshot.get("degraded_modules", [])) if isinstance(snapshot.get("degraded_modules"), list) else str(snapshot.get("degraded_modules", "")),
        # V25.3: 影子模式 + 多资产信号
        "jcs_v4_score": jcs.get("shadow", {}).get("v4_score"),
        "jcs_v6_score": jcs.get("shadow", {}).get("v6_score"),
        "jcs_shadow_delta": jcs.get("shadow", {}).get("delta"),
        "gold_signal": snapshot.get("gold_signal"),
        "bond_signal": snapshot.get("bond_signal"),
        # V26: Signal Conviction Model 影子数据
        "jcs_v26_score": jcs.get("shadow", {}).get("v26_score"),
        "delta_v26": jcs.get("shadow", {}).get("delta_v26"),
    }

    ac_db.upsert_decision_log(data)
    ac_db.cleanup_old_decisions(365)

    shadow = jcs.get("shadow", {})
    logger.info("决策快照存档: JCS=%.1f (%s) v26=%.1f delta=%.1f conflicts=%d pos=%s%%",
                jcs["score"], jcs["level"],
                shadow.get("v26_score", 0), shadow.get("delta", 0),
                conflicts["conflict_count"],
                snapshot.get("suggested_position", "?"))



def get_hub_data_with_events() -> dict:
    """
    get_hub_data 的增强版: 额外检测市场事件并附加事件列表。
    供 API 直接调用以原子化获取决策中枢 + 事件。
    """
    result = get_hub_data()

    try:
        snapshot = result.get("snapshot", {})
        if snapshot:
            events = detect_market_events(snapshot)
            result["market_events"] = get_recent_events(10)
            result["new_events_count"] = len(events)
    except Exception as e:
        logger.debug("事件检测异常: %s", e)
        result["market_events"] = []
        result["new_events_count"] = 0

    return result
