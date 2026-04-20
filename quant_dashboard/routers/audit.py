"""AlphaCore 审计/执行器 API — 从 main.py 提取"""
import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter

from audit_engine import run_full_audit

router = APIRouter(prefix="/api/v1", tags=["audit"])
executor = ThreadPoolExecutor(max_workers=4)


@router.get("/audit")
async def api_audit():
    """V4.0 五维系统审计 + Enforcer 执行 + 静音/降级"""
    try:
        report = await asyncio.get_event_loop().run_in_executor(
            executor, run_full_audit
        )
        return {"status": "ok", **report}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


@router.get("/audit/enforcer/status")
async def get_audit_enforcer_status():
    """获取执行器完整状态快照"""
    try:
        from audit_enforcer import get_enforcer_status
        return {"status": "ok", **get_enforcer_status()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/audit/enforcer/toggle")
async def toggle_audit_enforcer(enabled: bool = True):
    """开关执行器总开关"""
    try:
        from audit_enforcer import toggle_enforcer
        result = toggle_enforcer(enabled)
        return {"status": "ok", "enforcer_enabled": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/audit/mute")
async def set_audit_mute(minutes: int = 30, degraded: bool = False):
    """设置静音 (minutes=静音N分钟, degraded=降级模式)"""
    try:
        from audit_enforcer import set_mute
        result = set_mute(minutes=minutes, degraded=degraded)
        return {"status": "ok", "mute": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/audit/mute")
async def clear_audit_mute():
    """解除所有静音"""
    try:
        from audit_enforcer import clear_mute
        result = clear_mute()
        return {"status": "ok", "mute": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/audit/enforcer/log")
async def get_audit_enforcer_log(limit: int = 20):
    """获取执行器日志"""
    try:
        from audit_enforcer import get_enforcement_log
        logs = get_enforcement_log(limit)
        return {"status": "ok", "logs": logs}
    except Exception as e:
        return {"status": "error", "message": str(e)}
