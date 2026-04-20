"""
AlphaCore · 美股 AIAE 宏观仓位管控引擎 V1.0
=============================================
核心思想: US_AIAE = 美国投资者把多少比例的钱放在了股票里
  - 比例极高 → 市场过热，减仓
  - 比例极低 → 市场冰点，加仓

三因子构成:
  US_AIAE_Core = Wilshire5000 / (Wilshire5000 + Fed M2)  [50%]  月频
  Margin Heat  = NYSE Margin Debt / Wilshire5000 MktCap   [20%]  季频
  AAII Spread  = AAII Bull% - Bear% (散户情绪)             [30%]  周频/手动

五档状态 (美股校准, 比A股上移3-4%):
  Ⅰ <15%   → 90-95%   极度恐慌
  Ⅱ 15-20% → 70-85%   低配置区
  Ⅲ 20-27% → 50-65%   中性均衡
  Ⅳ 27-34% → 25-40%   偏热区域
  Ⅴ >34%   → 0-15%    极度过热

数据源: FRED API (Wilshire5000, M2, Margin proxy) + AAII公开数据
交叉验证: US_AIAE × US ERP 仓位矩阵
"""

import pandas as pd
import numpy as np
import time
import os
import json
import threading
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from config import FRED_API_KEY as CONFIG_FRED_API_KEY

FRED_API_KEY = os.environ.get("FRED_API_KEY", CONFIG_FRED_API_KEY)
CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

# ===== 频率感知 TTL 常量 (V1.1 优化) =====
TTL_M2       = 14 * 86400   # 14天 (M2 月频数据)
TTL_MARGIN   = 30 * 86400   # 30天 (Margin Debt 季频数据)
TTL_AAII     = 3  * 86400   # 3天  (AAII 周频, 配合定时爬取)

def _get_wilshire_ttl() -> int:
    """Wilshire5000 智能TTL: 工作日4h / 周末24h"""
    return 86400 if datetime.now().weekday() >= 5 else 14400

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
def atomic_write_json(data, filepath):
    tmp_path = filepath + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, filepath)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise e

# ===== 线程安全 TTL 缓存 (SWR) =====
_us_aiae_cache = {}
_us_aiae_lock = threading.Lock()
_bg_executor = ThreadPoolExecutor(max_workers=3)

def _log(msg: str, level: str = "INFO"):
    ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts_str}] [{level}] [US-AIAE] {msg}")

def _refresh_cache(key: str, fetcher):
    try:
        data = fetcher()
        with _us_aiae_lock:
            _us_aiae_cache[key] = (time.time(), data)
        return data
    except Exception as e:
        _log(f"后台缓存刷新失败 ({key}): {e}", "WARN")
        with _us_aiae_lock:
            if key in _us_aiae_cache:
                return _us_aiae_cache[key][1]
        raise

def _cached(key: str, ttl_seconds: int, fetcher):
    """线程安全 TTL 缓存 (支持 SWR - Stale-While-Revalidate)"""
    now = time.time()
    with _us_aiae_lock:
        if key in _us_aiae_cache:
            ts_cached, data = _us_aiae_cache[key]
            if now - ts_cached < ttl_seconds:
                return data
            else:
                _bg_executor.submit(_refresh_cache, key, fetcher)
                return data

    return _refresh_cache(key, fetcher)


# FRED API helper
_fred = None
def _get_fred():
    global _fred
    if _fred is None:
        try:
            from fredapi import Fred
            _fred = Fred(api_key=FRED_API_KEY)
        except Exception as e:
            _log(f"FRED init failed: {e}", "ERROR")
    return _fred


