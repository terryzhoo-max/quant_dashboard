"""
AlphaCore · 动态事件驱动信号引擎
==================================
从 decision_engine.py 拆分 (P2-A)

对比当前快照与上一次快照, 检测 VIX/AIAE/MR/ERP 突变事件,
自动运行冲击传播并记录事件日志。

公开 API:
  - detect_market_events(current_snapshot) → list
  - get_recent_events(limit) → list
"""

import os
import json
import threading
from datetime import datetime, timedelta

from services.logger import get_logger
from dashboard_modules.decision.jcs import _REGIME_CN_MAP, compute_jcs
from dashboard_modules.decision.scenarios import run_shock_simulation

logger = get_logger("ac.decision.events")

_EVENT_LOG_PATH = "data_lake/market_events.json"
_SNAPSHOT_PATH = "data_lake/event_last_snapshot.json"
_MAX_EVENTS = 50

# V22.2: 事件冷却期 (小时) — 同类事件在 N 小时内不重复触发
_EVENT_COOLDOWNS = {
    "vix_spike": 4,
    "aiae_regime_change": 8,
    "mr_regime_change": 8,
    "erp_extreme": 12,
}


def _check_event_cooldown(event_type: str, events_log: list) -> bool:
    """检查事件是否在冷却期内。返回 True = 冷却中, 应跳过。"""
    cooldown_hours = _EVENT_COOLDOWNS.get(event_type, 6)
    for evt in reversed(events_log):
        if evt.get("type") == event_type:
            try:
                last_time = datetime.fromisoformat(evt["detected_at"])
                if datetime.now() - last_time < timedelta(hours=cooldown_hours):
                    return True
            except (ValueError, KeyError):
                pass
            break
    return False


