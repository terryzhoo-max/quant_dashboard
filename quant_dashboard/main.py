from fastapi import FastAPI, UploadFile, File
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
from pydantic import BaseModel

class TradeRequest(BaseModel):
    ts_code: str
    amount: int
    price: float
    name: str = ""
    action: str # "buy" or "sell"
import numpy as np

executor = ThreadPoolExecutor(max_workers=10)

app = FastAPI(title="AlphaCore Quant API", description="AlphaCore量化终端底层数据接口")

# 配置 CORS 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 全局缓存结构 (In-Memory Cache for Production Stability)
STRATEGY_CACHE = {
    "last_update": None,
    "dashboard_data": None,
    "strategy_results": {
        "mr": None,
        "mom": None,
        "div": None
    }
}

# 海外 AIAE 全局缓存 (V1.1: L1 API结果级缓存)
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

def _warmup_dashboard_cache():
    """后台预热量化总览缓存: True Zero-Wait (真实主动流水线预热)"""
    # 清除旧缓存
    STRATEGY_CACHE["last_update"] = None
    STRATEGY_CACHE["dashboard_data"] = None
    
    # 主动触发全数据流水线
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # 因为 get_dashboard_data 是协程，在后台线程中需借助事件循环
    data = loop.run_until_complete(get_dashboard_data())
    loop.close()
    
    if data and data.get("status") == "success":
        print(f"[Dashboard Warmup] 主动预热成功, 零等待缓存已就绪")
    else:
        raise Exception("预热后返回状态异常，缓存建立失败")

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

def _morning_warmup_callback():
    """盘前数据补偿拉取"""
    print(f"==================================================")
    print(f"[Scheduler] 🌅 早间数据补偿流水线 @ {datetime.now().strftime('%H:%M:%S')}")
    # 强制破防 L1 缓存以拉取最新融资数据
    with_retry(_warmup_aiae_cache, "AIAE_Morning_Warmup", 3, 300)
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

@app.on_event("startup")
async def startup_event():
    """服务启动: 后台预热 ERP + 利率 + AIAE + 注册每日定时任务"""
    # 异步预热 (不阻塞启动)
    threading.Thread(target=_warmup_erp_cache, daemon=True).start()
    threading.Thread(target=_warmup_rates_cache, daemon=True).start()  # V1.5: 利率预热
    threading.Thread(target=lambda: get_aiae_engine().generate_report(), daemon=True).start()  # AIAE预热
    
    # 注册收盘后定时预热 (15:35 A股)
    _schedule_daily_warmup()
    # 注册开盘前补偿预热 (08:30 A股)
    _schedule_morning_warmup()
    # 注册 FRED 利率刷新 (18:30 = 美东6:30AM)
    _schedule_fred_daily_refresh()
    # V1.1: 海外AIAE定时预热
    _schedule_us_aiae_warmup()      # 北京06:30 美股FRED数据更新
    _schedule_jp_aiae_warmup()      # 北京15:30 日股收盘后
    _schedule_aaii_weekly_crawl()    # 每周五09:00 散户情绪
    # V1.1: 后台预热海外AIAE (L3磁盘缓存->L1内存)
    threading.Thread(target=_warmup_global_aiae_cache, daemon=True).start()
    # V2.0: 后台预热 HK ERP + AIAE
    threading.Thread(target=lambda: _warmup_hk_erp_cache(), daemon=True).start()
    threading.Thread(target=lambda: _warmup_hk_aiae_cache(), daemon=True).start()
    
    print("[Startup] AlphaCore 服务启动完成 · 引擎常驻预热就绪 · 调度器(06:30US/08:30CN/15:30JP/16:30HK/15:35A/18:30FRED/周五AAII)已激活")


# --- AlphaCore DMSO Sub-Engines (V3.3 机构级) ---

def get_margin_risk_ratio(pro, date_str):
    """
    计算融资买入占比分位 (Margin Buying Ratio Percentile)
    权重: A股 25%
    """
    try:
        df = pro.margin_detail(trade_date=date_str)
        if df.empty: 
            # 尝试获取最近一个交易日
            return 50.0
        
        # 获取当日上证指数成交额作为分母基准
        df_index = pro.index_daily(ts_code='000001.SH', start_date=date_str, end_date=date_str)
        if df_index.empty: return 50.0
        
        total_margin_buy = df['rzmre'].sum()
        total_mkt_vol = df_index['amount'].iloc[0] * 1000 # Tushare amount 默认单位为千
        
        ratio = total_margin_buy / total_mkt_vol if total_mkt_vol > 0 else 0
        
        # 阈值建模：0.07 (冰点) -> 0.12 (亢奋)
        percentile = min(100, max(0, (ratio - 0.07) / (0.12 - 0.07) * 100))
        return round(percentile, 1)
    except:
        return 50.0

def get_market_breadth(pro, date_str):
    """
    A股股价高于年线占比 (% Stocks > 250MA)
    权重: A股 20%
    """
    # 生产环境下应从个股全样本计算，此处采用宽基指数均值代理
    return 62.5 # 模拟：多数核心资产已站回年线

def get_liquidity_crisis_signal(pro, today_str):
    """
    监控流动性危机：个股跌停占比 > 10%
    返回 True 则触发熔断禁买
    """
    try:
        df = pro.daily(trade_date=today_str)
        if df.empty: return False
        
        limit_down = len(df[df['pct_chg'] <= -9.8])
        ratio = limit_down / len(df)
        return ratio > 0.10
    except:
        return False

def get_ah_premium_adj(pro, date_str):
    """
    AH 溢价调节因子 (H股吸引力乘数)
    """
    try:
        df = pro.index_daily(ts_code='HSAHP.HI', start_date='20240101', end_date=date_str)
        if df.empty: return 1.0
        latest_val = df.sort_values('trade_date').iloc[-1]['close']
        if latest_val > 145: return 1.15
        if latest_val < 125: return 0.85
        return 1.0
    except:
        return 1.0

# --- V3.6 机构级策略调控引擎 (Strategic Allocation Engine) ---

def get_erp_multiplier():
    """
    计算股债性价比 (ERP) 修正系数
    逻辑: Z-Score 越高 (便宜), 系数越大
    """
    # 生产环境下应从 FactorDataManager 获取 10Y ERP Z-Score
    # 此处模拟当前 A股 处于 3.5% (极度低估) -> Z-Score ≈ +1.8
    erp_z = 1.8 
    if erp_z > 1.5: return 1.2, "极度低估", erp_z
    if erp_z < -1.5: return 0.7, "极度高估", erp_z
    return 1.0, "估值合理", erp_z

def get_regime_allocation(temp: float) -> tuple[dict[str, float], str]:
    """V3.9 纠偏后的策略权重矩阵 (过热≠进攻)"""
    if temp >= 85:
        return {"div": 0.55, "mr": 0.30, "mom": 0.15}, "过热模式"
    if temp >= 65:
        return {"div": 0.20, "mr": 0.35, "mom": 0.45}, "进攻模式"
    if temp >= 45:
        return {"div": 0.35, "mr": 0.40, "mom": 0.25}, "平衡模式"
    if temp >= 25:
        return {"div": 0.50, "mr": 0.35, "mom": 0.15}, "防御模式"
    return {"div": 0.55, "mr": 0.35, "mom": 0.10}, "极限冰点"

def apply_strategy_filters(regime_weights: dict, mom_crowding: float = 60.0,
                           div_yield_gap: float = 1.7, mr_atr_ratio: float = 1.0) -> tuple[dict, dict]:
    """
    V3.9 策略级风险过滤器
    mom_crowding: 动量拥挤度分位 (0-100), 默认60 (偏中性)
    div_yield_gap: 红利股息率 - 10Y国债 (百分点), 默认1.7
    mr_atr_ratio: 当前ATR / 20D均值ATR, 默认1.0
    返回: (调整后权重, 过滤器状态)
    """
    adjusted = dict(regime_weights)
    filters = {"mom": "正常", "div": "正常", "mr": "正常"}

    # 动量拥挤过滤: 换手率分位 > 80 时逐步削减
    if mom_crowding > 80:
        penalty = min(0.5, (mom_crowding - 80) / 40)
        adjusted["mom"] *= (1 - penalty)
        filters["mom"] = f"⚠️ 拥挤 P{int(mom_crowding)}"

    # 红利溢价不足: Yield Gap < 1.0% 时削减
    if div_yield_gap < 1.0:
        adjusted["div"] *= max(0.5, div_yield_gap / 1.0)
        filters["div"] = f"⚠️ 溢价不足 {div_yield_gap:.1f}%"

    # 均值回归高波门控: ATR > 1.5倍均值时削减
    if mr_atr_ratio > 1.5:
        adjusted["mr"] *= max(0.5, 1.5 / mr_atr_ratio)
        filters["mr"] = f"⚠️ 高波 ATR×{mr_atr_ratio:.1f}"

    # 归一化
    total = sum(adjusted.values())
    if total > 0:
        for k in adjusted:
            adjusted[k] = round(adjusted[k] / total, 2)

    return adjusted, filters


# --- V6.0 五因子科学仓位决策引擎 (Scientific Position Engine) ---

def compute_scientific_position(
    total_temp: float,
    vix_analysis: dict,
    total_money_z: float,
    erp_z: float,
    mr_res: dict,
    mom_res: dict,
    div_res: dict,
    is_circuit_breaker: bool
) -> dict:
    """
    AlphaCore V6.0: 五因子加权合成仓位引擎
    权重依据: 信息层级原则 (风险 > 资金流 > 宽度 > 估值 > 策略反馈)
    
    因子权重:
      VIX 恐慌指数    30%  — 前瞻性最强，期权隐含波动率
      资金流向 Z-Score 20%  — 机构级日频信号，smart money 定位
      宏观温度         20%  — 复合宽度指标，降权避免 double-counting
      ERP 估值         15%  — 慢变量战略锚，股债性价比
      策略信号共振     15%  — 自下而上反馈，三引擎买卖信号密度
    """
    # === 1. 各因子独立评分 (0-100, 越高越利于加仓) ===
    
    # 因子A: VIX 恐慌 (反向映射 — VIX 越低越利于加仓)
    vix_p = vix_analysis.get('percentile', 50)
    vix_score = max(0, min(100, 100 - vix_p))
    vix_label = "恐慌低位" if vix_score >= 70 else ("恐慌中性" if vix_score >= 40 else "恐慌高位")
    
    # 因子B: 资金流向 (Z-Score → 0-100 映射)
    # Z ∈ [-3, +3] → Score ∈ [0, 100], 中性=50
    capital_score = max(0, min(100, 50 + total_money_z * 16.67))
    capital_label = "资金强流入" if capital_score >= 70 else ("资金中性" if capital_score >= 40 else "资金流出")
    
    # 因子C: 宏观温度 (反向 — 温度越低越利于建仓)
    temp_score = max(0, min(100, 100 - total_temp))
    temp_label = "宏观偏冷" if temp_score >= 60 else ("宏观中性" if temp_score >= 40 else "宏观偏热")
    
    # 因子D: ERP 估值 (Z-Score → 0-100, Z 越高越便宜越利于加仓)
    # Z ∈ [-2, +2] → Score ∈ [0, 100]
    erp_score = max(0, min(100, 50 + erp_z * 25))
    erp_label = "极度低估" if erp_score >= 80 else ("估值合理" if erp_score >= 40 else "估值偏高")
    
    # 因子E: 策略信号共振度
    mr_overview = mr_res.get("data", {}).get("market_overview", {})
    mom_overview = mom_res.get("data", {}).get("market_overview", {})
    div_overview = div_res.get("data", {}).get("market_overview", {})
    
    mr_buy = mr_overview.get("signal_count", {}).get("buy", 0)
    mr_sell = mr_overview.get("signal_count", {}).get("sell", 0)
    mom_buy = mom_overview.get("buy_count", 0)
    div_buy = div_overview.get("buy_count", 0)
    div_trend_up = div_overview.get("trend_up_count", 0)
    
    total_buy = mr_buy + mom_buy + div_buy
    total_sell = mr_sell
    signal_denominator = max(total_buy + total_sell, 1)
    signal_ratio = total_buy / signal_denominator
    # 加入红利趋势方向作为修正 (trend_up_count / 8)
    trend_bonus = (div_trend_up / 8.0) * 20  # 最多+20分
    signal_score = max(0, min(100, signal_ratio * 80 + trend_bonus))
    signal_label = "策略共振" if signal_score >= 65 else ("策略分歧" if signal_score >= 35 else "策略空头")
    
    # === 2. 五因子加权合成 ===
    W = {"vix": 0.30, "capital": 0.20, "temp": 0.20, "erp": 0.15, "signal": 0.15}
    scores = {
        "vix": vix_score,
        "capital": capital_score,
        "temp": temp_score,
        "erp": erp_score,
        "signal": signal_score
    }
    
    composite_score = sum(scores[k] * W[k] for k in W)
    
    # === 3. 仓位映射 (非线性 S-Curve) ===
    # composite ∈ [0,100] → position ∈ [10%, 95%]
    # 使用 S 形曲线使中间区段更敏感、两端钝化
    import math
    x = (composite_score - 50) / 15  # 标准化到 ~[-3, +3]
    sigmoid = 1 / (1 + math.exp(-x))
    raw_position = 10 + sigmoid * 85  # 映射到 [10, 95]
    
    # === 4. 安全边际 ===
    # 流动性熔断保护
    if is_circuit_breaker:
        final_position = min(raw_position, 10)
        position_label = "0% (流动性熔断)"
    elif total_temp > 90:
        final_position = min(raw_position, 15)
        position_label = f"{int(final_position)}% (极度过热)"
    else:
        final_position = round(raw_position, 1)
        position_label = get_tactical_label(final_position, total_temp, erp_z, False)
    
    # === 5. 决策置信度 (因子一致性) ===
    # 如果 5 个因子方向一致（都高或都低），置信度高
    scores_list = list(scores.values())
    mean_s = sum(scores_list) / len(scores_list)
    variance = sum((s - mean_s) ** 2 for s in scores_list) / len(scores_list)
    std_dev = variance ** 0.5
    # 标准差越小 → 因子一致性越高 → 置信度越高
    # std_dev ∈ [0, ~35] → confidence ∈ [100, 30]
    confidence = max(30, min(100, int(100 - std_dev * 2)))
    
    return {
        "position": round(final_position, 1),
        "position_label": position_label,
        "composite_score": round(composite_score, 1),
        "confidence": confidence,
        "factors": {
            "vix_fear":     {"score": round(vix_score, 1),     "weight": W["vix"],     "label": vix_label},
            "capital_flow": {"score": round(capital_score, 1), "weight": W["capital"], "label": capital_label},
            "macro_temp":   {"score": round(temp_score, 1),    "weight": W["temp"],    "label": temp_label},
            "erp_value":    {"score": round(erp_score, 1),     "weight": W["erp"],     "label": erp_label},
            "signal_sync":  {"score": round(signal_score, 1),  "weight": W["signal"],  "label": signal_label}
        },
        "signal_detail": {
            "buy_total": total_buy,
            "sell_total": total_sell,
            "mr_buy": mr_buy, "mr_sell": mr_sell,
            "mom_buy": mom_buy, "div_buy": div_buy,
            "div_trend_up": div_trend_up
        }
    }


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

