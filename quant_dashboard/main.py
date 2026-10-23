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
from version import VERSION_STRING, __version__
# 抑制 Windows ProactorEventLoop 的 ConnectionResetError 无害噪音 (WinError 10054)
_proactor_logger = logging.getLogger("asyncio")
class _SuppressConnectionReset(logging.Filter):
    def filter(self, record):
        return "ConnectionResetError" not in record.getMessage()
_proactor_logger.addFilter(_SuppressConnectionReset())

import os as _env_os
import copy
import time
import threading
import uvicorn
from datetime import datetime
from contextlib import asynccontextmanager
from services.logger import get_logger

_logger = get_logger("main")


def _env_int(name: str, default: int, min_value: int = 1) -> int:
    try:
        return max(min_value, int(_env_os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from concurrent.futures import ThreadPoolExecutor as _SchedPoolExecutor
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from services.cache_service import cache_manager
from services.cache_store import get_cache_ttl
from services.health_status import evaluate_system_health, get_aiae_max_age_sec
from services.dashboard_builder import _hot_data_reactor_tick, _STRATEGY_LOCK
from services.warmup_pipeline import (
    warmup_erp_cache, warmup_aiae_cache, warmup_dashboard_cache,
    warmup_rates_cache, warmup_hk_erp_cache, warmup_hk_aiae_cache,
    warmup_global_aiae_cache, warmup_swing_guard,
    daily_warmup_callback, morning_warmup_callback, fred_daily_callback,
    us_aiae_warmup_callback, jp_aiae_warmup_callback, aaii_crawl_callback,
    swing_guard_warmup_callback, daily_report_callback, alert_scan_callback,
    event_monitor_callback,
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

    # ── V21.2 Fix: 分层启动预热 (防止 shutdown 竞态) ──
    # 使用受控线程池替代 8 个裸 daemon Thread
    import atexit
    _warmup_workers = _env_int("STARTUP_WARMUP_WORKERS", 1, min_value=1)
    _warmup_stagger = _env_int("STARTUP_WARMUP_STAGGER_SECONDS", 60, min_value=0)
    _startup_pool = _SchedPoolExecutor(max_workers=_warmup_workers, thread_name_prefix="warmup")
    app.state._startup_pool = _startup_pool

    def _safe_warmup(fn, name):
        """安全包装: 捕获 shutdown 期间的 RuntimeError"""
        try:
            fn()
        except RuntimeError as e:
            if "shutdown" in str(e).lower() or "interpreter" in str(e).lower():
                _logger.debug("预热跳过 [%s]: interpreter shutting down", name)
            else:
                raise
        except Exception as e:
            _logger.warning("预热异常 [%s]: %s", name, e)

    def _submit_after_delay(fn, name, delay_seconds=0):
        def _runner():
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            _safe_warmup(fn, name)
        try:
            _startup_pool.submit(_runner)
        except RuntimeError:
            _logger.debug("预热提交跳过 [%s]: pool unavailable", name)

    def _schedule_after_delay(fn, name, delay_seconds=0):
        def _submit():
            try:
                _startup_pool.submit(_safe_warmup, fn, name)
            except RuntimeError:
                _logger.debug("warmup submit skipped [%s]: pool unavailable", name)

        if delay_seconds <= 0:
            _submit()
            return

        def _delayed_submit():
            time.sleep(delay_seconds)
            _submit()

        threading.Thread(target=_delayed_submit, name=f"warmup-delay-{name}", daemon=True).start()

    # Phase 1: core warmups. Stagger FRED-heavy tasks to avoid startup bursts.
    _schedule_after_delay(warmup_erp_cache, "ERP", 0)
    # Publish both the engine report and the canonical fail-closed aiae_ctx.
    _schedule_after_delay(warmup_aiae_cache, "AIAE", 0)
    _schedule_after_delay(warmup_rates_cache, "Rates", _warmup_stagger)
    _schedule_after_delay(warmup_dashboard_cache, "Dashboard", _warmup_stagger * 2)

    # Phase 2: non-core warmups. Queue them gradually after core warmups.
    def _phase2():
        time.sleep(max(30, _warmup_stagger * 2))
        for fn, name in [
            (warmup_global_aiae_cache, "Global_AIAE"),
            (warmup_hk_erp_cache, "HK_ERP"),
            (warmup_hk_aiae_cache, "HK_AIAE"),
            (warmup_swing_guard, "SwingGuard"),
        ]:
            try:
                _schedule_after_delay(fn, name, _warmup_stagger)
                time.sleep(_warmup_stagger)
            except RuntimeError:
                break  # Pool 已 shutdown, 放弃后续任务
        # V25.2 A-4: 启动时触发准确率回填 (force_recalc 修正旧逻辑记录)
        try:
            from dashboard_modules.decision_engine import backfill_signal_accuracy
            _startup_pool.submit(_safe_warmup,
                                 lambda: backfill_signal_accuracy(force_recalc=True),
                                 "AccuracyBackfill")
        except RuntimeError:
            pass

        # P1-A: 启动时触发自动抓取最新基金仓位 (AKShare)
        try:
            from services.aiae_scheduler import update_aiae_fund_position_task
            _startup_pool.submit(_safe_warmup, update_aiae_fund_position_task, "AIAE_Fund_Crawl")
        except RuntimeError:
            pass
    threading.Thread(target=_phase2, daemon=True).start()

    # ── Init APScheduler ──
    scheduler = BackgroundScheduler(
        timezone="Asia/Shanghai",
        executors={'default': {'type': 'threadpool', 'max_workers': 5}},
        job_defaults={'misfire_grace_time': 120, 'coalesce': True},
    )

    # 1. 自适应盘中轮询 (V25.3: 替代固定 120s)
    from services.realtime_poller import init_poller
    _poller = init_poller(
        tick_fn=_hot_data_reactor_tick,
        emergency_fn=lambda: _logger.info("[Emergency] VIX 跳变紧急刷新触发"),
    )
    scheduler.add_job(_poller.tick, IntervalTrigger(seconds=30), id="adaptive_poller")
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
    # 8. 波段守卫 15:40 (收盘后自动刷新7大ETF信号)
    scheduler.add_job(swing_guard_warmup_callback, CronTrigger(day_of_week='mon-fri', hour=15, minute=40), id="swing_guard")
    # 9. V21.0: 投委会日报 16:35 (收盘后自动生成, 等待 15:35 预热完成)
    scheduler.add_job(daily_report_callback, CronTrigger(day_of_week='mon-fri', hour=16, minute=35), id="daily_report")
    # 10. V21.2: 信号预警扫描 (每10分钟, 盘中监控 JCS/VIX)
    scheduler.add_job(alert_scan_callback, IntervalTrigger(minutes=10), id="alert_scan")
    # 11. V22.2: 事件驱动监控 (每5分钟, 盘中检测 VIX/AIAE/MR 跳变)
    scheduler.add_job(event_monitor_callback, IntervalTrigger(minutes=5), id="event_monitor")
    # 12. P1-3: 策略 CI/CD 月度自动优化 (每月1日 02:00, 非交易时段)
    def _ci_monthly_callback():
        try:
            from services.strategy_pipeline import run_full_ci
            run_full_ci()
        except Exception as e:
            _logger.error("策略 CI/CD 月度任务异常: %s", e)
    scheduler.add_job(_ci_monthly_callback, CronTrigger(day=1, hour=2, minute=0), id="strategy_ci_monthly")
    # 13. P2-C: NLP 情报扫描 (每日 09:35 + 15:15, 盘前+盘中各一次)
    def _nlp_scan_callback():
        try:
            from engines.news_intelligence import scan_news
            scan_news()
        except Exception as e:
            _logger.error("NLP 情报扫描异常: %s", e)
    scheduler.add_job(_nlp_scan_callback, CronTrigger(day_of_week='mon-fri', hour=9, minute=35), id="nlp_scan_am")
    scheduler.add_job(_nlp_scan_callback, CronTrigger(day_of_week='mon-fri', hour=15, minute=15), id="nlp_scan_pm")

    # 14. P1-A: 自动抓取 AIAE 基金仓位 (AKShare) 每日 16:00 (周一至周五)
    def _aiae_fund_position_update_callback():
        try:
            from services.aiae_scheduler import update_aiae_fund_position_task
            update_aiae_fund_position_task()
        except Exception as e:
            _logger.error("AIAE 基金仓位自动抓取任务异常: %s", e)
    scheduler.add_job(_aiae_fund_position_update_callback, CronTrigger(day_of_week='mon-fri', hour=16, minute=0), id="aiae_fund_position_update")

    # 15. 行业挑战者前向证据：收盘后记录不可变快照并结算成熟信号。
    def _industry_forward_monitor_callback():
        try:
            from services.industry_forward_monitor import run_forward_monitor
            run_forward_monitor()
        except Exception as exc:
            _logger.error("行业挑战者前向证据任务异常: %s", exc)

    scheduler.add_job(
        _industry_forward_monitor_callback,
        CronTrigger(day_of_week='mon-fri', hour=15, minute=45),
        id="industry_forward_monitor",
    )

    # 16. ETF 主数据周度校验：仅更新权威元数据，保留预注册研究池冻结日。
    def _industry_universe_refresh_callback():
        try:
            from services.industry_challenger import run_local_challenger_validation
            from services.industry_constituents import refresh_industry_constituents
            from services.industry_universe import refresh_existing_industry_universe
            from services.industry_validation import run_local_industry_validation

            refresh_existing_industry_universe()
            refresh_industry_constituents()
            run_local_industry_validation()
            run_local_challenger_validation()
        except Exception as exc:
            _logger.error("行业ETF主数据周度校验异常: %s", exc)

    scheduler.add_job(
        _industry_universe_refresh_callback,
        CronTrigger(day_of_week='sat', hour=8, minute=30),
        id="industry_universe_refresh",
    )

    # 17. 持仓跟踪止盈日终: 同步持仓日线 → 重放止损线 → 推送 RED/分批止盈 (晚于 15:35 预热与 15:45 行业任务)
    def _trailing_stop_callback():
        try:
            from services.trailing_stop_service import daily_job
            daily_job()
        except Exception as exc:
            _logger.error("跟踪止盈日终任务异常: %s", exc)

    scheduler.add_job(
        _trailing_stop_callback,
        CronTrigger(day_of_week='mon-fri', hour=15, minute=50),
        id="trailing_stop_daily",
    )

    scheduler.start()
    app.state.scheduler = scheduler

    _logger.info("AlphaCore 服务启动完成 · APScheduler(Redis就绪) 已激活全自动数据流水线")
    yield
    # ── Shutdown: 先关线程池, 再关调度器 ──
    _startup_pool.shutdown(wait=False)
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

@app.get("/version")
async def get_version():
    """P4: 版本信息端点 — 前端自动同步"""
    from version import __version__, __codename__, VERSION_STRING
    return {"version": __version__, "codename": __codename__, "display": VERSION_STRING}


@app.get("/health")
async def health_check():
    """V15.0 生产级健康检查: 引擎状态 + 数据新鲜度 + 调度器详情"""
    now_ts = time.time()
    last_update = cache_manager.get_json("last_update")
    last_hot_update = cache_manager.get_json("last_hot_update")

    # 引擎就绪状态
    dashboard_data = cache_manager.get_json("dashboard_data")
    dashboard_ready = dashboard_data is not None
    aiae_global_ready = cache_manager.get_json("aiae_global_report_data") is not None
    strategy_results = cache_manager.get_json("strategy_results") or {}

    # AIAE 上下文
    aiae_ctx = cache_manager.get_json("aiae_ctx") or {}

    # Fail-closed health evaluation. The dashboard threshold follows the same
    # market-aware TTL used by the cache producer; AIAE remains valid for at
    # least 24h and for the full weekend cache window.
    dashboard_max_age = get_cache_ttl()
    aiae_max_age = get_aiae_max_age_sec()
    health_state = evaluate_system_health(
        dashboard_ready=dashboard_ready,
        dashboard_updated_at=last_update,
        aiae_ctx=aiae_ctx,
        now_ts=now_ts,
        dashboard_max_age_sec=dashboard_max_age,
        aiae_max_age_sec=aiae_max_age,
    )
    cache_age = health_state["dashboard_age_sec"]

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

    # 只有行业数据契约失败才影响应用健康；模型验证/Regime 生命周期
    # 只锁定交易执行，不能阻止安全禁用策略的应用版本完成部署。
    industry_quality = _get_industry_quality_status()
    industry_execution_locked = bool(
        industry_quality.get("decision_locked", True)
    )
    industry_data_locked = not bool(industry_quality.get("is_usable", False))

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
    except Exception as e:
        _logger.debug("Health: DB 统计查询异常: %s", e)
        db_info = {"backend": "unavailable"}

    # Batch 11: uptime
    uptime = int(time.time() - getattr(app.state, 'startup_time', time.time()))

    status = health_state["status"]
    health_reasons = list(health_state["reasons"])
    if industry_data_locked:
        health_reasons.append("industry_data_locked")
        if status == "ok":
            status = "degraded"
    overall_decision_locked = bool(
        health_state["decision_locked"] or industry_execution_locked
    )
    dashboard_engine_status = (
        "cold" if not dashboard_ready
        else "ready" if health_state["dashboard_fresh"]
        else "stale"
    )
    aiae_engine_status = (
        "cold" if not aiae_ctx
        else "ready" if not health_state["decision_locked"] and health_state["aiae_fresh"]
        else "degraded"
    )
    return {
        "status": status,
        "health_reasons": health_reasons,
        "version": VERSION_STRING,
        "uptime_sec": uptime,
        "cache_age_sec": cache_age,
        "last_hot_update": last_hot_update,
        "data_quality": {
            "aiae_score": health_state["data_quality_score"],
            "aiae_decision_locked": health_state["decision_locked"],
            "decision_locked": overall_decision_locked,
            "industry": {
                "decision_locked": industry_execution_locked,
                "is_usable": industry_quality.get("is_usable", False),
                "execution_policy_ready": industry_quality.get(
                    "execution_policy_ready", False
                ),
                "policy_engine_ready": industry_quality.get("policy_engine_ready", False),
                "operational_gates_ready": industry_quality.get(
                    "operational_gates_ready", False
                ),
                "model_validation_ready": industry_quality.get(
                    "model_validation_ready", False
                ),
                "model_validation": industry_quality.get("model_validation", {}),
                "usable_count": industry_quality.get("usable_count", 0),
                "checked_count": industry_quality.get("checked_count", 0),
                "coverage_ratio": industry_quality.get("coverage_ratio", 0.0),
                "reasons": industry_quality.get("reasons", []),
            },
        },
        "freshness": {
            "dashboard": {
                "fresh": health_state["dashboard_fresh"],
                "age_sec": health_state["dashboard_age_sec"],
                "max_age_sec": health_state["dashboard_max_age_sec"],
            },
            "aiae": {
                "fresh": health_state["aiae_fresh"],
                "age_sec": health_state["aiae_age_sec"],
                "max_age_sec": health_state["aiae_max_age_sec"],
            },
            "industry": {
                "fresh": not bool(
                    industry_quality.get("missing_codes")
                    or industry_quality.get("stale_codes")
                ),
                "expected_trade_date": industry_quality.get("expected_trade_date"),
                "daily_latest": industry_quality.get("daily_latest"),
                "daily_earliest_latest": industry_quality.get("daily_earliest_latest"),
                "calendar_source": industry_quality.get("calendar_source"),
                "validation_generated_at": (
                    industry_quality.get("model_validation") or {}
                ).get("generated_at"),
                "validation_data_end_date": (
                    industry_quality.get("model_validation") or {}
                ).get("data_end_date"),
                "validation_data_lag_days": (
                    industry_quality.get("model_validation") or {}
                ).get("data_lag_days"),
            },
        },
        "engines": {
            "dashboard": {"status": dashboard_engine_status, "age_sec": cache_age},
            "aiae_global": {"status": "ready" if aiae_global_ready else "cold"},
            "aiae_cn": {
                "status": aiae_engine_status,
                "regime": aiae_ctx.get("regime"),
                "aiae_v1": aiae_ctx.get("aiae_v1"),
                "position": aiae_ctx.get("cap"),
                "data_quality_score": health_state["data_quality_score"],
                "decision_locked": health_state["decision_locked"],
                "fresh": health_state["aiae_fresh"],
                "age_sec": health_state["aiae_age_sec"],
            } if aiae_ctx else {
                "status": "cold",
                "data_quality_score": 0,
                "decision_locked": True,
                "fresh": False,
                "age_sec": None,
            },
            "industry": {
                "status": "degraded" if industry_execution_locked else "ready",
                "decision_locked": industry_execution_locked,
                "reasons": industry_quality.get("reasons", []),
                "validation_stage": (
                    industry_quality.get("model_validation") or {}
                ).get("stage", "missing"),
            },
            "strategies": {k: "cached" for k in strategy_results.keys()} if strategy_results else {"status": "cold"},
            "cache_backend": "redis" if cache_manager.use_redis else "memory",
        },
        "database": db_info,
        "data_freshness": data_freshness,
        "scheduler": scheduler_info,
        "poller": _get_poller_status(),
        "breakers": _get_breaker_summary(),
        "external_sources": {
            "fred": _get_fred_guard_status(),
        },
        "timestamp": datetime.now().isoformat(),
    }


def _get_poller_status() -> dict:
    try:
        from services.realtime_poller import get_poller
        poller = get_poller()
        return poller.get_status() if poller else {"status": "not_initialized"}
    except Exception as e:
        _logger.debug("Health: Poller 状态查询异常: %s", e)
        return {"status": "error"}


def _get_breaker_summary() -> dict:
    try:
        from services.circuit_breaker import get_all_breaker_status
        statuses = get_all_breaker_status()
        open_count = sum(1 for s in statuses if s["state"] == "open")
        return {"total": len(statuses), "open": open_count, "healthy": open_count == 0}
    except Exception:
        return {"status": "error"}


def _get_fred_guard_status() -> dict:
    try:
        from services.fred_guard import get_fred_guard_status
        return get_fred_guard_status()
    except Exception:
        return {"status": "error"}


def _get_industry_quality_status() -> dict:
    """读取行业数据与执行闸门；任何异常均按 fail-closed 返回。"""
    try:
        from data_manager import FactorDataManager
        from core_etf_config import CORE_ETF_CODES
        from services.industry_policy import build_industry_decision_context
        from services.market_regime import get_market_regime_snapshot

        quality = FactorDataManager().check_industry_data_quality(CORE_ETF_CODES)
        market_snapshot = (
            {}
            if quality.get("decision_locked", True)
            else get_market_regime_snapshot()
        )
        context = build_industry_decision_context(
            quality,
            market_snapshot,
        )
        quality["policy_engine_ready"] = True
        quality["operational_gates_ready"] = not context["hard_locked"]
        quality["model_validation_ready"] = context["model_validation_ready"]
        quality["model_validation"] = context["model_validation"]
        quality["execution_policy_ready"] = not context["decision_locked"]
        quality["decision_locked"] = context["decision_locked"]
        quality["reasons"] = context["decision_lock_reasons"]
        quality["execution_context"] = context
        return quality
    except Exception as exc:
        _logger.warning("Health: 产业数据质量检查异常: %s", exc)
        return {
            "decision_locked": True,
            "is_usable": False,
            "checked_count": 0,
            "usable_count": 0,
            "coverage_ratio": 0.0,
            "reasons": ["INDUSTRY_HEALTH_CHECK_ERROR"],
            "missing_codes": [],
            "stale_codes": [],
        }


# ═══════════════════════════════════════════════════════════════════
#  PWA 路由 (manifest + Service Worker)
# ═══════════════════════════════════════════════════════════════════

@app.get("/manifest.json")
async def serve_manifest():
    """PWA Manifest: 允许 '添加到主屏幕'"""
    return FileResponse("manifest.json", media_type="application/manifest+json")

@app.get("/sw.js")
async def serve_sw():
    """Service Worker: 必须从根路径提供, scope 才能覆盖全站"""
    return FileResponse(
        "static/js/sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


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
        response_data = copy.deepcopy(_cached_data)
        age_sec = time.time() - _cached_ts if isinstance(_cached_ts, (int, float)) else None
        response_data["is_stale"] = age_sec is None or age_sec > get_cache_ttl()
        response_data["cache_age_sec"] = round(age_sec) if age_sec is not None else None
        return response_data

    return {
        "status": "warming_up",
        "message": "引擎极速预热中...",
        "is_stale": True,
        "data": {}
    }


# ═══════════════════════════════════════════════════════════════════
#  Router 模块注册 (Batch 7: 策略路由独立)
# ═══════════════════════════════════════════════════════════════════

from routers import portfolio, audit, aiae, market, industry, strategy, decision, slippage, ci, intelligence, assistant
from routers import params_api  # V5.2: 参数同步 API
from routers import system as system_router  # V26.1: 系统健康检查
from routers import trailing as trailing_router  # 持仓跟踪止盈 + 历史成交导入
app.include_router(portfolio.router)
app.include_router(audit.router)
app.include_router(aiae.router)
app.include_router(market.router)
app.include_router(industry.router)
app.include_router(strategy.router)
app.include_router(decision.router)
app.include_router(slippage.router)
app.include_router(ci.router)
app.include_router(intelligence.router)
app.include_router(assistant.router)
app.include_router(params_api.router)  # V5.2: 参数同步
app.include_router(system_router.router)  # V26.1: 系统监控
app.include_router(trailing_router.router)  # 持仓跟踪止盈 + 历史成交导入



# ═══════════════════════════════════════════════════════════════════
#  静态文件 + HTML 路由
# ═══════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return FileResponse("index.html", headers={"Cache-Control": "no-cache"})

# P1 安全加固: HTML 页面白名单 (防止 /../ 路径穿越和任意文件读取)
_ALLOWED_PAGES = {
    "index", "decision", "portfolio", "audit", "strategy",
    "factor", "industry", "backtest", "treasury", "report",
    "smic_audit", "zijin_audit", "byd_audit", "eastmoney_audit",
    "fii_audit", "wus_audit", "scc_audit",
    "settings", "optimizer", "rebalance",
    "erp_timing", "global_analysis", "market_sentiment",
}

@app.get("/{filename}.html")
async def serve_html(filename: str):
    # 只允许白名单中的页面名，阻止路径穿越攻击
    if filename not in _ALLOWED_PAGES:
        from starlette.responses import Response
        return Response("Not Found", status_code=404)
    return FileResponse(f"{filename}.html", headers={"Cache-Control": "no-cache"})


# P0-2 安全加固: 仅暴露前端静态资源文件, 不暴露 .py/.git/config 等
import mimetypes
import os as _os
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

# ── Batch 5: 静态资源缓存策略 ──
_CACHE_LONG  = "public, max-age=2592000"   # 30天: 字体
_CACHE_SHORT = "no-cache"                  # JS/CSS: 每次验证 (304加速)
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
        '.ico', '.woff', '.woff2', '.ttf', '.eot', '.map',
    }
    # P1 安全加固: .json 仅允许 /static/ 路径下的文件
    # 防止 portfolio_store.json / trade_history.json 等敏感文件被直接访问
    STATIC_ONLY_EXTENSIONS = {'.json'}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            # 阻止访问隐藏文件、Python 文件、配置文件
            if any(seg.startswith('.') for seg in path.split('/') if seg):
                response = Response("Not Found", status_code=404)
                await response(scope, receive, send)
                return
            _, ext = _os.path.splitext(path)
            ext_lower = ext.lower() if ext else ""
            # P1: STATIC_ONLY 扩展名仅允许 /static/ 路径
            if ext_lower in self.STATIC_ONLY_EXTENSIONS:
                if not path.startswith("/static/"):
                    response = Response("Not Found", status_code=404)
                    await response(scope, receive, send)
                    return
            elif ext_lower and ext_lower not in self.ALLOWED_EXTENSIONS:
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
    uvicorn.run("main:app", host="127.0.0.1", port=8000)
