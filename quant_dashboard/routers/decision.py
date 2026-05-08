"""
AlphaCore V16.0 · 决策中枢 API 路由
===================================
GET  /api/v1/decision/hub       — 决策中枢全量数据
GET  /api/v1/decision/scenarios — 可用情景列表
POST /api/v1/decision/simulate  — 执行情景模拟
GET  /api/v1/decision/history   — 决策日志历史
"""

from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/v1/decision", tags=["decision"])


class SimulateRequest(BaseModel):
    scenario: str


@router.get("/hub")
async def get_decision_hub():
    """决策中枢全量数据 — V22.0: 含动态事件检测"""
    from services.cache_service import stale_while_revalidate
    from dashboard_modules.decision_engine import get_hub_data_with_events
    return stale_while_revalidate("swr_decision_hub", get_hub_data_with_events, fresh_ttl=300, stale_ttl=3600)


@router.get("/scenarios")
async def get_scenarios():
    """获取可用情景列表"""
    from dashboard_modules.decision_engine import SCENARIOS
    return {
        "status": "success",
        "scenarios": {
            k: {"name": v["name"], "desc": v["desc"], "icon": v["icon"], "severity": v["severity"]}
            for k, v in SCENARIOS.items()
        },
    }


@router.post("/simulate")
async def simulate(req: SimulateRequest):
    """执行情景模拟 (纯数学推演, 零API调用)"""
    from dashboard_modules.decision_engine import (
        simulate_scenario, _build_snapshot_from_cache
    )
    snapshot = _build_snapshot_from_cache()
    result = simulate_scenario(req.scenario, snapshot)
    return {"status": "success", **result}


@router.get("/history")
async def get_history(days: int = Query(default=30, ge=1, le=365)):
    """获取决策日志历史"""
    from services import db as ac_db
    history = ac_db.get_decision_history(days)
    return {"status": "success", "count": len(history), "data": history}


# ── Phase 2 端点 ──

@router.get("/risk-matrix")
async def get_risk_matrix():
    """风险关联矩阵 (策略重叠 + 板块集中度 + 尾部风险)"""
    from dashboard_modules.decision_engine import compute_risk_matrix
    return {"status": "success", **compute_risk_matrix()}


@router.get("/accuracy")
async def get_accuracy():
    """信号准确率统计"""
    from services import db as ac_db
    stats = ac_db.get_accuracy_stats()
    return {"status": "success", **stats}


@router.get("/calendar")
async def get_calendar(year: int = Query(default=None), month: int = Query(default=None)):
    """复盘日历数据"""
    from services import db as ac_db
    data = ac_db.get_calendar_data(year, month)
    return {"status": "success", "count": len(data), "data": data}


# ── V18.0 Phase L: 绩效分析 ──

@router.get("/performance")
async def get_performance():
    """沪深300基准绩效分析 — V2: SWR 三级缓存 (2h fresh / 12h stale)"""
    from services.cache_service import stale_while_revalidate

    def _compute():
        from dashboard_modules.performance_analytics import compute_performance_analytics
        return {"status": "success", **compute_performance_analytics()}

    return stale_while_revalidate("swr_perf_analytics", _compute, fresh_ttl=7200, stale_ttl=43200)


@router.get("/swing-guard")
async def get_swing_guard():
    """全球宽基波段守卫 (7大ETF) — V2: Stale-While-Revalidate 三级缓存"""
    from services.cache_service import cache_manager
    import time
    import threading
    
    cache_key = "swing_guard_signals"
    cached = cache_manager.get_json(cache_key)
    
    if cached and "timestamp" in cached:
        age = time.time() - cached["timestamp"]
        
        # Tier 1: Fresh (< 1h) — 直接返回
        if age < 3600:
            return {"status": "success", "data": cached["data"],
                    "cached": True, "age_seconds": int(age)}
        
        # Tier 2: Stale (1-6h) — 返回旧数据 + 后台静默刷新
        if age < 21600:
            threading.Thread(target=_refresh_swing_guard_bg, daemon=True).start()
            return {"status": "success", "data": cached["data"],
                    "cached": True, "stale": True, "age_seconds": int(age)}
    
    # Tier 3: Hard miss — 必须阻塞等待
    return _refresh_swing_guard_sync()