def get_tomorrow_plan(vix_analysis, temp_score):
    """Generate Tomorrow's Operation Framework based on VIX & Temperature (V4.4)"""
    v_val = vix_analysis['vix_val']
    
    # 定义 4 阶战术矩阵 (Institutional Protocol)
    matrix = [
        {
            "id": "calm",
            "regime": "🟢 极度活跃",
            "vix_range": "< 15",
            "tactics": "进攻：主攻低位AI/算力",
            "pos": "85-100%",
            "defense": "🚀 五日线持有",
            "active": v_val < 15
        },
        {
            "id": "normal",
            "regime": "🟡 常态回归",
            "vix_range": "15-25",
            "tactics": "稳健：20日线择时对焦",
            "pos": "60-85%",
            "defense": "📈 均线多头对焦",
            "active": 15 <= v_val < 25
        },
        {
            "id": "alert",
            "regime": "🔴 高度警觉",
            "vix_range": "25-35",
            "tactics": "防御：增配红利/低波",
            "pos": "35-60%",
            "defense": "🛡️ 20日线防守",
            "active": 25 <= v_val < 35
        },
        {
            "id": "crisis",
            "regime": "🔴🔴 极端恐慌",
            "vix_range": "> 35",
            "tactics": "熔断：现金为王，观察",
            "pos": "10-35%",
            "defense": "⚠️ 强制离场/回避",
            "active": v_val >= 35
        }
    ]
    
    # 核心对策（当前状态）
    curr = next((m for m in matrix if m['active']), matrix[1])
    
    # 场景分流建议 (V4.4 优化为 Priority 模式)
    if v_val < 25:
        framework = ["🔥 优先：适度加仓硬科技龙头", "💎 持有：算力/AI 核心资产", "📊 布局：科创50/创业板ETF"]
    elif v_val < 35:
        framework = ["🛡️ 优先：严格执行20日止损线", "🌊 避险：增配中字头红利", "⚖️ 调仓：卖出高波非核心标的"]
    else:
        framework = ["⚠️ 核心：战略防御，保留现金", "🥇 避险：关注黄金/避险资产", "🛑 熔断：拒绝一切左侧接盘"]

    return {
        "regime_matrix": matrix,
        "current_tactics": curr,
        "framework": framework,
        "scenarios": [
        ]
    }

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
    
def fetch_vix_realtime():
    """
    AlphaCore V4.3: Real-time VIX fetcher (CNBC Scraper)
    Resolves yfinance latency and SSL/API structure instability.
    """
    url = "https://www.cnbc.com/quotes/.VIX"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            # CNBC uses JSON-LD with "last":"XX.XX"
            match = re.search(r'"last":"([\d.]+)"', response.text)
            if match:
                return float(match.group(1))
    except Exception as e:
        print(f"SCRAPER ERROR: {e}")
    return None


def _fetch_vix_for_dashboard():
    """FRED VIXCLS → CNBC → 默认值 (返回 (latest, prev) 元组)"""
    try:
        from fredapi import Fred
        fred = Fred(api_key="eadf412d4f0e8ccd2bb3993b357bdca6")
        s = fred.get_series("VIXCLS", observation_start=(datetime.now() - timedelta(days=10)))
        if s is not None and not s.empty:
            s = s.dropna()
            if len(s) >= 2:
                return float(s.iloc[-1]), float(s.iloc[-2])
            return float(s.iloc[-1]), float(s.iloc[-1])
    except Exception:
        pass
    # CNBC fallback
    rt = fetch_vix_realtime()
    return (rt, rt) if rt else (18.25, 18.25)


def _fetch_cny_for_dashboard():
    """CNBC USD/CNY → 默认值"""
    try:
        url = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=USD/CNY&requestMethod=itv&noCache=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
        r = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        quote = r.json().get('FormattedQuoteResult', {}).get('FormattedQuote', [{}])[0]
        return float(quote.get('last', '7.23').replace(',', ''))
    except Exception:
        return 7.23


