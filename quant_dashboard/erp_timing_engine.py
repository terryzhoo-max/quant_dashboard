"""
AlphaCore · 宏观ERP择时引擎 V2.0
===================================
五维择时信号系统 (权重已通过回测优化):
  D1: ERP绝对值 (1/PE - 10Y国债)       — 权重20%  [估值]
  D2: ERP历史分位 (近4年)               — 权重30%  [估值]
  D3: M1同比趋势 (拐点+方向)            — 权重35%  [流动性] ← 最关键因子
  D4: 波动率指标 (PE滚动标准差)          — 权重 8%  [风险]
  D5: 信用环境 (M1-M2剪刀差)            — 权重 7%  [风险]

买卖规则引擎:
  - 逆向加仓型止损策略 (大跌反而加仓)
  - ETF标的: 沪深300ETF / 中证500ETF / 红利ETF

数据源: Tushare Pro
  - index_dailybasic → PE_TTM (日频)
  - yc_cb → 10Y国债收益率 (日频)
  - cn_m → M1/M2同比 (月频)
"""

import pandas as pd
import numpy as np
import tushare as ts
import time
import os
from datetime import datetime, timedelta
from typing import Optional

import json
import threading
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from config import TUSHARE_TOKEN as CONFIG_TOKEN
from erp_signal_enhancer import adaptive_weights, multi_timeframe_confirmation

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", CONFIG_TOKEN)
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

