# ── Windows 控制台 UTF-8 编码修复 (必须最先执行) ──
import sys, io
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

# ── 全局噪音抑制 (必须在所有第三方库 import 之前) ──
import warnings
warnings.filterwarnings("ignore", category=FutureWarning,
                        message=".*fillna with 'method' is deprecated.*")

import logging
# 抑制 Windows ProactorEventLoop 的 ConnectionResetError 无害噪音 (WinError 10054)
_proactor_logger = logging.getLogger("asyncio")
class _SuppressConnectionReset(logging.Filter):
    def filter(self, record):
        return "ConnectionResetError" not in record.getMessage()
_proactor_logger.addFilter(_SuppressConnectionReset())

import os as _env_os
import time
import threading
import uvicorn
from datetime import datetime
from contextlib import asynccontextmanager
from services.logger import get_logger

_logger = get_logger("main")

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from services.cache_service import cache_manager
from services.dashboard_builder import _hot_data_reactor_tick, _STRATEGY_LOCK
from services.warmup_pipeline import (
    warmup_erp_cache, warmup_aiae_cache, warmup_dashboard_cache,
    warmup_rates_cache, warmup_hk_erp_cache, warmup_hk_aiae_cache,
    warmup_global_aiae_cache,
    daily_warmup_callback, morning_warmup_callback, fred_daily_callback,
    us_aiae_warmup_callback, jp_aiae_warmup_callback, aaii_crawl_callback,
)
from aiae_engine import get_aiae_engine


# ═══════════════════════════════════════════════════════════════════
#  Lifespan (启动预热 + APScheduler)
# ═══════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """V3.0 Lifespan: 引入 APScheduler 替代粗糙的 threading.Timer"""
    # ── SQLite 初始化 + 旧 JSON 迁移 (Batch 10) ──
    from services import db as ac_db
    ac_db.init_db()
    ac_db.migrate_decision_log_v2()  # V16.0 Phase 2: 安全添加准确率字段
    mig = ac_db.migrate_from_json()
    _logger.info("SQLite 迁移完成 · trades=%d aiae=%d erp=%d", mig["trades"], mig["aiae"], mig["erp"])

    # Batch 11: 记录启动时间 (用于 uptime 计算)
    app.state.startup_time = time.time()

    # ── Startup Warmup (Threaded) ──
    threading.Thread(target=warmup_erp_cache, daemon=True).start()
    threading.Thread(target=warmup_rates_cache, daemon=True).start()
    threading.Thread(target=lambda: get_aiae_engine().generate_report(), daemon=True).start()
    threading.Thread(target=warmup_dashboard_cache, daemon=True).start()
    threading.Thread(target=warmup_global_aiae_cache, daemon=True).start()
    threading.Thread(target=warmup_hk_erp_cache, daemon=True).start()
    threading.Thread(target=warmup_hk_aiae_cache, daemon=True).start()

    # ── Init APScheduler ──
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    # 1. 盘中高频热点 (每2分钟)
    scheduler.add_job(_hot_data_reactor_tick, IntervalTrigger(seconds=120), id="hot_data")
    # 2. 定时收盘预热 15:35 (周一至周五)
    scheduler.add_job(daily_warmup_callback, CronTrigger(day_of_week='mon-fri', hour=15, minute=35), id="daily_warmup")
    # 3. 早间预热 08:30 (周一至周五)
    scheduler.add_job(morning_warmup_callback, CronTrigger(day_of_week='mon-fri', hour=8, minute=30), id="morning_warmup")
    # 4. FRED 利率更新 18:30 (周一至周五)
    scheduler.add_job(fred_daily_callback, CronTrigger(day_of_week='mon-fri', hour=18, minute=30), id="fred_daily")
    # 5. 美股 AIAE 06:30 (周二至周六, 适配美东盘后)
    scheduler.add_job(us_aiae_warmup_callback, CronTrigger(day_of_week='tue-sat', hour=6, minute=30), id="us_aiae")
    # 6. 日股 AIAE 15:30 (周一至周五)
    scheduler.add_job(jp_aiae_warmup_callback, CronTrigger(day_of_week='mon-fri', hour=15, minute=30), id="jp_aiae")
    # 7. AAII 情绪爬虫 每周五 09:00
    scheduler.add_job(aaii_crawl_callback, CronTrigger(day_of_week='fri', hour=9, minute=0), id="aaii_crawl")

    scheduler.start()
    app.state.scheduler = scheduler

    _logger.info("AlphaCore 服务启动完成 · APScheduler(Redis就绪) 已激活全自动数据流水线")
    yield
    # ── Shutdown ──
    scheduler.shutdown()
    _logger.info("AlphaCore 服务关闭，Scheduler 已终止")