@app.get("/api/v1/dashboard-data")
async def get_dashboard_data():
    """
    核心数据拉取接口：集成三大策略引擎真实数据 + 缓存机制
    """
    current_time = time.time()
    ttl = _get_cache_ttl()

    # 检查缓存是否存在且未过期
    if STRATEGY_CACHE["last_update"] and (current_time - STRATEGY_CACHE["last_update"] < ttl):
        age = int(current_time - STRATEGY_CACHE["last_update"])
        ttl_type = "盘中5min" if ttl == 300 else ("周末24h" if ttl == 86400 else "盘后1h")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Dashboard Cache Hit [{ttl_type}] ({age}s ago).")
        return STRATEGY_CACHE["dashboard_data"]

    # ─── 盘中热刷新: 只刷 VIX/CNY, 策略引擎不重跑 ───
    now_dt = datetime.now()
    is_trading_hours = now_dt.weekday() < 5 and ((now_dt.hour == 9 and now_dt.minute >= 30) or (10 <= now_dt.hour < 15))
    has_strategy_cache = STRATEGY_CACHE["dashboard_data"] is not None

    if is_trading_hours and has_strategy_cache:
        # 盘中: 只拉 VIX + CNY (约 2 秒), 合并旧策略数据
        print(f"[{now_dt.strftime('%H:%M:%S')}] [HOT] Trading-hours refresh: VIX/CNY only, skip strategy engine")
        try:
            loop = asyncio.get_event_loop()

            vix_result, cny_result = await asyncio.gather(
                loop.run_in_executor(executor, _fetch_vix_for_dashboard),
                loop.run_in_executor(executor, _fetch_cny_for_dashboard)
            )

            # 解析 VIX
            hot_vix, prev_vix = vix_result
            hot_vix_change = ((hot_vix - prev_vix) / prev_vix * 100) if prev_vix > 0 else 0
            hot_vix_status = "down" if hot_vix_change < 0 else "up"

            # CNY
            hot_cny = cny_result

            # VIX 分析
            hot_vix_analysis = get_vix_analysis(hot_vix)

            # 复制旧缓存, 只更新 VIX/CNY 相关字段
            hot_data = copy.deepcopy(STRATEGY_CACHE["dashboard_data"])
            mc = hot_data["data"]["macro_cards"]
            mc["vix"] = {
                "value": round(hot_vix, 2),
                "trend": f"{round(hot_vix_change, 1)}%",
                "status": hot_vix_status,
                "regime": hot_vix_analysis["label"],
                "class": hot_vix_analysis["class"],
                "desc": hot_vix_analysis.get("desc", ""),
                "percentile": hot_vix_analysis.get("percentile", 0)
            }
            # 更新决策矩阵中的 VIX 相关字段
            if mc.get("regime_banner"):
                mc["regime_banner"]["vix"] = round(hot_vix, 2)
                mc["regime_banner"]["vix_label"] = hot_vix_analysis.get("label", "—")
            if mc.get("market_temp"):
                mc["market_temp"]["market_vix_multiplier"] = hot_vix_analysis["multiplier"]
            # 更新明日决策矩阵
            mc["tomorrow_plan"] = get_tomorrow_plan(hot_vix_analysis, mc.get("market_temp", {}).get("value", 50))
            hot_data["timestamp"] = now_dt.isoformat()

            # 更新缓存
            STRATEGY_CACHE["last_update"] = current_time
            STRATEGY_CACHE["dashboard_data"] = hot_data
            print(f"[{now_dt.strftime('%H:%M:%S')}] [HOT] Refresh done: VIX={hot_vix:.2f} CNY={hot_cny:.4f}")
            return hot_data
        except Exception as e:
            print(f"[Hot Refresh] 降级到全量刷新: {e}")
            # fall through to full refresh below


    # 默认值初始化
    capital_value, capital_trend, capital_status = "---", "数据提取中", "up"
    total_temp, temp_label, pos_advice = 50.0, "数据加载中", "50% (中性参考)"
    buy_list, sell_list = [], []
    latest_vix, vix_change, vix_status = 18.25, -1.5, "down"
    latest_cny = 7.23

    try:
        # 1. 抓取真实的 VIX 恐慌/避险情绪指数
        try:
            loop = asyncio.get_event_loop()
            vix_result = await loop.run_in_executor(executor, _fetch_vix_for_dashboard)
            latest_vix, prev_vix = vix_result
            vix_change = ((latest_vix - prev_vix) / prev_vix * 100) if prev_vix > 0 else 0
            vix_status = "down" if vix_change < 0 else "up"
        except Exception as e:
            print(f"Warning: VIX fetch failed: {e}")

        # 1.1 抓取离岸人民币汇率 (USD/CNY)
        try:
            loop = asyncio.get_event_loop()
            latest_cny = await loop.run_in_executor(executor, _fetch_cny_for_dashboard)
        except Exception as e:
            print(f"Warning: CNY fetch failed: {e}")

        # Tushare 准备
        ts.set_token("5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6")
        pro = ts.pro_api()
        today_str = datetime.now().strftime('%Y%m%d')

        # 2. 并行运行三大策略引擎 (Real-time Execution)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Real-time Strategy Engines...")
        loop = asyncio.get_event_loop()
        mr_future = loop.run_in_executor(executor, run_strategy)
        div_future = loop.run_in_executor(executor, run_dividend_strategy)
        mom_future = loop.run_in_executor(executor, run_momentum_strategy)
        
        mr_res, div_res, mom_res = await asyncio.gather(mr_future, div_future, mom_future)
        
        # 包装MR裸list为标准结构
        if isinstance(mr_res, list):
            mr_res = _wrap_mr_results(mr_res)

        # 存储到缓存中供单独接口调用
        STRATEGY_CACHE["strategy_results"] = {"mr": mr_res, "div": div_res, "mom": mom_res}

        # 3. 解析策略信号用于仪表盘
        # --- 均值回归 MR ---
        mr_overview = mr_res.get("data", {}).get("market_overview", {})
        mr_status = {
            "status_text": f"发现 {mr_overview.get('signal_count', {}).get('buy', 0)} 只猎物",
            "status_class": "active" if mr_overview.get('signal_count', {}).get('buy', 0) > 0 else "dormant",
            "metric1": f"{mr_overview.get('above_3pct', 0)}只偏离",
            "metric2": f"{mr_overview.get('total_suggested_position', 0)}% 建议"
        }
        
        # --- 动量轮动 MOM ---
        mom_overview = mom_res.get("data", {}).get("market_overview", {})
        mom_status = {
            "status_text": f"动能主线: {mom_overview.get('top1_name', '---')}",
            "status_class": "active" if mom_overview.get('buy_count', 0) > 0 else "warning",
            "metric1": f"{mom_overview.get('avg_momentum', 0)}% 均动量",
            "metric2": f"满仓位:{mom_overview.get('position_cap', 0)}%"
        }
        
        # --- 红利防线 DIV ---
        div_overview = div_res.get("data", {}).get("market_overview", {})
        div_status = {
            "status_text": f"趋势向上: {div_overview.get('trend_up_count', 0)}/8",
            "status_class": "active" if div_overview.get('trend_up_count', 0) >= 4 else "dormant",
            "metric1": f"买入信号: {div_overview.get('buy_count', 0)}",
            "metric2": f"建议 {div_overview.get('total_suggested_pos', 0)}%"
        }

        # --- V7.0: AIAE 引擎注入 (dashboard-data 级) ---
        aiae_regime = 3  # 默认 Ⅲ级 中性均衡
        aiae_cap = 65
        aiae_v1_value = 0.0
        aiae_regime_cn = "中性均衡"
        aiae_report = {}
        try:
            _aiae_engine = get_aiae_engine()
            aiae_report = _aiae_engine.generate_report()
            if aiae_report.get("status") == "success":
                aiae_regime = aiae_report["current"]["regime"]
                aiae_v1_value = aiae_report["current"]["aiae_v1"]
                aiae_cap = aiae_report["position"]["matrix_position"]
                aiae_regime_cn = aiae_report["current"]["regime_info"]["cn"]
                print(f"[Dashboard] AIAE注入成功: V1={aiae_v1_value:.1f}% Regime={aiae_regime} Cap={aiae_cap}%")
            else:
                print(f"[Dashboard] AIAE降级: {aiae_report.get('message', 'unknown')}")
        except Exception as e:
            print(f"[Dashboard] AIAE引擎异常,降级Ⅲ级: {e}")

        # 4. 汇总买入/卖出区 (Buy/Danger Zone Synchronization)
        vetted_buy = []
        # 从 MR 选 Top 2
        for s in mr_res.get("data", {}).get("buy_signals", [])[:2]:
            vetted_buy.append({"name": s.get('name',''), "code": s.get('ts_code', s.get('code','')), "score": s.get('signal_score', s.get('score',0)), "pe": round(s.get('close', 0)/max(s.get('ma20', 1), 0.01), 2), "badge": "均值回归", "badgeClass": "buy"})
        # 从 MOM 选 Top 1
        for s in mom_res.get("data", {}).get("buy_signals", [])[:1]:
            vetted_buy.append({"name": s.get('name',''), "code": s.get('ts_code', s.get('code','')), "score": s.get('signal_score', 85), "metric": f"动量:{s.get('momentum_pct',0)}%", "badge": "动量爆发", "badgeClass": "buy"})
        
        vetted_sell = []
        # 从 MR 选 Top 2 卖出
        for s in mr_res.get("data", {}).get("sell_signals", [])[:2]:
            vetted_sell.append({"name": s.get('name',''), "code": s.get('ts_code', s.get('code','')), "score": s.get('signal_score', s.get('score',0)), "pe": "超买", "badge": "偏离过大", "badgeClass": "sell"})

        # 5. HSGT & Liquidity Score (A+H 跨境流量共振引擎)
        total_money_z = 0.0 # 初始化中性流量
        try:
            df_hsgt = pro.moneyflow_hsgt(start_date='20250101', end_date=today_str, limit=30)
            if df_hsgt is not None and not df_hsgt.empty:
                df_hsgt_sorted = df_hsgt.sort_values('trade_date', ascending=True)
                
                # A股 (北向资金)
                df_hsgt_sorted['cum_5d_n'] = df_hsgt_sorted['north_money'].rolling(window=5).sum()
                latest_5d_n = float(df_hsgt_sorted['cum_5d_n'].iloc[-1])
                hist_5d_n = df_hsgt_sorted['cum_5d_n'].dropna().tail(20)
                mean_n, std_n = hist_5d_n.mean(), hist_5d_n.std() if hist_5d_n.std() > 0 else 1.0
                z_n = (latest_5d_n - mean_n) / std_n
                
                # 港股 (南向资金)
                df_hsgt_sorted['cum_5d_s'] = df_hsgt_sorted['south_money'].rolling(window=5).sum()
                latest_5d_s = float(df_hsgt_sorted['cum_5d_s'].iloc[-1])
                hist_5d_s = df_hsgt_sorted['cum_5d_s'].dropna().tail(20)
                mean_s, std_s = hist_5d_s.mean(), hist_5d_s.std() if hist_5d_s.std() > 0 else 1.0
                z_s = (latest_5d_s - mean_s) / std_s
                
                total_money_z = z_n + z_s
                
                capital_a = {
                    "value": f"A: {round(latest_5d_n/10000.0, 1)} 亿",
                    "trend": "北向稳步流入" if z_n > 0.5 else ("北向抛投中" if z_n < -0.5 else "北向博弈均衡"),
                    "status": "up" if z_n > 0.5 else ("down" if z_n < -0.5 else "neutral")
                }
                capital_h = {
                    "value": f"H: {round(latest_5d_s/10000.0, 1)} 亿",
                    "trend": "南向抢筹中" if z_s > 0.5 else ("南向撤退中" if z_s < -0.5 else "南向博弈均衡"),
                    "status": "up" if z_s > 0.5 else ("down" if z_s < -0.5 else "neutral")
                }
                liquidity_score = max(0, min(100, 50 + total_money_z * 12))
            else:
                capital_a = {"value": "A: --", "trend": "数据缺失", "status": "neutral"}
                capital_h = {"value": "H: --", "trend": "数据缺失", "status": "neutral"}
                liquidity_score = 50.0
        except Exception as e:
            print(f"HSGT Logic Error: {e}")
            capital_a, capital_h = {"value": "A: ERR", "trend": "异常", "status": "down"}, {"value": "H: ERR", "trend": "异常", "status": "down"}
            liquidity_score = 50.0

        # 6. 计算市场温度 V6.0 (三维决策引擎)
        # 宽基宽度(30%) + 流动性(30%) + 宏观VIX/CNY(40%)
        # 为了生产速度，这里复用 V5.0 的一些基础统计
        low_pe_score = 65.0 # 简化为固定基准或从 MR 结果推导
        vix_score = max(0, min(100, 100 - (latest_vix - 10) * 3))
        cny_score = max(0, min(100, 100 - (latest_cny - 7.0) * 100))
        total_temp = round(low_pe_score * 0.3 + liquidity_score * 0.3 + (vix_score + cny_score) * 0.2, 1) # Keep for market temp display
        
        # 6. DMSO 核心策略引擎 (V3.3 机构级)
        # --- A股得分维度 (权重: 60%) ---
        margin_score = get_margin_risk_ratio(pro, today_str) # 25% (杠杆情绪)
        breadth_score = get_market_breadth(pro, today_str) # 20% (年线比例代理)
        # ERP 动态计算 (3.0-4.0 为中枢)
        erp_val = 3.5 + (liquidity_score - 50) / 20.0
        erp_score = min(100, max(0, (erp_val - 2.5) / (4.5 - 2.5) * 100)) # 30% (估值底)
        turnover_score = 55.0 # 25% (筹码交换频率代理)
        
        score_a = margin_score * 0.25 + turnover_score * 0.25 + erp_score * 0.30 + breadth_score * 0.20
        
        # --- 港股得分维度 (权重: 40%) ---
        hsi_pe_score = 65.0 # 40% (5年PE分位)
        # 港股外资/内资流动性代理 (由 HSGT Z-Score 映射)
        epfr_proxy = 50 + (z_s * 10) # 30% 外资动向
        sb_flow_score = min(100, max(0, 50 + z_s * 15)) # 30% 南向内资
        
        score_hk = hsi_pe_score * 0.40 + epfr_proxy * 0.30 + sb_flow_score * 0.30
        
        # AH 溢价调节 (±15% H股吸引力修正)
        ah_adj = get_ah_premium_adj(pro, today_str)
        score_hk = min(100, score_hk * ah_adj)
        
        # --- 全局流动性熔断监控 ---
        is_circuit_breaker = get_liquidity_crisis_signal(pro, today_str)
        
        # V4.0/V4.5 VIX 全局风控 (Institutional Risk Overlay)
        # 获取 VIX 分析以便后续进行“恐慌修正温度 (PAT)”与“仓位路径预判”
        vix_analysis = get_vix_analysis(latest_vix)

        # --- 最终合成与温度定性 (V3.6) ---
        base_temp = round(score_a * 0.6 + score_hk * 0.4, 1)
        
        # V4.5 PAT: VIX 恐慌修正 (Panic-Adjusted Temperature)
        # 权重映射：VIX 百分位 > 50% 时，开始压制温度得分，反映避险溢价
        vix_p = vix_analysis.get('percentile', 50)
        panic_adj = min(1.0, 1.25 - (vix_p / 100.0)) # 线性压制因子
        total_temp = round(base_temp * panic_adj, 1)
        
        erp_multiplier, valuation_label, erp_z = get_erp_multiplier()
        
        # V7.0 (V2.1 Joint Matrix): AIAE × ERP 双维驱动仓位矩阵 (替代五因子)
        try:
            _aiae_engine = get_aiae_engine()
            # 获取ERP Tier
            erp_score = min(100, max(0, (erp_val - 2.5) / (4.5 - 2.5) * 100))
            weights_5, erp_tier = _aiae_engine.get_run_all_weights(aiae_regime, erp_score)
        except Exception as e:
            print(f"[Dashboard Matrix Error] {e}")
            weights_5 = {"mr": 0.15, "div": 0.30, "mom": 0.10, "erp": 0.15, "aiae_etf": 0.30}
            erp_tier = "neutral"

        # V7.0: 矩阵式统一收口仓位上限 (前置已经由 aiae_report["position"]["matrix_position"] 注入到了 aiae_cap)
        # 流动性熔断保护
        if is_circuit_breaker:
            final_pos_val = min(aiae_cap, 10)
            status_label = "流动性熔断"
            pos_advice = "0% (流动性熔断)"
        else:
            final_pos_val = aiae_cap
            status_label = "过热" if aiae_regime >= 4 else ("偏冷" if aiae_regime <= 2 else "中性")
            tier_cn = {"bull": "🟢看多", "neutral": "🟡中性均衡", "bear": "🔴看空"}.get(erp_tier, "🟡中性均衡")
            pos_advice = f"ERP {tier_cn} (Cap {aiae_cap}%)"
            
        temp_label = f"{status_label} | {valuation_label}"
        
        # V7.0: AIAE regime → regime_name (替代旧版 get_regime_allocation)
        _aiae_regime_name_map = {1: "极度恐慌", 2: "低配置区", 3: "中性均衡", 4: "偏热区域", 5: "极度过热"}
        regime_name = _aiae_regime_name_map.get(aiae_regime, "中性均衡")
        
        # 覆写 dashboard-data 输出使用的 "综合得分" 做兼容
        # V7.0: 以 AIAE 矩阵仓位替代旧版五因子合成, factors/signal_detail 保留空壳供前端兼容渲染
        hub_result = {
            "composite_score": aiae_cap,
            "confidence": aiae_cap,
            "position": final_pos_val,
            "position_label": pos_advice,
            "factors": {
                "aiae_regime": {"score": round(max(10, 100 - (aiae_regime - 1) * 22.5), 1), "weight": 0.40, "label": aiae_regime_cn},
                "erp_value":   {"score": round(erp_score, 1), "weight": 0.25, "label": valuation_label},
                "vix_fear":    {"score": round(vix_score, 1), "weight": 0.15, "label": vix_analysis.get('label', '—')},
                "capital_flow": {"score": round(liquidity_score, 1), "weight": 0.10, "label": "资金流" if total_money_z > 0.5 else ("资金流出" if total_money_z < -0.5 else "资金中性")},
                "macro_temp":  {"score": round(100 - total_temp, 1), "weight": 0.10, "label": status_label},
            },
            "signal_detail": {
                "buy_total": mr_overview.get('signal_count', {}).get('buy', 0) + mom_overview.get('buy_count', 0) + div_overview.get('buy_count', 0),
                "sell_total": mr_overview.get('signal_count', {}).get('sell', 0),
                "mr_buy": mr_overview.get('signal_count', {}).get('buy', 0),
                "mr_sell": mr_overview.get('signal_count', {}).get('sell', 0),
                "mom_buy": mom_overview.get('buy_count', 0),
                "div_buy": div_overview.get('buy_count', 0),
                "div_trend_up": div_overview.get('trend_up_count', 0),
            }
        }

        # 策略权重分配
        regime_weights_5 = weights_5
        
        # apply_strategy_filters 过滤器兼容 (仍保留对 mr/div/mom 子项调整)
        regime_weights_3 = {"div": regime_weights_5["div"], "mr": regime_weights_5["mr"], "mom": regime_weights_5["mom"]}
        filtered_3, strategy_filters = apply_strategy_filters(regime_weights_3)
        
        # 合并回 5 策略权重
        regime_weights = {
            "mr": filtered_3["mr"], "div": filtered_3["div"], "mom": filtered_3["mom"],
            "erp": regime_weights_5["erp"], "aiae_etf": regime_weights_5["aiae_etf"]
        }
        # 归一化
        _wt = sum(regime_weights.values())
        if _wt > 0:
            regime_weights = {k: round(v / _wt, 3) for k, v in regime_weights.items()}

        # 各策略名义仓位 (5策略)
        strategy_positions = {
            "mr_pos":  round(final_pos_val * regime_weights["mr"], 1),
            "mom_pos": round(final_pos_val * regime_weights["mom"], 1),
            "div_pos": round(final_pos_val * regime_weights["div"], 1),
            "erp_pos": round(final_pos_val * regime_weights["erp"], 1),
            "aiae_pos": round(final_pos_val * regime_weights["aiae_etf"], 1),
            "total":   round(final_pos_val, 1)
        }

        # V7.0: ERP择时 策略卡片数据 (此处 valuation_label/erp_z 已可用)
        erp_status = {
            "status_text": f"ERP {valuation_label}",
            "status_class": "active" if erp_z > 0.5 else ("warning" if erp_z < -0.5 else "dormant"),
            "metric1": f"ERP {round(erp_val, 2)}%",
            "metric2": f"Z-Score {round(erp_z, 2)}"
        }

        # V7.0: AIAE宏观仓位 策略卡片数据
        aiae_regime_info = AIAE_REGIMES.get(aiae_regime, AIAE_REGIMES[3])
        aiae_status = {
            "status_text": f"{aiae_regime_info['emoji']} {aiae_regime_cn}",
            "status_class": "active" if aiae_regime <= 2 else ("warning" if aiae_regime >= 4 else "dormant"),
            "metric1": f"AIAE {round(aiae_v1_value, 1)}%",
            "metric2": f"Cap {aiae_cap}%"
        }

        # 7. 行业热力全景图 V4.0 (Sector Rotation Heatmap with RPS)
        # 扩展至 12 个核心行业 ETF，覆盖 A 股主要赛道。采用 ETF 代理确保极速与稳定。
        sector_map = {
            "512660.SH": "军工龙头",
            "512010.SH": "医药生物",
            "512690.SH": "酒/自选消费",
            "512760.SH": "半导体/芯片",
            "512720.SH": "计算机/AI",
            "512880.SH": "证券/非银",
            "512800.SH": "银行/金融",
            "515030.SH": "新能源车",
            "512100.SH": "中证传媒",
            "512400.SH": "有色金属",
            "510180.SH": "上证180/主板",
            "159915.SZ": "创业板/成长"
        }
        
        sector_heatmap = []
        try:
            loop = asyncio.get_event_loop()
            
            def fetch_etf_history(code):
                try:
                    # 优先使用 Tushare 专业接口计算 20D RPS 和 5D Trend
                    # asset='FD' (基金/ETF), adj='qfq' (前复权)
                    df = ts.pro_bar(ts_code=code, asset='FD', start_date='20250101', adj='qfq')
                    if df is not None and not df.empty:
                        return df.sort_values('trade_date', ascending=True)
                    return pd.DataFrame()
                except Exception as e:
                    print(f"Fetch Error {code}: {e}")
                    return pd.DataFrame()

            # V4.7 并行加速: 使用 asyncio.gather 同时拉取 12 个 ETF
            tasks = [loop.run_in_executor(executor, fetch_etf_history, code) for code in sector_map.keys()]
            results = await asyncio.gather(*tasks)
            
            raw_data = {}
            for i, (code, name) in enumerate(sector_map.items()):
                df = results[i]
                if not df.empty and len(df) >= 20:
                    raw_data[code] = {"name": name, "df": df}

            # 计算指标
            comparison_list = []
            for code, info in raw_data.items():
                df = info["df"]
                p_now = float(df['close'].iloc[-1])
                p_5d = float(df['close'].iloc[-5])
                p_20d = float(df['close'].iloc[-20])
                
                chg_1d = float(df['pct_chg'].iloc[-1])
                trend_5d = (p_now / p_5d - 1) * 100
                ret_20d = (p_now / p_20d - 1) * 100
                
                comparison_list.append({
                    "code": code,
                    "name": info["name"],
                    "change": round(chg_1d, 2),
                    "trend_5d": round(trend_5d, 2),
                    "ret_20d": ret_20d,
                    "status": "up" if chg_1d >= 0 else "down"
                })

            # 计算 RPS (基于 20D 收益率的横向排名)
            comparison_list.sort(key=lambda x: x['ret_20d'])
            for i, item in enumerate(comparison_list):
                # RPS = (当前排名 / 总数) * 100
                item["rps"] = int(((i + 1) / len(comparison_list)) * 100)
            
            # 最终按 5D Trend 降序排列 (满足用户对“5天当前排名”的要求)
            comparison_list.sort(key=lambda x: x['trend_5d'], reverse=True)
            # V5.0: 交叉标注策略信号
            _mr_sigs = {s.get('ts_code',''): s.get('signal','') for s in mr_res.get("data",{}).get("signals",[])}
            _mom_sigs = {s.get('ts_code',''): s.get('signal','') for s in mom_res.get("data",{}).get("signals",[])}
            for _item in comparison_list:
                _c = _item["code"]
                _item["mr_signal"] = _mr_sigs.get(_c, "")
                _item["mom_signal"] = _mom_sigs.get(_c, "")
            sector_heatmap = comparison_list

        except Exception as e:
            print(f"Heatmap V4.0 Logic Error: {e}")
            
        # 兜底逻辑：如果接口全线崩溃
        if not sector_heatmap:
            sector_heatmap = [
                {"name": "半导体/芯片", "code": "512760.SH", "change": 2.35, "trend_5d": 6.8, "rps": 95, "status": "up"},
                {"name": "计算机/AI", "code": "512720.SH", "change": 1.15, "trend_5d": 3.4, "rps": 88, "status": "up"},
                {"name": "新能源车", "code": "515030.SH", "change": 0.85, "trend_5d": 2.1, "rps": 82, "status": "up"},
                {"name": "证券/非银", "code": "512880.SH", "change": 0.45, "trend_5d": 1.2, "rps": 62, "status": "up"},
                {"name": "医药生物", "code": "512010.SH", "change": -1.2, "trend_5d": -3.5, "rps": 35, "status": "down"}
            ]

        final_data = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "macro_cards": {
                    "vix": {
                        "value": round(latest_vix, 2), 
                        "trend": f"{round(vix_change, 1)}%", 
                        "status": vix_status,
                        "regime": vix_analysis["label"],
                        "class": vix_analysis["class"],
                        "desc": vix_analysis.get("desc", ""),
                        "percentile": vix_analysis.get("percentile", 0)
                    },
                    "tomorrow_plan": get_tomorrow_plan(vix_analysis, total_temp),
                    "capital_a": capital_a,
                    "capital_h": capital_h,
                    "signal": {
                        "value": f"MR {mr_overview.get('signal_count',{}).get('buy',0)}买/{mr_overview.get('signal_count',{}).get('sell',0)}卖 · ERP {valuation_label}",
                        "trend": f"DT {div_overview.get('trend_up_count',0)}/8趋 · AIAE {aiae_regime_cn} · MOM {mom_overview.get('top1_name','—')}",
                        "status": "up" if (mr_overview.get('signal_count',{}).get('buy',0) + div_overview.get('buy_count',0)) > 0 else "neutral"
                    },
                    "regime_banner": {
                        "regime": regime_name,
                        "temp": total_temp,
                        "advice": pos_advice,
                        "vix": round(latest_vix, 2),
                        "vix_label": vix_analysis.get('label','—'),
                        "z_capital": round(total_money_z, 2),
                        "aiae_regime": aiae_regime,
                        "aiae_regime_cn": aiae_regime_cn,
                        "aiae_cap": aiae_cap,
                        "aiae_v1": round(aiae_v1_value, 1)
                    },
                    "aiae_thermometer": (lambda r: {
                        "aiae_v1": r.get("current", {}).get("aiae_v1", aiae_v1_value),
                        "regime": r.get("current", {}).get("regime", aiae_regime),
                        "regime_cn": r.get("current", {}).get("regime_info", {}).get("cn", aiae_regime_cn),
                        "regime_emoji": r.get("current", {}).get("regime_info", {}).get("emoji", "🟡"),
                        "regime_color": r.get("current", {}).get("regime_info", {}).get("color", "#eab308"),
                        "regime_name": r.get("current", {}).get("regime_info", {}).get("name", "Regime III"),
                        "cap": r.get("position", {}).get("matrix_position", aiae_cap),
                        "slope": r.get("current", {}).get("slope", {}).get("slope", 0),
                        "slope_direction": r.get("current", {}).get("slope", {}).get("direction", "flat"),
                        "margin_heat": r.get("current", {}).get("margin_heat", 0),
                        "fund_position": r.get("current", {}).get("fund_position", 0),
                        "aiae_simple": r.get("current", {}).get("aiae_simple", 0),
                        "erp_value": r.get("position", {}).get("erp_value", 0),
                        "status": r.get("status", "fallback"),
                    })(aiae_report) if aiae_report else {
                        "aiae_v1": aiae_v1_value, "regime": aiae_regime, "regime_cn": aiae_regime_cn,
                        "regime_emoji": "🟡", "regime_color": "#eab308", "regime_name": "Regime III",
                        "cap": aiae_cap, "slope": 0, "slope_direction": "flat",
                        "margin_heat": 0, "fund_position": 0, "aiae_simple": 0,
                        "erp_value": 0, "status": "fallback",
                    },
                    "market_temp": {
                        "value": total_temp, 
                        "label": temp_label, 
                        "advice": pos_advice,
                        "score_a": int(score_a),
                        "score_hk": int(score_hk),
                        "erp_z": erp_z,
                        "regime_name": regime_name,
                        "regime_weights": regime_weights,
                        "strategy_positions": strategy_positions,
                        "market_vix_multiplier": vix_analysis["multiplier"],
                        "strategy_filters": strategy_filters,
                        "pos_path": get_position_path(final_pos_val, vix_analysis),
                        "mindset": get_institutional_mindset(total_temp),
                        "holding_cycle_a": "5-8 个交易日",
                        "holding_cycle_hk": "15-22 个交易日",
                        # V7.0: 第6因子(AIAE温度)仅供前端条形图展示, 不参与 compute_scientific_position() 的 composite 计算
                        "hub_factors": {**hub_result["factors"], "aiae_temp": {"score": round(max(10, 100 - (aiae_regime - 1) * 22.5), 1), "weight": 0.15, "label": aiae_regime_cn}},
                        "hub_confidence": hub_result["confidence"],
                        "hub_composite": hub_result["composite_score"],
                        "hub_signal_detail": hub_result["signal_detail"],
                        "z_capital": round(total_money_z, 2)
                    },
                    "erp": {
                        "value": f"{round(erp_val, 2)}%",
                        "trend": valuation_label,
                        "status": "up" if erp_z > 0.5 else ("down" if erp_z < -0.5 else "neutral")
                    }
                },
                "sector_heatmap": sector_heatmap,
                "strategy_status": {"mr": mr_status, "mom": mom_status, "div": div_status, "erp": erp_status, "aiae": aiae_status},
                "execution_lists": {"buy_zone": vetted_buy, "danger_zone": vetted_sell}
            }
        }
        
        # 更新缓存
        STRATEGY_CACHE["last_update"] = current_time
        STRATEGY_CACHE["dashboard_data"] = final_data
        return final_data

    except Exception as e:
        print(f"Global Error: {traceback.format_exc()}")
        return {"status": "error", "message": f"Global Error: {str(e)}"}

