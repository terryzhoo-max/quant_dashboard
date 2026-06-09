"""
AlphaCore · 预热流水线 (从 main.py 提取)
==========================================
包含:
  - with_retry: 柔性重试机制
  - 全部 warmup 函数 (ERP/AIAE/Dashboard/Factor/Rates/Industry/Global)
  - 定时回调 (daily/morning/FRED/US AIAE/JP AIAE/AAII/HK)
"""

import time
import asyncio
from datetime import datetime, timedelta

from services.cache_service import cache_manager
from services.fred_guard import should_retry_fred_error
from services.locks import AIAE_GLOBAL_LOCK as _AIAE_GLOBAL_LOCK
from services.logger import get_logger
from services.aiae_normalizer import normalize_temp, get_region_thresholds, compute_global_position, REGION_NAMES

logger = get_logger("warmup")


# ═══════════════════════════════════════════════════
#  基础工具
# ═══════════════════════════════════════════════════

def with_retry(func, name, max_retries=3, delay=5):
    """柔性重试机制: P1-1 指数退避 (5s/15s/45s), 防阻塞线程池"""
    for i in range(max_retries):
        try:
            func()
            return True
        except Exception as e:
            if not should_retry_fred_error(e):
                logger.warning(f"{name} FRED guard open/rate-limited; skip retries: {e}")
                return False
            backoff = delay * (3 ** i)  # 指数退避: 5 → 15 → 45
            if i < max_retries - 1:
                logger.warning(f"{name} 失败: {e}。等待 {backoff}s 重试 ({i+1}/{max_retries})")
                time.sleep(backoff)
            else:
                logger.error(f"{name} 最终失败，已达最大重试次数")
                return False


# ═══════════════════════════════════════════════════
#  各引擎预热函数
# ═══════════════════════════════════════════════════

def warmup_erp_cache():
    """后台预热 ERP 引擎缓存: 拉取最新 PE/Yield/M1 + 生成报告"""
    from erp_timing_engine import get_erp_engine
    engine = get_erp_engine()
    report = engine.generate_report()
    status = report.get('status', 'unknown')
    if status != "success":
        raise Exception(f"ERP report failed with status: {status}")
    snap = report.get('current_snapshot', {})
    erp = snap.get('erp_value', '?')
    logger.info(f"ERP 预热完成 · status={status} · ERP={erp}%")


def warmup_aiae_cache():
    """预热 AIAE 引擎缓存 (V7.0/V8.1)"""
    from aiae_engine import get_aiae_engine
    engine = get_aiae_engine()
    engine.refresh()  # V8.1: 强制劈开 L1 缓存锁
    report = engine.generate_report()
    status = report.get('status', 'unknown')
    if status != "success":
        raise Exception(f"AIAE report failed with status: {status}")
    logger.info(f"AIAE 预热完成 · status={status}")


def warmup_dashboard_cache():
    """后台预热量化总览缓存: True Zero-Wait (真实主动流水线预热)"""
    # Batch 7: 已迁移至 services/dashboard_builder.py
    from services.dashboard_builder import _build_dashboard_data_full
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        data = loop.run_until_complete(_build_dashboard_data_full())
        if data and data.get("status") == "success":
            logger.info("Dashboard 主动预热成功, 零等待缓存已就绪")
        else:
            logger.warning("Dashboard 预热后返回状态异常，部分缓存建立失败")
    except Exception as e:
        logger.error(f"Dashboard 预热失败: {e}")
    finally:
        loop.close()


