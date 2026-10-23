"""AlphaCore 持仓跟踪止盈 + 历史成交导入 API

GET  /api/v1/portfolio/trailing-stops            每只持仓的止损线 / 阶段 / 状态 / 指令 / 条件单
POST /api/v1/portfolio/trailing-stops/run        同步行情 + 重算 + 推送 (与 15:50 定时任务相同)
POST /api/v1/portfolio/trailing-stops/{code}/rebaseline   遗留持仓重新基准化 (必须填写理由)
POST /api/v1/portfolio/trailing-stops/{code}/sleeve       core / satellite
POST /api/v1/portfolio/trailing-stops/{code}/ack          台账外已执行的分批止盈手动确认
POST /api/v1/portfolio/trailing-stops/{code}/anchor       人工设定建仓日 (成交记录超出通达信 60 天导出范围时)
POST /api/v1/portfolio/trades/import             导入通达信历史成交 .txt (GBK/UTF-8, 幂等去重)
POST /api/v1/portfolio/trades/scan               扫描 data_lake/trade_imports 文件夹, 自动累积
GET  /api/v1/portfolio/trades                    成交台账
GET  /api/v1/portfolio/trades/review             已完成回合复盘 (最大浮盈/利润回吐/规则 vs 实际)
"""
import asyncio
import logging

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from models import response as R

router = APIRouter(prefix="/api/v1/portfolio", tags=["trailing-stop"])
logger = logging.getLogger("alphacore.trailing")

MAX_UPLOAD = 2 * 1024 * 1024


class ReasonBody(BaseModel):
    reason: str = ""


class SleeveBody(BaseModel):
    sleeve: str
    reason: str = ""


class AnchorBody(BaseModel):
    date: str = ""          # 空 = 恢复自动锚点
    reason: str = ""


class AckBody(BaseModel):
    stage: int
    note: str = ""


def _clear_cache():
    try:
        from services.cache_service import cache_manager
        cache_manager.delete("trailing_stop_report_full")
    except Exception:
        pass


@router.get("/trailing-stops")
async def get_trailing_stops():
    try:
        from services.trailing_stop_service import ensure_prices_async, get_report
        data = await asyncio.to_thread(get_report)        # 只读; 仅在出现未提交的新收盘时补跑日终
        # 缺行情 / 行情滞后的持仓 → 后台增量同步, 页面不等待
        data["price_sync"] = ensure_prices_async(data.get("price_sync_needed") or [])
        return R.ok(data)
    except Exception as e:
        logger.exception("trailing-stops failed")
        return R.error(str(e), "ERR_TRAILING")


@router.post("/trailing-stops/run")
async def run_trailing_stops():
    try:
        from services.trailing_stop_service import daily_job
        data = await asyncio.to_thread(daily_job)
        return R.ok(data, "已同步行情并重新计算")
    except Exception as e:
        logger.exception("trailing-stops run failed")
        return R.error(str(e), "ERR_TRAILING_RUN")


@router.post("/trailing-stops/{ts_code}/rebaseline")
async def post_rebaseline(ts_code: str, body: ReasonBody):
    try:
        from services.trailing_stop_service import rebaseline
        data = await asyncio.to_thread(rebaseline, ts_code, body.reason)
        _clear_cache()
        return R.ok(data, "已重新基准化 (已写入审计日志)")
    except ValueError as e:
        return R.error(str(e), "ERR_REBASELINE")
    except Exception as e:
        return R.error(str(e), "ERR_REBASELINE")


@router.post("/trailing-stops/{ts_code}/sleeve")
async def post_sleeve(ts_code: str, body: SleeveBody):
    try:
        from services.trailing_stop_service import set_sleeve
        data = await asyncio.to_thread(set_sleeve, ts_code, body.sleeve, body.reason)
        _clear_cache()
        return R.ok(data)
    except ValueError as e:
        return R.error(str(e), "ERR_SLEEVE")


@router.post("/trailing-stops/{ts_code}/anchor")
async def post_anchor(ts_code: str, body: AnchorBody):
    try:
        from services.trailing_stop_service import clear_anchor, set_anchor
        if not body.date.strip():
            data = await asyncio.to_thread(clear_anchor, ts_code)
            return R.ok(data, "已恢复自动锚点")
        data = await asyncio.to_thread(set_anchor, ts_code, body.date.strip(), body.reason)
        _clear_cache()
        return R.ok(data, "建仓日已设定 (已写入审计日志)")
    except ValueError as e:
        return R.error(str(e), "ERR_ANCHOR")


@router.post("/trades/scan")
async def scan_trades():
    try:
        from services.trade_import import scan_import_folder
        data = await asyncio.to_thread(scan_import_folder)
        _clear_cache()
        n = len(data.get("files", []))
        return R.ok(data, f"扫描 {n} 个新文件, 新增 {data.get('added', 0)} 笔" if n else "没有新的导出文件")
    except Exception as e:
        logger.exception("trade scan failed")
        return R.error(str(e), "ERR_TRADE_SCAN")


@router.post("/trailing-stops/{ts_code}/ack")
async def post_ack(ts_code: str, body: AckBody):
    try:
        from services.trailing_stop_service import ack_stage
        data = await asyncio.to_thread(ack_stage, ts_code, body.stage, body.note)
        _clear_cache()
        return R.ok(data)
    except Exception as e:
        return R.error(str(e), "ERR_ACK")


@router.post("/trades/import")
async def import_trades(file: UploadFile = File(...)):
    from services.trade_import import TradeImportError, import_trade_file, load_ledger, reconcile_positions
    try:
        raw = await file.read()
        if len(raw) > MAX_UPLOAD:
            return R.error(f"文件过大 ({len(raw) // 1024}KB > {MAX_UPLOAD // 1024}KB)", "ERR_FILE_TOO_LARGE")
        summary = await asyncio.to_thread(import_trade_file, raw, file.filename or "")
        # 导入后立即对账, 让用户看到哪些持仓锚点已精确定位
        try:
            from services.trailing_stop_service import STORE_PATH, _read_json
            store = _read_json(STORE_PATH, {}) or {}
            rec = reconcile_positions(load_ledger().get("trades", []), store.get("positions") or {},
                                      as_of=store.get("import_date"))
            summary["reconciliation"] = list(rec.values())
        except Exception as e:
            summary["reconciliation_error"] = str(e)
        _clear_cache()
        return R.ok(summary, f"新增 {summary['added']} 笔, 重复 {summary['duplicates']} 笔")
    except TradeImportError as e:
        return R.error(str(e), e.code)
    except Exception as e:
        logger.exception("trade import failed")
        return R.error(str(e), "ERR_TRADE_IMPORT")


@router.get("/trades")
async def get_trades(limit: int = 200):
    from services.trade_import import load_ledger
    try:
        led = load_ledger()
        trades = led.get("trades", [])
        return R.ok({"count": len(trades), "trades": trades[-max(1, min(limit, 2000)):][::-1],
                     "imports": led.get("imports", [])[-10:]})
    except Exception as e:
        return R.error(str(e), "ERR_TRADES")


@router.get("/trades/review")
async def get_trade_review():
    try:
        from services.trailing_stop_service import _market_context, build_review
        regime, _ = await asyncio.to_thread(_market_context)
        data = await asyncio.to_thread(build_review, regime=regime)
        return R.ok(data)
    except Exception as e:
        logger.exception("trade review failed")
        return R.error(str(e), "ERR_REVIEW")
