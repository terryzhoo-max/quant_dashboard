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
    """决策中枢全量数据 — V2: SWR 三级缓存 (5min fresh / 1h stale)"""
    from services.cache_service import stale_while_revalidate
    from dashboard_modules.decision_engine import get_hub_data
    return stale_while_revalidate("swr_decision_hub", get_hub_data, fresh_ttl=300, stale_ttl=3600)


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