def warmup_factor_data():
    """
    V5.0: 收盘后自动同步因子数据 (日线 + 财务指标)
    V24.1: 追加因子代理指数同步 (Market/SMB/HML 归因引擎依赖)
    触发时机: 每日 15:35 (A股收盘后 35 分钟，给 Tushare 数据更新缓冲)
    """
    from data_manager import FactorDataManager
    dm = FactorDataManager()

    # V24.1: 同步三因子归因引擎依赖的指数行情 (asset='I')
    FACTOR_PROXY_INDICES = ["000300.SH", "000852.SH", "000015.SH", "399006.SZ"]
    try:
        dm.sync_daily_prices(FACTOR_PROXY_INDICES, start_date="20210101", asset='I')
        logger.info("因子代理指数同步完成: %s", FACTOR_PROXY_INDICES)
    except Exception as e:
        logger.warning("因子代理指数同步失败 (非致命): %s", e)

    stocks = dm.get_all_stocks()
    # 默认同步 Top 30 样本池 (与因子分析默认配置一致)
    sample = stocks.head(30)['ts_code'].tolist()
    result = dm.smart_sync(sample)
    synced = result.get('synced', False)
    latest = result.get('freshness', {}).get('daily_latest', '?')
    logger.info(f"Factor {'同步完成' if synced else '数据已是最新'} · 最新日线: {latest}")


def warmup_rates_cache():
    """V1.5: 后台预热利率择时引擎缓存: 拉取最新 FRED 数据 + 生成报告"""
    from rates_strategy_engine import warmup_rates_cache as _warmup
    _warmup()


def warmup_industry_tracking():
    """V6.0: 产业追踪自动预热 — 同步12只核心ETF日线 + 预计算指标写入缓存"""
    from data_manager import FactorDataManager
    from core_etf_config import CORE_ETF_CODES
    mgr = FactorDataManager()
    # Step 1: 同步最新日线数据 (Tushare asset='E')
    mgr.sync_daily_prices(CORE_ETF_CODES, asset='E')
    logger.info("12只核心ETF日线同步完成")
    # Step 2: 主动触发一次 tracking 指标计算，填充 latest 缓存
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        from routers.industry import get_industry_tracking
        result = loop.run_until_complete(get_industry_tracking(date=None))
        loop.close()
        cached_count = len(result.get('data', {}).get('sector_heatmap', []))
        logger.info(f"Industry 预热完成 · {cached_count} 只ETF指标已写入 latest 缓存")
    except Exception as e:
        logger.warning(f"Industry 指标预计算失败 (数据已同步): {e}")


def warmup_us_aiae_cache():
    """预热 US AIAE 引擎: 清除内存缓存 -> 重新拉取 FRED 数据 -> 生成报告"""
    from aiae_us_engine import get_us_aiae_engine
    engine = get_us_aiae_engine()
    engine.refresh()
    report = engine.generate_report()
    status = report.get('status', 'unknown')
    v1 = report.get('current', {}).get('aiae_v1', '?')
    logger.info(f"US AIAE 预热完成 · status={status} · AIAE={v1}%")
    if status != 'success':
        raise Exception(f"US AIAE warmup failed: {status}")


def warmup_jp_aiae_cache():
    """预热 JP AIAE 引擎: 清除内存缓存 -> 重新拉取 TOPIX/M2 -> 生成报告"""
    from aiae_jp_engine import get_jp_aiae_engine
    engine = get_jp_aiae_engine()
    engine.refresh()
    report = engine.generate_report()
    status = report.get('status', 'unknown')
    v1 = report.get('current', {}).get('aiae_v1', '?')
    logger.info(f"JP AIAE 预热完成 · status={status} · AIAE={v1}%")
    if status != 'success':
        raise Exception(f"JP AIAE warmup failed: {status}")


def warmup_aaii_sentiment():
    """周期性爬取 AAII Sentiment Survey: 强制重新爬取并写入文件"""
    from aiae_us_engine import get_us_aiae_engine
    engine = get_us_aiae_engine()
    crawled = engine._crawl_aaii_sentiment()
    if crawled:
        engine._aaii_data = crawled
        logger.info(f"AAII 爬取成功: spread={crawled.get('spread', 0):.1f}%")
    else:
        logger.warning("AAII 爬取失败, 保留旧数据")