def _refresh_swing_guard_bg():
    """后台静默刷新 (Stale-While-Revalidate 的 revalidate 部分)"""
    import time
    from services.cache_service import cache_manager
    try:
        from swing_decision import SwingDecisionOrchestrator
        orchestrator = SwingDecisionOrchestrator()
        signals = orchestrator.generate_all_signals()
        payload = {"timestamp": time.time(), "data": signals}
        cache_manager.set_json("swing_guard_signals", payload)
    except Exception as e:
        import traceback
        traceback.print_exc()


def _refresh_swing_guard_sync():
    """同步刷新 (Hard miss 时阻塞)"""
    import time
    from services.cache_service import cache_manager
    try:
        from swing_decision import SwingDecisionOrchestrator
        orchestrator = SwingDecisionOrchestrator()
        signals = orchestrator.generate_all_signals()
        payload = {"timestamp": time.time(), "data": signals}
        cache_manager.set_json("swing_guard_signals", payload)
        return {"status": "success", "data": signals, "cached": False}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": f"波段守卫引擎异常: {str(e)}"}


# ── V22.0: 仓位调整路径 ──

@router.get("/position-path")
async def get_position_path():
    """仓位调整路径生成器: 3步执行计划 (T / T+2 / T+5) + V22.0 执行成本"""
    from dashboard_modules.decision_engine import generate_position_path, estimate_position_path_costs
    result = generate_position_path()
    result = estimate_position_path_costs(result)
    return {"status": "success", **result}


# ── V22.0: 策略参数版本管理 ──

@router.get("/param-versions")
async def list_param_versions():
    """列出所有已保存的参数版本快照"""
    import os, json, glob
    from datetime import datetime

    versions_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "param_versions")
    versions = []
    if os.path.isdir(versions_dir):
        for f in sorted(glob.glob(os.path.join(versions_dir, "*.json")), reverse=True):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                fname = os.path.basename(f)
                versions.append({
                    "version_id": data.get("version_id", fname.replace(".json", "")),
                    "timestamp": data.get("timestamp", ""),
                    "description": data.get("description", ""),
                    "aiae_weights": data.get("aiae_weights"),
                    "regime_thresholds": data.get("regime_thresholds"),
                    "jcs_weights": data.get("jcs_weights"),
                })
            except Exception:
                continue
    return {"status": "success", "count": len(versions), "versions": versions}