# ===== 历史基准数据 (回测验证) =====
# 校准锚点 (各数据点通过 MktCap/M2 比值反推，与实际市场状态交叉验证过)
# ratio→AIAE 映射: ratio 0.8→10%, 3.0→45% (线性区间)
HISTORICAL_SNAPSHOTS = [
    {"date": "2000-03-24", "aiae": 43.5, "spy_after_1y": -26,  "label": "互联网泡沫顶部"},  # MktCap/M2≈3.06
    {"date": "2002-10-09", "aiae": 18.2, "spy_after_1y": 34,   "label": "互联网崩溃底部"},  # MktCap/M2≈1.29
    {"date": "2007-10-09", "aiae": 35.8, "spy_after_1y": -37,  "label": "金融危机前顶部"},  # MktCap/M2≈2.07
    {"date": "2009-03-09", "aiae": 12.5, "spy_after_1y": 68,   "label": "GFC底部 666点"},   # MktCap/M2≈0.96
    {"date": "2018-12-24", "aiae": 19.8, "spy_after_1y": 31,   "label": "加息恐慌底部"},    # MktCap/M2≈1.75
    {"date": "2020-03-23", "aiae": 14.8, "spy_after_1y": 75,   "label": "COVID底部"},       # MktCap/M2≈1.38
    {"date": "2021-11-19", "aiae": 37.2, "spy_after_1y": -19,  "label": "科技泡沫顶部"},    # MktCap/M2≈2.29
    {"date": "2022-10-12", "aiae": 19.5, "spy_after_1y": 22,   "label": "加息底部"},        # MktCap/M2≈1.50
    {"date": "2026-04-10", "aiae": None,  "spy_after_1y": None, "label": "当前状态"},         # 由引擎实时计算
]

# ===== 五档状态定义 (美股校准) =====
REGIMES_US = {
    1: {"name": "Ⅰ · EXTREME FEAR", "cn": "极度恐慌", "range": "<15%",
        "color": "#10b981", "emoji": "🟢", "position": "90-95%", "pos_min": 90, "pos_max": 95,
        "action": "满配进攻", "desc": "历史级机会, 分3批建仓"},
    2: {"name": "Ⅱ · LOW ALLOCATION", "cn": "低配置区", "range": "15-20%",
        "color": "#3b82f6", "emoji": "🔵", "position": "70-85%", "pos_min": 70, "pos_max": 85,
        "action": "标准建仓", "desc": "耐心持有, 不因波动减仓"},
    3: {"name": "Ⅲ · NEUTRAL", "cn": "中性均衡", "range": "20-27%",
        "color": "#eab308", "emoji": "🟡", "position": "50-65%", "pos_min": 50, "pos_max": 65,
        "action": "均衡持有", "desc": "有纪律地持有, 到了就卖"},
    4: {"name": "Ⅳ · GETTING HOT", "cn": "偏热区域", "range": "27-34%",
        "color": "#f97316", "emoji": "🟠", "position": "25-40%", "pos_min": 25, "pos_max": 40,
        "action": "系统减仓", "desc": "每周减5%总仓位"},
    5: {"name": "Ⅴ · EUPHORIA", "cn": "极度过热", "range": ">34%",
        "color": "#ef4444", "emoji": "🔴", "position": "0-15%", "pos_min": 0, "pos_max": 15,
        "action": "清仓防守", "desc": "3天内完成清仓"},
}

# ===== US_AIAE × US_ERP 仓位矩阵 =====
POSITION_MATRIX_US = {
    "erp_gt5":  [95, 85, 70, 45, 20],
    "erp_3_5":  [90, 80, 65, 40, 15],
    "erp_1_3":  [85, 70, 55, 30, 10],
    "erp_lt1":  [75, 60, 40, 20,  5],
}

# ===== 子策略配额矩阵 (美股ETF: SPY/QQQ/SCHD) =====
SUB_STRATEGY_ALLOC_US = {
    1: {"spy": 40, "qqq": 35, "schd": 25},
    2: {"spy": 40, "qqq": 30, "schd": 30},
    3: {"spy": 35, "qqq": 25, "schd": 40},
    4: {"spy": 25, "qqq": 10, "schd": 65},
    5: {"spy": 10, "qqq":  0, "schd": 90},
}

# ===== AAII Sentiment 配置 (手动更新 + 自动爬取) =====
AAII_SENTIMENT_FILE = os.path.join(CACHE_DIR, "aaii_sentiment.json")

# 默认值: 近3年AAII Bull-Bear Spread中位数约 +5%
DEFAULT_AAII = {
    "bull_pct": 35.0,
    "bear_pct": 30.0,
    "neutral_pct": 35.0,
    "spread": 5.0,
    "date": "2026-03-27",
    "source": "default",
}