def warmup_hk_erp_cache():
    """预热 HK ERP 引擎: HSI + HSTECH 双轨"""
    from erp_hk_engine import get_hk_erp_engine
    for mkt in ["HSI", "HSTECH"]:
        engine = get_hk_erp_engine(mkt)
        report = engine.generate_report()
        status = report.get('status', 'unknown')
        score = report.get('signal', {}).get('score', '?')
        logger.info(f"HK ERP {mkt} 预热完成 · status={status} · score={score}")
        if status not in ('success', 'fallback'):
            raise Exception(f"HK ERP {mkt} warmup failed: {status}")


def warmup_hk_aiae_cache():
    """预热 HK AIAE 引擎"""
    from aiae_hk_engine import get_hk_aiae_engine
    engine = get_hk_aiae_engine()
    engine.refresh()
    report = engine.generate_report()
    status = report.get('status', 'unknown')
    v1 = report.get('current', {}).get('aiae_v1', '?')
    logger.info(f"HK AIAE 预热完成 · status={status} · AIAE={v1}%")
    if status not in ('success', 'fallback'):
        raise Exception(f"HK AIAE warmup failed: {status}")


def warmup_swing_guard():
    """预热波段守卫: 并行拉取7大ETF + 缓存信号 (V25.0: 对齐 SWR 标准缓存键)"""
    from swing_decision import SwingDecisionOrchestrator
    orchestrator = SwingDecisionOrchestrator()
    signals = orchestrator.generate_all_signals()
    # V25.0: 使用 SWR 标准 payload 格式 {timestamp, data}
    payload = {"timestamp": time.time(), "data": {"status": "success", "data": signals}}
    cache_manager.set_json("swr_swing_guard", payload)
    logger.info(f"Swing Guard 预热完成 · {len(signals)} 只ETF")


# ═══════════════════════════════════════════════════
#  全球 AIAE 四地对比缓存
# ═══════════════════════════════════════════════════