# ═══════════════════════════════════════════════════════════════════
#  FastAPI App 创建 + 中间件
# ═══════════════════════════════════════════════════════════════════

app = FastAPI(title="AlphaCore Quant API", description="AlphaCore量化终端底层数据接口", lifespan=lifespan)

# ── Batch 6: CORS 白名单 (从环境变量读取, 不再硬编码) ──
_cors_env = _env_os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")
_CORS_ORIGINS = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Batch 6: API Key 认证中间件 (保护所有写入操作) ──
from services.auth_middleware import ApiKeyMiddleware
app.add_middleware(ApiKeyMiddleware)

# ── Batch 5: GZip 压缩 (JS/CSS/HTML 压缩率约 75%) ──
app.add_middleware(GZipMiddleware, minimum_size=500)


# ═══════════════════════════════════════════════════════════════════
#  健康检查
# ═══════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    """V15.0 生产级健康检查: 引擎状态 + 数据新鲜度 + 调度器详情"""
    now_ts = time.time()
    last_update = cache_manager.get_json("last_update") or 0
    cache_age = round(now_ts - last_update) if last_update else None

    # 引擎就绪状态
    dashboard_data = cache_manager.get_json("dashboard_data")
    dashboard_ready = dashboard_data is not None
    aiae_global_ready = cache_manager.get_json("aiae_global_report_data") is not None
    strategy_results = cache_manager.get_json("strategy_results") or {}

    # AIAE 上下文
    aiae_ctx = cache_manager.get_json("aiae_ctx") or {}

    # 调度器状态
    scheduler_info = {}
    if hasattr(app.state, "scheduler"):
        scheduler = app.state.scheduler
        jobs = scheduler.get_jobs()
        next_fires = []
        for job in jobs:
            if job.next_run_time:
                next_fires.append({
                    "id": job.id,
                    "next": job.next_run_time.isoformat(),
                })
        scheduler_info = {
            "running": scheduler.running,
            "job_count": len(jobs),
            "next_fires": sorted(next_fires, key=lambda x: x["next"])[:3],
        }

    # 数据新鲜度
    data_freshness = {}
    if dashboard_data and dashboard_data.get("data"):
        macro = dashboard_data["data"].get("macro_cards", {})
        if macro.get("erp_valuation"):
            data_freshness["erp"] = macro["erp_valuation"].get("date", "unknown")
        if macro.get("market_temp"):
            data_freshness["market_temp"] = macro["market_temp"].get("confidence", "unknown")

    # Batch 11: SQLite 数据库统计
    db_info = {}
    try:
        from services import db as ac_db
        db_info = {
            "backend": "SQLite (WAL)",
            "trades": ac_db.get_trade_count(),
            "aiae_months": len(ac_db.get_aiae_history()),
            "erp_days": len(ac_db.get_erp_history(9999)),
            "snapshots": ac_db.get_portfolio_snapshot_count(),
        }
    except Exception:
        db_info = {"backend": "unavailable"}

    # Batch 11: uptime
    uptime = int(time.time() - getattr(app.state, 'startup_time', time.time()))

    status = "ok" if dashboard_ready else "starting"
    return {
        "status": status,
        "version": "AlphaCore V15.1",
        "uptime_sec": uptime,
        "cache_age_sec": cache_age,
        "engines": {
            "dashboard": {"status": "ready" if dashboard_ready else "cold", "age_sec": cache_age},
            "aiae_global": {"status": "ready" if aiae_global_ready else "cold"},
            "aiae_cn": {
                "regime": aiae_ctx.get("regime"),
                "aiae_v1": aiae_ctx.get("aiae_v1"),
                "position": aiae_ctx.get("cap"),
            } if aiae_ctx else {"status": "cold"},
            "strategies": {k: "cached" for k in strategy_results.keys()} if strategy_results else {"status": "cold"},
            "cache_backend": "redis" if cache_manager.use_redis else "memory",
        },
        "database": db_info,
        "data_freshness": data_freshness,
        "scheduler": scheduler_info,
        "timestamp": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════
#  Dashboard 数据 API (只读, 从缓存返回)
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/v1/dashboard-data")
async def get_dashboard_data():
    """
    V14.0 核心数据拉取接口 — 彻底转向纯前端读取模式 (Producer-Consumer)
    不执行任何计算，仅仅从缓存返回快照。
    """
    with _STRATEGY_LOCK:
        _cached_data = cache_manager.get_json("dashboard_data")
        _cached_ts = cache_manager.get_json("last_update")

    if _cached_data:
        if time.time() - (_cached_ts or 0) > 10800:
            _cached_data["is_stale"] = True
        return _cached_data

    return {
        "status": "warming_up",
        "message": "引擎极速预热中...",
        "is_stale": True,
        "data": {}
    }


# ═══════════════════════════════════════════════════════════════════
#  Router 模块注册 (Batch 7: 策略路由独立)
# ═══════════════════════════════════════════════════════════════════

from routers import portfolio, audit, aiae, market, industry, strategy, decision
app.include_router(portfolio.router)
app.include_router(audit.router)
app.include_router(aiae.router)
app.include_router(market.router)
app.include_router(industry.router)
app.include_router(strategy.router)
app.include_router(decision.router)


# ═══════════════════════════════════════════════════════════════════
#  静态文件 + HTML 路由
# ═══════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return FileResponse("index.html", headers={"Cache-Control": "no-cache"})

@app.get("/{filename}.html")
async def serve_html(filename: str):
    return FileResponse(f"{filename}.html", headers={"Cache-Control": "no-cache"})


# P0-2 安全加固: 仅暴露前端静态资源文件, 不暴露 .py/.git/config 等
import mimetypes
import os as _os
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

# ── Batch 5: 静态资源缓存策略 ──
_CACHE_LONG  = "public, max-age=2592000"   # 30天: 字体
_CACHE_SHORT = "public, max-age=86400"     # 1天: JS/CSS
_CACHE_NONE  = "no-cache"                  # HTML: 每次验证

def _get_cache_control(path: str) -> str:
    _, ext = _os.path.splitext(path)
    ext = ext.lower()
    if ext in ('.woff', '.woff2', '.ttf', '.eot'):
        return _CACHE_LONG
    elif ext in ('.js', '.css', '.map'):
        return _CACHE_SHORT
    elif ext in ('.html',):
        return _CACHE_NONE
    return _CACHE_SHORT  # 图片等默认 1 天

class SafeStaticFiles(StaticFiles):
    """安全过滤 + Cache-Control 注入"""
    ALLOWED_EXTENSIONS = {
        '.html', '.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg',
        '.ico', '.woff', '.woff2', '.ttf', '.eot', '.map', '.json',
    }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            # 阻止访问隐藏文件、Python 文件、配置文件
            if any(seg.startswith('.') for seg in path.split('/') if seg):
                response = Response("Not Found", status_code=404)
                await response(scope, receive, send)
                return
            _, ext = _os.path.splitext(path)
            if ext and ext.lower() not in self.ALLOWED_EXTENSIONS:
                response = Response("Not Found", status_code=404)
                await response(scope, receive, send)
                return

            # 注入 Cache-Control 头
            original_send = send
            cache_value = _get_cache_control(path)
            async def _send_with_cache(message):
                if message.get("type") == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"cache-control", cache_value.encode()))
                    message["headers"] = headers
                await original_send(message)
            await super().__call__(scope, receive, _send_with_cache)
            return
        await super().__call__(scope, receive, send)

app.mount("/", SafeStaticFiles(directory="."), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)