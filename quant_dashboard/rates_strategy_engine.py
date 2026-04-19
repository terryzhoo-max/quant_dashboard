"""
AlphaCore · 利率择时引擎 V1.5
===================================
基于美国10年期国债收益率的五维择时系统:
  D1: 利率水平 (绝对值 → 债券吸引力)        — 权重20%
  D2: 利率动量 (3M/6M变化速度)              — 权重25%  ← 最关键
  D3: 曲线形态 (10Y-2Y期限利差)             — 权重20%
  D4: 实际利率 (TIPS 10Y)                  — 权重20%
  D5: Fed政策方向 (3M T-Bill趋势)          — 权重15%

输出: 股/债/黄金 三分配比 + 债券久期建议
数据源: FRED API (DGS10/DGS2/DFII10/T10YIE/DTB3)
"""

import pandas as pd
import numpy as np
import os
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("alphacore.rates")

# FRED API Key: 优先从环境变量读取，fallback 到内置默认值
FRED_API_KEY = __import__('config').FRED_API_KEY
CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

# FRED 初始化 (复用 erp_us_engine 的模式)
_fred_instance = None
_fred_lock = threading.Lock()
def _get_fred():
    global _fred_instance
    if _fred_instance is None:
        with _fred_lock:
            if _fred_instance is None:  # double-check
                try:
                    from fredapi import Fred
                    _fred_instance = Fred(api_key=FRED_API_KEY)
                except Exception as e:
                    logger.warning(f"FRED init failed: {e}")
    return _fred_instance

# ===== 智能缓存系统 (线程安全) =====
# FRED国债数据每日更新一次(美东6AM):
#   - 同一日数据命中 → 直接返回内存缓存, 不调API
#   - 跨日 → 重新拉取
#   - FRED不可达 → fallback磁盘缓存

_rates_cache = {}  # {key: (timestamp, last_data_date, DataFrame)}
_rates_cache_lock = threading.Lock()

def _is_same_trading_day(cached_ts):
    """判断缓存时间是否在同一个FRED交易日内
    FRED数据通常在美东6AM更新前一日数据 → 北京时间18:00
    """
    import time
    now = time.time()
    # 如果距上次缓存不到4小时, 视为同日
    if now - cached_ts < 4 * 3600:
        return True
    # 如果跨了FRED更新时间(北京18:00), 需要刷新
    from datetime import datetime as _dt
    cached_dt = _dt.fromtimestamp(cached_ts)
    now_dt = _dt.now()
    # 计算各自所在的"FRED日"(以18:00为界)
    def fred_day(dt):
        if dt.hour >= 18:
            return dt.date()
        return (dt - timedelta(days=1)).date()
    return fred_day(cached_dt) == fred_day(now_dt)

def _rates_cached(key, fetcher):
    """智能缓存: 同一FRED日命中直接返回, 跨日拉API (线程安全)"""
    import time
    now = time.time()
    with _rates_cache_lock:
        if key in _rates_cache:
            ts_cached, last_date, data = _rates_cache[key]
            if _is_same_trading_day(ts_cached):
                return data
            logger.info(f"cache expired (跨日), refreshing {key}")
    try:
        data = fetcher()
        with _rates_cache_lock:
            _rates_cache[key] = (now, datetime.now().strftime('%Y-%m-%d'), data)
        return data
    except Exception as e:
        logger.warning(f"cache fail ({key}): {e}")
        with _rates_cache_lock:
            if key in _rates_cache:
                logger.info(f"using stale memory cache for {key}")
                return _rates_cache[key][2]
        raise

def _force_refresh_cache():
    """强制清除所有内存缓存, 下次访问时重拉FRED"""
    global _rates_cache
    with _rates_cache_lock:
        _rates_cache = {}
    logger.info("内存缓存已全部清除")


# ===== Regime 中文映射 =====
REGIME_CN = {
    # D1: 利率水平
    "extreme_high": "极高", "very_high": "很高", "high": "偏高",
    "above_avg": "中偏高", "neutral": "中性", "below_avg": "偏低",
    "low": "低", "extreme_low": "极低",
    # D2: 利率动量
    "crash_down": "急速下行", "falling": "下行", "mild_falling": "温和下行",
    "flat": "持平", "mild_rising": "温和上行", "rising": "上行", "crash_up": "急速上行",
    # D3: 曲线形态
    "deep_inversion": "深度倒挂", "moderate_inversion": "明显倒挂",
    "mild_inversion": "轻微倒挂", "normal_steep": "健康陡峭", "extreme_steep": "极度陡峭",
    # D4: 实际利率
    "extreme_tight": "极紧缩", "very_tight": "很紧缩", "tight": "偏紧",
    "mild_loose": "偏宽松", "negative": "负利率",
    # D5: Fed政策
    "fast_easing": "快速宽松", "easing": "渐进宽松", "mild_easing": "温和宽松",
    "hold": "按兵不动", "mild_tightening": "温和紧缩", "tightening": "渐进紧缩", "fast_tightening": "急速紧缩",
}

def _regime_cn(key):
    return REGIME_CN.get(key, key or '--')

# ===== 卡片内嵌Tooltip百科 =====
CARD_TOOLTIPS = {
    "yield_10y": {
        "title": "10Y国债收益率",
        "desc": "全球资产定价的'锚'，代表无风险收益率基准",
        "logic": "利率高位→债券票息丰厚，买入锁定｜利率低位→资金追逐股市(TINA效应)",
        "alert": "⚠️ >5%=40年罕见(2007) | <1%=零利率(2020)",
        "history": "2023.10触及5.0%(16年高) | 2020.8触及0.5%(历史低)",
    },
    "yield_2y": {
        "title": "2Y国债收益率",
        "desc": "短端利率，紧跟联邦基金利率，是Fed政策的直接映射",
        "logic": "2Y与Fed利率高度相关，2Y见顶通常领先降息1-3个月",
        "alert": "⚠️ 2Y>10Y=曲线倒挂=衰退预警",
        "history": "2023年2Y峰值5.2%，高于10Y达107bps",
    },
    "spread": {
        "title": "期限利差 (10Y-2Y)",
        "desc": "正常应为正值。倒挂=市场预期Fed将被迫降息",
        "logic": "倒挂后12-18个月衰退概率约80%｜牛陡化=衰退真正开始的信号",
        "alert": "⚠️ 倒挂>100bps=极端悲观 | 恢复正值=配置信号",
        "history": "2022-2023持续倒挂107bps，史上最深",
    },
    "real_yield": {
        "title": "实际利率 (TIPS 10Y)",
        "desc": "剔除通胀后的真实资金成本，决定股票估值天花板",
        "logic": ">2%=极紧缩，利好TIPS/利空成长股｜<0%=负利率，驱动资金入股市和黄金",
        "alert": "⚠️ 2022年从-1%飙至2.5%，纳指暴跌30%核心因素",
        "history": "2022.10峰值2.5% | 2021低点-1.2%",
    },
    "momentum": {
        "title": "利率动量 (3M变化)",
        "desc": "利率变化速度比绝对水平更能预测市场反应",
        "logic": "快速上行→债灾+股灾(2022)｜见顶回落→宽松拐点，最佳买入窗口",
        "alert": "⚠️ 3M>+80bps=1994债灾级 | 3M<-80bps=恐慌避险",
        "history": "2022Q3单季上行120bps，40年最快",
    },
    "bei": {
        "title": "通胀预期 (BEI)",
        "desc": "10Y名义利率 - TIPS实际利率 = 市场隐含通胀预期",
        "logic": ">2.5%=通胀焦虑升温，利好TIPS和黄金｜<2%=通缩预期，利好长债",
        "alert": "⚠️ >3%=极端通胀恐慌(2022.3) | <1.5%=通缩风险",
        "history": "2022.3峰值3.0% | 2020.3低点0.5%",
    },
}