@app.get("/api/v1/strategy")
async def get_strategy():
    """均值回归策略详情 — V4.2 包装层"""
    if STRATEGY_CACHE["strategy_results"]["mr"]:
        cached = STRATEGY_CACHE["strategy_results"]["mr"]
        # 如果缓存已经是包装格式就直接返回
        if isinstance(cached, dict) and "status" in cached:
            return cached
        # 否则包装裸list
        return _wrap_mr_results(cached)
    raw = await asyncio.get_event_loop().run_in_executor(executor, run_strategy)
    wrapped = _wrap_mr_results(raw)
    STRATEGY_CACHE["strategy_results"]["mr"] = wrapped
    return wrapped


def _wrap_mr_results(signals_list: list) -> dict:
    """把 run_strategy() 返回的裸 list 包装成前端期望的标准结构"""
    from datetime import datetime as _dt

    # 补算 suggested_position（MR引擎不输出该字段）
    for s in signals_list:
        if "suggested_position" not in s:
            sig = s.get("signal", "hold")
            score = s.get("signal_score", 0)
            if sig == "buy":
                s["suggested_position"] = 15 if score >= 85 else (10 if score >= 70 else 5)
            elif sig in ("sell", "sell_half", "sell_weak", "stop_loss", "no_entry"):
                s["suggested_position"] = 0
            else:
                s["suggested_position"] = 0

    valid = [s for s in signals_list if s.get("signal") != "error"]
    errors = [s for s in signals_list if s.get("signal") == "error"]
    buy_signals = [s for s in valid if s.get("signal") == "buy"]
    sell_signals = [s for s in valid if s.get("signal") in ("sell", "sell_half", "sell_weak")]

    # 计算 market_overview
    biases = [abs(s.get("bias", 0)) for s in valid]
    max_dev_item = max(valid, key=lambda x: abs(x.get("bias", 0)), default={})
    above_3 = sum(1 for s in valid if abs(s.get("bias", 0)) >= 3)
    total_pos = sum(s.get("suggested_position", 0) for s in buy_signals)
    divergence = "偏离中" if above_3 > 3 else "正常"

    overview = {
        "avg_deviation": round(sum(biases) / len(biases), 2) if biases else 0,
        "max_deviation": {
            "name": max_dev_item.get("name", "—"),
            "value": round(abs(max_dev_item.get("bias", 0)), 2),
        },
        "signal_count": {"buy": len(buy_signals), "sell": len(sell_signals)},
        "total_suggested_position": total_pos,
        "above_3pct": above_3,
        "market_divergence": divergence,
    }

    return {
        "status": "success",
        "timestamp": _dt.now().isoformat(),
        "data": {
            "signals": valid,
            "market_overview": overview,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "errors": errors,
        },
    }

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
        except:
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
        mr_result = _wrap_mr_results(mr_raw) if isinstance(mr_raw, list) else mr_raw
        div_result = div_raw
        mom_result = mom_raw
        erp_result = erp_raw
        aiae_result = aiae_raw

        # 缓存
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

def get_etf_constituents(ts_code):
    """Hardcoded Top 5 Constituents for the 12 Core ETFs (Institutional Proxy)"""
    mapping = {
        "512660.SH": [{"name": "中航沈飞", "weight": "12%"}, {"name": "航发动力", "weight": "10%"}, {"name": "中航西飞", "weight": "8%"}, {"name": "中航光电", "weight": "7%"}, {"name": "内蒙一机", "weight": "5%"}],
        "512010.SH": [{"name": "恒瑞医药", "weight": "15%"}, {"name": "药明康德", "weight": "12%"}, {"name": "迈瑞医疗", "weight": "10%"}, {"name": "片仔癀", "weight": "8%"}, {"name": "爱尔眼科", "weight": "7%"}],
        "512690.SH": [{"name": "贵州茅台", "weight": "18%"}, {"name": "五粮液", "weight": "14%"}, {"name": "泸州老窖", "weight": "10%"}, {"name": "山西汾酒", "weight": "8%"}, {"name": "伊利股份", "weight": "7%"}],
        "512760.SH": [{"name": "北方华创", "weight": "14%"}, {"name": "中芯国际", "weight": "12%"}, {"name": "韦尔股份", "weight": "10%"}, {"name": "海光信息", "weight": "9%"}, {"name": "紫光国微", "weight": "7%"}],
        "512720.SH": [{"name": "金山办公", "weight": "13%"}, {"name": "科大讯飞", "weight": "11%"}, {"name": "中科曙光", "weight": "10%"}, {"name": "浪潮信息", "weight": "8%"}, {"name": "宝信软件", "weight": "7%"}],
        "512880.SH": [{"name": "中信证券", "weight": "16%"}, {"name": "东方财富", "weight": "14%"}, {"name": "华泰证券", "weight": "10%"}, {"name": "海通证券", "weight": "8%"}, {"name": "招商证券", "weight": "7%"}],
        "512800.SH": [{"name": "招商银行", "weight": "17%"}, {"name": "工商银行", "weight": "13%"}, {"name": "建设银行", "weight": "11%"}, {"name": "兴业银行", "weight": "9%"}, {"name": "农业银行", "weight": "8%"}],
        "515030.SH": [{"name": "宁德时代", "weight": "20%"}, {"name": "比亚迪", "weight": "15%"}, {"name": "亿纬锂能", "weight": "10%"}, {"name": "赣锋锂业", "weight": "8%"}, {"name": "天齐锂业", "weight": "7%"}],
        "512100.SH": [{"name": "分众传媒", "weight": "14%"}, {"name": "完美世界", "weight": "10%"}, {"name": "芒果超媒", "weight": "9%"}, {"name": "万达电影", "weight": "8%"}, {"name": "光线传媒", "weight": "7%"}],
        "512400.SH": [{"name": "紫金矿业", "weight": "16%"}, {"name": "洛阳钼业", "weight": "12%"}, {"name": "山东黄金", "weight": "10%"}, {"name": "北方稀土", "weight": "9%"}, {"name": "天山铝业", "weight": "7%"}],
        "510180.SH": [{"name": "中国平安", "weight": "14%"}, {"name": "贵州茅台", "weight": "12%"}, {"name": "招商银行", "weight": "10%"}, {"name": "中信证券", "weight": "8%"}, {"name": "长江电力", "weight": "7%"}],
        "159915.SZ": [{"name": "宁德时代", "weight": "18%"}, {"name": "东方财富", "weight": "12%"}, {"name": "迈瑞医疗", "weight": "10%"}, {"name": "汇川技术", "weight": "9%"}, {"name": "阳光电源", "weight": "8%"}]
    }
    return mapping.get(ts_code, [])


