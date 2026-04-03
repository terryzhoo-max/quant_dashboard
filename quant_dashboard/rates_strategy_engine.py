"""
AlphaCore · 利率择时引擎 V1.0
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
from datetime import datetime, timedelta
from typing import Optional

FRED_API_KEY = "eadf412d4f0e8ccd2bb3993b357bdca6"
CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

# FRED 初始化 (复用 erp_us_engine 的模式)
_fred_instance = None
def _get_fred():
    global _fred_instance
    if _fred_instance is None:
        try:
            from fredapi import Fred
            _fred_instance = Fred(api_key=FRED_API_KEY)
        except Exception as e:
            print(f"[RATES] FRED init failed: {e}")
    return _fred_instance

# ===== 智能缓存系统 =====
# FRED国债数据每日更新一次(美东6AM):
#   - 同一日数据命中 → 直接返回内存缓存, 不调API
#   - 跨日 → 重新拉取
#   - FRED不可达 → fallback磁盘缓存

_rates_cache = {}  # {key: (timestamp, last_data_date, DataFrame)}

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
    """智能缓存: 同一FRED日命中直接返回, 跨日拉API"""
    import time
    now = time.time()
    if key in _rates_cache:
        ts_cached, last_date, data = _rates_cache[key]
        if _is_same_trading_day(ts_cached):
            return data
        print(f"[RATES] cache expired (跨日), refreshing {key}")
    try:
        data = fetcher()
        _rates_cache[key] = (now, datetime.now().strftime('%Y-%m-%d'), data)
        return data
    except Exception as e:
        print(f"[RATES] cache fail ({key}): {e}")
        if key in _rates_cache:
            print(f"[RATES] using stale memory cache for {key}")
            return _rates_cache[key][2]
        raise

def _force_refresh_cache():
    """强制清除所有内存缓存, 下次访问时重拉FRED"""
    global _rates_cache
    _rates_cache = {}
    print(f"[RATES] 内存缓存已全部清除")


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
    """利率择时引擎 V1.0"""

    VERSION = "1.0"

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
        """通用FRED序列获取 (智能日级缓存)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, f"rates_{cache_key}.parquet")
            # 1. 先检查磁盘缓存是否是今天的数据
            if os.path.exists(cache_file):
                try:
                    disk_df = pd.read_parquet(cache_file)
                    if not disk_df.empty:
                        last_date = pd.Timestamp(disk_df['trade_date'].iloc[-1]).date()
                        today = datetime.now().date()
                        # FRED数据延迟1天, 所以昨天的数据就是最新的
                        if (today - last_date).days <= 1:
                            print(f"[RATES] {series_id}: disk cache fresh (latest={last_date})")
                            return disk_df
                except Exception:
                    pass
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
                        print(f"[RATES] {series_id} (FRED API): {len(df)} rows, latest={df[col_name].iloc[-1]:.3f}")
                        return df
                except Exception as e:
                    print(f"[RATES] FRED {series_id} error: {e}")
            # 3. FRED不可达, fallback磁盘缓存(即使过期也用)
            if os.path.exists(cache_file):
                print(f"[RATES] {series_id}: fallback to stale disk cache")
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

    def _score_d1_yield_level(self) -> tuple:
        """D1: 利率水平 → 0-100 (高利率=高分=债券有吸引力)"""
        df = self._fetch_10y()
        if df.empty:
            return 50.0, {}, "数据缺失"

        current = float(df["yield_10y"].iloc[-1])
        pct = float((df["yield_10y"] < current).mean() * 100)

        # 5年均值和标准差
        mean_5y = float(df["yield_10y"].mean())
        std_5y = float(df["yield_10y"].std())
        z_score = (current - mean_5y) / std_5y if std_5y > 0 else 0

        if current >= 5.0:
            score, regime = 95, "extreme_high"
            desc = f"10Y {current:.2f}% ≥ 5% → 40年罕见高位! 债券极具吸引力"
        elif current >= 4.5:
            score, regime = 85, "very_high"
            desc = f"10Y {current:.2f}% 高收益环境，长债配置价值突出"
        elif current >= 4.0:
            score, regime = 75, "high"
            desc = f"10Y {current:.2f}% 偏高，债券票息丰厚"
        elif current >= 3.5:
            score, regime = 65, "above_avg"
            desc = f"10Y {current:.2f}% 中性偏高"
        elif current >= 3.0:
            score, regime = 50, "neutral"
            desc = f"10Y {current:.2f}% 中性区间"
        elif current >= 2.0:
            score, regime = 35, "below_avg"
            desc = f"10Y {current:.2f}% 偏低，股票更有吸引力"
        elif current >= 1.0:
            score, regime = 20, "low"
            desc = f"10Y {current:.2f}% 低利率，TINA效应驱动股市"
        else:
            score, regime = 5, "extreme_low"
            desc = f"10Y {current:.2f}% < 1% → 零利率时代"

        info = {
            "current": round(current, 3),
            "pct": round(pct, 1),
            "mean_5y": round(mean_5y, 3),
            "z_score": round(z_score, 2),
            "regime": regime,
        }
        return round(score, 1), info, desc

    def _score_d2_yield_momentum(self) -> tuple:
        """D2: 利率动量 → 0-100 (利率下行=高分=债券牛市)"""
        df = self._fetch_10y()
        if df.empty or len(df) < 63:
            return 50.0, {}, "数据不足"

        current = float(df["yield_10y"].iloc[-1])
        prev_1m = float(df["yield_10y"].iloc[-22]) if len(df) >= 22 else current
        prev_3m = float(df["yield_10y"].iloc[-63]) if len(df) >= 63 else current
        prev_6m = float(df["yield_10y"].iloc[-126]) if len(df) >= 126 else current

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

    def _score_d3_curve_shape(self) -> tuple:
        """D3: 曲线形态 (10Y-2Y) → 0-100"""
        try:
            df_10y = self._fetch_10y()
            df_2y = self._fetch_2y()
        except:
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

        if spread_bps < -100:
            score, regime = 15, "deep_inversion"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 深度倒挂! 衰退预警"
        elif spread_bps < -50:
            score, regime = 30, "moderate_inversion"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 明显倒挂，12-18月衰退概率高"
        elif spread_bps < 0:
            score, regime = 45, "mild_inversion"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 轻微倒挂，警惕"
        elif spread_bps < 50:
            score, regime = 55, "flat"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 正常偏平坦"
        elif spread_bps < 150:
            score, regime = 75, "normal_steep"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 健康陡峭"
        else:
            score, regime = 90, "extreme_steep"
            desc = f"10Y-2Y = {spread_bps:+.0f}bps → 极度陡峭，经济复苏/通胀预期强"

        info = {
            "yield_10y": round(y10, 3),
            "yield_2y": round(y2, 3),
            "spread": round(spread, 3),
            "spread_bps": round(spread_bps, 0),
            "pct": round(pct, 1),
            "regime": regime,
        }
        return round(score, 1), info, desc

    def _score_d4_real_yield(self) -> tuple:
        """D4: 实际利率 (TIPS 10Y) → 0-100 (高实际利率=高分=债券有吸引力)"""
        try:
            df = self._fetch_real_yield()
        except:
            return 50.0, {}, "TIPS数据缺失"

        if df.empty:
            return 50.0, {}, "数据缺失"

        current = float(df["real_yield"].iloc[-1])
        pct = float((df["real_yield"] < current).mean() * 100)

        # 通胀预期 = 10Y名义 - TIPS
        try:
            bei_df = self._fetch_breakeven()
            bei = float(bei_df["breakeven"].iloc[-1]) if not bei_df.empty else 0
        except:
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

    def _score_d5_fed_policy(self) -> tuple:
        """D5: Fed政策方向 (3M T-Bill) → 0-100 (降息=高分)"""
        try:
            df = self._fetch_tbill_3m()
        except:
            return 50.0, {}, "3M T-Bill数据缺失"

        if df.empty or len(df) < 22:
            return 50.0, {}, "数据不足"

        current = float(df["rate_3m"].iloc[-1])
        prev_1m = float(df["rate_3m"].iloc[-22]) if len(df) >= 22 else current
        prev_3m = float(df["rate_3m"].iloc[-63]) if len(df) >= 63 else current

        chg_3m = current - prev_3m
        is_easing = chg_3m < -0.1  # 利率下行>10bps
        is_tightening = chg_3m > 0.1

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
            {"trigger": "曲线倒挂 > 100bps", "action": "全防御(SHV+Gold)", "type": "recession_hard", "color": "#ef4444",
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

    # ========== 买卖决策区 ==========

    def _generate_buy_sell_zones(self, dims, snap, signal) -> dict:
        """生成买入/卖出/避险条件汇总 — 10条核心条件"""
        y10 = snap.get("yield_10y", 4.0)
        spread_bps = dims.get("curve_shape", {}).get("curve_info", {}).get("spread_bps", 50)
        real_yield = dims.get("real_yield", {}).get("real_info", {}).get("current", 1.0)
        chg_3m_bps = dims.get("yield_momentum", {}).get("momentum_info", {}).get("chg_3m_bps", 0)
        bei = snap.get("breakeven", 2.0)
        fed_dir = dims.get("fed_policy", {}).get("fed_info", {}).get("direction", "hold")

        bond_buy = [
            {"cond": "10Y > 4.0%", "met": bool(y10 > 4.0), "val": f"{y10:.2f}%", "why": "高票息锁定收益"},
            {"cond": "实际利率 > 1.5%", "met": bool(real_yield > 1.5), "val": f"{real_yield:.2f}%", "why": "TIPS/长债配置价值"},
            {"cond": "Fed在降息", "met": fed_dir in ("fast_easing","easing","mild_easing"), "val": _regime_cn(fed_dir), "why": "降息→债牛"},
            {"cond": "利率3M下行>30bps", "met": bool(chg_3m_bps < -30), "val": f"{chg_3m_bps:+.0f}bps", "why": "动量确认宽松"},
        ]
        stock_buy = [
            {"cond": "10Y < 2.0%", "met": bool(y10 < 2.0), "val": f"{y10:.2f}%", "why": "TINA效应驱动股市"},
            {"cond": "实际利率 < 0%", "met": bool(real_yield < 0), "val": f"{real_yield:.2f}%", "why": "负利率→资产泡沫"},
            {"cond": "曲线陡峭化(>50bps)", "met": bool(spread_bps > 50), "val": f"{spread_bps:+.0f}bps", "why": "经济复苏信号"},
        ]
        defense = [
            {"cond": "曲线深度倒挂(<-50bps)", "met": bool(spread_bps < -50), "val": f"{spread_bps:+.0f}bps", "why": "衰退概率>80%"},
            {"cond": "3M利率骤变>60bps", "met": bool(abs(chg_3m_bps) > 60), "val": f"{chg_3m_bps:+.0f}bps", "why": "市场剧烈波动"},
            {"cond": "通胀预期>2.5%", "met": bool(bei > 2.5), "val": f"{bei:.2f}%", "why": "通胀焦虑，利空"},
        ]

        bond_met = sum(1 for c in bond_buy if c["met"])
        stock_met = sum(1 for c in stock_buy if c["met"])
        defense_met = sum(1 for c in defense if c["met"])

        # 决策文字
        if defense_met >= 2:
            conclusion = f"🔴 避险模式 · 防御信号{defense_met}条触发 · {signal.get('position','')}"
            conclusion_color = "#ef4444"
        elif bond_met >= 3:
            conclusion = f"🟢 债券买入窗口 · {bond_met}/4条满足 · {signal.get('position','')}"
            conclusion_color = "#10b981"
        elif stock_met >= 2:
            conclusion = f"🟠 股票超配区 · {stock_met}/3条满足 · {signal.get('position','')}"
            conclusion_color = "#f97316"
        else:
            conclusion = f"⚪ 均衡配置 · 无极端信号 · {signal.get('position','')}"
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

    def _build_chart_data(self) -> dict:
        try:
            df_10y = self._fetch_10y()
            df_2y = self._fetch_2y()
        except:
            return {"status": "error"}

        if df_10y.empty:
            return {"status": "error"}

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

        return {
            "status": "success",
            "dates": dates,
            "yields_10y": yields_10y,
            "spreads": spreads if spreads else None,
            "lines": {
                "high_zone": 4.5,
                "neutral": 3.0,
                "low_zone": 2.0,
            }
        }

    # ========== 主报告 ==========

    def generate_report(self) -> dict:
        try:
            # 五维评分
            d1_score, d1_info, d1_desc = self._score_d1_yield_level()
            d2_score, d2_info, d2_desc = self._score_d2_yield_momentum()
            d3_score, d3_info, d3_desc = self._score_d3_curve_shape()
            d4_score, d4_info, d4_desc = self._score_d4_real_yield()
            d5_score, d5_info, d5_desc = self._score_d5_fed_policy()

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

            # 买卖决策区
            buy_sell_zones = self._generate_buy_sell_zones(dims, snap, signal)

            # 警示
            alerts = self._generate_alerts(dims, snap)

            # 诊断
            diagnosis = self._generate_diagnosis(dims, signal)

            # 走势图
            chart = self._build_chart_data()

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
            print(f"[RATES] Report error: {traceback.format_exc()}")
            return {"version": self.VERSION, "error": str(e)}

    def warmup(self):
        """启动/定时预热: 强制刷新所有FRED数据到内存+磁盘缓存"""
        import time
        t0 = time.time()
        _force_refresh_cache()  # 先清空内存缓存
        try:
            # 拉取5个FRED序列
            self._fetch_10y()
            self._fetch_2y()
            self._fetch_real_yield()
            self._fetch_breakeven()
            self._fetch_tbill_3m()
            # 生成完整报告(触发评分计算, 填充结果缓存)
            report = self.generate_report()
            y10 = report.get('current_snapshot',{}).get('yield_10y', '?')
            score = report.get('signal',{}).get('score', '?')
            elapsed = time.time() - t0
            print(f"[RATES Warmup] \u5b8c\u6210 | 10Y={y10}% | \u5f97\u5206={score} | {elapsed:.1f}s")
            return True
        except Exception as e:
            print(f"[RATES Warmup] \u5931\u8d25: {e}")
            return False


# 单例
_rates_engine = None
def get_rates_engine() -> RatesStrategyEngine:
    global _rates_engine
    if _rates_engine is None:
        _rates_engine = RatesStrategyEngine()
    return _rates_engine


def warmup_rates_cache():
    """供 main.py \u8c03\u7528\u7684\u9884\u70ed\u51fd\u6570"""
    engine = get_rates_engine()
    engine.warmup()