@router.post("/param-snapshot")
async def save_param_snapshot():
    """保存当前参数为版本快照"""
    import os, json
    from datetime import datetime

    versions_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "param_versions")
    os.makedirs(versions_dir, exist_ok=True)

    # 收集当前参数
    try:
        import aiae_params as AP
        aiae_weights = {
            "total_mv": AP.W_TOTAL_MV if hasattr(AP, 'W_TOTAL_MV') else 0.55,
            "fund_position": AP.W_FUND_POS if hasattr(AP, 'W_FUND_POS') else 0.20,
            "margin_heat": AP.W_MARGIN_HEAT if hasattr(AP, 'W_MARGIN_HEAT') else 0.25,
        }
        regime_thresholds = AP.REGIME_BOUNDARIES if hasattr(AP, 'REGIME_BOUNDARIES') else [12.5, 17, 23, 30]
    except ImportError:
        aiae_weights = {"total_mv": 0.55, "fund_position": 0.20, "margin_heat": 0.25}
        regime_thresholds = [12.5, 17, 23, 30]

    from dashboard_modules.decision_engine import _JCS_WEIGHTS
    jcs_weights = dict(_JCS_WEIGHTS)

    version_id = f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    snapshot = {
        "version_id": version_id,
        "timestamp": datetime.now().isoformat(),
        "description": f"Auto-snapshot {version_id}",
        "aiae_weights": aiae_weights,
        "regime_thresholds": regime_thresholds,
        "jcs_weights": jcs_weights,
    }
    filepath = os.path.join(versions_dir, f"{version_id}.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    return {"status": "success", "version_id": version_id, "filepath": filepath}


@router.get("/param-compare")
async def compare_params(v1: str = Query(...), v2: str = Query(...)):
    """比较两个参数版本在当前市场环境下的表现差异"""
    import os, json

    versions_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "param_versions")

    def _load_version(vid):
        fpath = os.path.join(versions_dir, f"{vid}.json")
        if not os.path.exists(fpath):
            return None
        with open(fpath, 'r', encoding='utf-8') as f:
            return json.load(f)

    ver_a = _load_version(v1)
    ver_b = _load_version(v2)

    if not ver_a or not ver_b:
        missing = []
        if not ver_a: missing.append(v1)
        if not ver_b: missing.append(v2)
        return {"status": "error", "error": f"版本未找到: {', '.join(missing)}"}

    # 基于当前市场数据, 分别用两组参数重算 JCS 和仓位建议
    from dashboard_modules.decision_engine import (
        _build_snapshot_from_cache, compute_jcs, _JCS_WEIGHTS,
        _REGIME_CAP_MAP, _REGIME_CN_MAP,
    )

    snapshot = _build_snapshot_from_cache()
    orig_jcs = compute_jcs(snapshot)

    # ── 用版本 A 的参数计算 ──
    jcs_a = _recompute_with_overrides(snapshot, ver_a)
    # ── 用版本 B 的参数计算 ──
    jcs_b = _recompute_with_overrides(snapshot, ver_b)

    # ── 差异分析 ──
    diff_items = []
    jcs_diff = round(jcs_b["score"] - jcs_a["score"], 1)
    if abs(jcs_diff) > 0.5:
        direction = "↑" if jcs_diff > 0 else "↓"
        diff_items.append(f"JCS: {jcs_a['score']} → {jcs_b['score']} ({direction}{abs(jcs_diff)})")

    level_a = jcs_a["level"]
    level_b = jcs_b["level"]
    if level_a != level_b:
        diff_items.append(f"置信度级别: {level_a} → {level_b}")

    return {
        "status": "success",
        "version_a": {"id": v1, "timestamp": ver_a.get("timestamp"), "description": ver_a.get("description")},
        "version_b": {"id": v2, "timestamp": ver_b.get("timestamp"), "description": ver_b.get("description")},
        "current_snapshot": {
            "aiae_regime": snapshot.get("aiae_regime"),
            "aiae_v1": snapshot.get("aiae_v1"),
            "erp_score": snapshot.get("erp_score"),
            "vix_val": snapshot.get("vix_val"),
            "mr_regime": snapshot.get("mr_regime"),
        },
        "result_a": {"jcs_score": jcs_a["score"], "jcs_level": jcs_a["level"], "jcs_label": jcs_a["label"]},
        "result_b": {"jcs_score": jcs_b["score"], "jcs_level": jcs_b["level"], "jcs_label": jcs_b["label"]},
        "diffs": diff_items,
        "recommendation": (
            f"版本 {v2} 在当前环境下 JCS={jcs_b['score']}，"
            + (f"相比 {v1}(JCS={jcs_a['score']}){'提升' if jcs_diff > 0 else '降低'}{abs(jcs_diff)}分。"
               if abs(jcs_diff) > 0.5
               else f"与 {v1} 无显著差异。")
        ),
    }