# ===== 工业级重试装饰器 =====
def retry_with_backoff(max_retries=3, base_delay=2.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if i == max_retries - 1:
                        raise e
                    print(f"[Retry] {func.__name__} failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                    delay *= 2
            return None
        return wrapper
    return decorator

# ===== 原子性文件写入 =====
def atomic_write_parquet(df, filepath):
    tmp_path = filepath + ".tmp"
    try:
        df.to_parquet(tmp_path)
        os.replace(tmp_path, filepath)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise e

# ===== 线程安全 + SWR 后台缓存 =====
_cache = {}
_cache_lock = threading.Lock()
_bg_executor = ThreadPoolExecutor(max_workers=3)

def _refresh_cache(key: str, fetcher):
    try:
        data = fetcher()
        with _cache_lock:
            _cache[key] = (time.time(), data)
        return data
    except Exception as e:
        print(f"[ERP Engine] 后台缓存刷新失败 ({key}): {e}")
        with _cache_lock:
            if key in _cache:
                return _cache[key][1]
        raise

def _cached(key: str, ttl_seconds: int, fetcher):
    """线程安全 TTL 缓存 (支持 SWR - Stale-While-Revalidate)"""
    now = time.time()
    with _cache_lock:
        if key in _cache:
            ts_cached, data = _cache[key]
            if now - ts_cached < ttl_seconds:
                return data
            else:
                # SWR 模式: 返回旧数据，并在后台异步刷新
                _bg_executor.submit(_refresh_cache, key, fetcher)
                return data

    # 内存无数据，必须同步阻塞拉取（通常是冷启动或服务重启后）
    return _refresh_cache(key, fetcher)


# ===== 规则百科 =====
ENCYCLOPEDIA = {
    "erp_abs": {
        "title": "ERP 股权风险溢价",
        "what": 'ERP = 盈利收益率(1/PE) - 无风险利率(10Y国债)。代表"股票比债券多赚多少"。',
        "why": "ERP越高 → 股票相对债券越便宜 → 配置价值越大。A股历史中位数约4.5-5%。",
        "alert": 'ERP < 3% 时进入危险区，意味着买股票不如买国债。ERP > 6% 是极度低估的"黄金窗口"。',
        "history": "2018年底ERP约7.5%（底部），2021年初约3.2%（顶部），2024年初约6.8%（大底）。"
    },
    "erp_pct": {
        "title": "ERP 历史分位",
        "what": "过去4年中，有多少比例的交易日ERP比今天低。80%分位 → 过去80%时间股票比现在贵。",
        "why": "分位越高 → 当前估值越罕见地便宜 → 中长期赔率越好。",
        "alert": "分位 > 80% 是极度罕见的低估（历史级机会）。分位 < 20% 意味着高处不胜寒。",
        "history": "分位指标在2018/2022/2024年底均超过75%，之后市场都迎来了显著反弹。"
    },
    "m1_trend": {
        "title": "M1 流动性趋势",
        "what": "M1 = 现金 + 活期存款。M1同比增长意味着企业和个人手中活钱增多。",
        "why": "M1拐点领先股市约3-6个月。M1上行 → 资金面宽松 → 利好股市。",
        "alert": "M1连续3月下滑需警惕流动性收紧。M1转负（<0%）是强烈的防御信号。",
        "history": "2020年M1加速上行后，沪深300上涨超40%。2022年M1持续低迷，市场熊市。"
    },
    "volatility": {
        "title": "波动率指标",
        "what": "基于沪深300 PE-TTM 的60日滚动标准差，反映市场估值的波动程度。",
        "why": "高波动=市场分歧大，追涨杀跌频繁。但极端恐慌(超高波动)往往是中长期底部。",
        "alert": "波动率突破历史90%分位时，往往对应市场恐慌性抛售，逆向投资者的机会。",
        "history": "2020年3月、2022年4月、2024年1月均出现波动率飙升，之后市场见底反弹。"
    },
    "credit": {
        "title": "信用环境 (M1-M2剪刀差)",
        "what": "M1-M2剪刀差 = M1同比 - M2同比。反映资金活化程度。",
        "why": "剪刀差收窄/转正 → 定期存款活化 → 资金转向实体经济/股市 → 利好权益。",
        "alert": "剪刀差持续走阔（M1远低于M2）→ 居民/企业储蓄意愿强，消费投资低迷。",
        "history": "2020年剪刀差快速收窄，对应沪深300大涨。2022年剪刀差走阔，市场走弱。"
    }
}


class ERPTimingEngine:
    """宏观ERP择时引擎 V2.0"""

    VERSION = "2.0"
    INDEX_CODE = "000300.SH"
    BOND_CODE = "1001.CB"

    # 五维权重 (经回测网格搜索优化: IS 2018-2023 + OOS 2024-2025)
    # 最优参数: Alpha +3.89% OOS, Sharpe 1.62, MDD -10.08%
    W = {"erp_abs": 0.20, "erp_pct": 0.30, "m1_trend": 0.35, "volatility": 0.08, "credit": 0.07}

    # 信号映射 (6级)
    SIGNAL_MAP = {
        "strong_buy":  {"label": "强力买入", "position": "80-100%", "color": "#10b981", "emoji": "🟢🟢", "level": 6},
        "buy":         {"label": "买入",     "position": "60-80%",  "color": "#34d399", "emoji": "🟢",   "level": 5},
        "hold":        {"label": "标配持有", "position": "50-70%",  "color": "#3b82f6", "emoji": "🔵",   "level": 4},
        "reduce":      {"label": "逐步减仓", "position": "30-50%",  "color": "#f59e0b", "emoji": "🟡",   "level": 3},
        "underweight": {"label": "低配防御", "position": "10-30%",  "color": "#f97316", "emoji": "🟠",   "level": 2},
        "cash":        {"label": "清仓观望", "position": "0-10%",   "color": "#ef4444", "emoji": "🔴",   "level": 1},
    }

    # ETF标的
    ETF_TARGETS = {
        "aggressive": {"name": "中证500ETF", "code": "510500", "desc": "弹性最大，适合底部反弹"},
        "balanced":   {"name": "沪深300ETF", "code": "510300", "desc": "核心配置，攻守兼备"},
        "defensive":  {"name": "红利ETF",    "code": "510880", "desc": "防御优先，稳定现金流"},
    }

    def __init__(self):
        # P1/C1/C2 fix: 从本地文件加载状态，确保多进程/请求间无状态污染
        history = self._load_history()
        self._prev_score = history.get("prev_score")
        self._prev_score_date = history.get("prev_score_date")
        self._score_high_water = history.get("score_high_water", 0.0)
        self._score_history = history.get("score_history", [])  # O6: 最近5天Score列表

    def _load_history(self) -> dict:
        filepath = os.path.join(CACHE_DIR, "erp_daily_history.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_history(self):
        filepath = os.path.join(CACHE_DIR, "erp_daily_history.json")
        data = {
            "prev_score": self._prev_score,
            "prev_score_date": str(self._prev_score_date) if self._prev_score_date else None,
            "score_high_water": self._score_high_water,
            "score_history": self._score_history[-5:],  # O6: 保留最近5条
        }
        tmp_path = filepath + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, filepath)
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            print(f"[ERP Engine] 保存状态失败: {e}")

    # ========== 数据获取层 (带TTL缓存+磁盘持久化) ==========

    def _fetch_pe_ttm_history(self, years: int = 5) -> pd.DataFrame:
        """获取沪深300近N年PE-TTM日频数据"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_pe_ttm.parquet")
            existing = None
            last_date_str = None
            if os.path.exists(cache_file):
                existing = pd.read_parquet(cache_file)
                existing['trade_date'] = pd.to_datetime(existing['trade_date'])
                last_date_str = existing['trade_date'].max().strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
            if last_date_str and last_date_str >= end_date:
                return existing.sort_values('trade_date').reset_index(drop=True)
            start_date = last_date_str if last_date_str else (datetime.now() - timedelta(days=years * 365)).strftime("%Y%m%d")
            @retry_with_backoff(max_retries=3, base_delay=1.0)
            def _call_pro():
                return pro.index_dailybasic(
                    ts_code=self.INDEX_CODE, start_date=start_date, end_date=end_date,
                    fields="ts_code,trade_date,pe,pe_ttm,pb,turnover_rate"
                )
            df = _call_pro()
            if df is not None and not df.empty:
                df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
                if existing is not None:
                    df = pd.concat([existing, df]).drop_duplicates(subset='trade_date', keep='last')
                df = df.sort_values('trade_date').reset_index(drop=True)
                atomic_write_parquet(df, cache_file)
                print(f"[ERP] PE-TTM cached: {len(df)} rows")
            elif existing is not None:
                df = existing
            else:
                raise ValueError("PE-TTM 数据为空")
            return df.sort_values('trade_date').reset_index(drop=True)
        return _cached("pe_ttm_history", 30 * 60, _fetch)  # 30分钟TTL: 盘中实时刷新

    def _fetch_yield_10y_history(self, years: int = 5) -> pd.DataFrame:
        """获取10Y国债收益率 (磁盘缓存+增量更新, 分批拉取)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_yield_10y.parquet")
            existing = None
            last_date = None
            if os.path.exists(cache_file):
                existing = pd.read_parquet(cache_file)
                existing['trade_date'] = pd.to_datetime(existing['trade_date'])
                last_date = existing['trade_date'].max()
                if last_date.strftime("%Y%m%d") >= datetime.now().strftime("%Y%m%d"):
                    return existing.sort_values('trade_date').reset_index(drop=True)
            end_dt = datetime.now()
            start_dt = (last_date - timedelta(days=1)) if last_date else (end_dt - timedelta(days=years * 365))
            all_dfs = []
            chunk_start = start_dt
            batch_count = 0
            while chunk_start < end_dt:
                chunk_end = min(chunk_start + timedelta(days=180), end_dt)
                s_str, e_str = chunk_start.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")
                @retry_with_backoff(max_retries=3, base_delay=2.0)
                def _call_pro_yc():
                    return pro.yc_cb(ts_code=self.BOND_CODE, curve_type='0', start_date=s_str, end_date=e_str)

                try:
                    chunk = _call_pro_yc()
                    if chunk is not None and not chunk.empty:
                        chunk_10y = chunk[chunk['curve_term'] == 10.0].copy()
                        if not chunk_10y.empty:
                            all_dfs.append(chunk_10y)
                            batch_count += 1
                except Exception as e:
                    print(f"[ERP] yield batch {s_str}-{e_str}: {e}")
                chunk_start = chunk_end + timedelta(days=1)
                time.sleep(1.0)  # Rate limit safety
            if all_dfs:
                new_df = pd.concat(all_dfs, ignore_index=True)
                new_df['trade_date'] = pd.to_datetime(new_df['trade_date'], format='%Y%m%d')
                new_df = new_df.rename(columns={'yield': 'yield_10y'})
                new_df = new_df[['trade_date', 'yield_10y']]
                df = pd.concat([existing, new_df]).drop_duplicates(subset='trade_date', keep='last') if existing is not None else new_df
                df = df.sort_values('trade_date').reset_index(drop=True)
                atomic_write_parquet(df, cache_file)
                print(f"[ERP] 10Y yield cached: {len(df)} rows ({batch_count} batches)")
            elif existing is not None:
                df = existing
            else:
                raise ValueError("国债收益率数据全部拉取失败")
            return df.sort_values('trade_date').reset_index(drop=True)
        return _cached("yield_10y_history", 30 * 60, _fetch)  # 30分钟TTL: 盘中实时刷新

    def _fetch_m1_history(self, months: int = 36) -> pd.DataFrame:
        """获取M1/M2同比近N月数据"""
        def _fetch():
            end_m = datetime.now().strftime("%Y%m")
            start_m = (datetime.now() - timedelta(days=months * 31)).strftime("%Y%m")
            @retry_with_backoff(max_retries=3, base_delay=1.5)
            def _call_pro_cn():
                return pro.cn_m(start_m=start_m, end_m=end_m, fields="month,m1,m1_yoy,m2,m2_yoy")
            
            df = _call_pro_cn()
            if df is None or df.empty:
                raise ValueError("M1 数据为空")
            return df.sort_values('month').reset_index(drop=True)
        return _cached("m1_history", 6 * 3600, _fetch)  # 6小时TTL: 月频数据无需太频繁

    # ========== 核心计算层 ==========

    def _compute_erp_series(self) -> pd.DataFrame:
        """计算5年ERP时间序列"""
        pe_df = self._fetch_pe_ttm_history()
        yield_df = self._fetch_yield_10y_history()
        merged = pd.merge(pe_df, yield_df, on='trade_date', how='left')
        merged = merged.sort_values('trade_date')
        merged['yield_10y'] = merged['yield_10y'].ffill().bfill()
        merged = merged.dropna(subset=['pe_ttm', 'yield_10y'])
        merged = merged[merged['pe_ttm'] > 0].copy()
        merged['earnings_yield'] = 1.0 / merged['pe_ttm'] * 100
        merged['erp'] = merged['earnings_yield'] - merged['yield_10y']
        # D4用: PE滚动60日标准差
        merged['pe_vol_60d'] = merged['pe_ttm'].rolling(60, min_periods=20).std()
        return merged.sort_values('trade_date').reset_index(drop=True)

    # ========== 五维评分 ==========

    def _score_d1_erp_absolute(self, erp_val: float) -> tuple:
        """D1: ERP绝对值 → 0-100"""
        if erp_val >= 6.0:
            score, desc = 100, f"ERP {erp_val:.2f}% ≥ 6% → 极度低估，历史级加仓机会"
        elif erp_val >= 5.0:
            score, desc = 70 + (erp_val - 5.0) * 30, f"ERP {erp_val:.2f}% 处于5-6%区间 → 偏低估"
        elif erp_val >= 4.0:
            score, desc = 50 + (erp_val - 4.0) * 20, f"ERP {erp_val:.2f}% 处于4-5%区间 → 估值中性偏低"
        elif erp_val >= 3.0:
            score, desc = 25 + (erp_val - 3.0) * 25, f"ERP {erp_val:.2f}% 处于3-4%区间 → 估值中性偏高"
        elif erp_val >= 2.0:
            score, desc = (erp_val - 2.0) * 25, f"ERP {erp_val:.2f}% 处于2-3%区间 → 偏高估"
        else:
            score, desc = 0, f"ERP {erp_val:.2f}% < 2% → 极度高估，警惕泡沫"
        return round(score, 1), desc

    def _score_d2_erp_percentile(self, erp_val: float, erp_series: pd.Series) -> tuple:
        """D2: ERP历史分位 → 0-100 (V2.1: 窗口对齐回测参数1008日)"""
        window = erp_series.tail(1008)  # 对齐回测优化参数: ~4年
        pct = (window < erp_val).mean() * 100
        if pct >= 80:   desc = f"近4年{pct:.1f}%分位 → 历史极度低估区间"
        elif pct >= 60: desc = f"近4年{pct:.1f}%分位 → 偏低估区间"
        elif pct >= 40: desc = f"近4年{pct:.1f}%分位 → 估值中性"
        elif pct >= 20: desc = f"近4年{pct:.1f}%分位 → 偏高估区间"
        else:           desc = f"近4年{pct:.1f}%分位 → 历史极度高估区间"
        return round(pct, 1), round(pct, 1), desc

    def _score_d3_m1_trend(self) -> tuple:
        """D3: M1同比趋势 → 0-100"""
        m1_df = self._fetch_m1_history()
        if m1_df.empty:
            return 50.0, {"current": 0, "prev_month": 0, "3m_ago": 0, "m2_yoy": 0, "direction": "unknown", "3m_direction": "unknown", "scissor": 0}, "M1数据缺失"

        latest = m1_df.iloc[-1]
        prev = m1_df.iloc[-2] if len(m1_df) >= 2 else latest
        prev3 = m1_df.iloc[-4] if len(m1_df) >= 4 else latest

        m1_now = float(latest['m1_yoy'])
        m1_prev = float(prev['m1_yoy'])
        m1_3m = float(prev3['m1_yoy'])
        m2_now = float(latest['m2_yoy'])

        is_rising = m1_now > m1_prev
        is_3m_rising = m1_now > m1_3m
        is_positive = m1_now > 0

        m1_info = {
            "current": round(m1_now, 1), "prev_month": round(m1_prev, 1),
            "3m_ago": round(m1_3m, 1), "m2_yoy": round(m2_now, 1),
            "direction": "rising" if is_rising else "falling",
            "3m_direction": "rising" if is_3m_rising else "falling",
            "scissor": round(m1_now - m2_now, 1),  # M1-M2剪刀差
            "data_month": str(latest['month']),     # M1 fix: 数据所属月份 (如 '202603')
        }

        if is_positive and is_3m_rising:
            score = 80 + min(20, m1_now * 2)
            desc = f"M1同比{m1_now:.1f}% 正增长且3月趋势↑ → 流动性扩张"
        elif is_positive and is_rising:
            score = 60 + min(20, m1_now * 2)
            desc = f"M1同比{m1_now:.1f}% 正增长，环比回升 → 流动性改善"
        elif is_positive:
            score = 40 + min(20, m1_now * 2)
            desc = f"M1同比{m1_now:.1f}% 正增长但趋势↓ → 流动性收敛"
        elif is_rising:
            score = 30
            desc = f"M1同比{m1_now:.1f}% 负增长但拐头 → 底部信号"
        else:
            score = max(0, 20 + m1_now * 2)
            desc = f"M1同比{m1_now:.1f}% 负增长且下行 → 流动性收紧"

        return round(min(100, max(0, score)), 1), m1_info, desc

    def _score_d4_volatility(self, erp_df: pd.DataFrame) -> tuple:
        """D4: 波动率指标 → 0-100 (逆向: 高波给低分但标记机会)"""
        pe_vol = erp_df['pe_vol_60d'].dropna()
        if pe_vol.empty:
            return 50.0, {"current": 0, "pct": 50, "regime": "normal"}, "波动率数据不足"

        current_vol = float(pe_vol.iloc[-1])
        vol_pct = (pe_vol < current_vol).mean() * 100  # 百分位

        if vol_pct >= 90:
            score = 15  # 极高波动→低分但标记为逆向机会
            regime = "extreme_panic"
            desc = f"PE波动率{current_vol:.2f}({vol_pct:.0f}%分位) → 极端恐慌，逆向加仓窗口"
        elif vol_pct >= 70:
            score = 35
            regime = "high"
            desc = f"PE波动率{current_vol:.2f}({vol_pct:.0f}%分位) → 市场波动加大，关注风险"
        elif vol_pct >= 30:
            score = 70
            regime = "normal"
            desc = f"PE波动率{current_vol:.2f}({vol_pct:.0f}%分位) → 波动正常"
        else:
            score = 90
            regime = "calm"
            desc = f"PE波动率{current_vol:.2f}({vol_pct:.0f}%分位) → 市场平静，适合配置"

        vol_info = {"current": round(current_vol, 2), "pct": round(vol_pct, 1), "regime": regime}
        return round(score, 1), vol_info, desc

    def _score_d5_credit(self, m1_info: dict) -> tuple:
        """D5: 信用环境 (M1-M2剪刀差) → 0-100"""
        scissor = m1_info.get("scissor", 0)
        m1_dir = m1_info.get("3m_direction", "unknown")

        if scissor >= 0:
            score = 85 + min(15, scissor * 3)
            desc = f"M1-M2剪刀差 {scissor:+.1f}% → 资金活化，信用环境极佳"
        elif scissor >= -3:
            score = 55 + (scissor + 3) * 10
            desc = f"M1-M2剪刀差 {scissor:+.1f}% → 信用环境中性"
        elif scissor >= -6:
            score = 25 + (scissor + 6) * 10
            desc = f"M1-M2剪刀差 {scissor:+.1f}% → 资金沉淀，信用偏弱"
        else:
            score = max(0, 10 + scissor)
            desc = f"M1-M2剪刀差 {scissor:+.1f}% → 信用冻结，防御为主"

        # 趋势加分
        if m1_dir == "rising" and scissor < 0:
            score = min(100, score + 10)
            desc += "（剪刀差收窄中，边际改善）"

        credit_info = {"scissor": scissor, "trend": m1_dir}
        return round(min(100, max(0, score)), 1), credit_info, desc


    # ========== 买卖规则引擎 (逆向型) ==========

    # O7: ERP动量修正
    def _erp_momentum_modifier(self, erp_series) -> tuple:
        if len(erp_series) < 63:
            return 0, "数据不足"
        current = float(erp_series.iloc[-1])
        past = float(erp_series.iloc[-63])
        if abs(past) < 0.01:
            return 0, "基准值过小"
        momentum_pct = (current - past) / abs(past) * 100
        if momentum_pct > 10:
            return 5, f"ERP 3月动量+{momentum_pct:.0f}% → 价值回归(+5)"
        elif momentum_pct < -10:
            return -5, f"ERP 3月动量{momentum_pct:.0f}% → 估值恶化(-5)"
        return 0, f"ERP 3月动量{momentum_pct:+.0f}% → 中性"

    # O8: EMA平滑
    _prev_smooth_score = None

    def _smooth_composite(self, raw_score: float) -> float:
        if self._prev_smooth_score is None:
            self._prev_smooth_score = raw_score
            return raw_score
        alpha = 0.3
        smooth = alpha * raw_score + (1 - alpha) * self._prev_smooth_score
        self._prev_smooth_score = smooth
        return round(smooth, 1)

    def _generate_trade_rules(self, score: float, dims: dict, snap: dict) -> dict:
        """生成买卖信号 + 止盈止损规则 (逆向加仓型)"""
        erp = snap.get("erp_value", 0)
        pct = snap.get("erp_percentile", 50)
        m1_val = dims.get("m1_trend", {}).get("m1_info", {}).get("current", 0)
        vol_regime = dims.get("volatility", {}).get("vol_info", {}).get("regime", "normal")

        # === 信号判定 ===
        # 三维共振检测
        d1s = dims.get("erp_abs", {}).get("score", 50)
        d2s = dims.get("erp_pct", {}).get("score", 50)
        d3s = dims.get("m1_trend", {}).get("score", 50)

        bullish_count = sum([d1s >= 60, d2s >= 60, d3s >= 60])
        bearish_count = sum([d1s < 35, d2s < 35, d3s < 35])

        resonance = "none"
        if bullish_count >= 3:
            resonance = "bullish_resonance"  # 三维共振看多
        elif bearish_count >= 3:
            resonance = "bearish_resonance"  # 三维共振看空
        elif bullish_count >= 1 and bearish_count >= 1:
            resonance = "divergence"  # 信号分歧

        # === 信号分级 ===
        if score >= 80 and resonance == "bullish_resonance":
            signal_key = "strong_buy"
        elif score >= 70:
            signal_key = "buy"
        elif score >= 55:
            signal_key = "hold"
        elif score >= 40:
            signal_key = "reduce"
        elif score >= 25:
            signal_key = "underweight"
        else:
            signal_key = "cash"

        # 逆向修正: 极端恐慌时提升信号
        if vol_regime == "extreme_panic" and erp >= 5.0:
            if signal_key in ("hold", "reduce"):
                signal_key = "buy"  # 恐慌+低估 → 逆向升级为买入

        signal = self.SIGNAL_MAP[signal_key]

        # === ETF配置建议 ===
        if signal_key in ("strong_buy", "buy"):
            etf_advice = [
                {"etf": self.ETF_TARGETS["balanced"], "ratio": "50%", "reason": "核心配置"},
                {"etf": self.ETF_TARGETS["aggressive"], "ratio": "30%", "reason": "弹性进攻"},
                {"etf": self.ETF_TARGETS["defensive"], "ratio": "20%", "reason": "安全垫"},
            ]
        elif signal_key == "hold":
            etf_advice = [
                {"etf": self.ETF_TARGETS["balanced"], "ratio": "40%", "reason": "核心底仓"},
                {"etf": self.ETF_TARGETS["defensive"], "ratio": "40%", "reason": "防御为主"},
                {"etf": self.ETF_TARGETS["aggressive"], "ratio": "20%", "reason": "保留弹性"},
            ]
        else:
            etf_advice = [
                {"etf": self.ETF_TARGETS["defensive"], "ratio": "60%", "reason": "防御优先"},
                {"etf": self.ETF_TARGETS["balanced"], "ratio": "30%", "reason": "保留底仓"},
                {"etf": self.ETF_TARGETS["aggressive"], "ratio": "10%", "reason": "观察仓"},
            ]

        # === 止盈规则 (逆向型: 不轻易止损，高位才止盈) ===
        # V2.2: 动态触发标注 — 移除 gate 条件，让 triggered 可真正触发
        take_profit = [
            {
                "trigger": "ERP 回落至 4.0% 以下", "action": "减仓20%权益", "type": "valuation",
                "triggered": bool(erp < 4.0), "current": f"ERP={erp:.2f}%"
            },
            {
                "trigger": "分位跌破 30%", "action": "降至标配仓位", "type": "percentile",
                "triggered": bool(pct < 30), "current": f"分位={pct:.1f}%"
            },
            {
                "trigger": "综合得分从 ≥75 跌破 55", "action": "一次性降至50%", "type": "score_drop",
                "triggered": bool(self._score_high_water >= 75 and score < 55),
                "current": f"Score={score:.1f} (HW={self._score_high_water:.0f})"
            },
        ]
        m1_falling_3m = dims.get("m1_trend", {}).get("m1_info", {}).get("3m_direction") == "falling"
        take_profit.append({
            "trigger": "M1连续3月下滑且转负", "action": "减仓30%", "type": "liquidity",
            "triggered": bool(m1_val < 0 and m1_falling_3m), "current": f"M1={m1_val:.1f}%"
        })

        # === 止损规则 (逆向加仓型) ===
        # O6: Score跌幅改为3天滚动窗口 (替代仅当天比较, 使止损可实际触发)
        recent_scores = [h["score"] for h in self._score_history[-3:] if isinstance(h, dict)]
        if recent_scores:
            rolling_high = max(recent_scores)
            score_delta = round(score - rolling_high, 1)
        else:
            score_delta = 0.0  # 无历史数据
        score_drop_triggered = score_delta < -15
        stop_loss = [
            {
                "trigger": "ERP ≥ 7% (极端低估)", "action": "逆向加仓10-20%，分批买入",
                "type": "contrarian_buy", "color": "#10b981",
                "triggered": bool(erp >= 7.0), "current": f"ERP={erp:.2f}%"
            },
            {
                "trigger": "Score 3日跌幅 > 15分", "action": "不止损，观察1周后再决策",
                "type": "wait", "color": "#3b82f6",
                "triggered": bool(score_drop_triggered), "current": f"Score={score:.1f} (3d Δ{score_delta:+.1f})"
            },
            {
                "trigger": "ERP < 2.5% (极端高估)", "action": "唯一硬止损：清仓权益",
                "type": "hard_stop", "color": "#ef4444",
                "triggered": bool(erp < 2.5), "current": f"ERP={erp:.2f}%"
            },
            {
                "trigger": "M1同比 < -5% (流动性危机)", "action": "降仓至20%以下",
                "type": "liquidity_crisis", "color": "#ef4444",
                "triggered": bool(m1_val < -5), "current": f"M1={m1_val:.1f}%"
            },
        ]

        return {
            "signal_key": signal_key,
            "signal": signal,
            "resonance": resonance,
            "resonance_label": {"bullish_resonance": "🟢 三维共振看多", "bearish_resonance": "🔴 三维共振看空",
                                "divergence": "🟡 信号分歧", "none": "⚪ 中性"}[resonance],
            "etf_advice": etf_advice,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
        }

    # ========== 警示系统 ==========

    def _generate_alerts(self, score: float, erp: float, pct: float, m1_info: dict, vol_info: dict) -> list:
        """生成4级警示"""
        alerts = []
        m1_val = m1_info.get("current", 0)
        vol_regime = vol_info.get("regime", "normal")

        # 🔴 危险
        if erp < 3.0:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"ERP仅{erp:.2f}%，股票相对债券无吸引力", "pulse": True})
        if m1_val < -3:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"M1同比{m1_val:.1f}%深度负增长，流动性危机", "pulse": True})
        if score < 30:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"综合得分仅{score}，市场环境极度不利", "pulse": True})

        # 🟡 注意
        if 3.0 <= erp < 4.0:
            alerts.append({"level": "warning", "icon": "🟡", "text": f"ERP {erp:.2f}%偏低，关注估值风险"})
        if pct < 25:
            alerts.append({"level": "warning", "icon": "🟡", "text": f"ERP分位仅{pct:.1f}%，历史高估区间"})
        if m1_info.get("3m_direction") == "falling" and m1_val > 0:
            alerts.append({"level": "warning", "icon": "🟡", "text": "M1虽为正增长但趋势下滑，动能减弱"})

        # 🟢 机会
        if erp >= 6.0:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": f"ERP {erp:.2f}% ≥ 6%，极度低估！黄金窗口", "pulse": True})
        if pct >= 80:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": f"分位{pct:.1f}% → 历史级低估区间"})
        if score >= 80:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": f"综合得分{score}，三维共振看多"})
        if vol_regime == "extreme_panic" and erp >= 5.0:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": "恐慌+低估 → 逆向投资者的黄金组合", "pulse": True})

        return alerts if alerts else [{"level": "normal", "icon": "⚪", "text": "当前无特殊警示，市场环境中性"}]

    # ========== 信号融合 ==========

    def compute_signal(self) -> dict:
        """五维信号融合 → 综合得分 + 买卖信号"""
        try:
            erp_df = self._compute_erp_series()
            if erp_df.empty:
                return self._fallback_signal("ERP序列计算失败")

            latest = erp_df.iloc[-1]
            erp_val = float(latest['erp'])
            pe_ttm = float(latest['pe_ttm'])
            yield_10y = float(latest['yield_10y'])

            # 五维评分
            d1_score, d1_desc = self._score_d1_erp_absolute(erp_val)
            d2_score, d2_pct, d2_desc = self._score_d2_erp_percentile(erp_val, erp_df['erp'])
            d3_score, m1_info, d3_desc = self._score_d3_m1_trend()
            d4_score, vol_info, d4_desc = self._score_d4_volatility(erp_df)
            d5_score, credit_info, d5_desc = self._score_d5_credit(m1_info)

            # O10: 权重自适应
            vol_regime = vol_info.get("regime", "normal")
            aw = adaptive_weights(self.W, "volatility", vol_regime)

            # 加权融合
            composite = round(
                d1_score * aw["erp_abs"] + d2_score * aw["erp_pct"] +
                d3_score * aw["m1_trend"] + d4_score * aw["volatility"] +
                d5_score * aw["credit"], 1
            )

            # O7: ERP动量修正
            momentum_mod, momentum_desc = self._erp_momentum_modifier(erp_df['erp'])
            composite = round(min(100, max(0, composite + momentum_mod)), 1)

            # O11: 多时间框架确认
            mtf = multi_timeframe_confirmation(erp_df['erp'], composite)
            composite = round(min(100, max(0, composite + mtf["confidence_mod"])), 1)

            # O8: EMA平滑
            composite = self._smooth_composite(composite)

            snap = {
                "pe_ttm": round(pe_ttm, 2), "yield_10y": round(yield_10y, 4),
                "earnings_yield": round(1.0 / pe_ttm * 100, 2), "erp_value": round(erp_val, 2),
                "erp_percentile": round(d2_pct, 1), "trade_date": latest['trade_date'].strftime('%Y-%m-%d')
            }

            dims = {
                "erp_abs":    {"score": d1_score, "weight": self.W["erp_abs"], "label": "ERP绝对值", "desc": d1_desc},
                "erp_pct":    {"score": d2_score, "weight": self.W["erp_pct"], "label": "ERP历史分位", "desc": d2_desc, "percentile": d2_pct},
                "m1_trend":   {"score": d3_score, "weight": self.W["m1_trend"], "label": "M1流动性", "desc": d3_desc, "m1_info": m1_info},
                "volatility": {"score": d4_score, "weight": self.W["volatility"], "label": "波动率", "desc": d4_desc, "vol_info": vol_info},
                "credit":     {"score": d5_score, "weight": self.W["credit"], "label": "信用环境", "desc": d5_desc, "credit_info": credit_info},
                "erp_momentum": {"score": momentum_mod, "weight": 0, "label": "ERP动量", "desc": momentum_desc},
            }

            # 买卖规则
            trade = self._generate_trade_rules(composite, dims, snap)
            # C1+C2 fix: 更新 Score 追踪状态
            self._prev_score = composite
            self._prev_score_date = str(datetime.now().date())
            self._score_high_water = max(self._score_high_water, composite)
            # O6: 追加到Score历史 (每天仅记录一次)
            today_str = str(datetime.now().date())
            if not self._score_history or self._score_history[-1].get("date") != today_str:
                self._score_history.append({"date": today_str, "score": composite})
            else:
                self._score_history[-1]["score"] = composite  # 同天覆盖
            self._score_history = self._score_history[-5:]  # 只保留最近5天
            self._save_history()

            # 警示
            alerts = self._generate_alerts(composite, erp_val, d2_pct, m1_info, vol_info)

            # 诊断
            diagnosis = self._build_diagnosis(erp_val, pe_ttm, yield_10y, d2_pct, m1_info, vol_info, credit_info, trade)

            return {
                "status": "success",
                "adaptive_weights": aw,  # O10
                "multi_timeframe": mtf,  # O11
                "current_snapshot": snap,
                "signal": {
                    "score": composite, "key": trade["signal_key"],
                    "label": trade["signal"]["label"], "position": trade["signal"]["position"],
                    "color": trade["signal"]["color"], "emoji": trade["signal"]["emoji"],
                },
                "dimensions": dims,
                "trade_rules": trade,
                "alerts": alerts,
                "diagnosis": diagnosis,
                "encyclopedia": ENCYCLOPEDIA,
            }

        except Exception as e:
            print(f"[ERP Engine V2] compute_signal 异常: {e}")
            import traceback; traceback.print_exc()
            return self._fallback_signal(str(e))

    def _build_diagnosis(self, erp, pe, y10, pct, m1, vol, credit, trade) -> list:
        """构建诊断卡片 (6张)"""
        cards = []
        m1_val = m1.get("current", 0)
        vol_regime = vol.get("regime", "normal")
        scissor = credit.get("scissor", 0)
        signal = trade["signal"]

        # 1 — 估值
        if erp >= 5.0:
            cards.append({"type": "success", "title": "估值信号 · 低估",
                          "text": f"沪深300 PE-TTM {pe:.1f}倍，盈利收益率{1/pe*100:.1f}%远超10Y国债{y10:.2f}%，ERP={erp:.2f}%。股票配置价值显著。"})
        elif erp >= 3.5:
            cards.append({"type": "info", "title": "估值信号 · 中性",
                          "text": f"PE-TTM {pe:.1f}倍，ERP={erp:.2f}% 处于合理区间。"})
        else:
            cards.append({"type": "danger", "title": "估值信号 · 高估",
                          "text": f"PE-TTM {pe:.1f}倍推高，ERP仅{erp:.2f}%，股票相对债券吸引力不足。"})

        # 2 — 分位
        if pct >= 70:
            cards.append({"type": "success", "title": "历史分位 · 便宜", "text": f"ERP处于近4年{pct:.0f}%分位，历史上{100-pct:.0f}%的时间比现在更贵。赔率极佳。"})
        elif pct >= 40:
            cards.append({"type": "info", "title": "历史分位 · 中性", "text": f"ERP近4年{pct:.0f}%分位，处于中间位置。"})
        else:
            cards.append({"type": "warning", "title": "历史分位 · 昂贵", "text": f"ERP近4年仅{pct:.0f}%分位，历史大部分时间比现在便宜。"})

        # 3 — 流动性
        if m1_val > 0 and m1.get("3m_direction") == "rising":
            cards.append({"type": "success", "title": "流动性 · 宽松", "text": f"M1同比{m1_val:.1f}%（3月趋势↑），M2同比{m1.get('m2_yoy',0):.1f}%。货币环境友好。"})
        elif m1_val > 0:
            cards.append({"type": "info", "title": "流动性 · 中性", "text": f"M1同比{m1_val:.1f}%仍为正增长但动能减弱。"})
        else:
            cards.append({"type": "warning", "title": "流动性 · 收紧", "text": f"M1同比{m1_val:.1f}%转负，实体资金萎缩。"})

        # 4 — 波动率
        if vol_regime == "extreme_panic":
            cards.append({"type": "warning", "title": "波动率 · 恐慌", "text": f"市场波动率处于极端高位。逆向策略：恐慌+低估=加仓机会。"})
        elif vol_regime == "high":
            cards.append({"type": "info", "title": "波动率 · 偏高", "text": "市场波动加大，建议分批操作降低择时风险。"})
        else:
            cards.append({"type": "success", "title": "波动率 · 正常", "text": "市场波动平稳，适合执行仓位调整。"})

        # 5 — 信用环境
        if scissor >= -2:
            cards.append({"type": "success", "title": "信用 · 活化", "text": f"M1-M2剪刀差{scissor:+.1f}%，资金从定期转向活期，实体经济回暖。"})
        else:
            cards.append({"type": "warning", "title": "信用 · 沉淀", "text": f"M1-M2剪刀差{scissor:+.1f}%，储蓄意愿强，消费投资低迷。"})

        # 6 — 综合操作 + ETF建议
        etf_text = " / ".join([f"{e['etf']['name']}{e['ratio']}" for e in trade.get("etf_advice", [])])
        cards.append({"type": "info", "title": f"操作建议 · {signal['label']}",
                       "text": f"{trade['resonance_label']}。建议仓位{signal['position']}。配置方案: {etf_text}。"})
        return cards

    def _fallback_signal(self, reason: str) -> dict:
        """降级输出"""
        return {
            "status": "fallback", "message": f"数据异常: {reason}",
            "current_snapshot": {"pe_ttm": 12.5, "yield_10y": 1.80, "earnings_yield": 8.0, "erp_value": 6.2, "erp_percentile": 70.0, "trade_date": datetime.now().strftime('%Y-%m-%d')},
            "signal": {"score": 70, "key": "hold", "label": "标配(降级)", "position": "50-70%", "color": "#f59e0b", "emoji": "🟡"},
            "dimensions": {k: {"score": 50, "weight": v, "label": k, "desc": f"降级估算"} for k, v in self.W.items()},
            "trade_rules": {"signal_key": "hold", "signal": self.SIGNAL_MAP["hold"], "resonance": "none", "resonance_label": "⚪ 降级模式", "etf_advice": [], "take_profit": [], "stop_loss": []},
            "alerts": [{"level": "warning", "icon": "🟡", "text": reason}],
            "diagnosis": [{"type": "warning", "title": "数据降级", "text": reason}],
            "encyclopedia": ENCYCLOPEDIA,
        }

    # ========== 历史序列输出 ==========

    def get_erp_chart_data(self) -> dict:
        """输出ERP历史走势图数据 + 买卖区间 + M1叠加 (V3.0 — 增强统计)"""
        try:
            erp_df = self._compute_erp_series()
            erp_sampled = erp_df.iloc[::3].copy()
            # C3 fix: 确保采样后最后一行始终是原始序列的最新日期
            if len(erp_df) > 0 and (len(erp_sampled) == 0 or erp_sampled.index[-1] != erp_df.index[-1]):
                erp_sampled = pd.concat([erp_sampled, erp_df.iloc[[-1]]]).drop_duplicates(subset='trade_date', keep='last')

            dates = erp_sampled['trade_date'].dt.strftime('%Y-%m-%d').tolist()
            erp_vals = erp_sampled['erp'].round(2).tolist()
            pe_vals = erp_sampled['pe_ttm'].round(2).tolist()
            yield_vals = erp_sampled['yield_10y'].round(2).tolist()

            # V2.1: M1 同比叠加 (月频→日频, forward-fill)
            m1_vals = [None] * len(dates)  # 默认空值
            try:
                m1_df = self._fetch_m1_history(months=60)
                if not m1_df.empty:
                    m1_df['month_date'] = pd.to_datetime(m1_df['month'], format='%Y%m') + pd.offsets.MonthEnd(0)
                    m1_map = dict(zip(m1_df['month_date'].dt.strftime('%Y-%m'), m1_df['m1_yoy'].round(1)))
                    m1_vals = []
                    for d in dates:
                        ym = d[:7]  # 'YYYY-MM'
                        m1_vals.append(m1_map.get(ym, None))
                    # Forward-fill None gaps
                    last_v = None
                    for i in range(len(m1_vals)):
                        if m1_vals[i] is not None:
                            last_v = m1_vals[i]
                        else:
                            m1_vals[i] = last_v
            except Exception as e:
                print(f"[ERP Chart] M1 overlay failed: {e}")

            erp_mean = float(erp_df['erp'].mean())
            erp_std = float(erp_df['erp'].std())
            erp_current = float(erp_df['erp'].iloc[-1])
            overweight = round(erp_mean + 0.5 * erp_std, 2)
            underweight = round(erp_mean - 0.5 * erp_std, 2)
            strong_buy = round(erp_mean + 1.0 * erp_std, 2)
            danger = round(erp_mean - 1.0 * erp_std, 2)

            # V3.0: 增强统计 — 区间停留比例 + 偏离度 + 极值点 + 年跨度
            total_pts = len(erp_vals)
            buy_count = sum(1 for v in erp_vals if v >= overweight)
            sell_count = sum(1 for v in erp_vals if v <= underweight)
            current_vs_mean = round((erp_current - erp_mean) / erp_mean * 100, 1) if erp_mean else 0

            # 日期跨度 (年)
            date_range_years = round((erp_df['trade_date'].iloc[-1] - erp_df['trade_date'].iloc[0]).days / 365.25, 1)

            # 极值点 (用于 markPoint)
            erp_max_val = float(erp_df['erp'].max())
            erp_min_val = float(erp_df['erp'].min())
            max_row = erp_df.loc[erp_df['erp'].idxmax()]
            min_row = erp_df.loc[erp_df['erp'].idxmin()]
            extremes = [
                {"date": max_row['trade_date'].strftime('%Y-%m-%d'), "value": round(erp_max_val, 2), "type": "max"},
                {"date": min_row['trade_date'].strftime('%Y-%m-%d'), "value": round(erp_min_val, 2), "type": "min"},
            ]

            return {
                "status": "success", "dates": dates,
                "erp": erp_vals, "pe_ttm": pe_vals, "yield_10y": yield_vals,
                "m1_yoy": m1_vals,
                "stats": {
                    "mean": round(erp_mean, 2), "std": round(erp_std, 2),
                    "overweight_line": overweight, "underweight_line": underweight,
                    "strong_buy_line": strong_buy, "danger_line": danger,
                    "max": round(erp_max_val, 2), "min": round(erp_min_val, 2),
                    "current": round(erp_current, 2),
                    # V3.0 新增
                    "current_vs_mean": current_vs_mean,
                    "buy_zone_pct": round(buy_count / total_pts * 100, 1) if total_pts else 0,
                    "sell_zone_pct": round(sell_count / total_pts * 100, 1) if total_pts else 0,
                    "date_range_years": date_range_years,
                    "extremes": extremes,
                }
            }
        except Exception as e:
            print(f"[ERP Engine] chart error: {e}")
            return {"status": "error", "message": str(e)}

    def generate_report(self) -> dict:
        """生成完整策略报告"""
        signal_data = self.compute_signal()
        chart_data = self.get_erp_chart_data()
        return {**signal_data, "chart": chart_data, "engine_version": self.VERSION, "index": self.INDEX_CODE, "updated_at": datetime.now().isoformat()}