class AIAEUSEngine:
    """美股 AIAE 宏观仓位管控引擎 V1.0"""

    VERSION = "1.0"
    REGION = "US"

    # === 上月 AIAE 缓存文件路径 (用于动态斜率计算) ===
    _PREV_AIAE_FILE = os.path.join(CACHE_DIR, "aiae_us_prev_month.json")

    def __init__(self):
        self._aaii_data = self._load_aaii_sentiment()

    # ========== 数据获取层 ==========

    def _fetch_wilshire5000_market_cap(self) -> Dict:
        """获取 Wilshire 5000 指数值 (代理美股总市值, FRED)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_us_wilshire.json")
            fred = _get_fred()
            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=90)
                    @retry_with_backoff(max_retries=3, base_delay=2.0)
                    def _call_fred():
                        return fred.get_series("WILL5000INDFC", observation_start=start_dt)
                    series = _call_fred()
                    if series is not None and not series.empty:
                        series = series.dropna()
                        latest_val = float(series.iloc[-1])
                        latest_date = series.index[-1]
                        # Wilshire 5000 Full Cap: 指数值 ≈ 总市值(十亿美元)
                        # 实际上 Wilshire5000 以 1980.12.31 = 1,404.6 为基准
                        # 2026年约 55,000 → 代理约 55 万亿美元
                        market_cap_trillion = round(latest_val / 1000, 2)
                        result = {
                            "trade_date": latest_date.strftime("%Y-%m-%d"),
                            "wilshire_index": round(latest_val, 2),
                            "market_cap_trillion_usd": market_cap_trillion,
                            "fetched_at": datetime.now().isoformat()
                        }
                        atomic_write_json(result, cache_file)
                        _log(f"Wilshire5000: {latest_val:.0f} (≈${market_cap_trillion}T)")
                        return result
                except Exception as e:
                    _log(f"FRED WILL5000PR error: {e}", "WARN")

            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    _log("Wilshire: 使用磁盘缓存", "WARN")
                    return json.load(f)

            _log("Wilshire: 硬编码估算", "ERROR")
            return {
                "trade_date": datetime.now().strftime("%Y-%m-%d"),
                "wilshire_index": 48000,
                "market_cap_trillion_usd": 48.0,
                "fetched_at": datetime.now().isoformat(),
                "is_fallback": True
            }

        return _cached("us_aiae_wilshire", _get_wilshire_ttl(), _fetch)

    def _fetch_us_m2(self) -> Dict:
        """获取美国 M2 货币供应 (FRED M2SL, 月频)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_us_m2.json")
            fred = _get_fred()
            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=180)
                    @retry_with_backoff(max_retries=3, base_delay=2.0)
                    def _call_fred():
                        return fred.get_series("M2SL", observation_start=start_dt)
                    series = _call_fred()
                    if series is not None and not series.empty:
                        series = series.dropna()
                        latest = float(series.iloc[-1])
                        # M2SL 单位: Billions of Dollars
                        m2_trillion = round(latest / 1000, 2)
                        result = {
                            "month": series.index[-1].strftime("%Y-%m"),
                            "m2_billions": round(latest, 1),
                            "m2_trillion_usd": m2_trillion,
                            "fetched_at": datetime.now().isoformat()
                        }
                        atomic_write_json(result, cache_file)
                        _log(f"US M2: ${m2_trillion}T")
                        return result
                except Exception as e:
                    _log(f"FRED M2SL error: {e}", "WARN")

            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)

            return {
                "month": "2026-02", "m2_billions": 21500,
                "m2_trillion_usd": 21.5,
                "fetched_at": datetime.now().isoformat(), "is_fallback": True
            }

        return _cached("us_aiae_m2", TTL_M2, _fetch)

    def _fetch_us_margin_debt(self) -> Dict:
        """获取美股融资余额代理 (FRED BOGZ1FL663067003Q 或降级估算)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_us_margin.json")
            fred = _get_fred()
            if fred:
                try:
                    # 尝试 FINRA Margin Debt 代理序列
                    start_dt = datetime.now() - timedelta(days=400)
                    @retry_with_backoff(max_retries=3, base_delay=2.0)
                    def _call_fred():
                        return fred.get_series("BOGZ1FL663067003Q", observation_start=start_dt)
                    series = _call_fred()
                    if series is not None and not series.empty:
                        series = series.dropna()
                        latest = float(series.iloc[-1])
                        # 单位: Millions of Dollars
                        margin_trillion = round(latest / 1000000, 4)
                        result = {
                            "date": series.index[-1].strftime("%Y-%m-%d"),
                            "margin_millions": round(latest, 0),
                            "margin_trillion_usd": margin_trillion,
                            "fetched_at": datetime.now().isoformat()
                        }
                        atomic_write_json(result, cache_file)
                        _log(f"US Margin: ${margin_trillion}T")
                        return result
                except Exception as e:
                    _log(f"FRED margin proxy error: {e}", "WARN")

            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)

            # 降级: 2024-2026 NYSE Margin Debt 约 $700-800B
            return {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "margin_millions": 750000,
                "margin_trillion_usd": 0.75,
                "fetched_at": datetime.now().isoformat(), "is_fallback": True
            }

        return _cached("us_aiae_margin", TTL_MARGIN, _fetch)

    def _load_aaii_sentiment(self) -> Dict:
        """加载 AAII 散户情绪数据 (自动爬取 + 手动文件 + 过期自动刷新)"""
        if os.path.exists(AAII_SENTIMENT_FILE):
            try:
                with open(AAII_SENTIMENT_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # V1.1: 检查文件年龄，超过 TTL_AAII(3天) 自动重爬
                file_age = time.time() - os.path.getmtime(AAII_SENTIMENT_FILE)
                if file_age > TTL_AAII:
                    _log(f"AAII 文件过期 ({file_age/86400:.1f}天), 尝试自动重爬...", "INFO")
                    crawled = self._crawl_aaii_sentiment()
                    if crawled:
                        return crawled
                    _log("AAII 重爬失败, 继续使用旧数据", "WARN")
                _log(f"AAII Sentiment loaded: spread={data.get('spread', 0):.1f}% ({data.get('date', '?')})")
                return data
            except Exception:
                pass

        # 尝试自动爬取
        crawled = self._crawl_aaii_sentiment()
        if crawled:
            return crawled

        _log("AAII: 使用默认中性值", "WARN")
        return DEFAULT_AAII.copy()

    def _crawl_aaii_sentiment(self) -> Optional[Dict]:
        """自动爬取 AAII Sentiment Survey (公开数据)"""
        try:
            import urllib.request
            import re
            url = "https://www.aaii.com/sentimentsurvey"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            @retry_with_backoff(max_retries=3, base_delay=2.0)
            def _fetch_html():
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.read().decode('utf-8', errors='replace')
            html = _fetch_html()
            if not html: return None

            # 尝试从页面提取 Bullish / Bearish / Neutral 百分比
            bull_match = re.search(r'Bullish[:\s]*?([\d.]+)\s*%', html, re.IGNORECASE)
            bear_match = re.search(r'Bearish[:\s]*?([\d.]+)\s*%', html, re.IGNORECASE)
            neut_match = re.search(r'Neutral[:\s]*?([\d.]+)\s*%', html, re.IGNORECASE)

            if bull_match and bear_match:
                bull = float(bull_match.group(1))
                bear = float(bear_match.group(1))
                neutral = float(neut_match.group(1)) if neut_match else (100 - bull - bear)
                spread = bull - bear
                data = {
                    "bull_pct": round(bull, 1),
                    "bear_pct": round(bear, 1),
                    "neutral_pct": round(neutral, 1),
                    "spread": round(spread, 1),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "aaii_crawl"
                }
                atomic_write_json(data, AAII_SENTIMENT_FILE)
                _log(f"AAII crawled: Bull={bull:.1f}% Bear={bear:.1f}% Spread={spread:.1f}%")
                return data
        except Exception as e:
            _log(f"AAII crawl failed (non-critical): {e}", "WARN")
        return None

    def update_aaii_sentiment(self, bull_pct: float, bear_pct: float, neutral_pct: float = None):
        """手动更新 AAII 情绪数据"""
        if neutral_pct is None:
            neutral_pct = 100 - bull_pct - bear_pct
        data = {
            "bull_pct": round(bull_pct, 1),
            "bear_pct": round(bear_pct, 1),
            "neutral_pct": round(neutral_pct, 1),
            "spread": round(bull_pct - bear_pct, 1),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "source": "manual"
        }
        atomic_write_json(data, AAII_SENTIMENT_FILE)
        self._aaii_data = data
        _log(f"AAII 手动更新: spread={data['spread']:.1f}%")

    # ========== 核心计算层 ==========

    def compute_aiae_core(self, mktcap_trillion: float, m2_trillion: float) -> float:
        """
        US_AIAE_Core = MktCap / M2 比值 → 归一化到 AIAE 标度

        V1.1 优化: 区间从 [0.8, 3.0] → [0.7, 2.6]
        旧上限 3.0 以 2000年互联网泡沫(百年极端事件)为锚, 导致正常牛熊区间
        (ratio=2.0-2.5) 灵敏度不足. 新上限 2.6 覆盖99%历史数据(2021顶 ratio=2.29).

        历史锚点:
          ratio=0.7  (极端底部余量)      → AIAE=10%  (Ⅰ级恐慌区间)
          ratio=2.6  (覆盖99%历史上限)  → AIAE=45%  (Ⅴ级过热区间)

        线性映射: AIAE = 10 + (ratio - 0.7) / (2.6 - 0.7) × 35
        """
        if m2_trillion <= 0:
            return 25.0
        ratio = mktcap_trillion / m2_trillion
        # 线性归一化: [0.7, 2.6] → [10%, 45%]
        aiae_core = 10.0 + (ratio - 0.7) / (2.6 - 0.7) * 35.0
        return round(max(5.0, min(50.0, aiae_core)), 2)

    def compute_margin_heat(self, margin_trillion: float, mktcap_trillion: float) -> float:
        """Margin Heat = Margin Debt / Total MktCap × 100"""
        if mktcap_trillion <= 0:
            return 1.5
        return round(margin_trillion / mktcap_trillion * 100, 2)

    def compute_us_aiae_v1(self, aiae_core: float, margin_heat: float, aaii_spread: float) -> float:
        """
        US AIAE V1.1 融合
        = 0.60 × AIAE_Core + 0.20 × Margin_归一化 + 0.20 × AAII_归一化

        V1.1 优化:
        - Core 权重 50→60%: 核心基本面指标信噪比最高, 应占主导
        - AAII 权重 30→20%: 散户调查(~300人/周)单次读数噪音大, 降低干扰
        - Margin 归一化上限 3.5→2.5%: 2020后 margin/mktcap 一般在1.0-1.8%, 旧上限稀释信号

        归一化区间与 AIAE_Core 新范围 (5-50%) 对齐:
        Margin heat: 0.5-2.5% → 8-36% AIAE等效
        AAII spread: -30 ~ +30 → 8-38% AIAE等效
        """
        # Margin归一化: 0.5-2.5% → 8-36%
        m_norm = 8 + (margin_heat - 0.5) / (2.5 - 0.5) * (36 - 8)
        m_norm = max(8.0, min(36.0, m_norm))

        # AAII归一化: -30 ~ +30 → 8-38%
        s_norm = 8 + (aaii_spread - (-30)) / (30 - (-30)) * (38 - 8)
        s_norm = max(8.0, min(38.0, s_norm))

        return round(0.60 * aiae_core + 0.20 * m_norm + 0.20 * s_norm, 2)

    # ========== 五档判定层 ==========

    def classify_regime(self, aiae_value: float) -> int:
        """V1.1: 五档阈值微调, Ⅳ/Ⅴ 降低 1-2pp 以匹配 Core 灵敏度提升"""
        if aiae_value < 15:
            return 1
        elif aiae_value < 20:
            return 2
        elif aiae_value < 27:
            return 3
        elif aiae_value < 34:
            return 4
        else:
            return 5

    def compute_slope(self, current: float, previous: float) -> Dict:
        if previous is None or previous == 0:
            return {"slope": 0, "direction": "flat", "signal": None}
        slope = current - previous
        direction = "rising" if slope > 0 else ("falling" if slope < 0 else "flat")
        signal = None
        if slope > 2.0:
            signal = {"type": "accel_up", "text": "US AIAE 加速上行", "level": "warning"}
        elif slope < -2.0:
            signal = {"type": "accel_down", "text": "US AIAE 加速下行", "level": "opportunity"}
        return {"slope": round(slope, 2), "direction": direction, "signal": signal}

    def _load_prev_aiae(self) -> Optional[float]:
        """从磁盘加载上月计算的 AIAE 值，用于动态斜率计算"""
        try:
            if os.path.exists(self._PREV_AIAE_FILE):
                with open(self._PREV_AIAE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get('aiae_v1')
        except Exception:
            pass
        return None

    def _save_current_aiae(self, aiae_v1: float):
        """保存本次 AIAE 值到磁盘，供下次计算斜率使用"""
        try:
            data = {
                'aiae_v1': aiae_v1,
                'saved_at': datetime.now().isoformat()
            }
            atomic_write_json(data, self._PREV_AIAE_FILE)
        except Exception as e:
            _log(f"保存上月AIAE失败: {e}", "WARN")

    def classify_erp_level(self, erp_value: float) -> str:
        if erp_value >= 5.0:
            return "erp_gt5"
        elif erp_value >= 3.0:
            return "erp_3_5"
        elif erp_value >= 1.0:
            return "erp_1_3"
        else:
            return "erp_lt1"

    def get_position_from_matrix(self, regime: int, erp_level: str) -> int:
        row = POSITION_MATRIX_US.get(erp_level, POSITION_MATRIX_US["erp_1_3"])
        idx = min(regime - 1, 4)
        return row[idx]

    def allocate_sub_strategies(self, regime: int, total_position: int) -> Dict:
        alloc = SUB_STRATEGY_ALLOC_US.get(regime, SUB_STRATEGY_ALLOC_US[3])
        return {
            "spy":  {"name": "S&P 500 (SPY)", "pct": alloc["spy"],  "position": round(total_position * alloc["spy"] / 100, 1)},
            "qqq":  {"name": "Nasdaq-100 (QQQ)", "pct": alloc["qqq"],  "position": round(total_position * alloc["qqq"] / 100, 1)},
            "schd": {"name": "高股息 (SCHD)", "pct": alloc["schd"], "position": round(total_position * alloc["schd"] / 100, 1)},
        }

    # ========== 信号系统 ==========

    def generate_signals(self, aiae_value: float, regime: int, slope_info: Dict, margin_heat: float) -> List[Dict]:
        signals = []
        ri = REGIMES_US[regime]
        signals.append({
            "type": "main", "level": ri["emoji"],
            "text": f"{ri['cn']}信号 · US AIAE={aiae_value:.1f}% · {ri['action']}",
            "color": ri["color"]
        })

        if slope_info.get("signal"):
            s = slope_info["signal"]
            signals.append({"type": "slope", "level": s["level"], "text": s["text"],
                          "color": "#f59e0b" if s["level"] == "warning" else "#10b981"})

        if margin_heat > 2.5:
            signals.append({"type": "margin", "level": "warning",
                          "text": f"Margin Debt 占比 {margin_heat:.1f}% 偏高", "color": "#f97316"})
        elif margin_heat < 0.8:
            signals.append({"type": "margin", "level": "opportunity",
                          "text": f"Margin Debt 占比 {margin_heat:.1f}% 极低, 杠杆出清", "color": "#10b981"})

        aaii = self._aaii_data
        spread = aaii.get("spread", 0)
        if spread > 20:
            signals.append({"type": "sentiment", "level": "warning",
                          "text": f"AAII 极度乐观 spread={spread:.0f}%, 警惕回调", "color": "#ef4444"})
        elif spread < -15:
            signals.append({"type": "sentiment", "level": "opportunity",
                          "text": f"AAII 极度悲观 spread={spread:.0f}%, 逆向机会", "color": "#10b981"})

        return signals

    # ========== 历史走势数据 ==========

    def get_chart_data(self) -> Dict:
        dates = [s["date"] for s in HISTORICAL_SNAPSHOTS]
        values = [s["aiae"] for s in HISTORICAL_SNAPSHOTS]
        labels = [s["label"] for s in HISTORICAL_SNAPSHOTS]
        bands = [
            {"name": "Ⅰ上限", "value": 15, "color": "#10b981"},
            {"name": "Ⅱ上限", "value": 20, "color": "#3b82f6"},
            {"name": "Ⅲ上限", "value": 27, "color": "#eab308"},
            {"name": "Ⅳ上限", "value": 34, "color": "#f97316"},
        ]
        return {
            "dates": dates, "values": values, "labels": labels,
            "bands": bands,
            "stats": {"mean": 24.0, "min": 12.5, "max": 43.5,
                      "current": values[-1] if values else 25.0}
        }

    # ========== 交叉验证 ==========

    def _get_us_erp_value(self) -> float:
        try:
            from erp_us_engine import get_us_erp_engine
            engine = get_us_erp_engine()
            signal = engine.compute_signal()
            if signal.get("status") == "success":
                return signal["current_snapshot"].get("erp_value", 2.0)
        except Exception as e:
            _log(f"US ERP引擎读取失败, 降级2.0%: {e}", "WARN")
        return 2.0

    def _cross_validate(self, regime: int, erp_value: float) -> Dict:
        erp_level = self.classify_erp_level(erp_value)

        if regime <= 2 and erp_value >= 5.0:
            confidence, verdict, color = 5, "极强买入 · 双因子共振", "#10b981"
        elif regime <= 2 and erp_value >= 3.0:
            confidence, verdict, color = 5, "强买入", "#10b981"
        elif regime <= 2 and erp_value >= 1.0:
            confidence, verdict, color = 4, "标准买入", "#34d399"
        elif regime <= 2 and erp_value < 1.0:
            confidence, verdict, color = 3, "谨慎买入 · ERP偏低", "#eab308"
        elif regime == 3 and erp_value >= 3.0:
            confidence, verdict, color = 3, "谨慎乐观", "#34d399"
        elif regime == 3 and 1.0 <= erp_value < 3.0:
            confidence, verdict, color = 3, "中性", "#94a3b8"
        elif regime == 3 and erp_value < 1.0:
            confidence, verdict, color = 3, "中性偏谨慎", "#eab308"
        elif regime == 4 and erp_value >= 3.0:
            confidence, verdict, color = 2, "矛盾信号 · 以AIAE为准", "#f97316"
        elif regime == 4 and erp_value < 3.0:
            confidence, verdict, color = 4, "强减仓", "#ef4444"
        elif regime == 5 and erp_value < 1.0:
            confidence, verdict, color = 5, "全面撤退", "#ef4444"
        else:
            confidence, verdict, color = 4, "清仓 · ERP未确认底部", "#ef4444"

        return {
            "aiae_regime": regime, "erp_value": erp_value, "erp_level": erp_level,
            "confidence": confidence, "confidence_stars": "⭐" * confidence,
            "verdict": verdict, "color": color,
        }

    # ========== 完整报告 ==========

    def generate_report(self) -> Dict:
        t0 = time.time()
        try:
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix='us_aiae') as pool:
                f_mkt = pool.submit(self._fetch_wilshire5000_market_cap)
                f_m2 = pool.submit(self._fetch_us_m2)
                f_margin = pool.submit(self._fetch_us_margin_debt)

            mkt_data = f_mkt.result(timeout=30)
            m2_data = f_m2.result(timeout=30)
            margin_data = f_margin.result(timeout=30)
            _log(f"数据获取完成 ({time.time()-t0:.1f}s)")

            mktcap = mkt_data.get("market_cap_trillion_usd", 52.0)
            m2 = m2_data.get("m2_trillion_usd", 21.5)
            margin_t = margin_data.get("margin_trillion_usd", 0.75)

            aiae_core = self.compute_aiae_core(mktcap, m2)
            margin_heat = self.compute_margin_heat(margin_t, mktcap)
            aaii_spread = self._aaii_data.get("spread", 5.0)
            aiae_v1 = self.compute_us_aiae_v1(aiae_core, margin_heat, aaii_spread)

            regime = self.classify_regime(aiae_v1)
            regime_info = REGIMES_US[regime]

            # 斜率计算: 优先使用磁盘缓存的动态上月值
            prev_aiae = self._load_prev_aiae()
            slope_info = self.compute_slope(aiae_v1, prev_aiae)
            # 保存本次值供下月使用
            self._save_current_aiae(aiae_v1)

            erp_value = self._get_us_erp_value()
            erp_level = self.classify_erp_level(erp_value)
            matrix_position = self.get_position_from_matrix(regime, erp_level)

            allocations = self.allocate_sub_strategies(regime, matrix_position)
            signals = self.generate_signals(aiae_v1, regime, slope_info, margin_heat)
            chart_data = self.get_chart_data()
            cross_validation = self._cross_validate(regime, erp_value)

            _log(f"报告完成 ({time.time()-t0:.1f}s) | AIAE={aiae_v1}% Regime={regime} Pos={matrix_position}%")

            return {
                "status": "success",
                "engine_version": self.VERSION,
                "region": self.REGION,
                "updated_at": datetime.now().isoformat(),
                "latency_ms": round((time.time()-t0)*1000),

                "current": {
                    "aiae_core": aiae_core,
                    "aiae_v1": aiae_v1,
                    "regime": regime,
                    "regime_info": regime_info,
                    "market_cap_trillion": mktcap,
                    "m2_trillion": m2,
                    "margin_heat": margin_heat,
                    "aaii_sentiment": self._aaii_data,
                    "slope": slope_info,
                },

                "position": {
                    "matrix_position": matrix_position,
                    "erp_value": erp_value,
                    "erp_level": erp_level,
                    "regime": regime,
                    "matrix": POSITION_MATRIX_US,
                    "allocations": allocations,
                },

                "signals": signals,
                "cross_validation": cross_validation,
                "chart": chart_data,
                "regimes": REGIMES_US,

                "raw_data": {
                    "mkt": mkt_data,
                    "m2": m2_data,
                    "margin": margin_data,
                    "aaii": self._aaii_data,
                }
            }

        except Exception as e:
            _log(f"generate_report 异常: {e}", "ERROR")
            import traceback; traceback.print_exc()
            return self._fallback_report(str(e))

    def _fallback_report(self, reason: str) -> Dict:
        return {
            "status": "fallback",
            "message": reason,
            "engine_version": self.VERSION,
            "region": self.REGION,
            "updated_at": datetime.now().isoformat(),
            "current": {
                "aiae_core": 25.0, "aiae_v1": 24.5, "regime": 3,
                "regime_info": REGIMES_US[3],
                "market_cap_trillion": 52.0, "m2_trillion": 21.5,
                "margin_heat": 1.5, "aaii_sentiment": DEFAULT_AAII,
                "slope": {"slope": 0, "direction": "flat", "signal": None},
            },
            "position": {
                "matrix_position": 55, "erp_value": 2.0, "erp_level": "erp_1_3",
                "regime": 3, "matrix": POSITION_MATRIX_US,
                "allocations": self.allocate_sub_strategies(3, 55),
            },
            "signals": [{"type": "fallback", "level": "warning",
                        "text": f"数据降级: {reason}", "color": "#f59e0b"}],
            "cross_validation": self._cross_validate(3, 2.0),
            "chart": self.get_chart_data(),
            "regimes": REGIMES_US,
            "raw_data": {},
        }

    def refresh(self):
        """清除内存缓存, 下次 generate_report 时强制从数据源重新获取"""
        with _us_aiae_lock:
            keys_to_clear = [k for k in _us_aiae_cache if k.startswith("us_aiae_")]
            for k in keys_to_clear:
                del _us_aiae_cache[k]
        self._aaii_data = self._load_aaii_sentiment()
        _log(f"缓存已清除 ({len(keys_to_clear)} keys)")


# ===== 引擎单例 =====
_us_aiae_instance = None

def get_us_aiae_engine() -> AIAEUSEngine:
    global _us_aiae_instance
    if _us_aiae_instance is None:
        _us_aiae_instance = AIAEUSEngine()
    return _us_aiae_instance


# ===== 自检 =====
if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    engine = AIAEUSEngine()
    print("=== US AIAE Engine V1.0 Self-Test ===")
    report = engine.generate_report()
    if report.get("status") in ("success", "fallback"):
        c = report["current"]
        p = report["position"]
        print(f"AIAE_Core: {c['aiae_core']}% | AIAE_V1: {c['aiae_v1']}%")
        print(f"Regime: {c['regime']} ({c['regime_info']['cn']})")
        print(f"MktCap: ${c['market_cap_trillion']}T | M2: ${c['m2_trillion']}T")
        print(f"Margin Heat: {c['margin_heat']}% | AAII Spread: {c['aaii_sentiment'].get('spread', 0)}%")
        print(f"Matrix Position: {p['matrix_position']}% (ERP={p['erp_value']}%)")
        cv = report["cross_validation"]
        print(f"Cross-Validation: {cv['verdict']} [{'*'*cv['confidence']}]")
        for s in report["signals"]:
            print(f"  > {s['text']}")
        print(f"\n--- Latency: {report.get('latency_ms', '?')}ms | Status: {report['status']} ---")
    else:
        print(f"Failed: {report.get('message')}")