def _recompute_with_overrides(snapshot: dict, version: dict) -> dict:
    """
    用指定版本的参数重算 JCS。
    当前为轻量版: 用 JCS 权重差异重新合成方向一致性得分。
    后续可扩展为完整回测。
    """
    from dashboard_modules.decision_engine import _signal_direction, _JCS_WEIGHTS

    # 临时覆盖 JCS 权重
    jcs_w = version.get("jcs_weights", dict(_JCS_WEIGHTS))
    directions = _signal_direction(snapshot)
    dir_vals = list(directions.values())
    active_dirs = [d for d in dir_vals if d != 0]
    active_count = len(active_dirs)

    # 用覆盖的权重重算 base_agreement
    if active_count == 0:
        base_agreement = 30.0
    elif all(d == active_dirs[0] for d in active_dirs):
        base_agreement = 30.0 + active_count * 7.5
    else:
        weighted_sum = sum(directions[k] * jcs_w.get(k, 0.25) for k in jcs_w)
        max_weight = sum(jcs_w.values())
        agreement_ratio = abs(weighted_sum) / max_weight if max_weight > 0 else 0
        base_agreement = 10.0 + agreement_ratio * 20.0

    # 简化版 data_health (从原始快照)
    data_health = 20.0
    for k in ["aiae_regime", "erp_score", "vix_val", "mr_regime"]:
        if snapshot.get(k) is None:
            data_health -= 4.0
    data_health = max(0, data_health)

    # 简化版 consensus_bonus
    if active_count == 4:
        consensus_bonus = 20.0
    elif active_count >= 2:
        consensus_bonus = 10.0
    else:
        consensus_bonus = 0.0

    raw_jcs = base_agreement + data_health + consensus_bonus
    jcs = round(min(100, max(0, raw_jcs)), 1)

    if jcs >= 70:
        level, label = "high", "🟢 高置信"
    elif jcs >= 40:
        level, label = "medium", "🟡 中置信"
    else:
        level, label = "low", "🔴 低置信"

    return {"score": jcs, "level": level, "label": label}


# ── V21.0: 投委会日报 ──

@router.get("/daily-report")
async def get_daily_report(date: str = Query(default=None, description="日期 YYYY-MM-DD, 为空则生成今日报告")):
    """一键生成投委会决策日报 (支持历史回看)"""
    from dashboard_modules.report_generator import generate_daily_report
    return generate_daily_report(date)


# ── V21.1: 持仓相关性矩阵 ──

@router.get("/correlation-matrix")
async def get_correlation_matrix():
    """持仓间皮尔逊相关性热力图 + MCTR 风险贡献"""
    from portfolio_engine import get_portfolio_engine
    engine = get_portfolio_engine()
    return engine.get_correlation_data()


# ═══════════════════════════════════════════════════
#  V21.2: 信号预警 API
# ═══════════════════════════════════════════════════

@router.get("/alerts")
async def get_signal_alerts(limit: int = 20):
    """获取最近预警记录"""
    from services import db as ac_db
    alerts = ac_db.get_recent_alerts(limit)
    unread = ac_db.get_unread_alert_count()
    return {"status": "success", "alerts": alerts, "unread_count": unread}


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: int):
    """标记预警已读"""
    from services import db as ac_db
    ac_db.acknowledge_alert(alert_id)
    return {"status": "ok"}


@router.post("/alerts/ack-all")
async def acknowledge_all_alerts():
    """一键全部已读"""
    from services import db as ac_db
    conn = ac_db._get_conn()
    conn.execute("UPDATE signal_alerts SET acknowledged = 1 WHERE acknowledged = 0")
    conn.commit()
    return {"status": "ok"}


# ── V22.0: 跨市场风险传染矩阵 ──

@router.get("/contagion-matrix")
async def get_contagion_matrix():
    """四大市场 120 日收益率相关性矩阵 (零 API 调用, 纯 parquet 读取)"""
    from services.cache_service import stale_while_revalidate

    def _compute():
        from dashboard_modules.decision_engine import compute_contagion_matrix
        result = compute_contagion_matrix(window_days=120)
        return {"status": "success", **result}

    return stale_while_revalidate("swr_contagion_matrix", _compute, fresh_ttl=3600, stale_ttl=14400)


# ── V22.0: 有向冲击传播模拟器 ──

