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

from fastapi import FastAPI, UploadFile, File
from contextlib import asynccontextmanager
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
# yfinance removed — VIX/CNY via FRED/CNBC (see fetch_vix_realtime / dashboard)
import tushare as ts
import pandas as pd
import uvicorn
import asyncio
import requests
import re
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
import time
import traceback
import threading
import copy
from datetime import datetime, timedelta
from config import TUSHARE_TOKEN
from mean_reversion_engine import run_strategy, detect_regime, get_all_regime_params, load_regime_params, needs_reoptimize
from dividend_trend_engine import run_dividend_strategy
from audit_engine import run_full_audit
from momentum_rotation_engine import run_momentum_strategy
from momentum_backtest_engine import run_momentum_backtest, run_momentum_optimize
from erp_timing_engine import get_erp_engine
from aiae_engine import get_aiae_engine, AIAE_RUN_ALL_WEIGHTS, REGIMES as AIAE_REGIMES
from aiae_us_engine import get_us_aiae_engine
from aiae_jp_engine import get_jp_aiae_engine
from erp_hk_engine import get_hk_erp_engine
from aiae_hk_engine import get_hk_aiae_engine
from data_manager import FactorDataManager
from industry_engine import IndustryEngine
from core_etf_config import CORE_ETFS, CORE_ETF_CODES, CORE_ETF_NAME_MAP, ETF_CONSTITUENTS, FALLBACK_MOMENTUM
from portfolio_engine import PortfolioEngine
from backtest_engine import AlphaBacktester
from factor_analyzer import FactorAnalyzer
from strategies_backtest import (
    mean_reversion_strategy_vectorized,
    dividend_trend_strategy_vectorized,
    momentum_rotation_strategy_vectorized,
    erp_timing_strategy_vectorized
)
from erp_backtest_data import prepare_erp_backtest_data

import numpy as np

