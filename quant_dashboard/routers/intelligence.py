"""
AlphaCore · NLP 情报 API 路由 (P2-C)
======================================
/api/v1/intelligence/scan      POST  手动触发新闻扫描
/api/v1/intelligence/latest    GET   获取最新情报
/api/v1/intelligence/history   GET   查询历史事件
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Query
from typing import Optional
from services.logger import get_logger
from services import db as ac_db

logger = get_logger("intelligence.api")
router = APIRouter(prefix="/api/v1/intelligence", tags=["Intelligence"])

_nlp_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nlp")


@router.post("/scan")
async def trigger_scan():
    """手动触发 NLP 新闻扫描 (非阻塞, 后台执行)"""
    from engines.news_intelligence import scan_news

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_nlp_executor, scan_news)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error("[NLP API] 扫描异常: %s", e)
        return {"status": "error", "message": str(e)}


@router.get("/latest")
async def get_latest():
    """获取最新情报 (缓存优先)"""
    from engines.news_intelligence import get_latest_intelligence

    try:
        result = get_latest_intelligence()
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/history")
async def get_history(
    category: Optional[str] = Query(None, description="筛选: macro/industry/stock/risk"),
    limit: int = Query(20, ge=1, le=100),
):
    """查询历史事件"""
    try:
        events = ac_db.get_news_events(category=category, limit=limit)
        return {"status": "success", "data": events, "total": len(events)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