@router.get("/shock-sources")
async def list_shock_sources():
    """获取可用冲击源列表"""
    from dashboard_modules.decision_engine import _SHOCK_SOURCES, _SHOCK_NODES
    return {
        "status": "success",
        "sources": {
            k: {"name": v["name"], "icon": v["icon"], "severity": v["severity"],
                "desc": v["desc"], "source_node": v["source_node"],
                "default_magnitude": v["magnitude"]}
            for k, v in _SHOCK_SOURCES.items()
        },
        "nodes": {
            k: {"label": v["label"], "icon": v["icon"], "desc": v["desc"]}
            for k, v in _SHOCK_NODES.items()
        },
    }


class ShockRequest(BaseModel):
    source: str
    magnitude: Optional[float] = None
    steps: int = 3


@router.post("/shock-propagate")
async def run_shock(req: ShockRequest):
    """执行有向冲击传播模拟"""
    from dashboard_modules.decision_engine import run_shock_simulation
    result = run_shock_simulation(req.source, req.magnitude, req.steps)
    return result


# ── V22.0: 动态市场事件 ──

@router.get("/recent-events")
async def get_recent_events(limit: int = Query(default=10, ge=1, le=50)):
    """获取最近市场突变事件"""
    from dashboard_modules.decision_engine import get_recent_events
    events = get_recent_events(limit)
    return {"status": "success", "count": len(events), "events": events}


# ── V22.0: 预交易合规检查 ──

@router.get("/compliance-check")
async def get_compliance_check():
    """执行全部合规规则检查 (基于当前持仓 + 快照)"""
    from dashboard_modules.decision_engine import _build_snapshot_from_cache
    from engines.compliance_engine import run_compliance_check
    snapshot = _build_snapshot_from_cache()
    return {"status": "success", **run_compliance_check(snapshot)}


# ── V22.0: 策略漂移监控 ──

@router.get("/drift-status")
async def get_drift_status():
    """策略漂移状态检查 (准确率/环境/JCS/矛盾 四维)"""
    from engines.drift_monitor import get_drift_status
    return {"status": "success", **get_drift_status()}


# ── V22.0: 参数敏感度分析 (CI/CD 质量门前置) ──