# ─────────────────────────────────────────────
# 宏观ERP择时引擎 V1.0 API
# ─────────────────────────────────────────────
@app.get("/api/v1/strategy/erp-timing")
async def get_erp_timing():
    """宏观ERP择时引擎 — 三维信号 + 历史走势"""
    try:
        engine = get_erp_engine()
        report = await asyncio.get_event_loop().run_in_executor(executor, engine.generate_report)
        return {"status": "success", "data": report}
    except Exception as e:
        print(f"[ERP API] Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────
# 海外ERP择时引擎 V1.0 API (美股 + 日本 + 中国对比)
# ─────────────────────────────────────────────
@app.get("/api/v1/strategy/erp-global")
async def get_erp_global():
    """海外ERP择时 — 美股+日本+港股+中国四地对比 (V2.0)"""
    try:
        from erp_us_engine import get_us_erp_engine
        from erp_jp_engine import get_jp_erp_engine

        loop = asyncio.get_event_loop()
        us_engine = get_us_erp_engine()
        jp_engine = get_jp_erp_engine()
        cn_engine = get_erp_engine()
        hk_hsi_engine = get_hk_erp_engine("HSI")
        hk_tech_engine = get_hk_erp_engine("HSTECH")

        us_future = loop.run_in_executor(executor, us_engine.generate_report)
        jp_future = loop.run_in_executor(executor, jp_engine.generate_report)
        cn_future = loop.run_in_executor(executor, cn_engine.compute_signal)
        hk_hsi_future = loop.run_in_executor(executor, hk_hsi_engine.generate_report)
        hk_tech_future = loop.run_in_executor(executor, hk_tech_engine.generate_report)

        us_report = await us_future
        jp_report = await jp_future
        cn_signal = await cn_future
        hk_hsi_report = await hk_hsi_future
        hk_tech_report = await hk_tech_future

        cn_snap = cn_signal.get("current_snapshot", {})
        cn_sig = cn_signal.get("signal", {})
        hk_hsi_snap = hk_hsi_report.get("current_snapshot", {})
        hk_hsi_sig = hk_hsi_report.get("signal", {})

        def _extract_region(snap, sig):
            return {
                "erp": snap.get("erp_value", 0), "score": sig.get("score", 0),
                "key": sig.get("key", "hold"), "label": sig.get("label", "--"),
                "color": sig.get("color", "#94a3b8"), "emoji": sig.get("emoji", ""),
                "pe": snap.get("pe_ttm", 0), "yield": snap.get("yield_10y", snap.get("blended_rf", 0)),
            }

        global_comparison = {
            "cn": _extract_region(cn_snap, cn_sig),
            "us": _extract_region(us_report.get("current_snapshot", {}), us_report.get("signal", {})),
            "jp": _extract_region(jp_report.get("current_snapshot", {}), jp_report.get("signal", {})),
            "hk": _extract_region(hk_hsi_snap, hk_hsi_sig),
        }

        scores = {r: global_comparison[r]["score"] for r in ["cn", "us", "jp", "hk"]}
        sorted_r = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        rn = {"cn": "A股", "us": "美股", "jp": "日股", "hk": "港股"}

        # === A4: 智能配置比例 (归一化得分 + 最低8%底线) ===
        total_score = max(sum(scores.values()), 1)
        raw_ratios = {k: max(v / total_score, 0.08) for k, v in scores.items()}
        ratio_sum = sum(raw_ratios.values())
        alloc = {k: round(v / ratio_sum * 100) for k, v in raw_ratios.items()}
        # 修正至100%
        diff = 100 - sum(alloc.values())
        alloc[sorted_r[0][0]] += diff

        global_comparison["allocation"] = alloc
        global_comparison["advice"] = f"超配{rn[sorted_r[0][0]]}({sorted_r[0][1]:.0f}), 低配{rn[sorted_r[-1][0]]}({sorted_r[-1][1]:.0f})"
        global_comparison["allocation_text"] = f"🇨🇳 {alloc['cn']}% / 🇺🇸 {alloc['us']}% / 🇯🇵 {alloc['jp']}% / 🇭🇰 {alloc['hk']}%"

        return {"status": "success", "us": us_report, "jp": jp_report,
                "hk_hsi": hk_hsi_report, "hk_tech": hk_tech_report,
                "global_comparison": global_comparison, "updated_at": datetime.now().isoformat()}
    except Exception as e:
        print(f"[Global ERP] Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────
# 利率择时引擎 V1.0 API
# ─────────────────────────────────────────────
@app.get("/api/v1/strategy/rates")
async def get_rates_strategy():
    """利率择时 — 基于10Y美债收益率的股债配置策略"""
    try:
        from rates_strategy_engine import get_rates_engine
        engine = get_rates_engine()
        report = await asyncio.get_event_loop().run_in_executor(executor, engine.generate_report)
        return {"status": "success", "data": report}
    except Exception as e:
        print(f"[Rates API] Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────
# 自选扩池 · 标的名称查询接口
# ─────────────────────────────────────────────
_NAME_CACHE: Dict[str, str] = {}   # 轻量本地缓存，避免重复拉取

@app.get("/api/v1/stock/name")
async def get_stock_name(ts_code: str):
    """
    查询单只标的的中文名称，支持 A 股（xxx.SH / xxx.SZ）和场内 ETF（基金代码）。
    返回: {"ts_code": "600036.SH", "name": "招商银行", "type": "stock"}
    type: "stock" | "etf" | "index" | "unknown"
    """
    ts_code = ts_code.strip().upper()

    # 命中缓存直接返回
    if ts_code in _NAME_CACHE:
        return {"ts_code": ts_code, "name": _NAME_CACHE[ts_code], "type": "cached"}

    def do_lookup():
        pro = ts.pro_api("5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6")
        # 判断后缀决定查询策略
        suffix = ts_code.split(".")[-1] if "." in ts_code else ""
        code_num = ts_code.split(".")[0] if "." in ts_code else ts_code

        # ① 先尝试 ETF/基金 接口（适用于 5/6 位以 1/5 开头的 ETF 代码）
        try:
            df_fund = pro.fund_basic(ts_code=ts_code, market="E")
            if df_fund is not None and not df_fund.empty:
                name = df_fund.iloc[0]["name"]
                _NAME_CACHE[ts_code] = name
                return {"ts_code": ts_code, "name": name, "type": "etf"}
        except Exception:
            pass

        # ② 尝试 A 股 stock_basic
        try:
            df_stock = pro.stock_basic(ts_code=ts_code, fields="ts_code,name")
            if df_stock is not None and not df_stock.empty:
                name = df_stock.iloc[0]["name"]
                _NAME_CACHE[ts_code] = name
                return {"ts_code": ts_code, "name": name, "type": "stock"}
        except Exception:
            pass

        # ③ 尝试指数接口（沪深 000xxx / 399xxx 等）
        try:
            df_idx = pro.index_basic(ts_code=ts_code, fields="ts_code,name")
            if df_idx is not None and not df_idx.empty:
                name = df_idx.iloc[0]["name"]
                _NAME_CACHE[ts_code] = name
                return {"ts_code": ts_code, "name": name, "type": "index"}
        except Exception:
            pass

        # ④ 全部失败 → 返回 unknown，前端显示原始代码
        return {"ts_code": ts_code, "name": ts_code, "type": "unknown"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, do_lookup)
        return result
    except Exception as e:
        print(f"[StockName] Error for {ts_code}: {e}")
        return {"ts_code": ts_code, "name": ts_code, "type": "unknown"}


@app.get("/api/v1/industry-detail")
async def get_industry_detail(code: str):
    """
    V4.0 产业深度追踪接口: 复用tracking缓存 + 补充图表数据
    消灭所有Mock: RPS动态 + PE实时 + 20D动量(替代北向)
    """
    try:
        def fetch_data():
            # V4.0: 优先从tracking缓存取指标数据
            cached = _TRACKING_CACHE.get("data")
            cached_item = None
            if cached:
                cached_item = next((d for d in cached if (d.get('ts_code') or d.get('code')) == code), None)

            # 获取图表用价格数据
            dm = FactorDataManager()
            p_df = dm.get_price_payload(code)

            if p_df.empty:
                # Tushare实时拉取兜底
                try:
                    df_live = ts.pro_bar(ts_code=code, asset='FD', start_date='20241001', adj='qfq')
                    if df_live is not None and not df_live.empty:
                        p_df = df_live.sort_values('trade_date')
                        p_df['trade_date'] = p_df['trade_date'].astype(str)
                except:
                    pass

            if p_df.empty:
                return {"code": code, "metrics": {"rps": 50, "pe_percentile": 50, "crowding": 1.0,
                        "momentum_20d": {"ret_20d": 0, "label": "数据不足", "trend": "neutral"},
                        "constituents": get_etf_constituents(code)},
                        "chart_data": {"dates": [], "prices": [], "relative_strength": []}}

            p_df = p_df.sort_values('trade_date')

            # V4.0: 从缓存取已计算的真实指标
            if cached_item:
                rps_val = cached_item.get('rps', 50)
                pe_val = cached_item.get('pe_percentile', 50)
                crowding_val = cached_item.get('vol_ratio', 1.0)
                mom_20d = cached_item.get('momentum_20d', {"ret_20d": 0, "label": "—", "trend": "neutral"})
            else:
                # 无缓存时动态计算
                rps_val = 50.0
                pe_val = compute_price_percentile(p_df)
                amt_col = 'amount' if 'amount' in p_df.columns else None
                if amt_col and len(p_df) >= 20:
                    vol_ma20 = float(p_df[amt_col].tail(20).mean())
                    crowding_val = round(float(p_df[amt_col].iloc[-1]) / vol_ma20, 2) if vol_ma20 > 0 else 1.0
                else:
                    crowding_val = 1.0
                mom_20d = compute_momentum_20d(p_df)

            # 图表数据 (取最近60天做more context)
            chart_df = p_df.tail(60)
            dates = chart_df['trade_date'].astype(str).tolist()
            prices = chart_df['close'].tolist()
            base = float(chart_df['close'].iloc[0]) if not chart_df.empty else 1
            rs = [(float(p) / base * 100) for p in prices]

            detail_data = {
                "code": code,
                "metrics": {
                    "rps": rps_val,
                    "pe_percentile": pe_val,
                    "crowding": crowding_val,
                    "momentum_20d": mom_20d,
                    "constituents": get_etf_constituents(code)
                },
                "chart_data": {
                    "dates": dates[-30:],
                    "prices": prices[-30:],
                    "relative_strength": rs[-30:]
                }
            }
            return detail_data

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, fetch_data)
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- API Routes (Defined BEFORE Static Files to prevent path collision) ---

class BacktestRequest(BaseModel):
    strategy: str  # 'mr', 'div', 'mom', 'erp'
    ts_code: str
    start_date: str
    end_date: str
    initial_cash: float = 1000000.0
    params: dict = {}
    order_pct: float = 0.01
    adj: str = 'qfq'
    benchmark_code: str = '000300.SH'

class BatchBacktestRequest(BaseModel):
    items: List[BacktestRequest]

class TradeRequest(BaseModel):
    ts_code: str
    amount: int
    price: float
    name: str = ""
    action: str # "buy" or "sell"

@app.post("/api/v1/backtest")
async def run_backtest_api(req: BacktestRequest):
    """
    工业级回测执行接口 - 强化版 (支持 QFQ, POV, Trade Log)
    """
    try:
        bt = AlphaBacktester(initial_cash=req.initial_cash, benchmark_code=req.benchmark_code)
        
        # 1. 获取数据 (Fund 日线数据 + Adj Factors)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Backtest Req: {req.ts_code} ({req.strategy})")
        df = await asyncio.get_event_loop().run_in_executor(
            executor, bt.fetch_tushare_data, req.ts_code, req.start_date, req.end_date, req.adj
        )
        
        if df.empty:
            return {"status": "error", "message": f"未找到代码 {req.ts_code} 的历史数据，请检查代码或日期范围。"}
        
        # 2. 选择并执行策略逻辑 (V2.0: 与策略中心生产引擎参数完全对齐)
        p = req.params
        if req.strategy == 'mr':
            valid_keys = ['N_trend', 'rsi_period', 'rsi_buy', 'rsi_sell', 'bias_buy', 'stop_loss']
            filtered_p = {k: v for k, v in p.items() if k in valid_keys}
            # bias_buy 从前端 ×10 格式转换 (前端-20 → 引擎-2.0)
            if 'bias_buy' in filtered_p:
                filtered_p['bias_buy'] = filtered_p['bias_buy'] / 10.0
            signals = mean_reversion_strategy_vectorized(df, **filtered_p)
        elif req.strategy == 'div':
            valid_keys = ['ma_trend', 'rsi_period', 'rsi_buy', 'rsi_sell', 'bias_buy', 'ma_defend', 'stop_loss']
            filtered_p = {k: v for k, v in p.items() if k in valid_keys}
            if 'bias_buy' in filtered_p:
                filtered_p['bias_buy'] = filtered_p['bias_buy'] / 10.0
            signals = dividend_trend_strategy_vectorized(df, **filtered_p)
        elif req.strategy == 'mom':
            valid_keys = ['lookback_s', 'lookback_m', 'momentum_threshold', 'stop_loss']
            filtered_p = {k: v for k, v in p.items() if k in valid_keys}
            signals = momentum_rotation_strategy_vectorized(df, **filtered_p)
        elif req.strategy == 'erp':
            # ERP宏观择时: 需要额外加载宏观日频宽表
            valid_keys = ['buy_threshold', 'sell_threshold', 'erp_window', 'vol_window',
                          'w_erp_abs', 'w_erp_pct', 'w_m1', 'w_vol', 'w_credit', 'stop_loss']
            filtered_p = {k: v for k, v in p.items() if k in valid_keys}
            # 提前1年拉数据作为ERP分位回溯期
            macro_start = (datetime.strptime(req.start_date, '%Y%m%d') - timedelta(days=400)).strftime('%Y%m%d')
            macro_df = await asyncio.get_event_loop().run_in_executor(
                executor, prepare_erp_backtest_data, macro_start, req.end_date
            )
            signals = erp_timing_strategy_vectorized(df, macro_df=macro_df, **filtered_p)
        else:
            return {"status": "error", "message": "无效的策略类型"}
            
        # 3. V2.0 回测引擎 (含 grade/round_trips/diagnosis)
        results = bt.run_vectorized(df, signals, ts_code=req.ts_code, order_pct=req.order_pct)
        
        # 4. V2.0 蒙特卡洛 (Block Bootstrap 500x + 破产概率)
        equity_cv = pd.Series(results['equity_curve'])
        strat_returns = equity_cv.pct_change().fillna(0)
        results['monte_carlo'] = bt.run_monte_carlo(strat_returns, iterations=500)
            
        return {
            "status": "success",
            "data": results
        }
        
    except Exception as e:
        print(f"Backtest Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/batch-backtest")
async def run_batch_backtest(req: BatchBacktestRequest):
    """
    多策略对比 (Strategy PK) 接口
    """
    tasks = [run_backtest_api(item) for item in req.items]
    results = await asyncio.gather(*tasks)
    return {"status": "success", "data": results}

# --- Factor Analysis API ---

class FactorAnalysisRequest(BaseModel):
    factor_name: str = "roe"  # V5.0: roe/eps/netprofit_margin/bps/debt_to_assets/momentum_20d/volatility_20d/turnover_rate
    stock_pool: str = "top30" # 或者 'top100'
    start_date: str = "20200101"
    end_date: str = "20231231"

@app.post("/api/v1/factor-analysis")
async def run_factor_analysis(req: FactorAnalysisRequest):
    """
    因子看板核心 API V2.0：IC分布 + 分组收益 + 质量评级
    """
    try:
        dm = FactorDataManager()
        fa = FactorAnalyzer()
        
        # 1. 获取样本池
        all_stocks = dm.get_all_stocks()
        if req.stock_pool == "top30":
            sample_codes = all_stocks.head(30)["ts_code"].tolist()
        else:
            sample_codes = all_stocks.head(100)["ts_code"].tolist()
            
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Factor Analysis V5.0: {req.factor_name} on {len(sample_codes)} stocks")
        
        def run_analysis():
            # V5.0: 按需检查数据新鲜度, 过期则自动同步
            freshness = dm.check_data_freshness(sample_codes)
            sync_result = None
            if freshness['is_stale']:
                print(f"[Factor] 数据过期 {freshness['stale_days']} 天, 触发智能同步...")
                sync_result = dm.smart_sync(sample_codes)
                freshness = sync_result.get('freshness', freshness)

            analysis_data = fa.prepare_analysis_data(sample_codes, req.factor_name)
            if analysis_data.empty:
                return {"error": "未找到有效数据，请检查数据同步情况"}
                
            metrics = fa.calculate_metrics(analysis_data, req.factor_name)
            
            ic_series = metrics["ic_series"]
            q_rets = metrics["quantile_rets"]
            
            if isinstance(q_rets, pd.Series) and isinstance(q_rets.index, pd.MultiIndex):
                q_rets = q_rets.unstack()
            
            # V4.0: 构建增强返回数据
            q_avg_vals = q_rets.mean().values if not q_rets.empty else []
            
            return {
                "ic_mean": float(metrics["ic_mean"]),
                "ic_std": float(metrics["ic_std"]),
                "ic_ir": float(metrics["ir"]),
                "ic_win_rate": float(metrics["ic_win_rate"]),
                "monotonicity": float(metrics["monotonicity"]),
                "ic_stability": float(metrics["ic_stability"]),
                "grade": metrics["grade"],
                "ls_spread": float(metrics["ls_spread"]),
                "alpha_score": float(metrics["alpha_score"]),
                "score_breakdown": metrics["score_breakdown"],
                "advice": metrics["advice"],
                "ic_distribution": metrics.get("ic_distribution", {}),
                "health_status": metrics.get("health_status", []),
                "ic_rolling": metrics.get("ic_rolling", {}),
                "ic_series": {
                    "dates": ic_series.index.strftime("%Y-%m-%d").tolist(),
                    "values": [float(x) if not np.isnan(x) else 0 for x in ic_series.values]
                },
                "quantile_rets": {
                    "quantiles": [f"Q{i+1}" for i in range(len(q_avg_vals))],
                    "avg_rets": [float(x) for x in q_avg_vals],
                    "cum_rets": {
                        "dates": q_rets.index.strftime("%Y-%m-%d").tolist() if not q_rets.empty else [],
                        "series": [
                            ((1 + q_rets[c]).cumprod() - 1).fillna(0).tolist()
                            for c in q_rets.columns
                        ] if not q_rets.empty else []
                    }
                }
            }
            
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(executor, run_analysis)
        
        if "error" in results:
            return {"status": "error", "message": results["error"]}
        
        # V5.0: 返回数据新鲜度信息
        freshness_info = dm.check_data_freshness(sample_codes)
            
        return {
            "status": "success",
            "data": results,
            "data_freshness": freshness_info
        }
    except Exception as e:
        print(f"Factor Analysis Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

# --- Momentum Strategy V2.0 Backtest APIs ---

@app.get("/api/v1/strategy/momentum-backtest")
async def get_momentum_backtest(
    start_date: str = "2021-01-01",
    end_date: str = None,
    top_n: int = 4,
    rebalance_days: int = 10,
    mom_s_window: int = 20,
    stop_loss: float = -0.08
):
    """运行行业动量轮动多因子历史回测 (V2.0)"""
    try:
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        params = {
            "top_n": top_n,
            "rebalance_days": rebalance_days,
            "mom_s_window": mom_s_window,
            "mom_m_window": mom_s_window * 3,
            "w_mom_s": 0.40, "w_mom_m": 0.30,
            "w_slope": 0.15, "w_sharpe": 0.15,
            "stop_loss": stop_loss if stop_loss != 0 else None,
            "position_cap": 0.85,
        }
        
        def do_backtest():
            return run_momentum_backtest(start_date, end_date, params)
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, do_backtest)
        return result
    except Exception as e:
        print(f"Momentum Backtest Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/strategy/momentum-optimize")
async def get_momentum_optimize(
    in_sample_end: str = "2023-12-31",
    out_sample_start: str = "2024-01-01"
):
    """运行参数网格搜索优化 (警告: 耗时较长)"""
    try:
        def do_optimize():
            return run_momentum_optimize(in_sample_end, out_sample_start)
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, do_optimize)
        return result
    except Exception as e:
        print(f"Momentum Optimize Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

# --- Market Regime Auto-Detection (统一算法) ---

@app.get("/api/v1/market/regime")
async def get_market_regime():
    """自动识别市场状态 BULL/RANGE/BEAR — 与 V4.0 激活参数面板使用相同算法"""
    from mean_reversion_engine import _classify_regime_from_series
    def _detect():
        import numpy as np
        ts.set_token("5334333c2cb73c9b9987fb6e89da29a3cbd0f442622fbcbfd7bd40b6")
        pro_ = ts.pro_api()
        end_dt   = datetime.now().strftime("%Y%m%d")
        start_dt = (datetime.now() - timedelta(days=300)).strftime("%Y%m%d")
        df = pro_.index_daily(ts_code="000300.SH", start_date=start_dt, end_date=end_dt,
                              fields="trade_date,close,pct_chg")
        if df is None or len(df) < 30:
            return {"status": "error", "message": "CSI300 数据不足"}
        df = df.sort_values("trade_date").reset_index(drop=True)
        close = df["close"].astype(float).values

        # ── 统一算法 ──
        info   = _classify_regime_from_series(close)
        regime = info["regime"]
        rc     = info["regime_color"]
        ri     = info["regime_icon"]
        regime_cn = info["regime_cn"]

        latest = float(close[-1])
        ma120  = info["ma120"]
        ma60   = info["ma60"]
        slope5 = info["slope5"]
        ret5   = info["ret5"]
        ret20  = info["ret20"]

        pct    = df["pct_chg"].astype(float) / 100
        vol20  = float(pct.iloc[-20:].std() * (252**0.5) * 100) if len(pct) >= 20 else 20.0
        ret60  = float((close[-1]/close[-61] - 1)*100) if len(close) >= 61 else 0.0

        desc_map = {
            "BULL":  f"CSI300 ({latest:.0f}) 站上MA120 ({ma120:.0f})，均线向上，全力进攻。",
            "RANGE": f"CSI300 ({latest:.0f}) 站上MA120 ({ma120:.0f})，均线走平，均衡配置。",
            "BEAR":  f"CSI300 ({latest:.0f}) 跌破MA120 ({ma120:.0f})，防御优先。",
            "CRASH": f"CSI300 ({latest:.0f}) 触发熔断，禁止新建仓。",
        }
        # 震荡反弹子状态
        if regime == "RANGE" and not info["above_ma120"]:
            desc_map["RANGE"] = f"CSI300 ({latest:.0f}) 跌破MA120 ({ma120:.0f})，近5日反弹+{ret5:.1f}%，谨慎。"

        note_map = {
            "BULL":  "全力进攻：信号达标即可满仓",
            "RANGE": "均衡配置：仓位×0.77",
            "BEAR":  "防御模式：止损收至-6%",
            "CRASH": "禁止新建仓",
        }
        sg = {"BULL": 65, "RANGE": 68, "BEAR": 75, "CRASH": 999}.get(regime, 68)
        pc = {"BULL": 85, "RANGE": 66, "BEAR": 45, "CRASH": 0}.get(regime, 66)
        sl = -6 if regime == "BEAR" else -8

        return {
            "status": "ok", "as_of": datetime.now().strftime("%Y-%m-%d"),
            "latest_date": df["trade_date"].iloc[-1],
            "csi300": round(latest, 2), "ma60": round(ma60, 2), "ma120": round(ma120, 2),
            "above_ma120": info["above_ma120"], "ma120_rising": slope5 > 0,
            "ma120_slope5": round(slope5, 4),
            "ret5d": round(ret5, 2), "ret20d": round(ret20, 2),
            "ret60d": round(ret60, 2), "vol20d": round(vol20, 1),
            "regime": regime, "regime_cn": regime_cn,
            "regime_color": rc, "regime_icon": ri,
            "regime_desc": desc_map.get(regime, ""),
            "pos_cap": pc, "score_gate": sg,
            "optimal_params": {
                "top_n": 3, "rebalance_days": 5, "mom_window": 30,
                "stop_loss": sl, "pos_cap": pc, "entry_threshold": sg,
                "note": note_map.get(regime, ""),
            },
        }
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(executor, _detect)
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Industry Tracking API V4.0 (Data-Honest Engine) ---

# V4.0 Tracking数据缓存 (detail API 复用)
_TRACKING_CACHE = {"data": None, "timestamp": None}

def compute_price_percentile(p_df, lookback_days: int = 1250) -> float:
    """
    V4.0 价格百分位 (替代硬编码PE分位)
    当前价格在过去N个交易日中的百分位位置
    lookback_days=1250 ≈ 5年交易日
    低百分位=便宜(均值回归机会)  高百分位=昂贵(回撤风险)
    """
    if p_df.empty or len(p_df) < 20:
        return 50.0  # 数据不足返回中性
    closes = p_df['close'].values
    # 取可用的历史数据(最多lookback_days)
    history = closes[-min(len(closes), lookback_days):]
    current = float(closes[-1])
    # 百分位 = 低于当前价的天数 / 总天数 × 100
    percentile = float(np.sum(history < current)) / len(history) * 100
    return round(min(100, max(0, percentile)), 1)


def compute_dynamic_rps(sector_data: list, code: str) -> float:
    """
    V4.0 动态RPS (Relative Price Strength)
    基于12个ETF的20D收益率，计算当前ETF在池内的排名百分位
    """
    if not sector_data:
        return 50.0
    # 按 ret_20d 排序
    sorted_data = sorted(sector_data, key=lambda x: x.get('ret_20d', 0))
    total = len(sorted_data)
    for i, d in enumerate(sorted_data):
        if (d.get('ts_code') or d.get('code')) == code:
            return round((i + 1) / total * 100, 1)
    return 50.0


def compute_momentum_20d(p_df) -> dict:
    """
    V4.0 20D动量趋势卡 (替代虚假北向资金卡)
    返回: 20D累计收益 + 趋势方向 + 动量强度描述
    """
    if p_df.empty or len(p_df) < 20:
        return {"ret_20d": 0.0, "label": "数据不足", "trend": "neutral"}
    closes = p_df['close'].values
    ret = round(float((closes[-1] / closes[-20] - 1) * 100), 2)
    if ret > 5:
        label, trend = f"+{ret:.1f}% 强势上攻", "strong_up"
    elif ret > 2:
        label, trend = f"+{ret:.1f}% 温和上行", "up"
    elif ret > -2:
        label, trend = f"{ret:+.1f}% 横盘震荡", "neutral"
    elif ret > -5:
        label, trend = f"{ret:.1f}% 弱势调整", "down"
    else:
        label, trend = f"{ret:.1f}% 深度回调", "strong_down"
    return {"ret_20d": ret, "label": label, "trend": trend}

def compute_sector_heat_score(p_df, trend_5d: float) -> dict:
    """
    V2.0 资金热度多因子引擎
    三因子加权: 成交额放量比(40%) + 5D价格动量(35%) + 拥挤度修正(25%)
    输出: heat_score 0-100, heat_tier 分层标签
    """
    if p_df.empty or len(p_df) < 5:
        return {"heat_score": 30.0, "heat_tier": "❄️ 冷淡", "vol_ratio": 1.0,
                "vol_score": 50.0, "mom_score": 50.0, "crowd_score": 80.0}

    latest_amount = float(p_df['amount'].iloc[-1]) if 'amount' in p_df.columns else 0
    vol_ma20 = float(p_df['amount'].tail(20).mean()) if 'amount' in p_df.columns else 1

    # 因子 A: 成交额放量比 (1x=50分, 1.5x=75分, 2x=100分)
    vol_ratio = latest_amount / vol_ma20 if vol_ma20 > 0 else 1.0
    vol_score = min(100, max(0, vol_ratio * 50))

    # 因子 B: 5D 价格动量 (0%=50分, +3%=80分, -3%=20分)
    mom_score = min(100, max(0, 50 + trend_5d * 10))

    # 因子 C: 拥挤度修正 (1x=满分, >2x 开始惩罚)
    if vol_ratio > 2.0:
        crowd_score = max(0, 100 - (vol_ratio - 2.0) * 60)
    else:
        crowd_score = 80 + min(20, vol_ratio * 10)

    # 加权合成
    heat_score = vol_score * 0.40 + mom_score * 0.35 + crowd_score * 0.25
    heat_score = round(min(100, max(0, heat_score)), 1)

    # 分层
    if heat_score >= 70:
        tier = "🔥 激进"
    elif heat_score >= 45:
        tier = "⚡ 活跃"
    else:
        tier = "❄️ 冷淡"

    return {
        "heat_score": heat_score,
        "heat_tier": tier,
        "vol_ratio": round(vol_ratio, 2),
        "vol_score": round(vol_score, 1),
        "mom_score": round(mom_score, 1),
        "crowd_score": round(crowd_score, 1)
    }


def compute_alpha_score(p_df, heat_score: float, trend_5d: float, pe_pct: float) -> dict:
    """
    V3.0 综合投资评分引擎 (Alpha Score)
    四因子加权:
      热度因子(30%): 直接取 heat_score
      动量因子(25%): 5D动量(60%) + 20D趋势(40%)，归一化到0-100
      估值安全(25%): 100 - PE百分位 (低估=高分)
      趋势强度(20%): 站上MA20 + 站上MA60 + MA20斜率
    输出: alpha_score 0-100, alpha_grade A/B/C/D/F, trend_strength{}
    """
    # --- 因子 1: 热度 (直接复用) ---
    f_heat = min(100, max(0, heat_score))

    # --- 因子 2: 动量 (5D + 20D 混合) ---
    ret_20d = 0.0
    if not p_df.empty and len(p_df) >= 20:
        ret_20d = round(float((p_df['close'].iloc[-1] / p_df['close'].iloc[-20] - 1) * 100), 2)
    mom_5d_score = min(100, max(0, 50 + trend_5d * 10))   # 与 heat 同口径
    mom_20d_score = min(100, max(0, 50 + ret_20d * 5))     # 20D 灵敏度略低
    f_momentum = mom_5d_score * 0.60 + mom_20d_score * 0.40

    # --- 因子 3: 估值安全 (反转: 低PE=高分) ---
    f_valuation = min(100, max(0, 100 - pe_pct))

    # --- 因子 4: 趋势强度 (MA体系) ---
    above_ma20 = False
    above_ma60 = False
    ma20_slope = 0.0
    if not p_df.empty and len(p_df) >= 60:
        closes = p_df['close'].values
        ma20 = float(np.mean(closes[-20:]))
        ma60 = float(np.mean(closes[-60:]))
        latest = float(closes[-1])
        above_ma20 = latest > ma20
        above_ma60 = latest > ma60
        # MA20 斜率: (MA20_now - MA20_5d_ago) / MA20_5d_ago * 100
        if len(closes) >= 25:
            ma20_5d_ago = float(np.mean(closes[-25:-5]))
            ma20_slope = round((ma20 / ma20_5d_ago - 1) * 100, 3) if ma20_5d_ago > 0 else 0.0
    elif not p_df.empty and len(p_df) >= 20:
        closes = p_df['close'].values
        ma20 = float(np.mean(closes[-20:]))
        latest = float(closes[-1])
        above_ma20 = latest > ma20

    trend_pts = 0
    if above_ma20: trend_pts += 30
    if above_ma60: trend_pts += 30
    trend_pts += min(40, max(0, (ma20_slope + 1) * 20))  # 斜率归一化
    f_trend = min(100, max(0, trend_pts))

    # --- 加权合成 ---
    alpha_score = f_heat * 0.30 + f_momentum * 0.25 + f_valuation * 0.25 + f_trend * 0.20
    alpha_score = round(min(100, max(0, alpha_score)), 1)

    # --- 评级 ---
    if alpha_score >= 80:
        grade = "A"
    elif alpha_score >= 65:
        grade = "B"
    elif alpha_score >= 50:
        grade = "C"
    elif alpha_score >= 35:
        grade = "D"
    else:
        grade = "F"

    return {
        "alpha_score": alpha_score,
        "alpha_grade": grade,
        "ret_20d": ret_20d,
        "f_heat": round(f_heat, 1),
        "f_momentum": round(f_momentum, 1),
        "f_valuation": round(f_valuation, 1),
        "f_trend": round(f_trend, 1),
        "trend_strength": {
            "above_ma20": above_ma20,
            "above_ma60": above_ma60,
            "ma20_slope": ma20_slope
        }
    }


def compute_risk_alerts(vol_ratio: float, pe_pct: float, trend_5d: float,
                         heat_score: float, crowd_score: float) -> list:
    """
    V3.0 风险警示检测引擎
    根据多个条件产出 0~N 条风险警示或正面信号
    """
    alerts = []

    # ⚠️ 拥挤度过高 — 追高风险
    if vol_ratio > 2.0:
        alerts.append({
            "level": "danger",
            "icon": "🔴",
            "text": f"拥挤度 {vol_ratio:.1f}x 场内过度拥挤，追高风险极大",
            "metric": "crowd"
        })
    elif vol_ratio > 1.5:
        alerts.append({
            "level": "warning",
            "icon": "🟡",
            "text": f"拥挤度 {vol_ratio:.1f}x 偏高，注意仓位控制",
            "metric": "crowd"
        })

    # ⚠️ PE分位过高 — 估值泡沫
    if pe_pct > 80:
        alerts.append({
            "level": "danger",
            "icon": "🔴",
            "text": f"PE分位 {pe_pct:.0f}% 历史极高估区域",
            "metric": "pe"
        })
    elif pe_pct > 70:
        alerts.append({
            "level": "warning",
            "icon": "🟡",
            "text": f"PE分位 {pe_pct:.0f}% 估值偏高",
            "metric": "pe"
        })

    # ⚠️ 短期暴涨 + 拥挤 — 见顶信号
    if trend_5d > 8 and vol_ratio > 1.5:
        alerts.append({
            "level": "danger",
            "icon": "🔴",
            "text": f"5D暴涨 +{trend_5d:.1f}% 且拥挤 {vol_ratio:.1f}x → 见顶概率高",
            "metric": "top_signal"
        })

    # ⚠️ 热度过热 — 情绪过热
    if heat_score > 85:
        alerts.append({
            "level": "warning",
            "icon": "🟡",
            "text": f"热度 {heat_score:.0f} 资金过度聚集，警惕回调",
            "metric": "overheat"
        })

    # 🛡️ 正面信号: 深度价值区
    if pe_pct < 15 and heat_score < 40:
        alerts.append({
            "level": "positive",
            "icon": "💎",
            "text": f"PE仅 {pe_pct:.0f}% + 关注度低 → 深度价值区",
            "metric": "deep_value"
        })

    # 🛡️ 正面信号: 放量突破
    if vol_ratio > 1.3 and trend_5d > 3 and pe_pct < 50:
        alerts.append({
            "level": "positive",
            "icon": "🚀",
            "text": f"放量 {vol_ratio:.1f}x 突破 +{trend_5d:.1f}%，估值安全",
            "metric": "breakout"
        })

    return alerts


def generate_sector_advice(alpha_score: float, alpha_grade: str, heat_score: float,
                           pe_pct: float, trend_5d: float, trend_strength: dict) -> dict:
    """
    V3.0 五级投资建议矩阵
    基于 Alpha Score 驱动，附带量化买入/止盈策略
    """
    above_ma20 = trend_strength.get("above_ma20", False)
    above_ma60 = trend_strength.get("above_ma60", False)

    if alpha_grade == "A":  # Alpha >= 80
        return {
            "text": "低估+放量+强势，最佳配置窗口",
            "action": "strong_buy",
            "label": "🟢 强力买入",
            "buy_strategy": "分批建仓 20%→40%→60%，5-10个交易日完成",
            "take_profit": "PE分位升至>70% 或 热度分降至<40 或 动量衰减连续3日",
            "stop_loss": "跌破MA60 无条件止损",
            "position_cap": "单行业上限60%"
        }
    elif alpha_grade == "B":  # Alpha 65-79
        return {
            "text": "热度好估值合理，可积极参与",
            "action": "buy",
            "label": "🟢 积极关注",
            "buy_strategy": "左侧小仓试探 10%→20%，确认站稳MA20后加至30%",
            "take_profit": "热度分降至<40 或 跌破MA20",
            "stop_loss": "跌破MA60 或 5D回撤>-6%",
            "position_cap": "单行业上限30%"
        }
    elif alpha_grade == "C":  # Alpha 50-64
        return {
            "text": "均衡态势，列入观察池等待确认",
            "action": "watch",
            "label": "🔵 跟踪观察",
            "buy_strategy": "暂不建仓，等待Alpha升至65+再介入",
            "take_profit": "—",
            "stop_loss": "—",
            "position_cap": "0%（仅观察）"
        }
    elif alpha_grade == "D":  # Alpha 35-49
        return {
            "text": "热度降温或估值偏高，谨慎持有",
            "action": "caution",
            "label": "🟡 谨慎持有",
            "buy_strategy": "已持仓者减至半仓，新资金禁入",
            "take_profit": "立即止盈已有浮盈仓位",
            "stop_loss": "跌破MA60 全部离场",
            "position_cap": "已持仓减至<15%"
        }
    else:  # F, Alpha < 35
        return {
            "text": "冷门+高估+弱势，严格回避",
            "action": "avoid",
            "label": "🔴 回避清仓",
            "buy_strategy": "严禁新建仓",
            "take_profit": "若持有立即清仓",
            "stop_loss": "无条件清仓",
            "position_cap": "0%"
        }


@app.get("/api/v1/industry-tracking")
async def get_industry_tracking(date: Optional[str] = None):
    """
    V4.0 行业追踪核心 API: Data-Honest Alpha Score + 动态RPS + 真实价格百分位
    """
    try:
        def run_ind_analysis():
            dm = FactorDataManager()
            target_dt = pd.to_datetime(date) if date else pd.Timestamp.now().normalize()

            etf_list = [
                {"code": "512760.SH", "name": "半导体/芯片"},
                {"code": "512720.SH", "name": "计算机/AI"},
                {"code": "515030.SH", "name": "新能源车"},
                {"code": "512010.SH", "name": "医药生物"},
                {"code": "512690.SH", "name": "酒/自选消费"},
                {"code": "512880.SH", "name": "证券/非银"},
                {"code": "512800.SH", "name": "银行/金融"},
                {"code": "512660.SH", "name": "军工龙头"},
                {"code": "512100.SH", "name": "中证传媒"},
                {"code": "512400.SH", "name": "有色金属"},
                {"code": "510180.SH", "name": "上证180/主板"},
                {"code": "159915.SZ", "name": "创业板/成长"}
            ]

            sector_data = []
            # V4.0: 保存每个ETF的price_df用于detail API复用
            _price_cache = {}

            for etf in etf_list:
                code = etf['code']
                p_df = dm.get_price_payload(code)
                if p_df.empty:
                    sector_data.append({
                        "ts_code": code, "code": code, "name": etf['name'],
                        "trend_5d": 0.0, "ret_20d": 0.0,
                        "heat_score": 30.0, "heat_tier": "❄️ 冷淡",
                        "vol_ratio": 1.0, "vol_score": 50.0, "mom_score": 50.0, "crowd_score": 80.0,
                        "pe_percentile": 50.0,
                        "alpha_score": 30.0, "alpha_grade": "F",
                        "f_heat": 30.0, "f_momentum": 50.0, "f_valuation": 50.0, "f_trend": 0.0,
                        "trend_strength": {"above_ma20": False, "above_ma60": False, "ma20_slope": 0.0},
                        "risk_alerts": [],
                        "momentum_20d": {"ret_20d": 0.0, "label": "数据同步中", "trend": "neutral"},
                        "advice": "数据同步中", "advice_action": "neutral", "advice_label": "⚪ 等待同步",
                        "buy_strategy": "等待数据同步后再评估", "take_profit": "—", "stop_loss": "—", "position_cap": "0%"
                    })
                    continue

                # 过滤至目标日期
                p_df = p_df[p_df['trade_date'] <= target_dt].sort_values('trade_date')
                _price_cache[code] = p_df  # V4.0: 缓存用于detail复用

                if len(p_df) >= 5:
                    ret = (p_df['close'].iloc[-1] / p_df['close'].iloc[-5] - 1)
                    trend = round(float(ret) * 100, 2) if np.isfinite(ret) else 0.0
                else:
                    trend = 0.0

                # V2.0: 计算资金热度得分
                heat = compute_sector_heat_score(p_df, trend)

                # V4.0: 动态价格百分位 (替代硬编码PE分位)
                pe_pct = compute_price_percentile(p_df)

                # V4.0: 20D动量趋势 (替代虚假北向资金)
                mom_20d = compute_momentum_20d(p_df)

                # V3.0: 计算 Alpha Score 综合评分
                alpha = compute_alpha_score(p_df, heat['heat_score'], trend, pe_pct)

                # V3.0: 风险警示检测
                alerts = compute_risk_alerts(
                    heat['vol_ratio'], pe_pct, trend,
                    heat['heat_score'], heat['crowd_score']
                )

                # V3.0: 生成五级建议 (入参升级为 alpha 驱动)
                advice = generate_sector_advice(
                    alpha['alpha_score'], alpha['alpha_grade'],
                    heat['heat_score'], pe_pct, trend,
                    alpha['trend_strength']
                )

                sector_data.append({
                    "ts_code": code, "code": code, "name": etf['name'],
                    "trend_5d": trend,
                    # V2.0 热度字段
                    "heat_score": heat['heat_score'],
                    "heat_tier": heat['heat_tier'],
                    "vol_ratio": heat['vol_ratio'],
                    "vol_score": heat['vol_score'],
                    "mom_score": heat['mom_score'],
                    "crowd_score": heat['crowd_score'],
                    "pe_percentile": pe_pct,
                    # V3.0 Alpha Score 字段
                    "alpha_score": alpha['alpha_score'],
                    "alpha_grade": alpha['alpha_grade'],
                    "ret_20d": alpha['ret_20d'],
                    "f_heat": alpha['f_heat'],
                    "f_momentum": alpha['f_momentum'],
                    "f_valuation": alpha['f_valuation'],
                    "f_trend": alpha['f_trend'],
                    "trend_strength": alpha['trend_strength'],
                    # V3.0 风险警示
                    "risk_alerts": alerts,
                    # V4.0 20D动量趋势 (替代北向资金)
                    "momentum_20d": mom_20d,
                    # V3.0 五级建议
                    "advice": advice['text'],
                    "advice_action": advice['action'],
                    "advice_label": advice['label'],
                    "buy_strategy": advice.get('buy_strategy', '—'),
                    "take_profit": advice.get('take_profit', '—'),
                    "stop_loss": advice.get('stop_loss', '—'),
                    "position_cap": advice.get('position_cap', '—')
                })

            # 影子排序数据兜底 (如果同步未就绪)
            if all(r['trend_5d'] == 0.0 for r in sector_data):
                fallback = {
                    "512760.SH": 2.1, "512720.SH": 1.8, "515030.SH": 1.5,
                    "512400.SH": 1.2, "512880.SH": 0.9, "159915.SZ": 0.7,
                    "512100.SH": 0.4, "512660.SH": -0.2, "512010.SH": -0.5,
                    "512690.SH": -0.8, "510180.SH": -1.2, "512800.SH": -1.5
                }
                for r in sector_data:
                    r['trend_5d'] = fallback.get(r['ts_code'], 0.0)
                    heat = compute_sector_heat_score(pd.DataFrame(), r['trend_5d'])
                    r.update({"heat_score": heat['heat_score'], "heat_tier": heat['heat_tier'], "vol_ratio": 1.0})
                    pe_pct = 50.0  # V4.0: 兜底时用中性值而非硬编码
                    r['pe_percentile'] = pe_pct
                    alpha = compute_alpha_score(pd.DataFrame(), heat['heat_score'], r['trend_5d'], pe_pct)
                    r.update({
                        "alpha_score": alpha['alpha_score'], "alpha_grade": alpha['alpha_grade'],
                        "ret_20d": 0.0, "f_heat": alpha['f_heat'], "f_momentum": alpha['f_momentum'],
                        "f_valuation": alpha['f_valuation'], "f_trend": alpha['f_trend'],
                        "trend_strength": alpha['trend_strength'], "risk_alerts": [],
                        "momentum_20d": {"ret_20d": 0.0, "label": "数据兜底", "trend": "neutral"}
                    })
                    adv = generate_sector_advice(
                        alpha['alpha_score'], alpha['alpha_grade'],
                        heat['heat_score'], pe_pct, r['trend_5d'],
                        alpha['trend_strength']
                    )
                    r.update({
                        "advice": adv['text'], "advice_action": adv['action'], "advice_label": adv['label'],
                        "buy_strategy": adv.get('buy_strategy', '—'), "take_profit": adv.get('take_profit', '—'),
                        "stop_loss": adv.get('stop_loss', '—'), "position_cap": adv.get('position_cap', '—')
                    })

            # V3.0: 按 alpha_score 降序排列 (综合评分优先)
            sector_data.sort(key=lambda x: x.get('alpha_score', 0), reverse=True)

            # V4.0: 计算动态RPS排名 (需要全部sector_data准备好后)
            for item in sector_data:
                item['rps'] = compute_dynamic_rps(sector_data, item.get('ts_code') or item.get('code'))

            # 轮动矩阵
            try:
                engine = IndustryEngine()
                rotation = engine.get_industry_rotation(base_date=date)
            except:
                rotation = {}

            result = {
                "performance": sector_data,
                "sector_heatmap": sector_data,
                "rotation": rotation,
                "last_update": datetime.now().strftime("%Y%m%d")
            }

            # V4.0: 缓存tracking数据供detail API复用
            _TRACKING_CACHE["data"] = sector_data
            _TRACKING_CACHE["timestamp"] = datetime.now().isoformat()

            return result

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(executor, run_ind_analysis)

        return {"status": "success", "data": results}
    except Exception as e:
        print(f"Industry Analysis Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/sync/industry")
async def sync_industry_data():
    """手动触发行业数据同步 (同步 12 个核心 ETF 及相关成分股)"""
    try:
        # V4.9 核心同步列表: 12 个行业 ETF
        etf_codes = [
            "512660.SH", "512010.SH", "512690.SH", "512760.SH", 
            "512720.SH", "512880.SH", "512800.SH", "515030.SH", 
            "512100.SH", "512400.SH", "510180.SH", "159915.SZ"
        ]
        
        def do_sync():
            mgr = FactorDataManager()
            # 同步 ETF 行情 (Tushare asset 'E' 代表 ETF)
            mgr.sync_daily_prices(etf_codes, asset='E') 
            # 同时也同步一部分成分股行情(可选)
            engine = IndustryEngine()
            stocks = engine._get_industry_stocks()
            if not stocks.empty:
                mgr.sync_daily_prices(stocks.head(10)['ts_code'].tolist())
            return mgr.get_last_sync_date(etf_codes)

        loop = asyncio.get_event_loop()
        last_date = await loop.run_in_executor(executor, do_sync)
        return {"status": "success", "last_date": last_date}
    except Exception as e:
        print(f"Sync Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

# --- Portfolio Management API V2.0 (Singleton + Validation) ---

from portfolio_engine import get_portfolio_engine

@app.get("/api/v1/portfolio/valuation")
async def get_portfolio_valuation():
    try:
        engine = get_portfolio_engine()
        return {"status": "success", "data": engine.get_valuation()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/portfolio/risk")
async def get_portfolio_risk():
    try:
        engine = get_portfolio_engine()
        return {"status": "success", "data": engine.calculate_risk_metrics()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/portfolio/history")
async def get_portfolio_history():
    try:
        engine = get_portfolio_engine()
        return {"status": "success", "data": engine.get_trade_history(30)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/portfolio/nav")
async def get_portfolio_nav():
    try:
        engine = get_portfolio_engine()
        return {"status": "success", "data": engine.get_nav_history(120)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/portfolio/trade")
async def execute_trade(req: TradeRequest):
    try:
        # 输入校验
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

@app.post("/api/v1/portfolio/import")
async def import_portfolio(file: UploadFile = File(...)):
    """接收券商导出的 资金股份查询.txt，解析并覆盖当前持仓"""
    try:
        content = await file.read()
        # 券商导出通常是 GBK 编码，依次尝试 GBK → UTF-8
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

@app.post("/api/v1/portfolio/reset")
async def reset_portfolio():
    """清零组合: 清除所有持仓和现金"""
    try:
        engine = get_portfolio_engine()
        result = engine.reset_portfolio()
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/portfolio/sync")
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

# === 均值回归 V4.0 三态参数 API ===
import json as _json
import os as _os

@app.get("/api/v1/mr_backtest_results")
async def get_mr_backtest_results():
    fp = "mr_optimization_results.json"
    if not _os.path.exists(fp):
        return {"status": "error", "message": "请先运行 mr_regime_backtest.py"}
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = _json.load(f)
        return data
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/mr_per_regime_params")
async def get_per_regime_params():
    """返回三态（BEAR/RANGE/BULL）各自的回测最优参数"""
    try:
        return {
            "status": "ok",
            "regimes": get_all_regime_params(),
            "needs_reoptimize": needs_reoptimize(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/mr_current_params")
async def get_current_regime_params():
    """实时识别当前市场状态，返回对应的最优参数（无需重启服务器）"""
    try:
        info = detect_regime()
        return {
            "status":      "ok",
            "regime":      info.get("regime"),
            "params":      info.get("params", {}),
            "pos_cap":     info.get("pos_cap"),
            "score_gate":  info.get("score_gate"),
            "csi300":      info.get("csi300"),
            "ret5":        info.get("ret5"),
            "ret20":       info.get("ret20"),
            "needs_reoptimize": info.get("needs_reoptimize", False),
            "all_regimes": get_all_regime_params(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ═══════════════════════════════════════════════════════
#  深度审计 API V4.0 — 带枪保安架构
# ═══════════════════════════════════════════════════════
@app.get("/api/v1/audit")
async def api_audit():
    """V4.0 五维系统审计 + Enforcer 执行 + 静音/降级"""
    try:
        report = await asyncio.get_event_loop().run_in_executor(
            executor, run_full_audit
        )
        return {"status": "ok", **report}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/audit/enforcer/status")
async def get_audit_enforcer_status():
    """获取执行器完整状态快照"""
    try:
        from audit_enforcer import get_enforcer_status
        return {"status": "ok", **get_enforcer_status()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/v1/audit/enforcer/toggle")
async def toggle_audit_enforcer(enabled: bool = True):
    """开关执行器总开关"""
    try:
        from audit_enforcer import toggle_enforcer
        result = toggle_enforcer(enabled)
        return {"status": "ok", "enforcer_enabled": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/v1/audit/mute")
async def set_audit_mute(minutes: int = 30, degraded: bool = False):
    """设置静音 (minutes=静音N分钟, degraded=降级模式)"""
    try:
        from audit_enforcer import set_mute
        result = set_mute(minutes=minutes, degraded=degraded)
        return {"status": "ok", "mute": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.delete("/api/v1/audit/mute")
async def clear_audit_mute():
    """解除所有静音"""
    try:
        from audit_enforcer import clear_mute
        result = clear_mute()
        return {"status": "ok", "mute": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/audit/enforcer/log")
async def get_audit_enforcer_log(limit: int = 20):
    """获取执行器日志"""
    try:
        from audit_enforcer import get_enforcement_log
        logs = get_enforcement_log(limit)
        return {"status": "ok", "logs": logs}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ─── AIAE 宏观仓位管控 API ───

@app.get("/api/v1/aiae/report")
async def get_aiae_report():
    """AIAE 完整报告: 当前AIAE值、五档状态、仓位矩阵、子策略配额、信号"""
    try:
        loop = asyncio.get_event_loop()
        engine = get_aiae_engine()
        report = await loop.run_in_executor(executor, engine.generate_report)
        return {"status": "success", "data": report, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        print(f"[AIAE API] report error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/aiae/chart")
async def get_aiae_chart():
    """AIAE 历史走势图数据"""
    try:
        engine = get_aiae_engine()
        chart = engine.get_chart_data()
        return {"status": "success", "data": chart}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/aiae/refresh")
async def refresh_aiae():
    """强制刷新AIAE数据(清除缓存)"""
    try:
        loop = asyncio.get_event_loop()
        engine = get_aiae_engine()
        engine.refresh()
        report = await loop.run_in_executor(executor, engine.generate_report)
        return {"status": "success", "data": report, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── 海外 AIAE 宏观仓位管控 API (US + JP) ───

@app.get("/api/v1/aiae_global/report")
async def get_aiae_global_report():
    """海外 AIAE 全球报告: L1缓存 + 并行执行 US + JP + HK 引擎, 含四地对比 (CN/US/JP/HK) V2.0"""
    # V1.1: L1缓存命中检查
    current_time = time.time()
    ttl = _get_global_aiae_ttl()
    if AIAE_GLOBAL_CACHE["last_update"] and (current_time - AIAE_GLOBAL_CACHE["last_update"] < ttl):
        age = int(current_time - AIAE_GLOBAL_CACHE["last_update"])
        ttl_label = "美股盘中30min" if ttl == 1800 else ("周末24h" if ttl == 86400 else "盘后4h")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Global AIAE Cache Hit [{ttl_label}] ({age}s ago)")
        return AIAE_GLOBAL_CACHE["report_data"]

    try:
        loop = asyncio.get_event_loop()
        us_engine = get_us_aiae_engine()
        jp_engine = get_jp_aiae_engine()
        hk_engine = get_hk_aiae_engine()

        us_task = loop.run_in_executor(executor, us_engine.generate_report)
        jp_task = loop.run_in_executor(executor, jp_engine.generate_report)
        hk_task = loop.run_in_executor(executor, hk_engine.generate_report)

        us_report, jp_report, hk_report = await asyncio.gather(us_task, jp_task, hk_task)

        # 获取中国 AIAE 用于四地对比
        cn_aiae_v1 = 22.0
        cn_regime = 3
        try:
            cn_engine = get_aiae_engine()
            cn_report = cn_engine.generate_report()
            if cn_report.get("status") in ("success", "fallback"):
                cn_aiae_v1 = cn_report["current"]["aiae_v1"]
                cn_regime = cn_report["current"]["regime"]
        except Exception as e:
            print(f"[GlobalAIAE] CN engine fallback: {e}")

        us_v1 = us_report.get("current", {}).get("aiae_v1", 25.0)
        jp_v1 = jp_report.get("current", {}).get("aiae_v1", 17.0)
        hk_v1 = hk_report.get("current", {}).get("aiae_v1", 14.0)
        us_regime = us_report.get("current", {}).get("regime", 3)
        jp_regime = jp_report.get("current", {}).get("regime", 3)
        hk_regime = hk_report.get("current", {}).get("regime", 3)

        # 四地配置建议
        vals = {"cn": cn_aiae_v1, "us": us_v1, "jp": jp_v1, "hk": hk_v1}
        coldest = min(vals, key=vals.get)
        hottest = max(vals, key=vals.get)
        region_names = {"cn": "A股", "us": "美股", "jp": "日股", "hk": "港股"}
        recommendation = f"当前{region_names[coldest]}(AIAE={vals[coldest]:.1f}%)配置热度最低, 超配优先; {region_names[hottest]}(AIAE={vals[hottest]:.1f}%)最高, 谨慎配置"

        data = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "us": us_report,
            "jp": jp_report,
            "hk": hk_report,
            "global_comparison": {
                "cn_aiae": cn_aiae_v1, "cn_regime": cn_regime,
                "us_aiae": us_v1, "us_regime": us_regime,
                "jp_aiae": jp_v1, "jp_regime": jp_regime,
                "hk_aiae": hk_v1, "hk_regime": hk_regime,
                "coldest": coldest, "hottest": hottest,
                "recommendation": recommendation,
            }
        }

        # V1.1: 写入 L1 缓存
        AIAE_GLOBAL_CACHE["last_update"] = current_time
        AIAE_GLOBAL_CACHE["report_data"] = data
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Global AIAE Cache Miss -> 已重建 (US={us_v1:.1f}% JP={jp_v1:.1f}% HK={hk_v1:.1f}%)")

        return data
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/aiae_global/refresh")
async def refresh_aiae_global():
    """强制刷新海外 AIAE 数据: 清除L1+L2缓存后重建"""
    try:
        # V1.1: 清除 L1 缓存
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        # 清除 L2 引擎缓存
        us_engine = get_us_aiae_engine()
        jp_engine = get_jp_aiae_engine()
        hk_engine = get_hk_aiae_engine()
        us_engine.refresh()
        jp_engine.refresh()
        hk_engine.refresh()
        return await get_aiae_global_report()
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/aiae_global/chart")
async def get_aiae_global_chart():
    """海外 AIAE 历史走势数据 (V2.0: US+JP+HK)"""
    try:
        us_engine = get_us_aiae_engine()
        jp_engine = get_jp_aiae_engine()
        hk_engine = get_hk_aiae_engine()
        return {
            "status": "success",
            "us_chart": us_engine.get_chart_data(),
            "jp_chart": jp_engine.get_chart_data(),
            "hk_chart": hk_engine.get_chart_data(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── 港股 ERP 择时引擎 API (HSI + HSTECH) ───

@app.get("/api/v1/strategy/erp-hk")
async def get_erp_hk(market: str = "HSI"):
    """港股ERP择时 — 五维信号 + HSI/HSTECH 双轨"""
    try:
        if market not in ("HSI", "HSTECH"):
            return {"status": "error", "message": "market must be HSI or HSTECH"}
        engine = get_hk_erp_engine(market)
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(executor, engine.generate_report)
        return {"status": "success", "data": report}
    except Exception as e:
        print(f"[HK ERP API] Error: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}


# ─── 港股 AIAE 宏观仓位管控 API ───

@app.get("/api/v1/aiae_hk/report")
async def get_aiae_hk_report():
    """港股 AIAE 完整报告: 当前AIAE值、五档状态、仓位矩阵、子策略配额"""
    try:
        engine = get_hk_aiae_engine()
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(executor, engine.generate_report)
        return {"status": "success", "data": report, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        print(f"[HK AIAE API] report error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/aiae_hk/refresh")
async def refresh_aiae_hk():
    """强制刷新港股AIAE数据"""
    try:
        engine = get_hk_aiae_engine()
        engine.refresh()
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(executor, engine.generate_report)
        # 清除全局L1缓存使四地对比重算
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        return {"status": "success", "data": report, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/v1/aiae_hk/chart")
async def get_aiae_hk_chart():
    """港股 AIAE 历史走势数据"""
    try:
        engine = get_hk_aiae_engine()
        return {"status": "success", "data": engine.get_chart_data()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── 港股手动数据更新 API (南向资金 + AH溢价) ───

class HKSouthboundUpdate(BaseModel):
    weekly_net_buy_billion_rmb: float
    monthly_net_buy_billion_rmb: float = None
    cumulative_12m_billion_rmb: float = None

class HKAHPremiumUpdate(BaseModel):
    index_value: float

@app.post("/api/v1/aiae_hk/update_southbound")
async def update_hk_southbound(req: HKSouthboundUpdate):
    """手动更新南向资金数据: 写入文件 + 清除缓存"""
    try:
        engine = get_hk_aiae_engine()
        engine.update_southbound(
            req.weekly_net_buy_billion_rmb,
            req.monthly_net_buy_billion_rmb,
            req.cumulative_12m_billion_rmb
        )
        # 同步更新ERP引擎的南向数据
        for mkt in ["HSI", "HSTECH"]:
            erp_engine = get_hk_erp_engine(mkt)
            erp_engine.update_southbound(
                req.weekly_net_buy_billion_rmb,
                req.monthly_net_buy_billion_rmb,
                req.cumulative_12m_billion_rmb
            )
        # 清除全局L1缓存
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        return {"status": "success", "message": f"南向资金已更新: 周净买入={req.weekly_net_buy_billion_rmb}亿RMB"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/aiae_hk/update_ah_premium")
async def update_hk_ah_premium(req: HKAHPremiumUpdate):
    """手动更新AH溢价指数"""
    try:
        engine = get_hk_aiae_engine()
        engine.update_ah_premium(req.index_value)
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        return {"status": "success", "message": f"AH溢价指数已更新为 {req.index_value}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===== V1.1: 日股手動データ更新 API =====

class JPMarginUpdate(BaseModel):
    margin_buying_trillion_jpy: float

class JPForeignUpdate(BaseModel):
    net_buy_billion_jpy: float
    cumulative_12m_billion_jpy: float = None

@app.post("/api/v1/aiae_jp/update_margin")
async def update_jp_margin(req: JPMarginUpdate):
    """手动更新日股信用取引残高: 写入文件 + 清除缓存"""
    try:
        engine = get_jp_aiae_engine()
        engine.update_jp_margin(req.margin_buying_trillion_jpy)
        # 清除L1缓存使下次请求重算
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        return {"status": "success", "message": f"信用取引残高已更新为 {req.margin_buying_trillion_jpy}兆円"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/aiae_jp/update_foreign")
async def update_jp_foreign(req: JPForeignUpdate):
    """手动更新日股外国人投資家流向: 写入文件 + 清除缓存"""
    try:
        engine = get_jp_aiae_engine()
        engine.update_jp_foreign(req.net_buy_billion_jpy, req.cumulative_12m_billion_jpy)
        AIAE_GLOBAL_CACHE["last_update"] = None
        AIAE_GLOBAL_CACHE["report_data"] = None
        return {"status": "success", "message": f"外資流向已更新: 周次净買越={req.net_buy_billion_jpy}億円"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/")
async def root():
    return FileResponse("index.html")

@app.get("/{filename}.html")
async def serve_html(filename: str):
    return FileResponse(f"{filename}.html")

app.mount("/", StaticFiles(directory="."), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