def warmup_global_aiae_cache():
    """后台预热海外AIAE: US+JP+HK引擎并行, 写入L1缓存 (V2.0: 四地对比)"""
    from aiae_us_engine import get_us_aiae_engine
    from aiae_jp_engine import get_jp_aiae_engine
    from aiae_hk_engine import get_hk_aiae_engine
    from aiae_engine import get_aiae_engine
    try:
        us_engine = get_us_aiae_engine()
        jp_engine = get_jp_aiae_engine()
        hk_engine = get_hk_aiae_engine()
        us_report = us_engine.generate_report()
        jp_report = jp_engine.generate_report()
        hk_report = hk_engine.generate_report()
        cn_aiae_v1, cn_regime = 22.0, 3
        try:
            cn_engine = get_aiae_engine()
            cn_report = cn_engine.generate_report()
            if cn_report.get('status') in ('success', 'fallback'):
                cn_aiae_v1 = cn_report['current']['aiae_v1']
                cn_regime = cn_report['current']['regime']
        except Exception as e:
            logger.debug("CN AIAE 引擎异常, 使用默认值: %s", e)
        us_v1 = us_report.get('current', {}).get('aiae_v1', 25.0)
        jp_v1 = jp_report.get('current', {}).get('aiae_v1', 17.0)
        hk_v1 = hk_report.get('current', {}).get('aiae_v1', 14.0)
        us_regime = us_report.get('current', {}).get('regime', 3)
        jp_regime = jp_report.get('current', {}).get('regime', 3)
        hk_regime = hk_report.get('current', {}).get('regime', 3)
        vals = {'cn': cn_aiae_v1, 'us': us_v1, 'jp': jp_v1, 'hk': hk_v1}

        # P0: 跨区域归一化温度 (委托 aiae_normalizer 统一计算)
        _thresholds = get_region_thresholds()
        norm_vals = {r: round(normalize_temp(v, r, _thresholds), 1) for r, v in vals.items()}
        coldest = min(norm_vals, key=norm_vals.get)
        hottest = max(norm_vals, key=norm_vals.get)
        recommendation = f"当前{REGION_NAMES[coldest]}(标准温度={norm_vals[coldest]:.0f}°)配置热度最低, 相对超配优先; {REGION_NAMES[hottest]}(标准温度={norm_vals[hottest]:.0f}°)最高, 谨慎配置"

        avg_temp = sum(norm_vals.values()) / 4.0
        regimes = {'cn': cn_regime, 'us': us_regime, 'jp': jp_regime, 'hk': hk_regime}
        gp = compute_global_position(avg_temp, regimes)

        data = {
            'status': 'success',
            'timestamp': datetime.now().isoformat(),
            'us': us_report,
            'jp': jp_report,
            'hk': hk_report,
            'global_comparison': {
                'cn_aiae': cn_aiae_v1, 'cn_regime': cn_regime,
                'us_aiae': us_v1, 'us_regime': us_regime,
                'jp_aiae': jp_v1, 'jp_regime': jp_regime,
                'hk_aiae': hk_v1, 'hk_regime': hk_regime,
                'cn_temp': norm_vals['cn'], 'us_temp': norm_vals['us'],
                'jp_temp': norm_vals['jp'], 'hk_temp': norm_vals['hk'],
                'coldest': coldest, 'hottest': hottest,
                'recommendation': recommendation,
                'global_position': gp,
            }
        }
        with _AIAE_GLOBAL_LOCK:
            cache_manager.set_json("aiae_global_last_update", time.time())
            cache_manager.set_json("aiae_global_report_data", data)
        logger.info(f"Global AIAE L1缓存预热完成 · US={us_v1:.1f}% JP={jp_v1:.1f}% HK={hk_v1:.1f}% CN={cn_aiae_v1:.1f}% · 最冷={REGION_NAMES[coldest]} · 平均温度={avg_temp:.0f}°")
    except Exception as e:
        logger.error(f"Global AIAE 预热失败 (non-fatal): {e}")


def warmup_gem_cache():
    """预热 GEM 双重动量策略缓存: 拉取7资产历史数据 + 生成信号"""
    from engines.dual_momentum_engine import run_gem_strategy
    from services.cache_service import cache_manager
    result = run_gem_strategy()
    status = result.get('status', 'unknown')
    if status == 'success':
        _sr = cache_manager.get_json("strategy_results", {})
        _sr["gem"] = result
        cache_manager.set_json("strategy_results", _sr)
    overview = result.get('data', {}).get('market_overview', {})
    selected = overview.get('selected_asset', '?')
    signal = overview.get('signal_type', '?')
    logger.info(f"GEM 预热完成 · status={status} · 信号={signal} · 持有={selected}")
    if status not in ('success', 'fallback'):
        raise Exception(f"GEM warmup failed: {status}")


# ═══════════════════════════════════════════════════
#  定时回调 (由 APScheduler 在 lifespan 中注册)
# ═══════════════════════════════════════════════════

sched_logger = get_logger("scheduler")


def _ensure_daily_snapshot(source: str = "unknown"):
    """V3.2: 确保当日 snapshot + decision_log 已写入 (幂等, 可从多个回调安全调用)"""
    try:
        from portfolio_engine import get_portfolio_engine
        from services import db as ac_db
        engine = get_portfolio_engine()
        val = engine.get_valuation()
        if val.get("position_count", 0) > 0:
            today = datetime.now().strftime("%Y-%m-%d")
            ac_db.save_portfolio_snapshot(
                date=today,
                total_asset=val["total_asset"],
                cash=val["cash"],
                market_value=val["market_value"],
                total_pnl=val["total_pnl"],
                position_count=val["position_count"],
            )
            sched_logger.info(f"📸 [{source}] 组合快照已补录: {today} · 资产={val['total_asset']:,.0f}")
    except Exception as e:
        sched_logger.debug(f"[{source}] 快照补录跳过: {e}")
    try:
        from dashboard_modules.decision_engine import log_daily_decision
        log_daily_decision()
        sched_logger.info(f"📋 [{source}] 决策快照已补录")
    except Exception as e:
        sched_logger.debug(f"[{source}] 决策补录跳过: {e}")


