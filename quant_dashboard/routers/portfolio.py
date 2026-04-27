"""AlphaCore 投资组合管理 API — V15.1 标准化响应"""
import asyncio
import traceback
import logging
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, UploadFile, File

from models.schemas import TradeRequest
from models import response as R
from portfolio_engine import get_portfolio_engine
from services import db as ac_db

router = APIRouter(prefix="/api/v1", tags=["portfolio"])
logger = logging.getLogger("alphacore.portfolio")
executor = ThreadPoolExecutor(max_workers=4)


@router.get("/portfolio/valuation")
async def get_portfolio_valuation():
    try:
        engine = get_portfolio_engine()
        return R.ok(engine.get_valuation())
    except Exception as e:
        return R.error(str(e), "ERR_VALUATION")

@router.get("/portfolio/risk")
async def get_portfolio_risk():
    try:
        engine = get_portfolio_engine()
        return R.ok(engine.calculate_risk_metrics())
    except Exception as e:
        return R.error(str(e), "ERR_RISK")

@router.get("/portfolio/history")
async def get_portfolio_history():
    try:
        engine = get_portfolio_engine()
        return R.ok(engine.get_trade_history(30))
    except Exception as e:
        return R.error(str(e), "ERR_HISTORY")

@router.get("/portfolio/nav")
async def get_portfolio_nav():
    try:
        engine = get_portfolio_engine()
        return R.ok(engine.get_nav_history(120))
    except Exception as e:
        return R.error(str(e), "ERR_NAV")

@router.get("/portfolio/snapshots")
async def get_portfolio_snapshots():
    """获取组合每日净值快照 (SQLite, Batch 11)"""
    try:
        data = ac_db.get_portfolio_snapshots(90)
        return R.ok(data, f"{len(data)} snapshots")
    except Exception as e:
        return R.error(str(e), "ERR_SNAPSHOTS")

@router.post("/portfolio/trade")
async def execute_trade(req: TradeRequest):
    try:
        if req.price <= 0:
            return R.error("价格必须大于 0", "ERR_INVALID_PRICE")
        if req.amount <= 0:
            return R.error("数量必须大于 0", "ERR_INVALID_AMOUNT")
        if req.action not in ("buy", "sell"):
            return R.error("操作类型必须为 buy 或 sell", "ERR_INVALID_ACTION")
        if not req.ts_code or len(req.ts_code.strip()) < 3:
            return R.error("请输入有效的证券代码", "ERR_INVALID_CODE")

        engine = get_portfolio_engine()
        if req.action == "buy":
            success, msg = engine.add_position(req.ts_code.strip(), req.amount, req.price, req.name.strip())
        else:
            success, msg = engine.reduce_position(req.ts_code.strip(), req.amount, req.price)

        if success:
            return R.ok(message=msg)
        else:
            return R.error(msg, "ERR_TRADE_REJECTED")
    except Exception as e:
        return R.error(str(e), "ERR_TRADE")

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
        if result["success"]:
            return R.ok(result)
        else:
            return R.error("导入解析失败", "ERR_IMPORT", data=result)
    except Exception as e:
        traceback.print_exc()
        return R.error(str(e), "ERR_IMPORT")

@router.post("/portfolio/reset")
async def reset_portfolio():
    """清零组合: 清除所有持仓和现金"""
    try:
        engine = get_portfolio_engine()
        result = engine.reset_portfolio()
        return R.ok(result)
    except Exception as e:
        return R.error(str(e), "ERR_RESET")

@router.post("/portfolio/sync")
async def sync_portfolio_prices():
    """同步持仓行情: 从 Tushare 拉取最新日线数据到 data_lake"""
    try:
        engine = get_portfolio_engine()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, engine.sync_prices)
        return R.ok(result)
    except Exception as e:
        logger.error(f"[Portfolio Sync] Error: {traceback.format_exc()}")
        return R.error(str(e), "ERR_SYNC")