# ===== 卡片阈值提示 =====
ALERT_HINTS = {
    "yield_10y": "🎯 >4.5%=超配债券 | <2%=全股票",
    "yield_2y": "🎯 关注2Y vs 10Y差值",
    "spread": "🎯 <0=倒挂警报 | >150bps=强复苏",
    "real_yield": "🎯 >2%=极紧缩 | <0%=负利率",
    "momentum": "🎯 <-30bps=宽松 | >+30bps=紧缩",
    "bei": "🎯 >2.5%=通胀焦虑 | <2%=通缩",
}

# ===== 规则百科 (保留用于tooltip详情) =====
ENCYCLOPEDIA_RATES = {
    "yield_level": {
        "title": "10Y国债收益率 (利率水平)",
        "what": "美国10年期国债收益率，全球资产定价的'锚'。代表无风险收益率基准。",
        "why": "利率高位 → 债券票息丰厚，买入锁定高收益。利率低位 → 债券无吸引力，资金追逐股市(TINA效应)。",
        "alert": "10Y > 5% 是40年罕见高位(上一次是2007年)。10Y < 1% 是零利率时代(2020年)。",
        "history": "2023年10月触及5.0%(16年高点)。2020年8月触及0.5%(历史最低)。"
    },
    "yield_momentum": {
        "title": "利率动量 (变化速度)",
        "what": "10Y收益率近3个月的变化幅度。利率的变化速度比绝对水平更能预测市场反应。",
        "why": "利率快速上行 → 债灾+股灾(如2022年)。利率见顶回落 → 宽松拐点，最佳买入窗口。",
        "alert": "3个月上行超过80bps属于极端紧缩，对应1994年债灾级别。3个月下行80bps属于恐慌避险。",
    },
    "curve_shape": {
        "title": "收益率曲线 (10Y-2Y利差)",
        "what": "10年期减2年期国债收益率之差。正常应为正值(长期利率>短期利率)。",
        "why": "倒挂(负值) = 市场预期Fed将被迫降息 = 衰退预警。历史上倒挂后12-18个月发生衰退的准确率约80%。",
        "alert": "倒挂深度>100bps极为罕见，意味市场对衰退极度悲观。牛陡化(曲线重新变陡)才是衰退真正开始的信号。",
    },
    "real_yield": {
        "title": "实际利率 (TIPS 10Y)",
        "what": "10年期TIPS(通胀保护国债)收益率，代表剔除通胀后的真实资金成本。",
        "why": "实际利率>2% → 极度紧缩，企业实际融资成本高，利空股市但利好TIPS。实际利率<0% → 负利率，持有现金贬值，驱动资金入股市和黄金。",
        "alert": "2022年实际利率从-1%飙升至2.5%，是纳斯达克暴跌30%的核心驱动因素。",
    },
    "fed_policy": {
        "title": "Fed政策方向 (3M T-Bill)",
        "what": "用3个月国库券利率代理联邦基金利率方向。3M T-Bill下行 = Fed在降息或即将降息。",
        "why": "Fed降息周期平均带来18-24个月的股市上涨和债券牛市。方向比水平更重要。",
        "alert": "3M T-Bill连续3个月下行是降息周期确认信号。连续上行则紧缩周期延续。",
    }
}