def daily_warmup_callback():
    """定时回调: 每日 15:35 收盘预热 — V6.0 DAG 并行化版本

    依赖关系:
      Phase 1 (并行): ERP + AIAE + Industry + Factor + SwingGuard
         ↓ barrier (仅等待 ERP + AIAE)
      Phase 2 (串行): Dashboard (依赖 ERP + AIAE 的缓存)
         ↓
      Phase 3 (并行): GEM + Snapshot + AccuracyBackfill + AlertScan + SWR预热

    vs 旧版串行: 最差 91min → 现在 5-8min
    """
    from concurrent.futures import ThreadPoolExecutor, wait
    import time as _t
    import threading as _th

    _start = _t.time()
    sched_logger.info("⏰ 收盘 DAG 预热管线启动 (V6.0 并行化)")

    # ── 线程安全的状态容器 ──
    _status_lock = _th.Lock()
    _results = {}   # name → "ok"
    _errors = {}    # name → error_msg

    def _record_result(name, ok=True, err=None):
        with _status_lock:
            if ok:
                _results[name] = "ok"
            else:
                _errors[name] = str(err)

    def _get_snapshot():
        with _status_lock:
            return dict(_results), dict(_errors)

    # ── 写入进度状态 (前端可轮询感知) ──
    def _set_warmup_status(phase, completed, running, pending, error=None):
        cache_manager.set_json("warmup_status", {
            "phase": phase,
            "completed": completed,
            "running": running,
            "pending": pending,
            "error": error,
            "started_at": datetime.now().isoformat(),
            "elapsed_sec": round(_t.time() - _start, 1),
        })

    # ── Phase 1: 并行执行无依赖引擎 ──
    _set_warmup_status("Phase 1", [], ["ERP", "AIAE", "Industry", "Factor", "SwingGuard"],
                       ["Dashboard", "GEM", "Snapshot"])

    _dag_pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="dag")

    def _safe_warmup_task(fn, name):
        try:
            with_retry(fn, name, 3, 60)
            _record_result(name, ok=True)
        except Exception as e:
            _record_result(name, ok=False, err=e)
            sched_logger.error("DAG Phase 1 失败 [%s]: %s", name, e)

    f_erp = _dag_pool.submit(_safe_warmup_task, warmup_erp_cache, "ERP")
    f_aiae = _dag_pool.submit(_safe_warmup_task, warmup_aiae_cache, "AIAE")
    f_industry = _dag_pool.submit(_safe_warmup_task, warmup_industry_tracking, "Industry")
    f_factor = _dag_pool.submit(_safe_warmup_task, warmup_factor_data, "Factor")
    f_swing = _dag_pool.submit(_safe_warmup_task, warmup_swing_guard, "SwingGuard")

    # Barrier: 只等 ERP + AIAE (Dashboard 的依赖), 其他任务可以后台继续
    wait([f_erp, f_aiae], timeout=600)
    r_snap, e_snap = _get_snapshot()
    sched_logger.info("Phase 1 核心完成: ERP=%s, AIAE=%s (%.1fs)",
                      r_snap.get("ERP", "timeout"),
                      r_snap.get("AIAE", "timeout"),
                      _t.time() - _start)

    # ── Phase 2: Dashboard (依赖 ERP + AIAE 缓存) ──
    p2_start = _t.time()
    _set_warmup_status("Phase 2",
                       list(r_snap.keys()), ["Dashboard"],
                       ["GEM", "Snapshot", "SWR预热"])
    try:
        with_retry(warmup_dashboard_cache, "Dashboard_Warmup", 3, 60)
        _record_result("Dashboard")
    except Exception as e:
        _record_result("Dashboard", ok=False, err=e)
        sched_logger.error("Phase 2 Dashboard 失败: %s", e)
    sched_logger.info("Phase 2 Dashboard 完成 (%.1fs)", _t.time() - p2_start)

    # ── Phase 3: 后续并行任务 ──
    r_snap, _ = _get_snapshot()
    _set_warmup_status("Phase 3",
                       list(r_snap.keys()),
                       ["GEM", "Snapshot", "Accuracy", "SWR预热"],
                       [])

    def _phase3_gem():
        try:
            with_retry(warmup_gem_cache, "GEM_Warmup", 2, 60)
            _record_result("GEM")
        except Exception as e:
            _record_result("GEM", ok=False, err=e)

    def _phase3_snapshot():
        try:
            _ensure_daily_snapshot("daily_warmup")
            _record_result("Snapshot")
        except Exception as e:
            _record_result("Snapshot", ok=False, err=e)

    def _phase3_accuracy():
        try:
            from dashboard_modules.decision_engine import backfill_signal_accuracy
            backfill_signal_accuracy()
            _record_result("Accuracy")
        except Exception as e:
            sched_logger.warning("准确率回填失败 (非致命): %s", e)
            _record_result("Accuracy", ok=False, err=e)

    def _phase3_swr_preheat():
        """P1: 子页面 SWR 预加载 — 收盘后主动填充高频决策页面的 SWR 缓存"""
        _preheat_items = [
            ("swr_decision_hub", "dashboard_modules.decision_engine", "get_hub_data_with_events"),
            ("swr_risk_matrix", "dashboard_modules.decision_engine", "compute_risk_matrix"),
        ]
        for key, module, func_name in _preheat_items:
            try:
                import importlib
                mod = importlib.import_module(module)
                fn = getattr(mod, func_name)
                result = fn()
                if isinstance(result, dict):
                    payload = {"timestamp": _t.time(), "data": result}
                    cache_manager.set_json(key, payload)
                    sched_logger.info("SWR 预热完成: %s", key)
            except Exception as e:
                sched_logger.warning("SWR 预热失败 %s: %s", key, e)
        _record_result("SWR预热")

    f3_gem = _dag_pool.submit(_phase3_gem)
    f3_snap = _dag_pool.submit(_phase3_snapshot)
    f3_acc = _dag_pool.submit(_phase3_accuracy)
    f3_swr = _dag_pool.submit(_phase3_swr_preheat)

    # 等待 Phase 1 剩余任务 + Phase 3 全部完成
    wait([f_industry, f_factor, f_swing, f3_gem, f3_snap, f3_acc, f3_swr], timeout=600)

    # ── 收尾: Alert 扫描 + 状态广播 ──
    _run_alert_scan("daily_warmup")

    elapsed = round(_t.time() - _start, 1)
    final_results, final_errors = _get_snapshot()
    cache_manager.set_json("warmup_status", {
        "phase": "completed",
        "completed_at": datetime.now().isoformat(),
        "duration_sec": elapsed,
        "engines": final_results,
        "errors": final_errors if final_errors else None,
        "next_warmup": "tomorrow 15:35",
    })

    _dag_pool.shutdown(wait=False)
    sched_logger.info("收盘 DAG 预热管线完成 · 总耗时 %.1fs · 成功 %d · 错误 %d",
                      elapsed, len(final_results), len(final_errors))



