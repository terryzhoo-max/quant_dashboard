"""
AlphaCore · 策略 CI/CD API 路由 (P1-3)
========================================
/api/v1/ci/run         POST  手动触发 CI
/api/v1/ci/history     GET   查看历史 CI 记录
/api/v1/ci/latest/{s}  GET   某策略最近一次 CI
/api/v1/ci/accept/{id} POST  人工批准 REVIEW 状态
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from services.logger import get_logger
from services import db as ac_db

logger = get_logger("ci.api")
router = APIRouter(prefix="/api/v1/ci", tags=["CI/CD"])

_ci_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ci")


class CIRunRequest(BaseModel):
    strategy: str = "all"       # "all" | "mr" | "erp"
    regime: Optional[str] = None  # MR 专用: "BEAR" | "RANGE" | "BULL"


# ── POST /ci/run — 手动触发 CI ──
@router.post("/run")
async def trigger_ci(req: CIRunRequest):
    """
    手动触发 CI 管道 (非阻塞, 后台执行)
    注意: 全量优化耗时可能 5-30 分钟
    """
    from services.strategy_pipeline import run_full_ci, run_mr_ci, run_erp_ci

    def _run():
        if req.strategy == "all":
            return run_full_ci()
        elif req.strategy == "mr":
            return run_mr_ci(regime=req.regime)
        elif req.strategy == "erp":
            return run_erp_ci()
        else:
            raise ValueError(f"Unknown strategy: {req.strategy}")

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_ci_executor, _run)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error("[CI API] 执行异常: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /ci/history — 查看历史 ──
@router.get("/history")
async def get_ci_history(
    strategy: Optional[str] = Query(None, description="筛选策略: mr / erp"),
    limit: int = Query(20, ge=1, le=100),
):
    """获取 CI 运行历史"""
    try:
        rows = ac_db.get_ci_history(strategy=strategy, limit=limit)
        return {"status": "success", "data": rows, "total": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /ci/latest/{strategy} — 最近一次 CI ──
@router.get("/latest/{strategy}")
async def get_ci_latest(strategy: str):
    """获取某策略最近一次 CI 结果"""
    result = ac_db.get_ci_latest(strategy)
    if not result:
        return {"status": "success", "data": None, "message": f"无 {strategy} CI 记录"}
    return {"status": "success", "data": result}


# ── POST /ci/accept/{run_id} — 人工批准 ──
@router.post("/accept/{run_id}")
async def accept_ci_run(run_id: str):
    """
    人工批准 REVIEW 状态的 CI 运行
    仅 REVIEW 状态可被批准
    """
    # 查找记录
    rows = ac_db.get_ci_history(limit=100)
    target = next((r for r in rows if r.get("run_id") == run_id), None)

    if not target:
        raise HTTPException(status_code=404, detail=f"CI run {run_id} 不存在")

    if target.get("status") != "REVIEW":
        raise HTTPException(
            status_code=400,
            detail=f"仅 REVIEW 状态可被批准, 当前状态: {target.get('status')}"
        )

    ok = ac_db.update_ci_status(run_id, "ACCEPT")
    if not ok:
        raise HTTPException(status_code=500, detail="更新状态失败")

    logger.info("[CI] 人工批准: run_id=%s, strategy=%s", run_id, target.get("strategy"))
    return {"status": "success", "message": f"CI run {run_id} 已批准"}


# ── GET /ci/quality-gate — 质量门配置 ──
@router.get("/quality-gate")
async def get_quality_gate():
    """返回当前质量门阈值配置"""
    from services.strategy_pipeline import QUALITY_GATE
    return {"status": "success", "data": QUALITY_GATE}
