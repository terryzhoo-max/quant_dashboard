"""AlphaCore OMS 滑点归因 API — V26.0"""
import traceback
import logging
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from models import response as R
from services import db as ac_db

router = APIRouter(prefix="/api/v1", tags=["slippage"])
logger = logging.getLogger("alphacore.slippage")


# ── 请求模型 ──

class CreateOrderRequest(BaseModel):
    ts_code: str
    name: str = ""
    side: str  # buy / sell
    decision_price: Optional[float] = None
    exec_price: Optional[float] = None
    exec_amount: Optional[int] = None
    notes: str = ""


class FillOrderRequest(BaseModel):
    exec_price: float
    exec_amount: int
    arrival_price: Optional[float] = None
    commission: float = 0
    tax: float = 0
    notes: str = ""


# ── 查询端点 ──

@router.get("/slippage/summary")
async def get_slippage_summary():
    """滑点统计摘要 (面板总览)"""
    try:
        stats = ac_db.get_slippage_stats()
        return R.ok(stats)
    except Exception as e:
        return R.error(str(e), "ERR_SLIP_SUMMARY")


@router.get("/slippage/history")
async def get_slippage_history(days: int = 30):
    """滑点日度历史曲线"""
    try:
        data = ac_db.get_slippage_history(days)
        return R.ok(data, f"{len(data)} days")
    except Exception as e:
        return R.error(str(e), "ERR_SLIP_HISTORY")


@router.get("/slippage/orders")
async def get_execution_orders(days: int = 30, ts_code: str = None, status: str = None):
    """执行指令列表"""
    try:
        orders = ac_db.get_execution_orders(days=days, ts_code=ts_code, status=status)
        # 过滤掉系统指令, 只返回实际交易
        real = [o for o in orders if o.get("ts_code") not in ("PORTFOLIO", "IMPORT")]
        return R.ok(real, f"{len(real)} orders")
    except Exception as e:
        return R.error(str(e), "ERR_SLIP_ORDERS")


@router.get("/slippage/quality")
async def get_execution_quality():
    """EQS 执行质量评分"""
    try:
        from engines.slippage_engine import get_slippage_engine
        eqs = get_slippage_engine().get_execution_quality_score()
        return R.ok(eqs)
    except Exception as e:
        return R.error(str(e), "ERR_SLIP_EQS")


@router.get("/slippage/attribution")
async def get_attribution():
    """归因分解报告"""
    try:
        from engines.slippage_engine import get_slippage_engine
        report = get_slippage_engine().get_attribution_report()
        return R.ok(report)
    except Exception as e:
        return R.error(str(e), "ERR_SLIP_ATTR")


@router.get("/slippage/diagnose")
async def get_diagnosis():
    """智能诊断"""
    try:
        from engines.slippage_engine import get_slippage_engine
        findings = get_slippage_engine().diagnose()
        return R.ok(findings)
    except Exception as e:
        return R.error(str(e), "ERR_SLIP_DIAG")


# ── 写入端点 ──

@router.post("/slippage/orders")
async def create_order(req: CreateOrderRequest):
    """手动创建执行指令"""
    try:
        from engines.slippage_engine import get_slippage_engine
        se = get_slippage_engine()

        order_data = {
            "ts_code": req.ts_code.strip(),
            "name": req.name.strip(),
            "side": req.side,
            "decision_price": req.decision_price,
            "exec_price": req.exec_price,
            "exec_amount": req.exec_amount,
            "status": "filled" if req.exec_price else "pending",
            "notes": req.notes,
            "exec_source": "manual",
        }

        # 自动填充决策参考价
        if not req.decision_price:
            dp = se._get_prev_close(req.ts_code.strip())
            if dp:
                order_data["decision_price"] = dp

        # 自动填充到达价
        arrival = se._get_today_open(req.ts_code.strip())
        if arrival:
            order_data["arrival_price"] = arrival

        order_id = ac_db.create_execution_order(order_data)

        # 如果已有成交价, 立即归因
        if req.exec_price:
            se._compute_attribution(order_id)

        return R.ok({"order_id": order_id}, "指令已创建")
    except Exception as e:
        traceback.print_exc()
        return R.error(str(e), "ERR_SLIP_CREATE")


@router.put("/slippage/orders/{order_id}/fill")
async def fill_order(order_id: str, req: FillOrderRequest):
    """更新成交信息"""
    try:
        from engines.slippage_engine import get_slippage_engine

        existing = ac_db.get_execution_order_by_id(order_id)
        if not existing:
            return R.error(f"未找到指令 {order_id}", "ERR_NOT_FOUND")

        ac_db.update_execution_fill(order_id, {
            "exec_price": req.exec_price,
            "exec_amount": req.exec_amount,
            "arrival_price": req.arrival_price,
            "commission": req.commission,
            "tax": req.tax,
            "notes": req.notes,
            "status": "filled",
        })

        get_slippage_engine()._compute_attribution(order_id)
        return R.ok(message="成交信息已更新")
    except Exception as e:
        return R.error(str(e), "ERR_SLIP_FILL")


@router.post("/slippage/bootstrap")
async def bootstrap():
    """从历史交易回填执行记录"""
    try:
        from engines.slippage_engine import get_slippage_engine
        result = get_slippage_engine().bootstrap_from_history()
        return R.ok(result)
    except Exception as e:
        return R.error(str(e), "ERR_SLIP_BOOT")