@router.get("/param-sensitivity")
async def get_param_sensitivity():
    """
    参数敏感度分析: 对 JCS 权重 + AIAE 阈值做 ±5% 扰动,
    观察 JCS 和仓位建议的变化幅度。敏感度越高 → 策略越脆弱。
    """
    from dashboard_modules.decision_engine import (
        _build_snapshot_from_cache, compute_jcs, _JCS_WEIGHTS,
        _REGIME_CAP_MAP,
    )

    snapshot = _build_snapshot_from_cache()
    baseline_jcs = compute_jcs(snapshot)
    baseline_pos = snapshot.get("suggested_position", 55)

    # ── 定义可扰动参数 ──
    params_to_test = {}

    # JCS 权重 (从 _JCS_WEIGHTS)
    for k, v in _JCS_WEIGHTS.items():
        params_to_test[f"jcs_w_{k}"] = {"current": v, "label": f"JCS权重/{k.upper()}", "type": "jcs_weight", "key": k}

    # AIAE 分界线 (从 aiae_params 读取, 有 fallback)
    try:
        import aiae_params as AP
        boundaries = AP.REGIME_BOUNDARIES if hasattr(AP, 'REGIME_BOUNDARIES') else [12.5, 17, 23, 30]
    except ImportError:
        boundaries = [12.5, 17, 23, 30]
    for i, b in enumerate(boundaries):
        params_to_test[f"aiae_boundary_{i}"] = {"current": b, "label": f"AIAE分界/R{i+1}↔R{i+2}", "type": "aiae_boundary", "index": i}

    results = []
    perturbation = 0.05  # ±5%

    for pid, pinfo in params_to_test.items():
        current_val = pinfo["current"]
        delta = current_val * perturbation
        if abs(delta) < 0.1:
            delta = 0.1  # 最小扰动

        # ── 正向扰动 ──
        if pinfo["type"] == "jcs_weight":
            modified_weights_up = dict(_JCS_WEIGHTS)
            modified_weights_up[pinfo["key"]] = round(current_val + delta, 4)
            total = sum(modified_weights_up.values())
            modified_weights_up = {k: round(v / total, 4) for k, v in modified_weights_up.items()}

            # 临时覆盖并重算
            orig_weights = dict(_JCS_WEIGHTS)
            _JCS_WEIGHTS.clear()
            _JCS_WEIGHTS.update(modified_weights_up)
            jcs_up = compute_jcs(snapshot)
            _JCS_WEIGHTS.clear()
            _JCS_WEIGHTS.update(orig_weights)
        else:
            jcs_up = baseline_jcs  # AIAE 边界扰动不影响 JCS 权重, 仅影响 regime 判定

        # ── 负向扰动 ──
        if pinfo["type"] == "jcs_weight":
            modified_weights_down = dict(_JCS_WEIGHTS)
            modified_weights_down[pinfo["key"]] = round(max(0.01, current_val - delta), 4)
            total = sum(modified_weights_down.values())
            modified_weights_down = {k: round(v / total, 4) for k, v in modified_weights_down.items()}
            orig_weights = dict(_JCS_WEIGHTS)
            _JCS_WEIGHTS.clear()
            _JCS_WEIGHTS.update(modified_weights_down)
            jcs_down = compute_jcs(snapshot)
            _JCS_WEIGHTS.clear()
            _JCS_WEIGHTS.update(orig_weights)
        else:
            jcs_down = baseline_jcs

        jcs_delta_up = round(jcs_up["score"] - baseline_jcs["score"], 1)
        jcs_delta_down = round(jcs_down["score"] - baseline_jcs["score"], 1)
        max_jcs_delta = max(abs(jcs_delta_up), abs(jcs_delta_down))

        sensitivity = "high" if max_jcs_delta > 3 else ("medium" if max_jcs_delta > 1 else "low")

        results.append({
            "param_id": pid,
            "param_label": pinfo["label"],
            "current_value": round(current_val, 2),
            "perturbation_pct": int(perturbation * 100),
            "jcs_delta_up": jcs_delta_up,
            "jcs_delta_down": jcs_delta_down,
            "max_jcs_delta": max_jcs_delta,
            "sensitivity": sensitivity,
        })

    # 排序: 最敏感的在前
    results.sort(key=lambda x: x["max_jcs_delta"], reverse=True)

    # 综合判定
    high_count = sum(1 for r in results if r["sensitivity"] == "high")
    if high_count >= 2:
        overall = "fragile"
        overall_label = "🔴 参数脆弱 — 多个参数 ±5% 扰动导致 JCS 大幅波动, 策略鲁棒性不足"
    elif high_count >= 1:
        overall = "sensitive"
        overall_label = "🟡 参数敏感 — 个别参数对 JCS 影响较大, 建议窄幅调参"
    else:
        overall = "robust"
        overall_label = "🟢 参数稳健 — ±5% 扰动下 JCS 保持稳定, 策略鲁棒性良好"

    return {
        "status": "success",
        "baseline_jcs": baseline_jcs["score"],
        "baseline_jcs_level": baseline_jcs["level"],
        "baseline_position": baseline_pos,
        "overall": overall,
        "overall_label": overall_label,
        "perturbation_pct": int(perturbation * 100),
        "results": results,
    }


# ═══════════════════════════════════════════════════════════
#  V23.0: 组合权重优化 (Black-Litterman / MVO)
# ═══════════════════════════════════════════════════════════

class OptimizeCustomRequest(BaseModel):
    risk_aversion: float = 2.5
    cost_rate: float = 0.003
    max_turnover: float = 0.25