executor = ThreadPoolExecutor(max_workers=10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """V2.0 Lifespan: 替代 deprecated @app.on_event('startup')"""
    # ── Startup ──
    threading.Thread(target=_warmup_erp_cache, daemon=True).start()
    threading.Thread(target=_warmup_rates_cache, daemon=True).start()
    threading.Thread(target=lambda: get_aiae_engine().generate_report(), daemon=True).start()
    threading.Thread(target=_warmup_dashboard_cache, daemon=True).start()
    threading.Thread(target=_hot_data_reactor, daemon=True).start()
    _schedule_daily_warmup()
    _schedule_morning_warmup()
    _schedule_fred_daily_refresh()
    _schedule_us_aiae_warmup()
    _schedule_jp_aiae_warmup()
    _schedule_aaii_weekly_crawl()
    threading.Thread(target=_warmup_global_aiae_cache, daemon=True).start()
    threading.Thread(target=lambda: _warmup_hk_erp_cache(), daemon=True).start()
    threading.Thread(target=lambda: _warmup_hk_aiae_cache(), daemon=True).start()
    print("[Startup] AlphaCore 服务启动完成 · 引擎常驻预热就绪 · 调度器(06:30US/08:30CN/15:30JP/16:30HK/15:35A/18:30FRED/周五AAII)已激活")
    yield
    # ── Shutdown ──
    print("[Shutdown] AlphaCore 服务关闭")


app = FastAPI(title="AlphaCore Quant API", description="AlphaCore量化终端底层数据接口", lifespan=lifespan)

# 配置 CORS 跨域
# P1-3: CORS 白名单 (生产环境仅允许自身域名 + 本地开发)
_CORS_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://8.219.112.184:8000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 全局缓存结构 (In-Memory Cache for Production Stability)
_STRATEGY_LOCK = threading.Lock()  # P0-2: 线程安全保护
STRATEGY_CACHE = {
    "last_update": None,
    "dashboard_data": None,
    "aiae_ctx": None,  # P0-1: 全量刷新时存储原始 aiae_ctx，Hot-Refresh 直接复用
    "strategy_results": {
        "mr": None,
        "mom": None,
        "div": None
    }
}

# 海外 AIAE 全局缓存 (V1.1: L1 API结果级缓存)
_AIAE_GLOBAL_LOCK = threading.Lock()  # P0-2: 线程安全保护
AIAE_GLOBAL_CACHE = {
    "last_update": None,
    "report_data": None
}

def _get_cache_ttl() -> int:
    """智能缓存 TTL：盘中5分钟 / 盘后1小时 / 周末24小时"""
    now = datetime.now()
    weekday = now.weekday()  # 0=周一 ... 6=周日
    h, m = now.hour, now.minute
    if weekday >= 5:               # 周末
        return 86400
    in_session = (h == 9 and m >= 30) or (10 <= h < 15)  # 09:30-15:00
    return 300 if in_session else 3600

CACHE_TTL = 3600  # 向下兼容，实际使用 _get_cache_ttl()

def _get_global_aiae_ttl() -> int:
    """海外AIAE缓存TTL: 美股盘中30min / 盘后4h / 周末24h (UTC+8)"""
    now = datetime.now()
    if now.weekday() >= 5:
        return 86400    # 周末 24h
    h = now.hour
    # 美股盘中 (北京 21:30~04:00)
    if h >= 21 or h < 4:
        return 1800     # 30min
    return 14400        # 4h

# ─── 收盘后自动预热缓存 (每日 15:30 触发) ───

def with_retry(func, name, max_retries=3, delay=300):
    """柔性重试机制: 避免 Tushare 等接口拥堵导致的单点故障"""
    for i in range(max_retries):
        try:
            func()
            return True
        except Exception as e:
            if i < max_retries - 1:
                print(f"[Retry] {name} 失败: {e}。等待 {delay}秒后重试 ({i+1}/{max_retries})...")
                time.sleep(delay)
            else:
                print(f"[Retry] {name} 最终失败，已达最大重试次数。")
                return False

def _warmup_erp_cache():
    """后台预热 ERP 引擎缓存: 拉取最新 PE/Yield/M1 + 生成报告"""
    engine = get_erp_engine()
    report = engine.generate_report()
    status = report.get('status', 'unknown')
    if status != "success":
        raise Exception(f"ERP report failed with status: {status}")
    snap = report.get('current_snapshot', {})
    erp = snap.get('erp_value', '?')
    print(f"[ERP Warmup] 预热完成 · status={status} · ERP={erp}%")

def _warmup_aiae_cache():
    """预热 AIAE 引擎缓存 (V7.0/V8.1)"""
    engine = get_aiae_engine()
    engine.refresh() # V8.1: 强制劈开 L1 缓存锁
    report = engine.generate_report()
    status = report.get('status', 'unknown')
    if status != "success":
        raise Exception(f"AIAE report failed with status: {status}")
    print(f"[AIAE Warmup] 预热完成 · status={status}")

def _hot_data_reactor():
    """后台高频预热循环：盘中提取 VIX/CNY，主动写入缓存"""
    from dashboard_modules.fetch_macro import fetch_vix_for_dashboard, fetch_cny_for_dashboard
    while True:
        try:
            now_dt = datetime.now()
            is_trading_hours = now_dt.weekday() < 5 and ((now_dt.hour == 9 and now_dt.minute >= 30) or (10 <= now_dt.hour < 15))
            with _STRATEGY_LOCK:
                has_strategy_cache = STRATEGY_CACHE["dashboard_data"] is not None
                
            if is_trading_hours and has_strategy_cache:
                hot_vix, prev_vix = fetch_vix_for_dashboard()
                cny_result = fetch_cny_for_dashboard()
                
                hot_vix_change = ((hot_vix - prev_vix) / prev_vix * 100) if prev_vix > 0 else 0
                hot_vix_status = "down" if hot_vix_change < 0 else "up"
                hot_vix_analysis = get_vix_analysis(hot_vix)
                
                with _STRATEGY_LOCK:
                    hot_data = copy.deepcopy(STRATEGY_CACHE["dashboard_data"])
                    _hot_aiae_ctx = STRATEGY_CACHE.get("aiae_ctx")
                
                mc = hot_data.get("data", {}).get("macro_cards", {})
                if "vix" in mc:
                    mc["vix"]["value"] = round(hot_vix, 2)
                    mc["vix"]["trend"] = f"{round(hot_vix_change, 1)}%"
                    mc["vix"]["status"] = hot_vix_status
                    mc["vix"]["regime"] = hot_vix_analysis["label"]
                    mc["vix"]["class"] = hot_vix_analysis["class"]
                    mc["vix"]["desc"] = hot_vix_analysis.get("desc", "")
                    mc["vix"]["percentile"] = hot_vix_analysis.get("percentile", 0)
                if mc.get("regime_banner"):
                    mc["regime_banner"]["vix"] = round(hot_vix, 2)
                    mc["regime_banner"]["vix_label"] = hot_vix_analysis.get("label", "—")
                if mc.get("market_temp") and "multiplier" in hot_vix_analysis:
                    mc["market_temp"]["market_vix_multiplier"] = hot_vix_analysis["multiplier"]
                
                if "tomorrow_plan" in mc:
                    mc["tomorrow_plan"] = get_tomorrow_plan(hot_vix_analysis, mc.get("market_temp", {}).get("value", 50), _hot_aiae_ctx)
                hot_data["timestamp"] = now_dt.isoformat()
                
                with _STRATEGY_LOCK:
                    STRATEGY_CACHE["last_update"] = time.time()
                    STRATEGY_CACHE["dashboard_data"] = hot_data
        except Exception as e:
            print(f"[Reactor Warning] {e}")
        time.sleep(120)

def _warmup_dashboard_cache():
    """后台预热量化总览缓存: True Zero-Wait (真实主动流水线预热)"""
    # 主动触发全数据流水线
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        data = loop.run_until_complete(_build_dashboard_data_full())
        if data and data.get("status") == "success":
            print(f"[Dashboard Warmup] 主动预热成功, 零等待缓存已就绪")
        else:
            print("[Dashboard Warmup] 预热后返回状态异常，部分缓存建立失败")
    except Exception as e:
        print(f"[Dashboard Warmup] 失败: {e}")
    finally:
        loop.close()

def _schedule_daily_warmup():
    """计算距下一个 15:35 的秒数, 注册定时器"""
    now = datetime.now()
    # V5.0: 目标 15:35 (给 Tushare 一些IR后的缓冲)
    target = now.replace(hour=15, minute=35, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    # 跳过周末
    while target.weekday() >= 5:  # 5=周六, 6=周日
        target += timedelta(days=1)
    delay = (target - now).total_seconds()
    print(f"[Scheduler] 下次预热: {target.strftime('%Y-%m-%d %H:%M')} ({delay/3600:.1f}h后)")
    timer = threading.Timer(delay, _daily_warmup_callback)
    timer.daemon = True
    timer.start()

def _schedule_morning_warmup():
    """早间 08:30 数据刷新定时器 (专解决融资融券等延迟发布数据的抓取)"""
    now = datetime.now()
    target = now.replace(hour=8, minute=30, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    delay = (target - now).total_seconds()
    print(f"[Scheduler] 早间预热: {target.strftime('%Y-%m-%d %H:%M')} ({delay/3600:.1f}h后)")
    timer = threading.Timer(delay, _morning_warmup_callback)
    timer.daemon = True
    timer.start()

def _warmup_industry_tracking():
    """V6.0: 产业追踪自动预热 — 同步12只核心ETF日线 + 预计算指标写入缓存"""
    from data_manager import FactorDataManager
    mgr = FactorDataManager()
    # Step 1: 同步最新日线数据 (Tushare asset='E')
    mgr.sync_daily_prices(CORE_ETF_CODES, asset='E')
    print(f"[Industry Warmup] 12只核心ETF日线同步完成")
    # Step 2: 主动触发一次 tracking 指标计算，填充 latest 缓存
    #         通过 HTTP 内部调用太重，直接复用 run_ind_analysis 的核心逻辑
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # 用 None date 触发 latest 路径
        from main import get_industry_tracking
        result = loop.run_until_complete(get_industry_tracking(date=None))
        loop.close()
        cached_count = len(result.get('data', {}).get('sector_heatmap', []))
        print(f"[Industry Warmup] 预热完成 · {cached_count} 只ETF指标已写入 latest 缓存")
    except Exception as e:
        print(f"[Industry Warmup] 指标预计算失败 (数据已同步): {e}")

def _morning_warmup_callback():
    """盘前数据补偿拉取"""
    print(f"==================================================")
    print(f"[Scheduler] 🌅 早间数据补偿流水线 @ {datetime.now().strftime('%H:%M:%S')}")
    # 强制破防 L1 缓存以拉取最新融资数据
    with_retry(_warmup_aiae_cache, "AIAE_Morning_Warmup", 3, 300)
    # V6.0: 产业追踪ETF同步 + 指标预计算
    with_retry(_warmup_industry_tracking, "Industry_Morning_Warmup", 2, 120)
    # 更新数据后再同步更新大总览 Dashboard
    with_retry(_warmup_dashboard_cache, "Dashboard_Morning_Warmup", 3, 300)
    _schedule_morning_warmup()
    print(f"==================================================")

def _warmup_factor_data():
    """
    V5.0: 收盘后自动同步因子数据 (日线 + 财务指标)
    触发时机: 每日 15:35 (A股收盘后 35 分钟，给 Tushare 数据更新缓冲)
    """
    from data_manager import FactorDataManager
    dm = FactorDataManager()
    stocks = dm.get_all_stocks()
    # 默认同步 Top 30 様本池 (与因子分析默认配置一致)
    sample = stocks.head(30)['ts_code'].tolist()
    result = dm.smart_sync(sample)
    synced = result.get('synced', False)
    if not synced and "数据已是最新" not in str(result):
         pass # 视为成功，可能真的最新
    latest = result.get('freshness', {}).get('daily_latest', '?')
    print(f"[Factor Sync] {'同步完成' if synced else '数据已是最新'} · 最新日线: {latest}")

def _warmup_rates_cache():
    """V1.5: 后台预热利率择时引擎缓存: 拉取最新 FRED 数据 + 生成报告"""
    from rates_strategy_engine import warmup_rates_cache
    warmup_rates_cache()

def _schedule_fred_daily_refresh():
    """注册 FRED 数据每日刷新定时器 (北京18:30 = 美东6:30AM)
    FRED国债数据在美东6AM更新, 给半小时缓冲"""
    now = datetime.now()
    target = now.replace(hour=18, minute=30, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    # 周末跳过
    while target.weekday() >= 5:
        target += timedelta(days=1)
    delay = (target - now).total_seconds()
    print(f"[Scheduler] FRED利率刷新: {target.strftime('%Y-%m-%d %H:%M')} ({delay/3600:.1f}h后)")
    timer = threading.Timer(delay, _fred_daily_callback)
    timer.daemon = True
    timer.start()

def _fred_daily_callback():
    """每日18:30 刷新FRED数据 + 注册明天的"""
    print(f"[Scheduler] FRED利率刷新触发 @ {datetime.now().strftime('%H:%M:%S')}")
    with_retry(_warmup_rates_cache, "Rates_Warmup", 3, 300)
    _schedule_fred_daily_refresh()

def _daily_warmup_callback():
    """定时回调: 执行全部预热 + 注册下一次"""
    print(f"==================================================")
    print(f"[Scheduler] ⏰ 收盘真实主动预热流水线 @ {datetime.now().strftime('%H:%M:%S')}")
    
    # 阶梯式重试
    with_retry(_warmup_erp_cache, "ERP_Warmup", 3, 300)
    with_retry(_warmup_aiae_cache, "AIAE_Warmup", 3, 300)
    # V6.0: 产业追踪ETF收盘同步 + 指标预热 (必须在 Dashboard 前，因为 Dashboard 可能读取)
    with_retry(_warmup_industry_tracking, "Industry_Warmup", 2, 120)
    with_retry(_warmup_dashboard_cache, "Dashboard_Warmup", 3, 300)
    with_retry(_warmup_factor_data, "Factor_Sync", 3, 300)
    
    _schedule_daily_warmup()  # 注册明天的
    print(f"==================================================")

# --- V1.1: 海外 AIAE 定时预热 (US 06:30 / JP 15:30 / AAII 周五09:00) ---

def _warmup_us_aiae_cache():
    """预热 US AIAE 引擎: 清除内存缓存 -> 重新拉取 FRED 数据 -> 生成报告"""
    engine = get_us_aiae_engine()
    engine.refresh()
    report = engine.generate_report()
    status = report.get('status', 'unknown')
    v1 = report.get('current', {}).get('aiae_v1', '?')
    print(f"[US AIAE Warmup] 预热完成 · status={status} · AIAE={v1}%")
    if status != 'success':
        raise Exception(f"US AIAE warmup failed: {status}")

def _warmup_jp_aiae_cache():
    """预热 JP AIAE 引擎: 清除内存缓存 -> 重新拉取 TOPIX/M2 -> 生成报告"""
    engine = get_jp_aiae_engine()
    engine.refresh()
    report = engine.generate_report()
    status = report.get('status', 'unknown')
    v1 = report.get('current', {}).get('aiae_v1', '?')
    print(f"[JP AIAE Warmup] 预热完成 · status={status} · AIAE={v1}%")
    if status != 'success':
        raise Exception(f"JP AIAE warmup failed: {status}")

def _warmup_aaii_sentiment():
    """周期性爬取 AAII Sentiment Survey: 强制重新爬取并写入文件"""
    engine = get_us_aiae_engine()
    crawled = engine._crawl_aaii_sentiment()
    if crawled:
        engine._aaii_data = crawled
        print(f"[AAII Warmup] 爬取成功: spread={crawled.get('spread', 0):.1f}%")
    else:
        print(f"[AAII Warmup] 爬取失败, 保留旧数据")

def _warmup_hk_erp_cache():
    """预热 HK ERP 引擎: HSI + HSTECH 双轨"""
    for mkt in ["HSI", "HSTECH"]:
        engine = get_hk_erp_engine(mkt)
        report = engine.generate_report()
        status = report.get('status', 'unknown')
        score = report.get('signal', {}).get('score', '?')
        print(f"[HK ERP Warmup] {mkt} 预热完成 · status={status} · score={score}")
        if status not in ('success', 'fallback'):
            raise Exception(f"HK ERP {mkt} warmup failed: {status}")

def _warmup_hk_aiae_cache():
    """预热 HK AIAE 引擎"""
    engine = get_hk_aiae_engine()
    engine.refresh()
    report = engine.generate_report()
    status = report.get('status', 'unknown')
    v1 = report.get('current', {}).get('aiae_v1', '?')
    print(f"[HK AIAE Warmup] 预热完成 · status={status} · AIAE={v1}%")
    if status not in ('success', 'fallback'):
        raise Exception(f"HK AIAE warmup failed: {status}")

def _warmup_global_aiae_cache():
    """后台预热海外AIAE: US+JP+HK引擎并行, 写入L1缓存 (V2.0: 四地对比)"""
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
            AIAE_GLOBAL_CACHE['last_update'] = time.time()
            AIAE_GLOBAL_CACHE['report_data'] = data
        print(f"[Global AIAE Warmup] L1缓存预热完成 · US={us_v1:.1f}% JP={jp_v1:.1f}% HK={hk_v1:.1f}% CN={cn_aiae_v1:.1f}% · 最冷={region_names[coldest]}")
    except Exception as e:
        print(f"[Global AIAE Warmup] 预热失败 (non-fatal): {e}")

def _schedule_us_aiae_warmup():
    """美股AIAE数据刷新: 北京06:30 (美东收盘后, FRED数据更新)"""
    now = datetime.now()
    target = now.replace(hour=6, minute=30, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    delay = (target - now).total_seconds()
    print(f"[Scheduler] US AIAE预热: {target.strftime('%Y-%m-%d %H:%M')} ({delay/3600:.1f}h后)")
    timer = threading.Timer(delay, _us_aiae_warmup_callback)
    timer.daemon = True
    timer.start()

def _us_aiae_warmup_callback():
    print(f"==================================================")
    print(f"[Scheduler] US AIAE定时预热 @ {datetime.now().strftime('%H:%M:%S')}")
    with_retry(_warmup_us_aiae_cache, "US_AIAE_Warmup", 3, 300)
    _warmup_global_aiae_cache()
    _schedule_us_aiae_warmup()
    print(f"==================================================")

def _schedule_jp_aiae_warmup():
    """日股AIAE数据刷新: 北京15:30 (東証収盘后)"""
    now = datetime.now()
    target = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    delay = (target - now).total_seconds()
    print(f"[Scheduler] JP AIAE预热: {target.strftime('%Y-%m-%d %H:%M')} ({delay/3600:.1f}h后)")
    timer = threading.Timer(delay, _jp_aiae_warmup_callback)
    timer.daemon = True
    timer.start()

def _jp_aiae_warmup_callback():
    print(f"==================================================")
    print(f"[Scheduler] JP AIAE定时预热 @ {datetime.now().strftime('%H:%M:%S')}")
    with_retry(_warmup_jp_aiae_cache, "JP_AIAE_Warmup", 3, 300)
    _warmup_global_aiae_cache()
    _schedule_jp_aiae_warmup()
    print(f"==================================================")

def _schedule_aaii_weekly_crawl():
    """AAII Sentiment 每周五09:00自动爬取 (美东周四发布)"""
    now = datetime.now()
    days_ahead = (4 - now.weekday()) % 7  # 4=Friday
    if days_ahead == 0 and now.hour >= 9:
        days_ahead = 7
    target = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
    delay = (target - now).total_seconds()
    print(f"[Scheduler] AAII爬取: {target.strftime('%Y-%m-%d %H:%M')} ({delay/3600:.1f}h后)")
    timer = threading.Timer(delay, _aaii_crawl_callback)
    timer.daemon = True
    timer.start()

def _aaii_crawl_callback():
    print(f"[Scheduler] AAII Sentiment 自动爬取 @ {datetime.now().strftime('%H:%M:%S')}")
    with_retry(_warmup_aaii_sentiment, "AAII_Crawl", 2, 600)
    _schedule_aaii_weekly_crawl()

# [DEPRECATED] @app.on_event("startup") 已迁移至 lifespan context manager (L57-79)
# 删除时间: 2026-04-15  原因: FastAPI deprecated on_event, 使用 lifespan 替代


# --- [DEPRECATED V12.0] AlphaCore DMSO Sub-Engines ---
# 以下函数已迁移至 dashboard_modules/market_temp.py (Issue #14):
#   get_margin_risk_ratio, get_market_breadth, get_liquidity_crisis_signal,
#   get_ah_premium_adj, get_real_turnover_score, get_real_erp_data
# 以下函数已被 AIAE×ERP 联合矩阵完全替代 (V12.0):
#   get_regime_allocation, apply_strategy_filters (旧版3参)
# 删除时间: 2026-04-15  原因: dashboard_modules 拆分后的残留死代码

# --- [DEPRECATED V7.0] compute_scientific_position() 已删除 ---
# 原五因子仓位引擎 (VIX/资金/温度/ERP/信号) 已由 AIAE×ERP 联合矩阵取代。
# 当前仓位决策入口: aiae_hk_engine.get_run_all_weights() → main.py L1247
# 删除时间: 2026-04-12  删除原因: dead code + 权重注释与现行系统矛盾


def get_vix_analysis(vix_val: float):
    """V4.2 VIX Professional 4-Tier Protocol (Institutional Grade)"""
    # 52周范围参考：13.38 - 60.13
    vix_min, vix_max = 13.38, 60.13
    percentile = min(100, max(0, (vix_val - vix_min) / (vix_max - vix_min) * 100))
    
    res = {}
    if vix_val < 15:
        res = {
            "label": "🟢 极度平静", 
            "multiplier": 1.05, 
            "class": "vix-status-low", 
            "desc": "风险低估，避险布局",
            "percentile": round(percentile, 1)
        }
    elif vix_val < 25:
        res = {
            "label": "🟡 正常震荡", 
            "multiplier": 1.0, 
            "class": "vix-status-norm", 
            "desc": "市场常态，结构性调仓",
            "percentile": round(percentile, 1)
        }
    elif vix_val < 35:
        res = {
            "label": "🔴 高度警觉", 
            "multiplier": 0.75, 
            "class": "vix-status-alert", 
            "desc": "当前临界区，加强风控",
            "percentile": round(percentile, 1)
        }
    else:
        res = {
            "label": "🔴🔴 极端恐慌", 
            "multiplier": 0.5, 
            "class": "vix-status-crisis", 
            "desc": "防守优先，等待企稳",
            "percentile": round(percentile, 1)
        }
    res["vix_val"] = vix_val
    return res

def get_position_path(current_pos: float, vix_analysis: dict) -> list[float]:
    """
    AlphaCore V4.5: 5-Day Position Pathing Engine
    外推未来 5 个交易日的阶梯式仓位建议路径
    """
    v_val = vix_analysis.get('vix_val', 20)
    v_p = vix_analysis.get('percentile', 50)
    
    path = []
    # 模拟路径：基于 VIX 向常态(20)回归的假设进行预测
    for i in range(1, 6):
        # 回归步长：15% 每周期
        regression_factor = 0.15 * i
        projected_vix = v_val + (20 - v_val) * regression_factor
        
        # 仓位对冲逻辑：VIX 每变动 1点，对仓位影响约 2-3%
        vix_gap = v_val - projected_vix
        step_pos = current_pos * (1 + vix_gap * 0.02)
        
        # 边界约束 (10% - 100%)
        path.append(round(max(10, min(100, step_pos)), 1))
    return path

def _synthesize_directives(aiae_ctx, vix_analysis):
    """V2.0 三因子决策树 → 3行可执行指令"""
    regime = aiae_ctx["regime"]
    cap = aiae_ctx["cap"]
    erp_tier = aiae_ctx.get("erp_tier", "neutral")
    vix_val = vix_analysis.get("vix_val", 20)
    regime_info = aiae_ctx["regime_info"]

    # Line 1: AIAE 主指令 (永远来自 regime)
    d1 = {
        "priority": "primary", "icon": "🎯",
        "text": f"AIAE {regime_info['emoji']} {regime_info['cn']} Cap{cap}% → {regime_info['action']}",
        "color": regime_info["color"],
    }

    # Line 2: ERP 验证 (确认 or 警告)
    erp_confirms = (erp_tier == "bull" and regime <= 3) or \
                   (erp_tier == "bear" and regime >= 4)
    if erp_confirms:
        d2_text = f"ERP {aiae_ctx.get('erp_val', '--')}% {aiae_ctx.get('erp_label', '--')} → 验证主轴方向"
        d2_color = "#10b981"
        d2_icon = "✅"
    elif erp_tier == "bull" and regime >= 4:
        d2_text = f"ERP {aiae_ctx.get('erp_val', '--')}% {aiae_ctx.get('erp_label', '--')} → ⚠ 矛盾! 估值低但AIAE偏热"
        d2_color = "#f59e0b"
        d2_icon = "⚠️"
    else:
        d2_text = f"ERP {aiae_ctx.get('erp_val', '--')}% {aiae_ctx.get('erp_label', '--')} → 中性参考"
        d2_color = "#94a3b8"
        d2_icon = "📊"
    d2 = {"priority": "confirm", "icon": d2_icon, "text": d2_text, "color": d2_color}

    # Line 3: VIX 风控 (通过 or 警报)
    if vix_val >= 35:
        d3 = {"priority": "risk", "icon": "🚨",
              "text": f"VIX {vix_val} 极端恐慌 → 风控降级Cap×0.5, 停手观望",
              "color": "#ef4444"}
    elif vix_val >= 25:
        d3 = {"priority": "risk", "icon": "⚠️",
              "text": f"VIX {vix_val} 高度紧张 → 风控边际Cap×0.75, 增配红利",
              "color": "#f97316"}
    else:
        d3 = {"priority": "risk", "icon": "🛡️",
              "text": f"VIX {vix_val} 正常 → 风控不触发",
              "color": "#94a3b8"}

    return [d1, d2, d3]




def get_tomorrow_plan(vix_analysis, temp_score, aiae_ctx=None):
    """V2.0: 明日交易计划 · AIAE五档主轴 + ERP/VIX 验证
    
    当 aiae_ctx 传入时, 使用 AIAE×ERP×VIX 三因子决策树; 否则降级为旧版 VIX 4阶查表。
    """
    v_val = vix_analysis.get('vix_val', 20)

    # ========== 新版 V2.0 逻辑 ==========
    if aiae_ctx and aiae_ctx.get("regime"):
        regime = aiae_ctx["regime"]
        regime_info = aiae_ctx["regime_info"]
        cap = aiae_ctx["cap"]

        # 1. primary_regime: 决策锚
        primary_regime = {
            "tier": regime,
            "emoji": regime_info["emoji"],
            "cn": regime_info["cn"],
            "aiae_v1": aiae_ctx.get("aiae_v1", 0),
            "cap": cap,
            "cap_range": regime_info.get("position", "50-65%"),
            "action": regime_info["action"],
            "action_detail": regime_info.get("desc", ""),
        }

        # 2. validators: ERP + VIX 验证维度
        erp_tier = aiae_ctx.get("erp_tier", "neutral")
        erp_confirms = (erp_tier == "bull" and regime <= 3) or \
                       (erp_tier == "bear" and regime >= 4)
        risk_override = v_val >= 30
        vix_mult = vix_analysis.get("multiplier", 1.0)
        validators = {
            "erp": {
                "value": aiae_ctx.get("erp_val", 0),
                "label": aiae_ctx.get("erp_label", "--"),
                "erp_tier": erp_tier,
                "confirms": erp_confirms,
            },
            "vix": {
                "value": v_val,
                "label": vix_analysis.get("label", ""),
                "risk_override": risk_override,
                "multiplier": vix_mult,
            },
        }

        # 3. regime_matrix: 五档操作矩阵
        _vix_cross = {
            1: "VIX>30时分批介入", 2: "VIX<20加速建仓", 3: "VIX>30启动减仓",
            4: "VIX<15警惕拥挤", 5: "任何VIX都清仓"
        }
        regime_matrix = []
        for t in range(1, 6):
            ri = AIAE_REGIMES.get(t, AIAE_REGIMES[3])
            regime_matrix.append({
                "tier": t,
                "emoji": ri["emoji"],
                "cn": ri["cn"],
                "range": ri["range"],
                "cap_range": ri["position"],
                "action": f"{ri['action']} · {ri['desc']}",
                "vix_cross": _vix_cross.get(t, ""),
                "active": t == regime,
            })

        # 4. directives: 三因子指令合成
        directives = _synthesize_directives(aiae_ctx, vix_analysis)

        # 5. scenarios: AIAE+VIX+ERP 三轴情景预判
        scenarios = [
            {"condition": f"AIAE上行至{'Ⅴ' if regime == 4 else 'Ⅳ'}级" if regime <= 4 else "AIAE维持Ⅴ级",
             "action": "启动系统减仓至40%以下" if regime <= 3 else ("3天清仓无例外" if regime >= 5 else "继续每周减仓5%"),
             "type": "aiae_upgrade"},
            {"condition": "VIX突破30+",
             "action": f"风控降级Cap×0.75 + 增配红利" if v_val < 30 else "维持风控降级状态",
             "type": "vix_alert"},
            {"condition": "ERP跌破3%",
             "action": "估值吸引力下降·降低进攻权重",
             "type": "erp_shift"},
        ]

        # 6. risk_panel: 三大预警
        margin_heat_val = aiae_ctx.get("margin_heat", 2.0)
        slope_val = aiae_ctx.get("slope", 0)
        fund_pos_val = aiae_ctx.get("fund_position", 80)
        risk_panel = {
            "margin_heat": {
                "value": margin_heat_val,
                "threshold": 3.5,
                "status": "danger" if margin_heat_val > 3.5 else ("warning" if margin_heat_val > 2.5 else "safe"),
            },
            "slope": {
                "value": slope_val,
                "threshold": 1.5,
                "status": "danger" if abs(slope_val) > 1.5 else "safe",
                "direction": aiae_ctx.get("slope_direction", "flat"),
            },
            "fund_position": {
                "value": fund_pos_val,
                "threshold": 90,
                "status": "danger" if fund_pos_val > 90 else ("warning" if fund_pos_val > 85 else "safe"),
            },
            "overall_risk": "high" if margin_heat_val > 3.5 or abs(slope_val) > 1.5 else (
                "medium" if margin_heat_val > 2.5 or fund_pos_val > 85 else "low"
            ),
        }

        # 7. 兼容旧字段
        framework_compat = [d["text"] for d in directives]
        tactics_compat = {"regime": f"{regime_info['emoji']} Ⅲ级 {regime_info['cn']}" if regime == 3 else f"{regime_info['emoji']} {'Ⅰ' if regime==1 else 'Ⅱ' if regime==2 else 'Ⅲ' if regime==3 else 'Ⅳ' if regime==4 else 'Ⅴ'}级 {regime_info['cn']}"}
        scenarios_compat = [{"case": s["condition"], "action": s["action"]} for s in scenarios]

        return {
            "primary_regime": primary_regime,
            "validators": validators,
            "regime_matrix": regime_matrix,
            "directives": directives,
            "scenarios": scenarios,
            "risk_panel": risk_panel,
            # 兼容旧字段
            "framework": framework_compat,
            "current_tactics": tactics_compat,
        }

    # ========== 旧版降级: VIX 4阶查表 (无 aiae_ctx) ==========
    matrix = [
        {"id": "calm", "regime": "🟢 极度活跃", "vix_range": "< 15",
         "tactics": "进攻：主攻低位AI/算力", "pos": "85-100%", "active": v_val < 15},
        {"id": "normal", "regime": "🟡 常态回归", "vix_range": "15-25",
         "tactics": "稳健：20日线择时对焦", "pos": "60-85%", "active": 15 <= v_val < 25},
        {"id": "alert", "regime": "🔴 高度警觉", "vix_range": "25-35",
         "tactics": "防御：增配红利/低波", "pos": "35-60%", "active": 25 <= v_val < 35},
        {"id": "crisis", "regime": "🔴🔴 极端恐慌", "vix_range": "> 35",
         "tactics": "熔断：现金为王，观察", "pos": "10-35%", "active": v_val >= 35},
    ]
    curr = next((m for m in matrix if m['active']), matrix[1])
    if v_val < 25:
        framework = ["🔥 优先：适度加仓硬科技龙头", "💎 持有：算力/AI 核心资产", "📊 布局：科创50/创业板ETF"]
    elif v_val < 35:
        framework = ["🛡️ 优先：严格执行20日止损线", "🌊 避险：增配中字头红利", "⚖️ 调仓：卖出高波非核心标的"]
    else:
        framework = ["⚠️ 核心：战略防御，保留现金", "🥇 避险：关注黄金/避险资产", "🛑 熔断：拒绝一切左侧接盘"]
    scenarios = [{"case": "VIX<18", "action": "加仓科技主线"}, {"case": "VIX>30", "action": "降仓至50%以下"}]
    return {"regime_matrix": matrix, "current_tactics": curr, "framework": framework, "scenarios": scenarios}

def get_institutional_mindset(temp: float) -> str:
    """实战对策心态矩阵 (V3.8) - 严格映射统一阶梯"""
    if temp >= 85: return "⚡ 离场观望，宁缺毋滥"
    if temp >= 65: return "🏹 乘胜追击，聚焦领涨"
    if temp >= 45: return "⚖️ 仓位中型，等待分歧"
    if temp >= 25: return "🎯 精准打击，聚焦 Alpha"
    return "💎 别人恐惧，战略建仓"

def get_tactical_label(final_pos, temp, erp_z, crisis):
    """
    根据 V3.6 矩阵生成实战标签 (Position Scaling Matrix)
    """
    if crisis: return "0% (流动性熔断)"
    if temp > 90: return "0% (极度过热)"
    
    if final_pos >= 90: return f"{int(final_pos)}% (代际大底)"
    if final_pos >= 75: return f"{int(final_pos)}% (黄金布局)"
    if final_pos >= 55: return f"{int(final_pos)}% (趋势共振)"
    if final_pos >= 45: return f"{int(final_pos)}% (动态平衡)"
    if final_pos >= 35: return f"{int(final_pos)}% (战略超配)"
    if final_pos >= 25: return f"{int(final_pos)}% (防御窗口)"
    if final_pos >= 15: return f"{int(final_pos)}% (风险预警)"
    return f"{int(final_pos)}% (极端亢奋)"
    
# --- [DEPRECATED V12.0] fetch_vix_realtime / _fetch_vix_for_dashboard / _fetch_cny_for_dashboard ---
# 已迁移至 dashboard_modules/fetch_macro.py · 删除时间: 2026-04-15


@app.get("/api/v1/dashboard-data")
async def get_dashboard_data():
    """
    V14.0 核心数据拉取接口 — 彻底转向纯前端读取模式 (Producer-Consumer)
    不执行任何计算，仅仅从 STRATEGY_CACHE 返回快照。
    """
    with _STRATEGY_LOCK:
        _cached_data = STRATEGY_CACHE.get("dashboard_data")
        _cached_ts = STRATEGY_CACHE.get("last_update")
        
    if _cached_data:
        # P0: 若超过3小时未更新，增加一个 stale 标记
        if time.time() - (_cached_ts or 0) > 10800:
            _cached_data["is_stale"] = True
        return _cached_data
        
    return {
        "status": "warming_up",
        "message": "引擎极速预热中...",
        "is_stale": True,
        "data": {}
    }

async def _build_dashboard_data_full():
    """由后台 Reactor 主动触发的全量构建逻辑，绝不在 API 线程中直接调用"""
    from dashboard_modules.fetch_macro import fetch_vix_for_dashboard, fetch_cny_for_dashboard, fetch_macro_data
    from dashboard_modules.run_strategies import run_all_strategies, wrap_mr_results
    from dashboard_modules.capital_flow import compute_capital_flow
    from dashboard_modules.market_temp import compute_market_temperature
    from dashboard_modules.sector_heatmap import compute_sector_heatmap
    from dashboard_modules.assemble_response import assemble_dashboard_response

    current_time = time.time()

    # ── 全量刷新: 子模块并发编排 ──
    latest_vix, vix_change, vix_status = 18.25, -1.5, "down"
    latest_cny = 7.23
    
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()
    today_str = datetime.now().strftime('%Y%m%d')
    loop = asyncio.get_event_loop()

    try:
        # 第一层: 并发执行 I/O 和独立计算
        async def fetch_macro_safe():
            try:
                v, p, c = await fetch_macro_data(executor)
                return v, p, c
            except Exception as e:
                print(f"Warning: Macro fetch partial failure: {e}")
                return 18.25, 18.25, 7.23
                
        async def get_capital_flow():
            return await loop.run_in_executor(executor, compute_capital_flow, pro, today_str)
            
        async def get_aiae_report():
            def _fetch():
                try:
                    eng = get_aiae_engine()
                    return eng.generate_report()
                except Exception as e:
                    print(f"[Dashboard] AIAE引擎异常: {e}")
                    return {"status": "error", "message": str(e)}
            return await loop.run_in_executor(executor, _fetch)

        macro_task = asyncio.create_task(fetch_macro_safe())
        strat_task = asyncio.create_task(run_all_strategies(executor))
        cap_task = asyncio.create_task(get_capital_flow())
        aiae_task = asyncio.create_task(get_aiae_report())

        # 等待第一层完成
        macro_res, strat_res, cap_res, aiae_report = await asyncio.gather(
            macro_task, strat_task, cap_task, aiae_task
        )

        # 解包第一层结果
        latest_vix, prev_vix, latest_cny = macro_res
        vix_change = ((latest_vix - prev_vix) / prev_vix * 100) if prev_vix > 0 else 0
        vix_status = "down" if vix_change < 0 else "up"

        mr_res, div_res, mom_res = strat_res
        STRATEGY_CACHE["strategy_results"] = {"mr": mr_res, "div": div_res, "mom": mom_res}

        capital_a, capital_h, liquidity_score, total_money_z, z_s = cap_res

        # 处理 AIAE
        aiae_regime = 3
        aiae_cap = 65
        aiae_v1_value = 0.0
        aiae_regime_cn = "中性均衡"
        if aiae_report.get("status") == "success":
            aiae_regime = aiae_report["current"]["regime"]
            aiae_v1_value = aiae_report["current"]["aiae_v1"]
            aiae_cap = aiae_report["position"]["matrix_position"]
            aiae_regime_cn = aiae_report["current"]["regime_info"]["cn"]
            print(f"[Dashboard] AIAE注入成功: V1={aiae_v1_value:.1f}% Regime={aiae_regime} Cap={aiae_cap}%")
        else:
            print(f"[Dashboard] AIAE降级: {aiae_report.get('message', 'unknown')}")

        # 第二层: 温度分析与热力图
        vix_analysis = get_vix_analysis(latest_vix)

        async def get_temp():
            def _calc():
                return compute_market_temperature(
                    pro, today_str, latest_vix, latest_cny, liquidity_score, z_s,
                    aiae_regime, aiae_cap, aiae_v1_value, aiae_regime_cn, aiae_report, vix_analysis
                )
            return await loop.run_in_executor(executor, _calc)
            
        temp_task = asyncio.create_task(get_temp())
        heatmap_task = asyncio.create_task(compute_sector_heatmap(executor, mr_res, mom_res))
        
        temp_data, sector_heatmap = await asyncio.gather(temp_task, heatmap_task)

        # Step 8: 组装最终响应
        final_data = assemble_dashboard_response(
            latest_vix=latest_vix, vix_change=vix_change,
            vix_status=vix_status, vix_analysis=vix_analysis,
            capital_a=capital_a, capital_h=capital_h,
            total_money_z=total_money_z,
            temp_data=temp_data,
            mr_res=mr_res, div_res=div_res, mom_res=mom_res,
            aiae_regime=aiae_regime, aiae_cap=aiae_cap,
            aiae_v1_value=aiae_v1_value, aiae_regime_cn=aiae_regime_cn,
            aiae_report=aiae_report,
            sector_heatmap=sector_heatmap,
            get_tomorrow_plan_fn=get_tomorrow_plan,
            get_position_path_fn=get_position_path,
            get_institutional_mindset_fn=get_institutional_mindset,
            liquidity_score=liquidity_score,
        )

        # P0-1: 构建并缓存原始 aiae_ctx (供 Hot-Refresh 复用)
        _full_aiae_ctx = {
            "regime": aiae_regime,
            "regime_cn": aiae_regime_cn,
            "regime_info": AIAE_REGIMES.get(aiae_regime, AIAE_REGIMES[3]),
            "cap": aiae_cap,
            "aiae_v1": round(aiae_v1_value, 1),
            "slope": aiae_report.get("current", {}).get("slope", {}).get("slope", 0),
            "slope_direction": aiae_report.get("current", {}).get("slope", {}).get("direction", "flat"),
            "erp_val": round(temp_data["erp_val"], 2),
            "erp_label": temp_data["valuation_label"],
            "erp_tier": temp_data["erp_tier"],
            "margin_heat": aiae_report.get("current", {}).get("margin_heat", 2.0),
            "fund_position": aiae_report.get("current", {}).get("fund_position", 80),
        }

        # 更新缓存 (P0-2: 原子写入)
        with _STRATEGY_LOCK:
            STRATEGY_CACHE["last_update"] = current_time
            STRATEGY_CACHE["dashboard_data"] = final_data
            STRATEGY_CACHE["aiae_ctx"] = _full_aiae_ctx
        return final_data

    except Exception as e:
        print(f"Global Error: {traceback.format_exc()}")
        return {"status": "error", "message": f"Global Error: {str(e)}"}
@app.get("/api/v1/strategy")
async def get_strategy():
    """均值回归策略详情 — V4.2 包装层"""
    from dashboard_modules.run_strategies import wrap_mr_results
    if STRATEGY_CACHE["strategy_results"]["mr"]:
        cached = STRATEGY_CACHE["strategy_results"]["mr"]
        # 如果缓存已经是包装格式就直接返回
        if isinstance(cached, dict) and "status" in cached:
            return cached
        # 否则包装裸list
        return wrap_mr_results(cached)
    raw = await asyncio.get_event_loop().run_in_executor(executor, run_strategy)
    wrapped = wrap_mr_results(raw)
    STRATEGY_CACHE["strategy_results"]["mr"] = wrapped
    return wrapped

@app.get("/api/v1/dividend_strategy")
async def get_dividend_strategy(regime: str = None):
    """红利增强策略详情 V3.1 · 支持市场状态参数
    regime: BULL / RANGE / BEAR / CRASH (可选，默认RANGE)
    """
    # 如有regime参数则强制刷新（不走缓存）
    if not regime and STRATEGY_CACHE["strategy_results"]["div"]:
        return STRATEGY_CACHE["strategy_results"]["div"]
    result = await asyncio.get_event_loop().run_in_executor(
        executor, lambda: run_dividend_strategy(regime=regime)
    )
    if not regime:
        STRATEGY_CACHE["strategy_results"]["div"] = result
    return result

@app.get("/api/v1/momentum_strategy")
async def get_momentum_strategy():
    """行业动量策略详情"""
    if STRATEGY_CACHE["strategy_results"]["mom"]:
        return STRATEGY_CACHE["strategy_results"]["mom"]
    return await asyncio.get_event_loop().run_in_executor(executor, run_momentum_strategy)


# ─────────────────────────────────────────────
# ERP 宏观择时策略 — 标的池实时信号 API
# ─────────────────────────────────────────────
ERP_TARGET_POOL = [
    {"ts_code": "510300.SH", "name": "沪深300ETF", "style": "核心宽基"},
    {"ts_code": "510500.SH", "name": "中证500ETF", "style": "中盘成长"},
    {"ts_code": "510880.SH", "name": "红利ETF",    "style": "防御红利"},
    {"ts_code": "510900.SH", "name": "H股ETF",     "style": "港股宽基"},
]

def _run_erp_strategy() -> dict:
    """ERP策略执行：获取宏观评分 → 对标的池5只ETF生成标准化信号"""
    from datetime import datetime as _dt
    try:
        engine = get_erp_engine()
        report = engine.compute_signal()
        if report.get("status") not in ("success", "fallback"):
            return {"status": "error", "message": report.get("message", "ERP引擎异常")}

        score = report["signal"]["score"]
        signal_key = report["signal"]["key"]
        snap = report["current_snapshot"]
        dims = report["dimensions"]

        # 信号映射 (对齐回测最优阈值: buy>=55, sell<=40)
        if score >= 55:
            std_signal = "buy"
        elif score <= 40:
            std_signal = "sell"
        else:
            std_signal = "hold"

        # 仓位映射
        pos_map = {"buy": 80, "hold": 50, "sell": 0}
        base_pos = pos_map.get(std_signal, 50)

        signals = []
        for etf in ERP_TARGET_POOL:
            signals.append({
                "name": etf["name"],
                "ts_code": etf["ts_code"],
                "code": etf["ts_code"].split(".")[0],
                "signal": std_signal,
                "signal_score": round(score),
                "suggested_position": base_pos if std_signal == "buy" else 0,
                "style": etf["style"],
                # ERP 专属因子
                "erp_abs": snap.get("erp_value", 0),
                "erp_pct": snap.get("erp_percentile", 0),
                "m1_yoy": dims.get("m1_trend", {}).get("m1_info", {}).get("current", 0),
                "pe_vol": dims.get("volatility", {}).get("vol_info", {}).get("current_vol", 0),
                "scissor": dims.get("credit", {}).get("credit_info", {}).get("scissor", 0),
            })

        buy_count = sum(1 for s in signals if s["signal"] == "buy")
        sell_count = sum(1 for s in signals if s["signal"] == "sell")

        return {
            "status": "success",
            "timestamp": _dt.now().isoformat(),
            "data": {
                "signals": signals,
                "market_overview": {
                    "composite_score": round(score),
                    "signal_key": std_signal,
                    "signal_label": report["signal"]["label"],
                    "buy_count": buy_count,
                    "sell_count": sell_count,
                    "total_suggested_pos": sum(s["suggested_position"] for s in signals if s["signal"] == "buy"),
                },
            },
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/erp_strategy")
async def get_erp_strategy():
    """ERP宏观择时策略实时信号"""
    return await asyncio.get_event_loop().run_in_executor(executor, _run_erp_strategy)


# ─────────────────────────────────────────────
# AIAE 宏观仓位管控策略 — ETF标的池执行 API
# ─────────────────────────────────────────────
def _run_aiae_strategy() -> dict:
    """AIAE策略执行：获取AIAE五档判定 → 对8只ETF标的池生成标准化信号"""
    from datetime import datetime as _dt
    try:
        engine = get_aiae_engine()
        report = engine.generate_report()

        if report.get("status") not in ("success", "fallback"):
            return {"status": "error", "message": "AIAE引擎异常"}

        regime = report["current"]["regime"]
        regime_info = report["current"]["regime_info"]
        aiae_v1 = report["current"]["aiae_v1"]
        matrix_pos = report["position"]["matrix_position"]

        # 生成 ETF 信号
        signals = engine.generate_etf_signals(regime)

        # 获取ERP评分 (用于联合权重)
        erp_score_for_weights = None
        try:
            from erp_timing_engine import get_erp_engine
            erp_eng = get_erp_engine()
            erp_sig = erp_eng.compute_signal()
            if erp_sig.get("status") == "success":
                erp_score_for_weights = erp_sig["signal"].get("score", None)
        except Exception:
            pass

        # 获取联合权重 V2.0 (AIAE×ERP双维)
        run_all_weights, erp_tier = engine.get_run_all_weights(regime, erp_score_for_weights)

        buy_count = sum(1 for s in signals if s["signal"] == "buy")
        sell_count = sum(1 for s in signals if s["signal"] == "sell")

        return {
            "status": "success",
            "timestamp": _dt.now().isoformat(),
            "data": {
                "signals": signals,
                "market_overview": {
                    "aiae_value": aiae_v1,
                    "regime": regime,
                    "regime_cn": regime_info["cn"],
                    "matrix_position": matrix_pos,
                    "buy_count": buy_count,
                    "sell_count": sell_count,
                    "composite_score": max(10, 100 - (regime - 1) * 20),
                    "erp_score_for_weights": erp_score_for_weights,
                    "erp_tier": erp_tier,
                },
                "run_all_weights": run_all_weights,
                "erp_tier": erp_tier,
                "aiae_report": report,  # 完整 AIAE 报告供前端展示
            },
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"[AIAE Strategy] Error: {e}")
        # 降级: 返回 Regime III 中性信号
        try:
            engine = get_aiae_engine()
            fallback_signals = engine.generate_etf_signals(3)
            return {
                "status": "fallback",
                "timestamp": _dt.now().isoformat(),
                "data": {
                    "signals": fallback_signals,
                    "market_overview": {
                        "aiae_value": 22.0, "regime": 3, "regime_cn": "中性均衡",
                        "matrix_position": 55, "buy_count": 5, "sell_count": 0,
                        "composite_score": 60,
                    },
                    "run_all_weights": engine.get_run_all_weights(3, None)[0],
                },
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}


@app.get("/api/v1/aiae_strategy")
async def get_aiae_strategy():
    """AIAE ETF标的池实时信号"""
    return await asyncio.get_event_loop().run_in_executor(executor, _run_aiae_strategy)


# ─────────────────────────────────────────────
# 五策略并行执行 + 共振分析 API (V4.0)
# ─────────────────────────────────────────────
def _extract_signals_normalized(strategy_type: str, raw_result) -> list:
    """从各策略原始返回中提取标准化信号列表"""
    if strategy_type == "mr":
        if isinstance(raw_result, dict) and "data" in raw_result:
            return raw_result["data"].get("signals", [])
        if isinstance(raw_result, list):
            return [s for s in raw_result if s.get("signal") != "error"]
        return []
    elif strategy_type == "div":
        if isinstance(raw_result, dict) and "data" in raw_result:
            return raw_result["data"].get("signals", [])
        return []
    elif strategy_type == "mom":
        if isinstance(raw_result, dict) and "data" in raw_result:
            return raw_result["data"].get("signals", [])
        return []
    elif strategy_type == "erp":
        if isinstance(raw_result, dict) and "data" in raw_result:
            return raw_result["data"].get("signals", [])
        return []
    elif strategy_type == "aiae_etf":
        if isinstance(raw_result, dict) and "data" in raw_result:
            return raw_result["data"].get("signals", [])
        return []
    return []


def _compute_resonance(mr_signals, div_signals, mom_signals, erp_signals=None, aiae_signals=None):
    """计算五策略信号共振：找到多策略一致看好/看空的重叠标的 (V4.2: AIAE独立参与)"""
    if erp_signals is None:
        erp_signals = []
    if aiae_signals is None:
        aiae_signals = []

    def build_map(signals):
        m = {}
        for s in signals:
            code = s.get("ts_code") or s.get("code", "")
            if code:
                m[code] = {
                    "name": s.get("name", ""),
                    "signal": s.get("signal", "hold"),
                    "score": s.get("signal_score", 0),
                    "position": s.get("suggested_position", 0),
                }
        return m

    mr_map = build_map(mr_signals)
    div_map = build_map(div_signals)
    mom_map = build_map(mom_signals)
    erp_map = build_map(erp_signals)
    aiae_map = build_map(aiae_signals)

    all_codes = set(list(mr_map.keys()) + list(div_map.keys()) + list(mom_map.keys()) + list(erp_map.keys()) + list(aiae_map.keys()))

    consensus_buy = []
    consensus_sell = []
    divergence = []

    for code in all_codes:
        mr_s = mr_map.get(code, {})
        div_s = div_map.get(code, {})
        mom_s = mom_map.get(code, {})
        erp_s = erp_map.get(code, {})
        aiae_s = aiae_map.get(code, {})

        present = sum([1 for s in [mr_s, div_s, mom_s, erp_s, aiae_s] if s])
        if present < 2:
            continue

        name = mr_s.get("name") or div_s.get("name") or mom_s.get("name") or erp_s.get("name") or aiae_s.get("name", code)
        signals = {
            "mr": mr_s.get("signal", "-"),
            "div": div_s.get("signal", "-"),
            "mom": mom_s.get("signal", "-"),
            "erp": erp_s.get("signal", "-"),
            "aiae": aiae_s.get("signal", "-"),
        }

        buy_count = sum(1 for v in signals.values() if v == "buy")
        sell_count = sum(1 for v in signals.values() if v in ("sell", "sell_half", "sell_weak"))

        entry = {
            "code": code,
            "name": name,
            "signals": signals,
            "scores": {
                "mr": mr_s.get("score", 0),
                "div": div_s.get("score", 0),
                "mom": mom_s.get("score", 0),
                "erp": erp_s.get("score", 0),
                "aiae": aiae_s.get("score", 0),
            },
        }

        if buy_count >= 2:
            entry["resonance"] = "strong_buy"
            entry["label"] = "Strong Buy Resonance"
            consensus_buy.append(entry)
        elif sell_count >= 2:
            entry["resonance"] = "strong_sell"
            entry["label"] = "Strong Sell Resonance"
            consensus_sell.append(entry)
        elif buy_count >= 1 and sell_count >= 1:
            entry["resonance"] = "divergence"
            entry["label"] = "Signal Divergence"
            divergence.append(entry)

    consensus_buy.sort(key=lambda x: sum(x["scores"].values()), reverse=True)
    consensus_sell.sort(key=lambda x: sum(x["scores"].values()))

    return {
        "consensus_buy": consensus_buy,
        "consensus_sell": consensus_sell,
        "divergence": divergence,
        "total_overlap": len(consensus_buy) + len(consensus_sell) + len(divergence),
    }


def _compute_risk_overlay(all_signals):
    """计算风险覆盖层：集中度+波动率预警"""
    # 统计行业/板块集中度
    sector_counts = {}
    vol_alerts = []

    for s in all_signals:
        group = s.get("group", s.get("sector", "unknown"))
        if group and group != "unknown":
            sector_counts[group] = sector_counts.get(group, 0) + 1

        vol = s.get("vol_30d", s.get("annualized_vol", 0))
        if vol and float(vol) > 25:
            vol_alerts.append({
                "name": s.get("name", ""),
                "code": s.get("ts_code") or s.get("code", ""),
                "vol_30d": round(float(vol), 1),
            })

    # 找最集中的板块
    top_sector = max(sector_counts, key=sector_counts.get) if sector_counts else "N/A"
    top_ratio = round(sector_counts.get(top_sector, 0) / max(len(all_signals), 1) * 100) if sector_counts else 0

    # 波动率预警按波动率降序
    vol_alerts.sort(key=lambda x: x["vol_30d"], reverse=True)

    return {
        "concentration": {
            "top_sector": top_sector,
            "ratio": f"{top_ratio}%",
            "sectors": dict(sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:5]),
        },
        "volatility_alerts": vol_alerts[:5],
        "alert_count": len(vol_alerts),
    }


@app.get("/api/v1/strategy/run-all")
async def run_all_strategies(override_cap: int = None):
    """V4.0 五策略并行执行 (MR+DIV+MOM+ERP+AIAE_ETF)
    + AIAE主控仓位Cap + 动态权重 + 共振分析

    Query Params:
        override_cap (int, optional): 手动覆盖仓位上限 (0-100), 用于人工干预AIAE判定
    """
    from datetime import datetime as _dt
    loop = asyncio.get_event_loop()

    try:
        # ── 并行执行5策略 ──
        mr_task   = loop.run_in_executor(executor, run_strategy)
        div_task  = loop.run_in_executor(executor, lambda: run_dividend_strategy(regime=None))
        mom_task  = loop.run_in_executor(executor, run_momentum_strategy)
        erp_task  = loop.run_in_executor(executor, _run_erp_strategy)
        aiae_task = loop.run_in_executor(executor, _run_aiae_strategy)

        mr_raw, div_raw, mom_raw, erp_raw, aiae_raw = await asyncio.gather(
            mr_task, div_task, mom_task, erp_task, aiae_task
        )

        # 包装结果
        from dashboard_modules.run_strategies import wrap_mr_results
        mr_result = wrap_mr_results(mr_raw) if isinstance(mr_raw, list) else mr_raw
        div_result = div_raw
        mom_result = mom_raw
        erp_result = erp_raw
        aiae_result = aiae_raw

        # 缓存 (P1-4: 线程安全写入)
        with _STRATEGY_LOCK:
            STRATEGY_CACHE["strategy_results"]["mr"] = mr_result
            STRATEGY_CACHE["strategy_results"]["div"] = div_result
            STRATEGY_CACHE["strategy_results"]["mom"] = mom_result

        # 提取标准化信号
        mr_signals   = _extract_signals_normalized("mr", mr_result)
        div_signals  = _extract_signals_normalized("div", div_result)
        mom_signals  = _extract_signals_normalized("mom", mom_result)
        erp_signals  = _extract_signals_normalized("erp", erp_result)
        aiae_signals = _extract_signals_normalized("aiae_etf", aiae_result)

        # 五策略共振分析 (AIAE独立参与共振 V4.2)
        resonance = _compute_resonance(mr_signals, div_signals, mom_signals, erp_signals, aiae_signals)

        # 风险覆盖
        all_buy_signals = (
            [s for s in mr_signals if s.get("signal") == "buy"] +
            [s for s in div_signals if s.get("signal") == "buy"] +
            [s for s in mom_signals if s.get("signal") == "buy"] +
            [s for s in aiae_signals if s.get("signal") == "buy"]
        )
        risk_overlay = _compute_risk_overlay(all_buy_signals)

        # 全局指标
        mr_ov   = mr_result.get("data", {}).get("market_overview", {}) if isinstance(mr_result, dict) else {}
        div_ov  = div_result.get("data", {}).get("market_overview", {}) if isinstance(div_result, dict) else {}
        mom_ov  = mom_result.get("data", {}).get("market_overview", {}) if isinstance(mom_result, dict) else {}
        erp_ov  = erp_result.get("data", {}).get("market_overview", {}) if isinstance(erp_result, dict) else {}
        aiae_ov = aiae_result.get("data", {}).get("market_overview", {}) if isinstance(aiae_result, dict) else {}

        mr_regime = mr_signals[0].get("regime", "RANGE") if mr_signals else "RANGE"
        total_buy = (mr_ov.get("signal_count", {}).get("buy", 0) + div_ov.get("buy_count", 0) +
                     mom_ov.get("buy_count", 0) + erp_ov.get("buy_count", 0) + aiae_ov.get("buy_count", 0))
        total_sell = (mr_ov.get("signal_count", {}).get("sell", 0) + div_ov.get("sell_count", 0) +
                      mom_ov.get("sell_count", 0) + erp_ov.get("sell_count", 0) + aiae_ov.get("sell_count", 0))

        # ─── 科学仓位计算 V4.0 (AIAE主控) ───
        def _avg_confidence(signals_list):
            """计算策略内buy信号的平均仓位(=策略信心度，0~100%)"""
            buy_sigs = [s for s in signals_list if s.get("signal") == "buy"]
            if not buy_sigs:
                return 0.0
            positions = [s.get("suggested_position", 0) for s in buy_sigs]
            return sum(positions) / len(positions) if positions else 0.0

        mr_conf   = _avg_confidence(mr_signals)
        div_conf  = _avg_confidence(div_signals)
        mom_conf  = _avg_confidence(mom_signals)
        erp_conf  = _avg_confidence(erp_signals)
        aiae_conf = _avg_confidence(aiae_signals)

        # ── AIAE×ERP 联合权重 V2.0 (双维驱动) ──
        aiae_regime = aiae_ov.get("regime", 3)
        erp_score = erp_ov.get("composite_score", 50)

        # 从AIAE策略结果获取联合权重（已在_run_aiae_strategy中计算）
        aiae_weights = aiae_result.get("data", {}).get("run_all_weights", None)
        erp_tier = aiae_result.get("data", {}).get("erp_tier", "neutral")

        if aiae_weights:
            w = aiae_weights
        else:
            # 降级: 重新查表
            try:
                engine = get_aiae_engine()
                w, erp_tier = engine.get_run_all_weights(aiae_regime, erp_score)
            except Exception:
                w = {"mr": 0.15, "div": 0.30, "mom": 0.10, "erp": 0.15, "aiae_etf": 0.30}
                erp_tier = "neutral"

        raw_pos = round(
            mr_conf   * w["mr"] +
            div_conf  * w["div"] +
            mom_conf  * w["mom"] +
            erp_conf  * w["erp"] +
            aiae_conf * w["aiae_etf"]
        )

        # ── 仓位Cap V2.0: POSITION_MATRIX(AIAE×ERP) + MA安全网 ──
        # Layer A: POSITION_MATRIX 直查 (已包含ERP维度, 替代旧版ERP硬编码屏障)
        aiae_cap = aiae_ov.get("matrix_position", 65)

        # Layer B: MA 趋势安全网 (保留作为技术面辅助)
        ma_cap_map = {"BULL": 95, "RANGE": 70, "BEAR": 50, "CRASH": 20}
        ma_cap = ma_cap_map.get(mr_regime, 70)

        # 双保险: POSITION_MATRIX Cap + MA趋势安全网
        cap = min(aiae_cap, ma_cap)

        # 手动覆盖选项 (PO 人工干预)
        override_active = False
        original_cap = cap
        if override_cap is not None and 0 <= override_cap <= 100:
            cap = override_cap
            override_active = True
            print(f"[RUN-ALL V5] 手动覆盖仓位Cap: {original_cap}% → {cap}%")

        avg_pos = min(raw_pos, cap)

        # ── V2.1: 矩阵锚定地板 (Regime Position Floor) ──
        # 问题: 当 MR/DIV 无 buy 信号时, 信心度=0, 加权仓位会被压到极低值(如15%),
        #        与 AIAE×ERP 矩阵指示的目标区间(如 Regime Ⅲ: 50-65%)严重脱节。
        # 方案: 使用 AIAE 五档的 pos_min 作为地板, ERP tier 微调。
        #        信号驱动的仓位 (raw_pos) 在 [floor, cap] 区间内调节。
        regime_info_for_floor = AIAE_REGIMES.get(aiae_regime, AIAE_REGIMES[3])
        regime_floor = regime_info_for_floor.get("pos_min", 50)

        # ERP tier 微调地板: bull +5 / bear -10
        if erp_tier == "bull":
            regime_floor = min(regime_floor + 5, cap)
        elif erp_tier == "bear":
            regime_floor = max(regime_floor - 10, 0)

        # 仓位锚定: max(信号驱动, 矩阵地板) → 再受 Cap 限制
        avg_pos = max(avg_pos, regime_floor)
        print(f"[RUN-ALL V2.1] 矩阵锚定: raw={raw_pos}% floor={regime_floor}%(R{aiae_regime}/{erp_tier}) cap={cap}% → final={avg_pos}%")

        # V2.0: ERP屏障已内嵌到JOINT_WEIGHTS+POSITION_MATRIX中，不再需要硬编码30%屏障
        # 保留变量供前端展示用
        erp_cap_active = False  # 矩阵已连续调节，无需二值屏障

        # 策略一致性评估 (增加 AIAE regime 参与)
        regimes = [mr_regime]
        div_regime = div_result.get("data", {}).get("regime_params", {}).get("regime", "RANGE") if isinstance(div_result, dict) else "RANGE"
        regimes.append(div_regime)
        consistency = "high" if len(set(regimes)) == 1 else "low"

        # 分歧降仓: 一致性低时再打8折 (手动覆盖时跳过, 不低于矩阵地板)
        if consistency != "high" and not override_active:
            avg_pos = max(round(avg_pos * 0.8), regime_floor)

        return {
            "status": "success",
            "timestamp": _dt.now().isoformat(),
            "data": {
                "global": {
                    "regime": mr_regime,
                    "total_position": avg_pos,
                    "regime_cap": cap,
                    "total_buy": total_buy,
                    "total_sell": total_sell,
                    "consistency": consistency,
                    "strategy_count": 5,
                    "erp_score": erp_score,
                    "erp_cap_active": erp_cap_active,
                    "confidence": {
                        "mr": round(mr_conf),
                        "div": round(div_conf),
                        "mom": round(mom_conf),
                        "erp": round(erp_conf),
                        "aiae_etf": round(aiae_conf),
                    },
                    "weights": w,
                    # ── AIAE 主控状态 (供前端展示) ──
                    "aiae": {
                        "regime": aiae_regime,
                        "regime_cn": aiae_ov.get("regime_cn", "中性均衡"),
                        "aiae_value": aiae_ov.get("aiae_value", 22.0),
                        "aiae_cap": aiae_cap,
                        "regime_floor": regime_floor,
                        "raw_pos": raw_pos,
                        "ma_cap": ma_cap,
                        "erp_tier": erp_tier,
                        "erp_score_tier": {"bull": "🟢看多", "neutral": "🟡中性", "bear": "🔴看空"}.get(erp_tier, "🟡中性"),
                        "override_active": override_active,
                        "override_cap": override_cap if override_active else None,
                        "original_cap": original_cap,
                    },
                },
                "strategies": {
                    "mr": mr_result.get("data", mr_result) if isinstance(mr_result, dict) else {"signals": mr_signals},
                    "div": div_result.get("data", div_result) if isinstance(div_result, dict) else {"signals": div_signals},
                    "mom": mom_result.get("data", mom_result) if isinstance(mom_result, dict) else {"signals": mom_signals},
                    "erp": erp_result.get("data", erp_result) if isinstance(erp_result, dict) else {"signals": erp_signals},
                    "aiae_etf": aiae_result.get("data", aiae_result) if isinstance(aiae_result, dict) else {"signals": aiae_signals},
                },
                "resonance": resonance,
                "risk_overlay": risk_overlay,
            },
        }
    except Exception as e:
        import traceback
        print(f"[RUN-ALL V4] Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


# --- V4.8 Industry Deep-Dive Engine (Value-Flow Synergy) ---



# ═══ Phase 5: Router 模块注册 ═══
from routers import portfolio, audit, aiae, market, industry
app.include_router(portfolio.router)
app.include_router(audit.router)
app.include_router(aiae.router)
app.include_router(market.router)
app.include_router(industry.router)

@app.get("/")
async def root():
    return FileResponse("index.html")

@app.get("/{filename}.html")
async def serve_html(filename: str):
    return FileResponse(f"{filename}.html")

# P0-2 安全加固: 仅暴露前端静态资源文件, 不暴露 .py/.git/config 等
import mimetypes
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

class SafeStaticFiles(StaticFiles):
    """只允许安全的前端文件类型通过"""
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
            import os
            _, ext = os.path.splitext(path)
            if ext and ext.lower() not in self.ALLOWED_EXTENSIONS:
                response = Response("Not Found", status_code=404)
                await response(scope, receive, send)
                return
        await super().__call__(scope, receive, send)

app.mount("/", SafeStaticFiles(directory="."), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)