def morning_warmup_callback():
    """盘前数据补偿拉取"""
    sched_logger.info(f"🌅 早间数据补偿流水线启动")
    with_retry(warmup_aiae_cache, "AIAE_Morning_Warmup", 3, 60)
    with_retry(warmup_industry_tracking, "Industry_Morning_Warmup", 2, 60)
    with_retry(warmup_dashboard_cache, "Dashboard_Morning_Warmup", 3, 60)
    # V21.2: 信号预警扫描 (盘前检测)
    _run_alert_scan("morning_warmup")
    # V3.2: 启动时自动补录 snapshot + decision_log (防止 15:35 回调缺失导致数据稀疏)
    _ensure_daily_snapshot("morning_warmup")
    sched_logger.info("早间补偿流水线完成")



def fred_daily_callback():
    """每日18:30 刷新FRED数据"""
    sched_logger.info("FRED 利率刷新触发")
    with_retry(warmup_rates_cache, "Rates_Warmup", 3, 60)


def us_aiae_warmup_callback():
    """美股AIAE定时预热 + 全球对比更新"""
    sched_logger.info("US AIAE 定时预热启动")
    with_retry(warmup_us_aiae_cache, "US_AIAE_Warmup", 3, 60)
    warmup_global_aiae_cache()
    sched_logger.info("US AIAE 预热完成")