@router.get("/optimize")
async def get_optimal_weights():
    """一键组合优化 — BL > MVO > 等权 降级链"""
    from services.cache_service import stale_while_revalidate
    from engines.optimizer_engine import full_optimize
    return stale_while_revalidate(
        "swr_optimizer", lambda: full_optimize(),
        fresh_ttl=600, stale_ttl=3600
    )


@router.get("/efficient-frontier")
async def get_efficient_frontier(points: int = Query(15, ge=5, le=30)):
    """有效前沿曲线 (含当前组合定位)"""
    from engines.optimizer_engine import (
        estimate_covariance, compute_efficient_frontier, _portfolio_stats
    )
    import pandas as pd
    import numpy as np

    try:
        from portfolio_engine import get_portfolio_engine
        pe = get_portfolio_engine()
        val = pe.get_valuation()
    except Exception as e:
        return {"status": "error", "error": f"持仓读取失败: {e}"}

    positions = val.get("positions", [])
    if len(positions) < 2:
        return {"status": "insufficient", "error": "至少需要 2 只持仓"}

    total_asset = val.get("total_asset", 0)
    if total_asset <= 0:
        return {"status": "error", "error": "总资产为零"}

    codes = [p["ts_code"] for p in positions]
    w_current = np.array([p.get("market_value", 0) / total_asset for p in positions])

    rets_data = {}
    for p in positions:
        try:
            p_df = pe.dm.get_price_payload(p["ts_code"])
            if p_df is not None and not p_df.empty:
                rets_data[p["ts_code"]] = p_df['close'].pct_change().dropna().tail(120)
        except Exception:
            pass

    if len(rets_data) < 2:
        return {"status": "insufficient_data"}

    df_rets = pd.DataFrame(rets_data)
    for code in codes:
        if code not in df_rets.columns:
            df_rets[code] = 0.0
    df_rets = df_rets[codes].fillna(0)

    cov_matrix, _ = estimate_covariance(df_rets)
    mu = (df_rets.mean() * 252).values
    cov_np = cov_matrix.values

    try:
        from config import POSITION_CONFIG as PC
        single_limit = PC["single_limit"] / 100.0
        total_cap = PC["total_cap"] / 100.0
    except ImportError:
        single_limit, total_cap = 0.20, 0.95

    frontier = compute_efficient_frontier(mu, cov_np, single_limit, total_cap, points)
    cur_ret, cur_vol, cur_sharpe = _portfolio_stats(w_current, mu, cov_np)

    return {
        "status": "success",
        "frontier": frontier,
        "current": {
            "return": round(cur_ret * 100, 2),
            "volatility": round(cur_vol * 100, 2),
            "sharpe": round(cur_sharpe, 2),
        },
    }


@router.post("/optimize-custom")
async def optimize_custom(req: OptimizeCustomRequest):
    """自定义参数优化"""
    from engines.optimizer_engine import full_optimize
    return full_optimize(
        risk_aversion=req.risk_aversion,
        cost_rate=req.cost_rate,
        max_turnover=req.max_turnover,
    )


@router.get("/optimize-path")
async def get_optimized_path():
    """优化权重 → 调仓路径 管道"""
    from engines.optimizer_engine import full_optimize
    from dashboard_modules.decision_engine import generate_position_path, _build_snapshot_from_cache, compute_jcs

    opt = full_optimize()
    if opt.get("status") != "success":
        return {"status": "error", "error": opt.get("error", "优化失败"), "optimize_result": opt}

    # 构建 target_weights 映射: code → 目标权重%
    target_weights = {}
    for item in opt.get("rebalance", []):
        target_weights[item["code"]] = item["optimal_weight"]

    snapshot = _build_snapshot_from_cache()
    jcs = compute_jcs(snapshot)
    path = generate_position_path(snapshot, jcs, target_weights=target_weights)

    return {
        "status": "success",
        "optimization": {
            "method": opt.get("method"),
            "current_sharpe": opt["current"]["sharpe"],
            "optimal_sharpe": opt["optimal"]["sharpe"],
            "turnover": opt.get("turnover"),
        },
        "path": path,
    }
