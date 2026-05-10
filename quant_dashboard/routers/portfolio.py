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

# V26.0: 统一持仓变更后缓存失效 (import / trade / reset 共用)
_PORTFOLIO_SWR_KEYS = ("swr_portfolio_risk", "swr_corr_matrix", "swr_compliance")
# Import/Reset 是全量覆盖操作, 额外清决策层缓存
_DECISION_SWR_KEYS = ("swr_decision_hub", "swr_risk_matrix", "swr_drift_status")


def _invalidate_portfolio_caches(full: bool = False):
    """清除持仓相关 SWR 缓存。full=True 时额外清决策中枢缓存。"""
    from services.cache_service import swr_clear
    for key in _PORTFOLIO_SWR_KEYS:
        swr_clear(key)
    if full:
        for key in _DECISION_SWR_KEYS:
            swr_clear(key)
        logger.info("[Cache] 全量持仓变更: 已失效 %d 个 SWR 缓存",
                    len(_PORTFOLIO_SWR_KEYS) + len(_DECISION_SWR_KEYS))


@router.get("/portfolio/valuation")
async def get_portfolio_valuation():
    try:
        engine = get_portfolio_engine()
        return R.ok(engine.get_valuation())
    except Exception as e:
        return R.error(str(e), "ERR_VALUATION")

@router.get("/portfolio/risk")
async def get_portfolio_risk():
    """V25.0: SWR 缓存 (5min/30min), 交易后自动失效"""
    from services.cache_service import stale_while_revalidate

    def _compute():
        engine = get_portfolio_engine()
        return R.ok(engine.calculate_risk_metrics())

    return stale_while_revalidate("swr_portfolio_risk", _compute, fresh_ttl=300, stale_ttl=1800)

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
            # V26.0: 交易成功后，失效持仓相关 SWR 缓存
            _invalidate_portfolio_caches(full=False)
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
            # V26.0: 全量导入后失效所有持仓+决策缓存 (影响面远大于单笔交易)
            _invalidate_portfolio_caches(full=True)
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
        # V26.0: 清零后失效所有缓存
        _invalidate_portfolio_caches(full=True)
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