def _load_last_snapshot() -> dict:
    """加载上一次保存的快照"""
    if os.path.exists(_SNAPSHOT_PATH):
        try:
            with open(_SNAPSHOT_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_last_snapshot(snapshot: dict):
    """保存当前快照供下次对比"""
    try:
        payload = {
            "timestamp": datetime.now().isoformat(),
            "aiae_regime": snapshot.get("aiae_regime"),
            "aiae_v1": snapshot.get("aiae_v1"),
            "erp_score": snapshot.get("erp_score"),
            "erp_val": snapshot.get("erp_val"),
            "vix_val": snapshot.get("vix_val"),
            "mr_regime": snapshot.get("mr_regime"),
        }
        os.makedirs(os.path.dirname(_SNAPSHOT_PATH), exist_ok=True)
        with open(_SNAPSHOT_PATH, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("保存事件快照失败: %s", e)


def _load_event_log() -> list:
    """加载事件日志"""
    if os.path.exists(_EVENT_LOG_PATH):
        try:
            with open(_EVENT_LOG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_event_log(events: list):
    """保存事件日志 (保留最近 MAX_EVENTS 条)"""
    try:
        os.makedirs(os.path.dirname(_EVENT_LOG_PATH), exist_ok=True)
        trimmed = events[-_MAX_EVENTS:]
        with open(_EVENT_LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("保存事件日志失败: %s", e)


def detect_market_events(current_snapshot: dict) -> list:
    """
    对比当前快照与上次快照, 检测市场突变事件。

    检测规则:
      1. VIX 跳变: |Δ| > 5 或 |Δ%| > 25%
      2. AIAE regime 变化
      3. MR regime 变化
      4. ERP 极端: 突破 6.5% 或跌破 3%
      5. JCS 跨级: high↔medium↔low
    """
    prev = _load_last_snapshot()
    if not prev:
        _save_last_snapshot(current_snapshot)
        return []

    existing_log = _load_event_log()
    events = []
    now_ts = datetime.now().isoformat()

    curr_vix = current_snapshot.get("vix_val") or 20
    prev_vix = prev.get("vix_val") or 20
    curr_aiae_r = current_snapshot.get("aiae_regime") or 3
    prev_aiae_r = prev.get("aiae_regime") or 3
    curr_mr = current_snapshot.get("mr_regime") or "RANGE"
    prev_mr = prev.get("mr_regime") or "RANGE"
    curr_erp = current_snapshot.get("erp_val") or 4.5
    prev_erp = prev.get("erp_val") or 4.5

    # ── 1. VIX 跳变 ──
    vix_delta = curr_vix - prev_vix
    vix_delta_pct = (curr_vix - prev_vix) / max(prev_vix, 1) * 100
    if abs(vix_delta) > 5 or abs(vix_delta_pct) > 25:
        if not _check_event_cooldown("vix_spike", existing_log):
            severity = "extreme" if abs(vix_delta) > 10 else ("high" if abs(vix_delta) > 7 else "medium")
            direction = "飙升" if vix_delta > 0 else "骤降"
            events.append({
                "type": "vix_spike", "severity": severity, "icon": "🌪️",
                "title": f"VIX {direction}",
                "detail": f"VIX {prev_vix:.1f} → {curr_vix:.1f} (Δ{vix_delta:+.1f}, {vix_delta_pct:+.0f}%)",
                "detected_at": now_ts,
                "auto_scenario": "vix_explosion" if vix_delta > 0 else None,
            })
        else:
            logger.debug("事件冷却中 [vix_spike]: %dh 内已触发", _EVENT_COOLDOWNS.get('vix_spike', 4))

    # ── 2. AIAE regime 变化 ──
    if curr_aiae_r != prev_aiae_r:
        if not _check_event_cooldown("aiae_regime_change", existing_log):
            direction = "升温" if curr_aiae_r > prev_aiae_r else "降温"
            severity = "high" if abs(curr_aiae_r - prev_aiae_r) >= 2 else "medium"
            events.append({
                "type": "aiae_regime_change", "severity": severity, "icon": "🌡️",
                "title": f"AIAE Regime {direction}",
                "detail": f"R{prev_aiae_r}({_REGIME_CN_MAP.get(prev_aiae_r, '?')}) → R{curr_aiae_r}({_REGIME_CN_MAP.get(curr_aiae_r, '?')})",
                "detected_at": now_ts,
                "auto_scenario": "aiae_overheat_v" if curr_aiae_r >= 4 else None,
            })
        else:
            logger.debug("事件冷却中 [aiae_regime_change]: %dh 内已触发", _EVENT_COOLDOWNS.get('aiae_regime_change', 8))

    # ── 3. MR regime 变化 ──
    if curr_mr != prev_mr:
        if not _check_event_cooldown("mr_regime_change", existing_log):
            severity = "high" if curr_mr in ("BEAR", "CRASH") else "medium"
            events.append({
                "type": "mr_regime_change", "severity": severity, "icon": "📉",
                "title": "MR 技术面切换",
                "detail": f"{prev_mr} → {curr_mr}",
                "detected_at": now_ts, "auto_scenario": None,
            })
        else:
            logger.debug("事件冷却中 [mr_regime_change]: %dh 内已触发", _EVENT_COOLDOWNS.get('mr_regime_change', 8))

    # ── 4. ERP 极端 ──
    if (curr_erp > 6.5 and prev_erp <= 6.5) or (curr_erp < 3.0 and prev_erp >= 3.0):
        if not _check_event_cooldown("erp_extreme", existing_log):
            direction = "极度低估" if curr_erp > 6.5 else "极度高估"
            events.append({
                "type": "erp_extreme", "severity": "high", "icon": "📊",
                "title": f"ERP {direction}",
                "detail": f"ERP {prev_erp:.2f}% → {curr_erp:.2f}%",
                "detected_at": now_ts,
                "auto_scenario": "erp_extreme_bull" if curr_erp > 6.5 else None,
            })
        else:
            logger.debug("事件冷却中 [erp_extreme]: %dh 内已触发", _EVENT_COOLDOWNS.get('erp_extreme', 12))

    # ── 保存快照 ──
    _save_last_snapshot(current_snapshot)

    if not events:
        return []

    # ── JCS delta 补全 ──
    try:
        jcs_before = compute_jcs(prev).get("score")
        jcs_after = compute_jcs(current_snapshot).get("score")
    except Exception:
        jcs_before, jcs_after = None, None

    for evt in events:
        evt["jcs_before"] = jcs_before
        evt["jcs_after"] = jcs_after
        evt["jcs_delta"] = round(jcs_after - jcs_before, 1) if jcs_before is not None and jcs_after is not None else None

    # ── 自动冲击传播 ──
    for evt in events:
        scenario_id = evt.get("auto_scenario")
        if scenario_id:
            try:
                shock_result = run_shock_simulation(scenario_id)
                if shock_result.get("status") == "success":
                    evt["shock_result"] = {
                        "jcs_before": shock_result["jcs_before"]["score"],
                        "jcs_after": shock_result["jcs_after"]["score"],
                        "impact": shock_result.get("impact_summary", []),
                    }
            except Exception as e:
                logger.debug("事件自动冲击传播失败 (%s): %s", evt["type"], e)

    # ── 持久化 ──
    existing_log.extend(events)
    _save_event_log(existing_log)

    # ── 高严重度事件推送 ──
    push_events = [e for e in events if e["severity"] in ("extreme", "high")]
    if push_events:
        def _push():
            try:
                from services.alert_monitor import _push_all_channels
                alerts = [{
                    "icon": e["icon"],
                    "title": e["title"],
                    "detail": e["detail"] + (f" | JCS {e['jcs_before']:.0f}→{e['jcs_after']:.0f}" if e.get("jcs_before") is not None else ""),
                    "severity": e["severity"],
                } for e in push_events]
                _push_all_channels(alerts)
            except Exception as ex:
                logger.debug("事件推送异常: %s", ex)
        threading.Thread(target=_push, daemon=True).start()

    return events


def get_recent_events(limit: int = 10) -> list:
    """获取最近的市场事件 (供 API)"""
    events = _load_event_log()
    return events[-limit:][::-1]
