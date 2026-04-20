"""AlphaCore 投资组合管理 API — 从 main.py 提取"""
import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, UploadFile, File

from models.schemas import TradeRequest
from portfolio_engine import get_portfolio_engine

router = APIRouter(prefix="/api/v1", tags=["portfolio"])
executor = ThreadPoolExecutor(max_workers=4)


@router.get("/portfolio/valuation")
async def get_portfolio_valuation():
    try:
        engine = get_portfolio_engine()
        return {"status": "success", "data": engine.get_valuation()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/portfolio/risk")
async def get_portfolio_risk():
    try:
        engine = get_portfolio_engine()
        return {"status": "success", "data": engine.calculate_risk_metrics()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/portfolio/history")
async def get_portfolio_history():
    try:
        engine = get_portfolio_engine()
        return {"status": "success", "data": engine.get_trade_history(30)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/portfolio/nav")
async def get_portfolio_nav():
    try:
        engine = get_portfolio_engine()
        return {"status": "success", "data": engine.get_nav_history(120)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/portfolio/trade")
async def execute_trade(req: TradeRequest):
    try:
        if req.price <= 0:
            return {"status": "error", "message": "价格必须大于 0"}
        if req.amount <= 0:
            return {"status": "error", "message": "数量必须大于 0"}
        if req.action not in ("buy", "sell"):
            return {"status": "error", "message": "操作类型必须为 buy 或 sell"}
        if not req.ts_code or len(req.ts_code.strip()) < 3:
            return {"status": "error", "message": "请输入有效的证券代码"}

        engine = get_portfolio_engine()
        if req.action == "buy":
            success, msg = engine.add_position(req.ts_code.strip(), req.amount, req.price, req.name.strip())
        else:
            success, msg = engine.reduce_position(req.ts_code.strip(), req.amount, req.price)

        if success:
            return {"status": "success", "message": msg}
        else:
            return {"status": "error", "message": msg}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/portfolio/import")
async def import_portfolio(file: UploadFile = File(...)):
    """接收券商导出的 资金股份查询.txt，解析并覆盖当前持仓"""
    try:
        content = await file.read()
        text = None
        for enc in ['gbk', 'gb18030', 'utf-8']:
            try:
                text = content.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:
            text = content.decode('gbk', errors='replace')

        engine = get_portfolio_engine()
        result = engine.import_from_txt(text)
        return {"status": "success" if result["success"] else "error", "data": result}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

@router.post("/portfolio/reset")
async def reset_portfolio():
    """清零组合: 清除所有持仓和现金"""
    try:
        engine = get_portfolio_engine()
        result = engine.reset_portfolio()
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/portfolio/sync")
async def sync_portfolio_prices():
    """同步持仓行情: 从 Tushare 拉取最新日线数据到 data_lake"""
    try:
        engine = get_portfolio_engine()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, engine.sync_prices)
        return {"status": "success", "data": result}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}
