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
import threading
from datetime import datetime, timedelta

from services.cache_service import cache_manager
from services.logger import get_logger

logger = get_logger("warmup")


# ═══════════════════════════════════════════════════
#  基础工具
# ═══════════════════════════════════════════════════

def with_retry(func, name, max_retries=3, delay=300):
    """柔性重试机制: 避免 Tushare 等接口拥堵导致的单点故障"""
    for i in range(max_retries):
        try:
            func()
            return True
        except Exception as e:
            if i < max_retries - 1:
                logger.warning(f"{name} 失败: {e}。等待 {delay}s 重试 ({i+1}/{max_retries})")
                time.sleep(delay)
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
    触发时机: 每日 15:35 (A股收盘后 35 分钟，给 Tushare 数据更新缓冲)
    """
    from data_manager import FactorDataManager
    dm = FactorDataManager()
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


# ═══════════════════════════════════════════════════
#  全球 AIAE 四地对比缓存
# ═══════════════════════════════════════════════════

_AIAE_GLOBAL_LOCK = threading.Lock()


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
        except Exception:
            pass
        us_v1 = us_report.get('current', {}).get('aiae_v1', 25.0)
        jp_v1 = jp_report.get('current', {}).get('aiae_v1', 17.0)
        hk_v1 = hk_report.get('current', {}).get('aiae_v1', 14.0)
        us_regime = us_report.get('current', {}).get('regime', 3)
        jp_regime = jp_report.get('current', {}).get('regime', 3)
        hk_regime = hk_report.get('current', {}).get('regime', 3)
        vals = {'cn': cn_aiae_v1, 'us': us_v1, 'jp': jp_v1, 'hk': hk_v1}
        coldest = min(vals, key=vals.get)
        hottest = max(vals, key=vals.get)
        region_names = {'cn': 'A股', 'us': '美股', 'jp': '日股', 'hk': '港股'}
        recommendation = f"当前{region_names[coldest]}(AIAE={vals[coldest]:.1f}%)配置热度最低, 超配优先; {region_names[hottest]}(AIAE={vals[hottest]:.1f}%)最高, 谨慎配置"
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
                'coldest': coldest, 'hottest': hottest,
                'recommendation': recommendation,
            }
        }
        with _AIAE_GLOBAL_LOCK:
            cache_manager.set_json("aiae_global_last_update", time.time())
            cache_manager.set_json("aiae_global_report_data", data)
        logger.info(f"Global AIAE L1缓存预热完成 · US={us_v1:.1f}% JP={jp_v1:.1f}% HK={hk_v1:.1f}% CN={cn_aiae_v1:.1f}% · 最冷={region_names[coldest]}")
    except Exception as e:
        logger.error(f"Global AIAE 预热失败 (non-fatal): {e}")


# ═══════════════════════════════════════════════════
#  定时回调 (由 APScheduler 在 lifespan 中注册)
# ═══════════════════════════════════════════════════

sched_logger = get_logger("scheduler")


def daily_warmup_callback():
    """定时回调: 每日 15:35 收盘预热"""
    sched_logger.info(f"⏰ 收盘真实主动预热流水线启动")
    with_retry(warmup_erp_cache, "ERP_Warmup", 3, 300)
    with_retry(warmup_aiae_cache, "AIAE_Warmup", 3, 300)
    with_retry(warmup_industry_tracking, "Industry_Warmup", 2, 120)
    with_retry(warmup_dashboard_cache, "Dashboard_Warmup", 3, 300)
    with_retry(warmup_factor_data, "Factor_Sync", 3, 300)
    # Batch 11: 收盘后自动存档组合净值快照
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
            sched_logger.info(f"📸 组合快照已存档: {today} · 资产={val['total_asset']:,.0f}")
    except Exception as e:
        sched_logger.warning(f"组合快照存档失败 (非致命): {e}")
    # V16.0: 决策快照 (科学辅助决策模块)
    try:
        from dashboard_modules.decision_engine import log_daily_decision
        log_daily_decision()
        sched_logger.info("📋 决策快照已存档")
    except Exception as e:
        sched_logger.warning(f"决策快照存档失败 (非致命): {e}")
    # V16.0 Phase 2: 准确率回填 (T+5 市场收益)
    try:
        from dashboard_modules.decision_engine import backfill_signal_accuracy
        backfill_signal_accuracy()
    except Exception as e:
        sched_logger.warning(f"准确率回填失败 (非致命): {e}")
    sched_logger.info("收盘预热流水线完成")


def morning_warmup_callback():
    """盘前数据补偿拉取"""
    sched_logger.info(f"🌅 早间数据补偿流水线启动")
    with_retry(warmup_aiae_cache, "AIAE_Morning_Warmup", 3, 300)
    with_retry(warmup_industry_tracking, "Industry_Morning_Warmup", 2, 120)
    with_retry(warmup_dashboard_cache, "Dashboard_Morning_Warmup", 3, 300)
    sched_logger.info("早间补偿流水线完成")


def fred_daily_callback():
    """每日18:30 刷新FRED数据"""
    sched_logger.info("FRED 利率刷新触发")
    with_retry(warmup_rates_cache, "Rates_Warmup", 3, 300)


def us_aiae_warmup_callback():
    """美股AIAE定时预热 + 全球对比更新"""
    sched_logger.info("US AIAE 定时预热启动")
    with_retry(warmup_us_aiae_cache, "US_AIAE_Warmup", 3, 300)
    warmup_global_aiae_cache()
    sched_logger.info("US AIAE 预热完成")


def jp_aiae_warmup_callback():
    """日股AIAE定时预热 + 全球对比更新"""
    sched_logger.info("JP AIAE 定时预热启动")
    with_retry(warmup_jp_aiae_cache, "JP_AIAE_Warmup", 3, 300)
    warmup_global_aiae_cache()
    sched_logger.info("JP AIAE 预热完成")


def aaii_crawl_callback():
    """AAII Sentiment 每周五自动爬取"""
    sched_logger.info("AAII Sentiment 自动爬取启动")
    with_retry(warmup_aaii_sentiment, "AAII_Crawl", 2, 600)