class RatesStrategyEngine:
    """利率择时引擎 V1.5"""

    VERSION = "1.5"

    # 五维权重
    W = {
        "yield_level": 0.20,
        "yield_momentum": 0.25,
        "curve_shape": 0.20,
        "real_yield": 0.20,
        "fed_policy": 0.15,
    }

    # 信号 → 股债配比
    ALLOCATION_MAP = {
        "overweight_bonds":  {"label": "超配债券",   "emoji": "🟢", "color": "#10b981", "stock": 20, "bond": 70, "gold": 10, "duration": "超长久期(TLT)", "level": 6},
        "tilt_bonds":        {"label": "标配偏债",   "emoji": "🔵", "color": "#3b82f6", "stock": 35, "bond": 55, "gold": 10, "duration": "中长久期(IEF)", "level": 5},
        "balanced":          {"label": "均衡配置",   "emoji": "⚪", "color": "#94a3b8", "stock": 45, "bond": 45, "gold": 10, "duration": "中久期(IEF)",   "level": 4},
        "tilt_stocks":       {"label": "标配偏股",   "emoji": "🟡", "color": "#f59e0b", "stock": 55, "bond": 35, "gold": 10, "duration": "短久期(SHV)",   "level": 3},
        "overweight_stocks": {"label": "超配股票",   "emoji": "🟠", "color": "#f97316", "stock": 70, "bond": 20, "gold": 10, "duration": "超短久期(SHV)", "level": 2},
        "full_equity":       {"label": "全股票",     "emoji": "🔴", "color": "#ef4444", "stock": 85, "bond":  5, "gold": 10, "duration": "极短/免配",     "level": 1},
    }

    ETF_TARGETS = {
        "long_bond":  {"name": "TLT (20+年美债)", "code": "TLT",  "desc": "利率敏感度最高，降息最受益"},
        "mid_bond":   {"name": "IEF (7-10年美债)", "code": "IEF",  "desc": "核心债券配置，攻守兼备"},
        "short_bond": {"name": "SHV (短期美债)",   "code": "SHV",  "desc": "利率风险最小，类现金"},
        "tips":       {"name": "TIP (通胀保护)",   "code": "TIP",  "desc": "实际利率下降时受益"},
        "stock":      {"name": "SPY (S&P 500)",   "code": "SPY",  "desc": "核心权益配置"},
        "gold":       {"name": "GLD (黄金ETF)",    "code": "GLD",  "desc": "实际利率下降+避险双受益"},
    }

    def __init__(self):
        pass

    # ========== 数据获取层 ==========

    def _fetch_fred_series(self, series_id: str, cache_key: str, col_name: str, years: int = 5) -> pd.DataFrame:
        """通用FRED序列获取 (智能日级缓存, 工作日感知)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, f"rates_{cache_key}.parquet")
            # 1. 先检查磁盘缓存是否是当前工作日的数据
            if os.path.exists(cache_file):
                try:
                    disk_df = pd.read_parquet(cache_file)
                    if not disk_df.empty:
                        last_date = pd.Timestamp(disk_df['trade_date'].iloc[-1]).date()
                        today = datetime.now().date()
                        # P1-4: 工作日感知 — FRED 周末/假日不更新
                        # 生成最近2个工作日，取上一个工作日作为"最新可用数据日"
                        try:
                            bdays = pd.bdate_range(end=today, periods=2)
                            prev_bday = bdays[0].date()
                            if last_date >= prev_bday:
                                logger.debug(f"{series_id}: disk cache fresh (latest={last_date}, prev_bday={prev_bday})")
                                return disk_df
                        except Exception:
                            # bdate_range 降级: 原始逻辑
                            if (today - last_date).days <= 1:
                                return disk_df
                except Exception as e:
                    logger.warning(f"{series_id}: disk cache read error: {e}")
            # 2. 磁盘缓存过期或不存在, 从FRED拉取
            fred = _get_fred()
            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=years * 365)
                    series = fred.get_series(series_id, observation_start=start_dt)
                    if series is not None and not series.empty:
                        series = series.dropna()
                        df = pd.DataFrame({
                            "trade_date": series.index.tz_localize(None) if series.index.tz else series.index,
                            col_name: series.values.astype(float),
                        })
                        df.to_parquet(cache_file)
                        logger.info(f"{series_id} (FRED API): {len(df)} rows, latest={df[col_name].iloc[-1]:.3f}")
                        return df
                except Exception as e:
                    logger.warning(f"FRED {series_id} error: {e}")
            # 3. FRED不可达, fallback磁盘缓存(即使过期也用)
            if os.path.exists(cache_file):
                logger.info(f"{series_id}: fallback to stale disk cache")
                return pd.read_parquet(cache_file)
            raise ValueError(f"{series_id} data unavailable")
        return _rates_cached(f"rates_{cache_key}", _fetch)

    def _fetch_10y(self) -> pd.DataFrame:
        return self._fetch_fred_series("DGS10", "dgs10", "yield_10y")

    def _fetch_2y(self) -> pd.DataFrame:
        return self._fetch_fred_series("DGS2", "dgs2", "yield_2y")

    def _fetch_real_yield(self) -> pd.DataFrame:
        return self._fetch_fred_series("DFII10", "dfii10", "real_yield")

    def _fetch_breakeven(self) -> pd.DataFrame:
        return self._fetch_fred_series("T10YIE", "t10yie", "breakeven")

    def _fetch_tbill_3m(self) -> pd.DataFrame:
        return self._fetch_fred_series("DTB3", "dtb3", "rate_3m", years=3)

    # ========== 核心评分层 ==========

    def _score_d1_yield_level(self, df_10y=None, pct_stats=None) -> tuple:
        """D1: 利率水平 → 0-100 (高利率=高分=债券有吸引力)
        V2.0: 使用5年滚动分位数动态阈值, 替代硬编码 (与买卖决策区/图表区间线统一)
        """
        df = df_10y if df_10y is not None else self._fetch_10y()
        if df.empty:
            return 50.0, {}, "数据缺失"

        current = float(df["yield_10y"].iloc[-1])
        pct = float((df["yield_10y"] < current).mean() * 100)

        # 5年均值和标准差
        mean_5y = float(df["yield_10y"].mean())
        std_5y = float(df["yield_10y"].std())
        z_score = (current - mean_5y) / std_5y if std_5y > 0 else 0

        # V2.0: 动态分位数阈值 (与 _compute_yield_percentiles 统一)
        if pct_stats is None:
            pct_stats = self._compute_yield_percentiles()
        t_bond_ow = pct_stats["bond_overweight"]  # P87 超配债券
        t_bond_tl = pct_stats["bond_tilt"]         # P75 标配偏债
        t_p50     = pct_stats["p50"]               # P50 中位数
        t_stock_tl = pct_stats["stock_tilt"]       # P25 标配偏股
        t_full_eq = pct_stats["full_equity"]       # P13 全股票

        if current >= t_bond_ow + 0.5 * std_5y:
            score, regime = 95, "extreme_high"
            desc = f"10Y {current:.2f}% >> P87({t_bond_ow:.1f}%) → 极端高位! 债券极具吸引力"
        elif current >= t_bond_ow:
            score, regime = 85, "very_high"
            desc = f"10Y {current:.2f}% > P87({t_bond_ow:.1f}%) → 超配债券区"
        elif current >= t_bond_tl:
            score, regime = 75, "high"
            desc = f"10Y {current:.2f}% > P75({t_bond_tl:.1f}%) → 偏高，债券票息丰厚"
        elif current >= t_p50:
            score, regime = 60, "above_avg"
            desc = f"10Y {current:.2f}% > P50({t_p50:.1f}%) → 中性偏高"
        elif current >= t_stock_tl:
            score, regime = 45, "neutral"
            desc = f"10Y {current:.2f}% P25-P50 中性区间"
        elif current >= t_full_eq:
            score, regime = 30, "below_avg"
            desc = f"10Y {current:.2f}% < P25({t_stock_tl:.1f}%) → 偏低，股票更有吸引力"
        elif current >= t_full_eq - 0.5 * std_5y:
            score, regime = 15, "low"
            desc = f"10Y {current:.2f}% < P13({t_full_eq:.1f}%) → 低利率，TINA效应"
        else:
            score, regime = 5, "extreme_low"
            desc = f"10Y {current:.2f}% << P13 → 极端低利率时代"

        info = {
            "current": round(current, 3),
            "pct": round(pct, 1),
            "mean_5y": round(mean_5y, 3),
            "z_score": round(z_score, 2),
            "regime": regime,
        }
        return round(score, 1), info, desc

    def _score_d2_yield_momentum(self, df_10y=None) -> tuple:
        """D2: 利率动量 → 0-100 (利率下行=高分=债券牛市)
        P1-5: 使用日期回溯而非固定索引偏移，避免非交易日导致的窗口漂移
        """
        df = df_10y if df_10y is not None else self._fetch_10y()
        if df.empty or len(df) < 63:
            return 50.0, {}, "数据不足"

        current = float(df["yield_10y"].iloc[-1])
        latest_date = pd.Timestamp(df["trade_date"].iloc[-1])

        def _lookback(days):
            """按日期回溯，找到目标日期之前最近的数据点"""
            target = latest_date - pd.Timedelta(days=days)
            mask = df["trade_date"] <= target
            if mask.any():
                return float(df.loc[mask, "yield_10y"].iloc[-1])
            return current

        prev_1m = _lookback(30)
        prev_3m = _lookback(91)
        prev_6m = _lookback(182)

        chg_1m = current - prev_1m  # 正值=利率上行
        chg_3m = current - prev_3m
        chg_6m = current - prev_6m

        # 核心指标: 3M变化 (bps)
        chg_3m_bps = chg_3m * 100

        if chg_3m_bps <= -80:
            score, regime = 90, "crash_down"
            desc = f"3M下行{abs(chg_3m_bps):.0f}bps → 急速降息/避险，强烈利好长债"
        elif chg_3m_bps <= -30:
            score, regime = 75, "falling"
            desc = f"3M下行{abs(chg_3m_bps):.0f}bps → 渐进降息周期"
        elif chg_3m_bps <= -10:
            score, regime = 60, "mild_falling"
            desc = f"3M下行{abs(chg_3m_bps):.0f}bps → 温和宽松"
        elif chg_3m_bps <= 10:
            score, regime = 50, "flat"
            desc = f"3M变化{chg_3m_bps:+.0f}bps → 利率持平"
        elif chg_3m_bps <= 30:
            score, regime = 40, "mild_rising"
            desc = f"3M上行{chg_3m_bps:.0f}bps → 温和收紧"
        elif chg_3m_bps <= 80:
            score, regime = 20, "rising"
            desc = f"3M上行{chg_3m_bps:.0f}bps → 渐进加息，利空债券"
        else:
            score, regime = 5, "crash_up"
            desc = f"3M上行{chg_3m_bps:.0f}bps → 债灾! 极端紧缩"

        info = {
            "current": round(current, 3),
            "chg_1m": round(chg_1m, 3),
            "chg_3m": round(chg_3m, 3),
            "chg_6m": round(chg_6m, 3),
            "chg_3m_bps": round(chg_3m_bps, 0),
            "regime": regime,
        }
        return round(score, 1), info, desc

    def _score_d3_curve_shape(self, df_10y=None, df_2y=None) -> tuple:
        """D3: 曲线形态 (10Y-2Y) → 0-100"""
        try:
            if df_10y is None: df_10y = self._fetch_10y()
            if df_2y is None: df_2y = self._fetch_2y()
        except Exception as e:
            logger.warning(f"D3 curve_shape data error: {e}")
            return 50.0, {}, "数据缺失"

        if df_10y.empty or df_2y.empty:
            return 50.0, {}, "数据缺失"

        y10 = float(df_10y["yield_10y"].iloc[-1])
        y2 = float(df_2y["yield_2y"].iloc[-1])
        spread = y10 - y2  # 正常应为正值
        spread_bps = spread * 100

        # 历史比较
        merged = pd.merge_asof(
            df_10y.sort_values("trade_date"),
            df_2y.sort_values("trade_date"),
            on="trade_date", direction="nearest"
        )
        if not merged.empty:
            merged["spread"] = merged["yield_10y"] - merged["yield_2y"]
            pct = float((merged["spread"] < spread).mean() * 100)
        else:
            pct = 50.0

        # V1.5: 评分方向 = "高分=债券有吸引力"
        #   倒挂 → 预期Fed降息 → 债券牛市在即 → 高分
        #   陡峭 → 通胀升温/经济过热 → 利率上行压力 → 低分
        if spread_bps < -100:
            score, regime = 90, "deep_inversion"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 深度倒挂! Fed被迫降息在即，长债锁定窗口"
        elif spread_bps < -50:
            score, regime = 75, "moderate_inversion"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 明显倒挂，降息预期升温，债券配置价值高"
        elif spread_bps < 0:
            score, regime = 60, "mild_inversion"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 轻微倒挂，宽松信号渐现"
        elif spread_bps < 50:
            score, regime = 50, "flat"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 曲线平坦，中性观望"
        elif spread_bps < 150:
            score, regime = 35, "normal_steep"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 曲线陡峭，经济扩张期，股票更有吸引力"
        else:
            score, regime = 20, "extreme_steep"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 极度陡峭，通胀升温利空债券"

        info = {
            "yield_10y": round(y10, 3),
            "yield_2y": round(y2, 3),
            "spread": round(spread, 3),
            "spread_bps": round(spread_bps, 0),
            "pct": round(pct, 1),
            "regime": regime,
        }
        return round(score, 1), info, desc

    def _score_d4_real_yield(self, df_real=None, df_bei=None) -> tuple:
        """D4: 实际利率 (TIPS 10Y) → 0-100 (高实际利率=高分=债券有吸引力)"""
        try:
            df = df_real if df_real is not None else self._fetch_real_yield()
        except Exception as e:
            logger.warning(f"D4 real_yield data error: {e}")
            return 50.0, {}, "TIPS数据缺失"

        if df.empty:
            return 50.0, {}, "数据缺失"

        current = float(df["real_yield"].iloc[-1])
        pct = float((df["real_yield"] < current).mean() * 100)

        # 通胀预期 = 10Y名义 - TIPS
        try:
            bei_df = df_bei if df_bei is not None else self._fetch_breakeven()
            bei = float(bei_df["breakeven"].iloc[-1]) if not bei_df.empty else 0
        except Exception as e:
            logger.debug(f"BEI data unavailable: {e}")
            bei = 0

        if current >= 2.5:
            score, regime = 90, "extreme_tight"
            desc = f"实际利率 {current:.2f}% ≥ 2.5% → 极度紧缩，TIPS+长债配置窗口"
        elif current >= 2.0:
            score, regime = 80, "very_tight"
            desc = f"实际利率 {current:.2f}% → 非常紧缩，债券价值显著"
        elif current >= 1.5:
            score, regime = 65, "tight"
            desc = f"实际利率 {current:.2f}% → 偏紧缩"
        elif current >= 0.5:
            score, regime = 50, "neutral"
            desc = f"实际利率 {current:.2f}% → 中性区间"
        elif current >= 0:
            score, regime = 35, "mild_loose"
            desc = f"实际利率 {current:.2f}% → 偏宽松"
        else:
            score, regime = 15, "negative"
            desc = f"实际利率 {current:.2f}% < 0 → 负利率! 资金追逐风险资产"

        info = {
            "current": round(current, 3),
            "pct": round(pct, 1),
            "breakeven": round(bei, 3),
            "regime": regime,
        }
        return round(score, 1), info, desc

    def _score_d5_fed_policy(self, df_3m=None) -> tuple:
        """D5: Fed政策方向 (3M T-Bill) → 0-100 (降息=高分)
        V2.0: 使用日期回溯替代固定索引偏移, 与D2统一
        """
        try:
            df = df_3m if df_3m is not None else self._fetch_tbill_3m()
        except Exception as e:
            logger.warning(f"D5 fed_policy data error: {e}")
            return 50.0, {}, "3M T-Bill数据缺失"

        if df.empty or len(df) < 22:
            return 50.0, {}, "数据不足"

        current = float(df["rate_3m"].iloc[-1])
        latest_date = pd.Timestamp(df["trade_date"].iloc[-1])

        def _lookback_3m(days):
            target = latest_date - pd.Timedelta(days=days)
            mask = df["trade_date"] <= target
            if mask.any():
                return float(df.loc[mask, "rate_3m"].iloc[-1])
            return current

        prev_1m = _lookback_3m(30)
        prev_3m = _lookback_3m(91)

        chg_3m = current - prev_3m

        if chg_3m <= -0.5:
            score, direction = 90, "fast_easing"
            desc = f"3M T-Bill 3M下行{abs(chg_3m*100):.0f}bps → 快速降息周期"
        elif chg_3m <= -0.2:
            score, direction = 75, "easing"
            desc = f"3M T-Bill 3M下行{abs(chg_3m*100):.0f}bps → 渐进降息"
        elif chg_3m <= -0.05:
            score, direction = 60, "mild_easing"
            desc = f"3M T-Bill 温和下行 → 宽松信号"
        elif chg_3m <= 0.05:
            score, direction = 50, "hold"
            desc = f"3M T-Bill 持平 → Fed按兵不动"
        elif chg_3m <= 0.2:
            score, direction = 35, "mild_tightening"
            desc = f"3M T-Bill 温和上行 → 偏紧缩"
        elif chg_3m <= 0.5:
            score, direction = 20, "tightening"
            desc = f"3M T-Bill 3M上行{chg_3m*100:.0f}bps → 加息周期"
        else:
            score, direction = 5, "fast_tightening"
            desc = f"3M T-Bill 3M上行{chg_3m*100:.0f}bps → 急速加息"

        info = {
            "current": round(current, 3),
            "chg_3m": round(chg_3m, 3),
            "direction": direction,
        }
        return round(score, 1), info, desc

    # ========== 综合信号 ==========

    def _compute_signal(self, score: float) -> dict:
        """综合得分 → 配置信号"""
        if score >= 80:
            key = "overweight_bonds"
        elif score >= 65:
            key = "tilt_bonds"
        elif score >= 50:
            key = "balanced"
        elif score >= 35:
            key = "tilt_stocks"
        elif score >= 20:
            key = "overweight_stocks"
        else:
            key = "full_equity"

        alloc = self.ALLOCATION_MAP[key]
        return {
            "key": key,
            "label": alloc["label"],
            "emoji": alloc["emoji"],
            "color": alloc["color"],
            "level": alloc["level"],
            "stock_pct": alloc["stock"],
            "bond_pct": alloc["bond"],
            "gold_pct": alloc["gold"],
            "duration": alloc["duration"],
            "score": round(score, 1),
            "position": f"股{alloc['stock']}% / 债{alloc['bond']}% / 金{alloc['gold']}%",
        }

    # ========== 买卖规则 ==========

    def _generate_trade_rules(self, score, dims, snap) -> dict:
        y10 = snap.get("yield_10y", 4.0)
        chg_3m_bps = dims.get("yield_momentum", {}).get("momentum_info", {}).get("chg_3m_bps", 0)
        spread_bps = dims.get("curve_shape", {}).get("curve_info", {}).get("spread_bps", 50)
        real_yield = dims.get("real_yield", {}).get("real_info", {}).get("current", 1.0)
        
        signal = self._compute_signal(score)

        # ETF配置 (依据信号)
        if signal["key"] in ("overweight_bonds", "tilt_bonds"):
            etf_advice = [
                {"etf": self.ETF_TARGETS["long_bond"], "ratio": f"{signal['bond_pct']//2}%", "reason": "核心长债"},
                {"etf": self.ETF_TARGETS["mid_bond"],  "ratio": f"{signal['bond_pct']//2}%", "reason": "中久期配置"},
                {"etf": self.ETF_TARGETS["stock"],     "ratio": f"{signal['stock_pct']}%",   "reason": "权益底仓"},
                {"etf": self.ETF_TARGETS["gold"],      "ratio": f"{signal['gold_pct']}%",    "reason": "避险对冲"},
            ]
        elif signal["key"] == "balanced":
            etf_advice = [
                {"etf": self.ETF_TARGETS["mid_bond"],   "ratio": f"{signal['bond_pct']}%",  "reason": "核心债券"},
                {"etf": self.ETF_TARGETS["stock"],      "ratio": f"{signal['stock_pct']}%",  "reason": "核心权益"},
                {"etf": self.ETF_TARGETS["gold"],       "ratio": f"{signal['gold_pct']}%",   "reason": "避险"},
            ]
        else:  # tilt_stocks / overweight_stocks / full_equity
            etf_advice = [
                {"etf": self.ETF_TARGETS["stock"],      "ratio": f"{signal['stock_pct']}%",  "reason": "核心权益"},
                {"etf": self.ETF_TARGETS["short_bond"],  "ratio": f"{signal['bond_pct']}%",  "reason": "短久期防御"},
                {"etf": self.ETF_TARGETS["gold"],       "ratio": f"{signal['gold_pct']}%",   "reason": "通胀对冲"},
            ]

        take_profit = [
            {"trigger": "10Y跌破3.0%(从高位回落)", "action": "减持长债20%", "type": "yield_bottom",
             "triggered": bool(y10 < 3.0), "current": f"10Y={y10:.2f}%"},
            {"trigger": "3M动量反转(>+50bps)", "action": "减持TLT 30%", "type": "momentum_reversal",
             "triggered": bool(chg_3m_bps > 50), "current": f"3M变化={chg_3m_bps:+.0f}bps"},
            {"trigger": "曲线恢复至+50bps以上", "action": "减持防御,增权益", "type": "recession_over",
             "triggered": bool(spread_bps > 50), "current": f"利差={spread_bps:+.0f}bps"},
        ]

        stop_loss = [
            {"trigger": "10Y > 5.0% (历史罕见)", "action": "逆向加仓TLT 20%", "type": "contrarian_buy", "color": "#10b981",
             "triggered": bool(y10 > 5.0), "current": f"10Y={y10:.2f}%"},
            {"trigger": "曲线倒挂 > 100bps", "action": "超配TLT+Gold 30%", "type": "recession_bonds", "color": "#10b981",
             "triggered": bool(spread_bps < -100), "current": f"利差={spread_bps:+.0f}bps"},
            {"trigger": "实际利率 > 2.5%", "action": "逆向买入TIPS 20%", "type": "contrarian_tips", "color": "#10b981",
             "triggered": bool(real_yield > 2.5), "current": f"实际利率={real_yield:.2f}%"},
            {"trigger": "10Y单月跳涨 > 50bps", "action": "暂停操作,等待稳定", "type": "shock", "color": "#f59e0b",
             "triggered": bool(chg_3m_bps > 80), "current": f"3M变化={chg_3m_bps:+.0f}bps"},
        ]

        return {
            "signal": signal,
            "etf_advice": etf_advice,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
        }

    # ========== 分位数统计 ==========

    def _compute_yield_percentiles(self) -> dict:
        """基于5年10Y数据计算滚动分位数和统计量
        用于动态区间划分，替代硬编码阈值。
        科学依据:
          - P75+0.5σ ≈ P87 (高利率 → 超配债券区)
          - P75       (偏高 → 标配偏债区)
          - P50       (中位数 → 中性)
          - P25       (偏低 → 标配偏股区)
          - P25-0.5σ ≈ P13 (极低利率 → 全股票区)
        优势: 低波动期阈值收紧(更灵敏), 高波动期阈值放宽(防假信号)
        """
        df = self._fetch_10y()
        if df.empty:
            # fallback到硬编码值
            return {"p75": 4.5, "p50": 3.5, "p25": 2.5, "std": 0.5,
                    "bond_overweight": 4.5, "bond_tilt": 4.0,
                    "stock_tilt": 2.5, "full_equity": 2.0,
                    "current_pct": 50.0, "mean": 3.5}

        vals = df["yield_10y"].dropna()
        p75 = float(np.percentile(vals, 75))
        p50 = float(np.percentile(vals, 50))
        p25 = float(np.percentile(vals, 25))
        std = float(vals.std())
        mean = float(vals.mean())
        current = float(vals.iloc[-1])
        current_pct = float((vals < current).mean() * 100)

        # 动态区间线
        bond_overweight = round(p75 + 0.5 * std, 3)  # ~P87 超配债券
        bond_tilt       = round(p75, 3)               # P75 标配偏债
        stock_tilt      = round(p25, 3)               # P25 标配偏股
        full_equity     = round(max(p25 - 0.5 * std, 0.5), 3)  # ~P13 全股票 (下限0.5%)

        stats = {
            "p75": round(p75, 3), "p50": round(p50, 3), "p25": round(p25, 3),
            "std": round(std, 3), "mean": round(mean, 3),
            "bond_overweight": bond_overweight,
            "bond_tilt": bond_tilt,
            "stock_tilt": stock_tilt,
            "full_equity": full_equity,
            "current": round(current, 3),
            "current_pct": round(current_pct, 1),
        }

        # 当前所处区间
        if current >= bond_overweight:
            stats["current_zone"] = "bond_overweight"
            stats["current_zone_label"] = "超配债券区"
            stats["current_zone_color"] = "#10b981"
        elif current >= bond_tilt:
            stats["current_zone"] = "bond_tilt"
            stats["current_zone_label"] = "标配偏债区"
            stats["current_zone_color"] = "#3b82f6"
        elif current > stock_tilt:
            stats["current_zone"] = "neutral"
            stats["current_zone_label"] = "中性区"
            stats["current_zone_color"] = "#94a3b8"
        elif current > full_equity:
            stats["current_zone"] = "stock_tilt"
            stats["current_zone_label"] = "标配偏股区"
            stats["current_zone_color"] = "#f97316"
        else:
            stats["current_zone"] = "full_equity"
            stats["current_zone_label"] = "全股票区"
            stats["current_zone_color"] = "#ef4444"

        logger.debug(f"Yield percentiles: P25={p25:.2f} P50={p50:.2f} P75={p75:.2f} σ={std:.2f} "
                     f"→ 超配>{bond_overweight:.2f} 全股票<{full_equity:.2f} 当前={current:.2f}({stats['current_zone_label']})")
        return stats

    # ========== 买卖决策区 ==========

    def _generate_buy_sell_zones(self, dims, snap, signal, pct_stats=None) -> dict:
        """生成买入/卖出/避险条件汇总 — 自适应分位数阈值
        V2.0: 利率水平条件从硬编码改为5年滚动分位数自适应
        """
        y10 = snap.get("yield_10y", 4.0)
        spread_bps = dims.get("curve_shape", {}).get("curve_info", {}).get("spread_bps", 50)
        real_yield = dims.get("real_yield", {}).get("real_info", {}).get("current", 1.0)
        chg_3m_bps = dims.get("yield_momentum", {}).get("momentum_info", {}).get("chg_3m_bps", 0)
        bei = snap.get("breakeven", 2.0)
        fed_dir = dims.get("fed_policy", {}).get("fed_info", {}).get("direction", "hold")

        # V2.0: 自适应分位数阈值
        if pct_stats is None:
            pct_stats = self._compute_yield_percentiles()

        bond_thresh = pct_stats["bond_tilt"]       # P75 → 债券买入门槛
        stock_thresh = pct_stats["stock_tilt"]     # P25 → 股票超配门槛
        y10_pct = pct_stats.get("current_pct", 50)

        bond_buy = [
            {"cond": f"10Y > P75({bond_thresh:.1f}%)", "met": bool(y10 > bond_thresh),
             "val": f"{y10:.2f}%", "why": "高于5年75%分位", "pct": round(y10_pct, 1)},
            {"cond": "实际利率 > 1.5%", "met": bool(real_yield > 1.5),
             "val": f"{real_yield:.2f}%", "why": "TIPS/长债配置价值"},
            {"cond": "Fed在降息", "met": fed_dir in ("fast_easing","easing","mild_easing"),
             "val": _regime_cn(fed_dir), "why": "降息→债牛"},
            {"cond": "利率3M下行>30bps", "met": bool(chg_3m_bps < -30),
             "val": f"{chg_3m_bps:+.0f}bps", "why": "动量确认宽松"},
            {"cond": "曲线倒挂(<0bps)", "met": bool(spread_bps < 0),
             "val": f"{spread_bps:+.0f}bps", "why": "降息预期→债牛在即"},
        ]
        stock_buy = [
            {"cond": f"10Y < P25({stock_thresh:.1f}%)", "met": bool(y10 < stock_thresh),
             "val": f"{y10:.2f}%", "why": "低于5年25%分位", "pct": round(y10_pct, 1)},
            {"cond": "实际利率 < 0%", "met": bool(real_yield < 0),
             "val": f"{real_yield:.2f}%", "why": "负利率→资产泡沫"},
            {"cond": "曲线陡峭化(>50bps)", "met": bool(spread_bps > 50),
             "val": f"{spread_bps:+.0f}bps", "why": "经济复苏信号"},
        ]
        defense = [
            {"cond": "曲线深度倒挂(<-50bps)", "met": bool(spread_bps < -50),
             "val": f"{spread_bps:+.0f}bps", "why": "衰退在即→长债锁定"},
            {"cond": "3M利率骤变>60bps", "met": bool(abs(chg_3m_bps) > 60),
             "val": f"{chg_3m_bps:+.0f}bps", "why": "市场剧烈波动"},
            {"cond": "通胀预期>2.5%", "met": bool(bei > 2.5),
             "val": f"{bei:.2f}%", "why": "通胀焦虑，利空"},
        ]

        bond_met = sum(1 for c in bond_buy if c["met"])
        stock_met = sum(1 for c in stock_buy if c["met"])
        defense_met = sum(1 for c in defense if c["met"])

        # 综合得分 (用于决策badge)
        composite_score = signal.get("score", 0)

        # 决策文字 (V2.0: 追加得分)
        if defense_met >= 2:
            conclusion = f"🔴 避险模式 · 防御{defense_met}条触发 · 得分{composite_score} · {signal.get('position','')}"
            conclusion_color = "#ef4444"
        elif bond_met >= 3:
            conclusion = f"🟢 债券买入窗口 · {bond_met}/{len(bond_buy)}条 · 得分{composite_score} · {signal.get('position','')}"
            conclusion_color = "#10b981"
        elif stock_met >= 2:
            conclusion = f"🟠 股票超配区 · {stock_met}/3条 · 得分{composite_score} · {signal.get('position','')}"
            conclusion_color = "#f97316"
        else:
            conclusion = f"⚪ 均衡配置 · 无极端信号 · 得分{composite_score} · {signal.get('position','')}"
            conclusion_color = "#94a3b8"

        return {
            "bond_buy": bond_buy,
            "stock_buy": stock_buy,
            "defense": defense,
            "bond_met": bond_met,
            "stock_met": stock_met,
            "defense_met": defense_met,
            "conclusion": conclusion,
            "conclusion_color": conclusion_color,
            "regime_label": f"{_regime_cn(dims.get('yield_level',{}).get('yield_info',{}).get('regime',''))}利率·{signal.get('label','')}",
            "percentile_stats": pct_stats,  # V2.0: 前端可展示分位数上下文
        }

    # ========== 警示系统 ==========

    def _generate_alerts(self, dims, snap) -> list:
        alerts = []
        y10 = snap.get("yield_10y", 4.0)
        spread_bps = dims.get("curve_shape", {}).get("curve_info", {}).get("spread_bps", 50)
        real_yield = dims.get("real_yield", {}).get("real_info", {}).get("current", 1.0)
        chg_3m_bps = dims.get("yield_momentum", {}).get("momentum_info", {}).get("chg_3m_bps", 0)

        if y10 > 5.0:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": f"10Y {y10:.2f}% > 5%! 历史罕见高位，长债锁定超额收益窗口", "pulse": True})
        if spread_bps < -50:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"曲线倒挂 {spread_bps:+.0f}bps! 衰退预警，建议防御配置", "pulse": True})
        if real_yield > 2.0:
            alerts.append({"level": "warning", "icon": "⚠️", "text": f"实际利率 {real_yield:.2f}% > 2%，资金成本极高，利空成长股", "pulse": False})
        if abs(chg_3m_bps) > 60:
            direction = "飙升" if chg_3m_bps > 0 else "骤降"
            alerts.append({"level": "warning", "icon": "⚡", "text": f"利率3M{direction}{abs(chg_3m_bps):.0f}bps! 市场波动加剧", "pulse": False})

        return alerts

    # ========== 诊断卡片 ==========

    def _generate_diagnosis(self, dims, signal) -> list:
        cards = []
        # 利率水平
        yl = dims.get("yield_level", {})
        yi = yl.get("yield_info", {})
        regime_cn = _regime_cn(yi.get('regime',''))
        cards.append({
            "title": f"利率·{regime_cn}",
            "type": "info" if yi.get("current",0) < 4 else "warning" if yi.get("current",0) < 5 else "danger",
            "text": f"10Y={yi.get('current',0):.2f}%, 5Y分位{yi.get('pct',0):.0f}%, Z={yi.get('z_score',0):.1f}σ"
        })
        # 动量
        ym = dims.get("yield_momentum", {})
        mi = ym.get("momentum_info", {})
        mom_cn = _regime_cn(mi.get('regime',''))
        mom_icon = "📉" if mi.get("chg_3m",0) < 0 else "📈"
        cards.append({
            "title": f"动量·{mom_cn}{mom_icon}",
            "type": "success" if mi.get("chg_3m",0) < 0 else "warning",
            "text": f"1M {mi.get('chg_1m',0)*100:+.0f}bps, 3M {mi.get('chg_3m',0)*100:+.0f}bps, 6M {mi.get('chg_6m',0)*100:+.0f}bps"
        })
        # 曲线
        cs = dims.get("curve_shape", {})
        ci = cs.get("curve_info", {})
        inverted = ci.get("spread_bps",0) < 0
        curve_cn = _regime_cn(ci.get('regime',''))
        cards.append({
            "title": "曲线·" + (curve_cn + "⚠️" if inverted else curve_cn if curve_cn != ci.get('regime','') else "正常"),
            "type": "danger" if ci.get("spread_bps",0) < -50 else "warning" if inverted else "success",
            "text": f"10Y-2Y={ci.get('spread_bps',0):+.0f}bps (分位{ci.get('pct',50):.0f}%)"
        })
        # 实际利率
        ry = dims.get("real_yield", {})
        ri = ry.get("real_info", {})
        real_cn = _regime_cn(ri.get('regime',''))
        cards.append({
            "title": f"实际利率·{real_cn}",
            "type": "warning" if ri.get("current",0) > 2 else "info",
            "text": f"TIPS 10Y={ri.get('current',0):.2f}%, BEI={ri.get('breakeven',0):.2f}%"
        })
        # 操作建议
        sig = signal
        cards.append({
            "title": f"操作·{sig.get('label','--')}",
            "type": "success" if sig.get('level',0) >= 4 else "info" if sig.get('level',0) >= 3 else "warning",
            "text": f"配置: {sig.get('position','--')}。久期: {sig.get('duration','--')}。"
        })
        return cards

    # ========== 走势图 ==========

    def _build_chart_data(self, pct_stats=None) -> dict:
        """V3.0: 生产级图表数据 — 扩展到~5年 + stats统计 + extremes极值 (对标ERP历史走势图)"""
        try:
            df_10y = self._fetch_10y()
            df_2y = self._fetch_2y()
        except Exception as e:
            logger.warning(f"chart data error: {e}")
            return {"status": "error"}

        if df_10y.empty:
            return {"status": "error"}

        # V2.0: 分位数统计 (复用已计算结果避免重复)
        if pct_stats is None:
            pct_stats = self._compute_yield_percentiles()

        # V3.0: 扩展到~5年数据 (~1200个交易日) 提供完整利率周期视角 (dataZoom缓解渲染负担)
        df_10y = df_10y.tail(1200)
        dates = df_10y["trade_date"].dt.strftime("%Y-%m-%d").tolist()
        yields_10y = [round(float(v), 3) for v in df_10y["yield_10y"].values]

        # 计算利差
        spreads = []
        if not df_2y.empty:
            merged = pd.merge_asof(
                df_10y.sort_values("trade_date"),
                df_2y.sort_values("trade_date"),
                on="trade_date", direction="nearest"
            )
            spreads = [round(float(a - b), 3) for a, b in zip(merged["yield_10y"], merged["yield_2y"])]

        # V2.0: 动态区间线 (替代硬编码 4.5/3.0/2.0)
        lines = {
            "high_zone": pct_stats["bond_overweight"],    # P75+0.5σ
            "high_tilt": pct_stats["bond_tilt"],          # P75
            "neutral":   pct_stats["p50"],                # P50 中位数
            "low_tilt":  pct_stats["stock_tilt"],         # P25
            "low_zone":  pct_stats["full_equity"],        # P25-0.5σ
        }

        # V2.0: markArea 渐变色带数据 (前端ECharts直接使用)
        y_max = max(yields_10y) + 0.5 if yields_10y else 6.0
        y_min = max(min(yields_10y) - 0.3, 0) if yields_10y else 0.0
        mark_areas = [
            {"name": "超配债券区", "y_from": lines["high_zone"], "y_to": y_max,
             "color": "rgba(16,185,129,0.08)", "border": "#10b981",
             "label": f"超配债券 >{lines['high_zone']:.1f}%"},
            {"name": "标配偏债区", "y_from": lines["high_tilt"], "y_to": lines["high_zone"],
             "color": "rgba(59,130,246,0.05)", "border": "#3b82f6",
             "label": f"偏债 {lines['high_tilt']:.1f}-{lines['high_zone']:.1f}%"},
            {"name": "标配偏股区", "y_from": lines["low_zone"], "y_to": lines["low_tilt"],
             "color": "rgba(249,115,22,0.06)", "border": "#f97316",
             "label": f"偏股 {lines['low_zone']:.1f}-{lines['low_tilt']:.1f}%"},
            {"name": "全股票区", "y_from": y_min, "y_to": lines["low_zone"],
             "color": "rgba(239,68,68,0.06)", "border": "#ef4444",
             "label": f"全股票 <{lines['low_zone']:.1f}%"},
        ]

        # ═══ V3.0: stats 统计增强 (对标 ERP chart.stats 结构) ═══
        import numpy as np
        arr = np.array(yields_10y)
        current_val = arr[-1] if len(arr) > 0 else 0
        mean_val = round(float(np.nanmean(arr)), 2)
        std_val = round(float(np.nanstd(arr)), 3)
        min_val = round(float(np.nanmin(arr)), 2) if len(arr) > 0 else 0
        max_val = round(float(np.nanmax(arr)), 2) if len(arr) > 0 else 0

        # 数据跨度(年)
        date_range_years = round(len(arr) / 252, 1) if len(arr) > 0 else 0

        # 当前值vs均值偏离
        current_vs_mean = round(float(current_val - mean_val), 2)

        # 当前5年分位数
        current_pct = round(float(np.sum(arr <= current_val) / max(len(arr), 1) * 100), 1)

        # 区间分类函数
        def _zone_classify(v):
            if v >= lines["high_zone"]:
                return "超配债券区", "#10b981"
            elif v >= lines["high_tilt"]:
                return "标配偏债区", "#3b82f6"
            elif v <= lines["low_zone"]:
                return "全股票区", "#ef4444"
            elif v <= lines["low_tilt"]:
                return "标配偏股区", "#f97316"
            else:
                return "中性均衡区", "#94a3b8"

        current_zone_label, current_zone_color = _zone_classify(current_val)

        # 各区间历史占比
        bond_zone_count = int(np.sum(arr >= lines["high_zone"]))
        stock_zone_count = int(np.sum(arr <= lines["low_zone"]))
        bond_zone_pct = round(bond_zone_count / max(len(arr), 1) * 100, 1)
        stock_zone_pct = round(stock_zone_count / max(len(arr), 1) * 100, 1)

        # 极值点标注 (历史最高+最低)
        extremes = []
        if len(arr) > 0:
            max_idx = int(np.nanargmax(arr))
            min_idx = int(np.nanargmin(arr))
            extremes.append({"date": dates[max_idx], "value": round(float(arr[max_idx]), 2), "type": "max"})
            extremes.append({"date": dates[min_idx], "value": round(float(arr[min_idx]), 2), "type": "min"})

        # 利差倒挂统计 (科学优化: 衰退预警)
        inversion_days = 0
        if spreads:
            inversion_days = sum(1 for s in spreads if s < 0)

        stats = {
            "current": round(float(current_val), 2),
            "mean": mean_val,
            "std": std_val,
            "min": min_val,
            "max": max_val,
            "current_vs_mean": current_vs_mean,
            "current_pct": current_pct,
            "current_zone_label": current_zone_label,
            "current_zone_color": current_zone_color,
            "date_range_years": date_range_years,
            "bond_zone_pct": bond_zone_pct,
            "stock_zone_pct": stock_zone_pct,
            "extremes": extremes,
            "inversion_days": inversion_days,
            "inversion_pct": round(inversion_days / max(len(dates), 1) * 100, 1),
            # 前端区间判定所需的阈值 (供 JS getYieldZoneLabel 使用)
            "zone_thresholds": {
                "high_zone": round(float(lines["high_zone"]), 2),
                "high_tilt": round(float(lines["high_tilt"]), 2),
                "neutral": round(float(lines["neutral"]), 2),
                "low_tilt": round(float(lines["low_tilt"]), 2),
                "low_zone": round(float(lines["low_zone"]), 2),
            },
        }

        return {
            "status": "success",
            "dates": dates,
            "yields_10y": yields_10y,
            "spreads": spreads if spreads else None,
            "lines": lines,
            "mark_areas": mark_areas,
            "percentile_stats": pct_stats,
            "stats": stats,
        }

    # ========== V2.0: 并行数据预取 ==========

    def _prefetch_all_data(self) -> dict:
        """并行获取所有FRED序列, 避免串行延迟 (5x200ms→1x200ms)"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = {}
        fetchers = {
            "df_10y": self._fetch_10y,
            "df_2y": self._fetch_2y,
            "df_real": self._fetch_real_yield,
            "df_bei": self._fetch_breakeven,
            "df_3m": self._fetch_tbill_3m,
        }
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(fn): key for key, fn in fetchers.items()}
            for f in as_completed(futures):
                key = futures[f]
                try:
                    results[key] = f.result()
                except Exception as e:
                    logger.warning(f"Prefetch {key} failed: {e}")
                    results[key] = pd.DataFrame()
        return results

    # ========== 主报告 ==========

    def generate_report(self) -> dict:
        try:
            # V2.0: 并行预取所有FRED序列 (5个请求并行, ~200ms)
            data = self._prefetch_all_data()
            df_10y = data["df_10y"]
            df_2y = data["df_2y"]
            df_real = data["df_real"]
            df_bei = data["df_bei"]
            df_3m = data["df_3m"]

            # V2.0: 分位数统计 (一次计算, 全链路共享)
            pct_stats = self._compute_yield_percentiles()

            # 五维评分 (传入预取数据, 消除重复fetch)
            d1_score, d1_info, d1_desc = self._score_d1_yield_level(df_10y=df_10y, pct_stats=pct_stats)
            d2_score, d2_info, d2_desc = self._score_d2_yield_momentum(df_10y=df_10y)
            d3_score, d3_info, d3_desc = self._score_d3_curve_shape(df_10y=df_10y, df_2y=df_2y)
            d4_score, d4_info, d4_desc = self._score_d4_real_yield(df_real=df_real, df_bei=df_bei)
            d5_score, d5_info, d5_desc = self._score_d5_fed_policy(df_3m=df_3m)

            dims = {
                "yield_level":    {"score": d1_score, "label": "利率水平", "weight": self.W["yield_level"],    "yield_info": d1_info, "desc": d1_desc},
                "yield_momentum": {"score": d2_score, "label": "利率动量", "weight": self.W["yield_momentum"], "momentum_info": d2_info, "desc": d2_desc},
                "curve_shape":    {"score": d3_score, "label": "曲线形态", "weight": self.W["curve_shape"],    "curve_info": d3_info, "desc": d3_desc},
                "real_yield":     {"score": d4_score, "label": "实际利率", "weight": self.W["real_yield"],     "real_info": d4_info, "desc": d4_desc},
                "fed_policy":     {"score": d5_score, "label": "Fed政策",  "weight": self.W["fed_policy"],     "fed_info": d5_info, "desc": d5_desc},
            }

            # 加权综合
            composite = sum(dims[k]["score"] * self.W[k] for k in self.W)
            composite = round(min(100, max(0, composite)), 1)

            # 信号
            signal = self._compute_signal(composite)

            # 快照 (新增 regime_cn 字段)
            snap = {
                "yield_10y": d1_info.get("current", 0),
                "yield_2y": d3_info.get("yield_2y", 0),
                "real_yield": d4_info.get("current", 0),
                "breakeven": d4_info.get("breakeven", 0),
                "spread_bps": d3_info.get("spread_bps", 0),
                "rate_3m": d5_info.get("current", 0),
                "regime_cn": {
                    "yield_level": _regime_cn(d1_info.get("regime","")),
                    "momentum": _regime_cn(d2_info.get("regime","")),
                    "curve": _regime_cn(d3_info.get("regime","")),
                    "real_yield": _regime_cn(d4_info.get("regime","")),
                    "fed": _regime_cn(d5_info.get("direction","")),
                },
            }

            # 买卖规则
            trade = self._generate_trade_rules(composite, dims, snap)

            # 买卖决策区 (传入分位数, 避免重复计算)
            buy_sell_zones = self._generate_buy_sell_zones(dims, snap, signal, pct_stats)

            # 警示
            alerts = self._generate_alerts(dims, snap)

            # 诊断
            diagnosis = self._generate_diagnosis(dims, signal)

            # 走势图 (传入预取数据+分位数)
            chart = self._build_chart_data(pct_stats)

            return {
                "version": self.VERSION,
                "current_snapshot": snap,
                "dimensions": dims,
                "signal": signal,
                "trade_rules": trade,
                "buy_sell_zones": buy_sell_zones,
                "alerts": alerts,
                "diagnosis": diagnosis,
                "chart": chart,
                "card_tooltips": CARD_TOOLTIPS,
                "alert_hints": ALERT_HINTS,
                "encyclopedia": ENCYCLOPEDIA_RATES,
            }
        except Exception as e:
            import traceback
            logger.error(f"Report error: {traceback.format_exc()}")
            return {"version": self.VERSION, "error": str(e)}

    def warmup(self):
        """启动/定时预热: 强制刷新所有FRED数据到内存+磁盘缓存"""
        import time
        t0 = time.time()
        _force_refresh_cache()  # 先清空内存缓存
        try:
            # 并行拉取5个FRED序列
            self._prefetch_all_data()
            # 生成完整报告(触发评分计算, 填充结果缓存)
            report = self.generate_report()
            y10 = report.get('current_snapshot',{}).get('yield_10y', '?')
            score = report.get('signal',{}).get('score', '?')
            elapsed = time.time() - t0
            logger.info(f"Warmup 完成 | 10Y={y10}% | 得分={score} | {elapsed:.1f}s")
            return True
        except Exception as e:
            logger.error(f"Warmup 失败: {e}")
            return False


# 单例
_rates_engine = None
def get_rates_engine() -> RatesStrategyEngine:
    global _rates_engine
    if _rates_engine is None:
        _rates_engine = RatesStrategyEngine()
    return _rates_engine


def warmup_rates_cache():
    """供 main.py 调用的预热函数"""
    engine = get_rates_engine()
    engine.warmup()


