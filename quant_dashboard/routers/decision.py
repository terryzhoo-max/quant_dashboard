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
    """决策中枢全量数据 (矛盾检测 + JCS + 情景列表)"""
    from dashboard_modules.decision_engine import get_hub_data
    return get_hub_data()


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