# ===== 引擎单例 =====
_engine_instance = None

def get_erp_engine() -> ERPTimingEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ERPTimingEngine()
    return _engine_instance


if __name__ == "__main__":
    engine = ERPTimingEngine()
    print("=== ERP Timing Engine V2.0 Self-Test ===")
    report = engine.generate_report()
    if report.get("status") == "success":
        snap = report["current_snapshot"]
        sig = report["signal"]
        trade = report["trade_rules"]
        print("PE-TTM: {} | 10Y: {}% | ERP: {}%".format(snap['pe_ttm'], snap['yield_10y'], snap['erp_value']))
        print("分位: {}% | 综合得分: {} | 信号: {} {} ({})".format(snap['erp_percentile'], sig['score'], sig['emoji'], sig['label'], sig['position']))
        print("共振: {}".format(trade['resonance_label']))
        etf_parts = [e['etf']['name'] + " " + e['ratio'] for e in trade['etf_advice']]
        print("ETF建议: " + " | ".join(etf_parts))
        dim_parts = [k + "=" + str(v['score']) for k, v in report['dimensions'].items()]
        print("维度: " + " | ".join(dim_parts))
        for a in report.get("alerts", []):
            print("  {} {}".format(a['icon'], a['text']))
    else:
        print("降级: " + str(report.get('message')))