def jp_aiae_warmup_callback():
    """日股AIAE定时预热 + 全球对比更新"""
    sched_logger.info("JP AIAE 定时预热启动")
    with_retry(warmup_jp_aiae_cache, "JP_AIAE_Warmup", 3, 60)
    warmup_global_aiae_cache()
    sched_logger.info("JP AIAE 预热完成")


def aaii_crawl_callback():
    """AAII Sentiment 每周五自动爬取"""
    sched_logger.info("AAII Sentiment 自动爬取启动")
    with_retry(warmup_aaii_sentiment, "AAII_Crawl", 2, 120)


def swing_guard_warmup_callback():
    """波段守卫定时预热: 15:40 收盘后刷新 (独立于 daily_warmup 的补充通道)"""
    sched_logger.info("Swing Guard 定时预热启动")
    with_retry(warmup_swing_guard, "SwingGuard_Scheduled", 2, 30)
    sched_logger.info("Swing Guard 预热完成")


def daily_report_callback():
    """V21.0: 每个交易日 16:35 自动生成投委会日报"""
    sched_logger.info("📄 投委会日报自动生成启动")
    try:
        from dashboard_modules.report_generator import auto_generate_report
        auto_generate_report()
        sched_logger.info("📄 投委会日报生成完成")
    except Exception as e:
        sched_logger.warning(f"日报自动生成失败 (非致命): {e}")


# ═══════════════════════════════════════════════════
#  V21.2: 信号预警扫描 (非致命包装)
# ═══════════════════════════════════════════════════

def _run_alert_scan(source: str):
    """安全执行预警扫描 (非致命, 不影响主流程)"""
    try:
        from services.alert_monitor import scan_and_alert
        alerts = scan_and_alert()
        if alerts:
            sched_logger.info(f"🔔 预警触发 [{source}]: {len(alerts)} 条")
        else:
            sched_logger.debug(f"预警扫描 [{source}]: 无触发")
    except Exception as e:
        sched_logger.warning(f"预警扫描失败 (非致命): {e}")


def alert_scan_callback():
    """盘中定时预警扫描 (每 10 分钟, 由 APScheduler 调用)"""
    _run_alert_scan("interval_scan")


def event_monitor_callback():
    """V22.2: 独立事件监控 — 每 5 分钟主动检测 VIX/AIAE/MR 跳变

    区别于 alert_scan (监控绝对阈值: VIX>30, JCS<25),
    event_monitor 监控变化量 (VIX Δ>25%, AIAE 跳档, MR 反转),
    并自动触发冲击传播评估 + 多通道推送。
    """
    try:
        from dashboard_modules.decision_engine import (
            _build_snapshot_from_cache, detect_market_events
        )
        snapshot = _build_snapshot_from_cache()
        if not snapshot:
            return
        events = detect_market_events(snapshot)
        if events:
            sched_logger.info(
                "⚡ 事件监控触发 %d 条: %s",
                len(events),
                [e["title"] for e in events],
            )
    except Exception as e:
        sched_logger.debug("事件监控异常 (非致命): %s", e)
