"""
AlphaCore · 日本 AIAE 宏観仓位管控引擎 V1.0
=============================================
核心思想: JP_AIAE = 日本投資者把多少比例的資金配置在了株式市場
  - 比例極高 → バブル信号, 減倉
  - 比例極低 → 底値信号, 加倉

三因子構成:
  JP_AIAE_Core = TOPIX推計時価総額 / (TOPIX + 日本M2)     [50%]  月頻
  信用取引熱度 = 信用买残 / 推計時価総額                     [20%]  推定/固定
  外国人買い越し = 外資フロー正規化 (日本最重要指標)          [30%]  推定/固定

五档状態 (日本校準, 比A股下移 5-8%):
  Ⅰ <10%   → 90-95%   極度悲観
  Ⅱ 10-14% → 70-85%   低配置区
  Ⅲ 14-20% → 50-65%   中性均衡
  Ⅳ 20-28% → 25-40%   偏熱区域
  Ⅴ >28%   → 0-15%    バブル警報

数据源: FRED API (Nikkei225代理, 日本M2) + 固定推定値
交叉验証: JP_AIAE × JP ERP 仓位矩阵
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
from typing import Optional, Dict, List
from config import FRED_API_KEY as CONFIG_FRED_API_KEY

FRED_API_KEY = os.environ.get("FRED_API_KEY", CONFIG_FRED_API_KEY)
CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

# ===== 频率感知 TTL 常量 (V1.1 优化) =====
TTL_JP_M2 = 14 * 86400    # 14天 (M2 月频数据)

def _get_topix_ttl() -> int:
    """TOPIX 智能TTL: 工作日4h / 周末24h"""
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
_jp_aiae_cache = {}
_jp_aiae_lock = threading.Lock()
_bg_executor = ThreadPoolExecutor(max_workers=3)

def _log(msg: str, level: str = "INFO"):
    ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts_str}] [{level}] [JP-AIAE] {msg}")

def _refresh_cache(key: str, fetcher):
    try:
        data = fetcher()
        with _jp_aiae_lock:
            _jp_aiae_cache[key] = (time.time(), data)
        return data
    except Exception as e:
        _log(f"后台缓存刷新失败 ({key}): {e}", "WARN")
        with _jp_aiae_lock:
            if key in _jp_aiae_cache:
                return _jp_aiae_cache[key][1]
        raise

def _cached(key: str, ttl_seconds: int, fetcher):
    """线程安全 TTL 缓存 (支持 SWR - Stale-While-Revalidate)"""
    now = time.time()
    with _jp_aiae_lock:
        if key in _jp_aiae_cache:
            ts_cached, data = _jp_aiae_cache[key]
            if now - ts_cached < ttl_seconds:
                return data
            else:
                _bg_executor.submit(_refresh_cache, key, fetcher)
                return data

    return _refresh_cache(key, fetcher)

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


# ===== 歴史基準データ (回測検証) =====
# 校準锚点: MktCap/M2 比値で反推・実績検証済み
# ratio→AIAE 映射: ratio 0.4→8%, 1.2→32% (線形区間)
HISTORICAL_SNAPSHOTS = [
    {"date": "1989-12-29", "aiae": 32.0, "nk_after_1y": -38, "label": "バブル崩壊直前"},  # MktCap/M2≈1.20
    {"date": "2003-04-28", "aiae":  8.5, "nk_after_1y": 47,  "label": "りそな危機底値"},  # MktCap/M2≈0.41
    {"date": "2006-01-16", "aiae": 21.5, "nk_after_1y":  2,  "label": "ライブドアショック前"},
    {"date": "2008-10-28", "aiae":  7.2, "nk_after_1y": 29,  "label": "リーマン底値"},    # MktCap/M2≈0.38
    {"date": "2012-11-14", "aiae":  8.0, "nk_after_1y": 56,  "label": "アベノミクス前夜"},  # MktCap/M2≈0.40
    {"date": "2018-01-23", "aiae": 19.5, "nk_after_1y": -12, "label": "日経24,000天井"},
    {"date": "2020-03-19", "aiae":  9.5, "nk_after_1y": 55,  "label": "COVID底値"},        # MktCap/M2≈0.43
    {"date": "2024-03-22", "aiae": 24.0, "nk_after_1y":  5,  "label": "日経41,000突破"},
    {"date": "2024-07-11", "aiae": 26.5, "nk_after_1y": -8,  "label": "バブル前兆"},
    {"date": "2026-04-10", "aiae": None,  "nk_after_1y": None, "label": "現在状態"},        # 引擎実時計算
]

# ===== 五档状態定義 (日本校準) =====
REGIMES_JP = {
    1: {"name": "Ⅰ · 極度悲観", "cn": "极度悲观", "range": "<10%",
        "color": "#10b981", "emoji": "🟢", "position": "90-95%", "pos_min": 90, "pos_max": 95,
        "action": "全力買い", "desc": "歴史級の買い場、3回に分けて建倉"},
    2: {"name": "Ⅱ · 低配置区", "cn": "低配置区", "range": "10-14%",
        "color": "#3b82f6", "emoji": "🔵", "position": "70-85%", "pos_min": 70, "pos_max": 85,
        "action": "標準建倉", "desc": "忍耐強く保有、変動で減倉しない"},
    3: {"name": "Ⅲ · 中性均衡", "cn": "中性均衡", "range": "14-20%",
        "color": "#eab308", "emoji": "🟡", "position": "50-65%", "pos_min": 50, "pos_max": 65,
        "action": "均衡保有", "desc": "規律正しく保有、目標到達で売却"},
    4: {"name": "Ⅳ · 偏熱区域", "cn": "偏热区域", "range": "20-28%",
        "color": "#f97316", "emoji": "🟠", "position": "25-40%", "pos_min": 25, "pos_max": 40,
        "action": "系統的減倉", "desc": "毎週5%ずつ減倉"},
    5: {"name": "Ⅴ · バブル警報", "cn": "泡沫警报", "range": ">28%",
        "color": "#ef4444", "emoji": "🔴", "position": "0-15%", "pos_min": 0, "pos_max": 15,
        "action": "全面撤退", "desc": "3日以内に完全撤退"},
}

# ===== JP_AIAE × JP_ERP 仓位矩阵 =====
POSITION_MATRIX_JP = {
    "erp_gt4":  [95, 85, 70, 45, 20],
    "erp_2_4":  [90, 80, 65, 40, 15],
    "erp_0_2":  [85, 70, 55, 30, 10],
    "erp_lt0":  [75, 60, 40, 20,  5],
}

# ===== 子策略配額矩阵 (日本ETF: 1306/1321/1489) =====
SUB_STRATEGY_ALLOC_JP = {
    1: {"topix": 40, "n225": 35, "dividend": 25},
    2: {"topix": 40, "n225": 30, "dividend": 30},
    3: {"topix": 35, "n225": 25, "dividend": 40},
    4: {"topix": 25, "n225": 10, "dividend": 65},
    5: {"topix": 10, "n225":  0, "dividend": 90},
}

# ===== 固定推定値 =====
JP_MARGIN_FILE = os.path.join(CACHE_DIR, "jp_margin_estimate.json")
JP_FOREIGN_FILE = os.path.join(CACHE_DIR, "jp_foreign_flow.json")

DEFAULT_JP_MARGIN = {
    "margin_buying_trillion_jpy": 3.8,
    "date": "2026-03-28",
    "source": "estimate",
    "note": "東証信用取引統計から推定 (2024-2026中央値)"
}

DEFAULT_JP_FOREIGN = {
    "net_buy_billion_jpy": 150,
    "cumulative_12m_billion_jpy": 2500,
    "date": "2026-03-28",
    "source": "estimate",
    "note": "東証投資家部門別統計から推定"
}


class AIAEJPEngine:
    """日本 AIAE 宏観仓位管控引擎 V1.1"""

    VERSION = "1.1"
    REGION = "JP"

    # === 上月 AIAE 缓存文件路径 (用于动态斜率计算) ===
    _PREV_AIAE_FILE = os.path.join(CACHE_DIR, "aiae_jp_prev_month.json")

    def __init__(self):
        self._margin_data = self._load_jp_margin()
        self._foreign_data = self._load_jp_foreign()

    # ========== データ取得層 ==========

    def _fetch_topix_market_cap(self) -> Dict:
        """TOPIX/日経225 から推估時価総額 (FRED主力 + CNBC備用)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_jp_topix.json")

            # 1. FRED Nikkei225 (主力データソース)
            fred = _get_fred()
            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=30)
                    @retry_with_backoff(max_retries=3, base_delay=2.0)
                    def _call_fred():
                        return fred.get_series("NIKKEI225", observation_start=start_dt)
                    series = _call_fred()
                    if series is not None and not series.empty:
                        series = series.dropna()
                        latest = float(series.iloc[-1])
                        # N225 → TOPIX推估 → 時価総額
                        # N225/TOPIX 比率は歴史的に ~14 前後
                        topix_est = latest / 14.0
                        mktcap = round(topix_est * 0.27, 1)
                        result = {
                            "trade_date": series.index[-1].strftime("%Y-%m-%d"),
                            "topix_index": round(latest / 14.3, 2),
                            "nikkei225": round(latest, 2),
                            "market_cap_trillion_jpy": mktcap,
                            "fetched_at": datetime.now().isoformat()
                        }
                        atomic_write_json(result, cache_file)
                        _log(f"N225→TOPIX推估: {mktcap}兆円")
                        return result
                except Exception as e:
                    _log(f"FRED NIKKEI225 error: {e}", "WARN")

            # 2. CNBC 日経225 リアルタイム (バックアップ)
            try:
                import requests
                cnbc_url = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=.N225&requestMethod=itv&noCache=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
                @retry_with_backoff(max_retries=3, base_delay=2.0)
                def _call_cnbc():
                    r = requests.get(cnbc_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                    r.raise_for_status()
                    return r.json().get('FormattedQuoteResult', {}).get('FormattedQuote', [{}])[0]
                quote = _call_cnbc()
                price_str = quote.get('last', '0').replace(',', '')
                n225 = float(price_str)
                if n225 > 10000:
                    topix_est = n225 / 14.0
                    mktcap = round(topix_est * 0.27, 1)
                    result = {
                        "trade_date": datetime.now().strftime("%Y-%m-%d"),
                        "topix_index": round(topix_est, 2),
                        "nikkei225": round(n225, 2),
                        "market_cap_trillion_jpy": mktcap,
                        "fetched_at": datetime.now().isoformat(),
                        "source": "cnbc"
                    }
                    atomic_write_json(result, cache_file)
                    _log(f"CNBC N225={n225:.0f}→TOPIX推估: {mktcap}兆円")
                    return result
            except Exception as e:
                _log(f"CNBC N225 error: {e}", "WARN")

            # 3. キャッシュファイル
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)

            # 4. ハードコードフォールバック
            _log("TOPIX: ハードコード推定値使用", "ERROR")
            return {
                "trade_date": datetime.now().strftime("%Y-%m-%d"),
                "topix_index": 2700,
                "market_cap_trillion_jpy": 870,
                "fetched_at": datetime.now().isoformat(),
                "is_fallback": True
            }

        return _cached("jp_aiae_topix", _get_topix_ttl(), _fetch)

    def _fetch_jp_m2(self) -> Dict:
        """日本M2 (FRED MYAGM2JPM189N, 月頻)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_jp_m2.json")
            fred = _get_fred()
            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=180)
                    @retry_with_backoff(max_retries=3, base_delay=2.0)
                    def _call_fred():
                        return fred.get_series("MYAGM2JPM189N", observation_start=start_dt)
                    series = _call_fred()
                    if series is not None and not series.empty:
                        series = series.dropna()
                        latest = float(series.iloc[-1])
                        # 単位: Billions of Yen (十億円)
                        m2_trillion = round(latest / 1000, 1)
                        result = {
                            "month": series.index[-1].strftime("%Y-%m"),
                            "m2_billions_jpy": round(latest, 0),
                            "m2_trillion_jpy": m2_trillion,
                            "fetched_at": datetime.now().isoformat()
                        }
                        atomic_write_json(result, cache_file)
                        _log(f"JP M2: {m2_trillion}兆円")
                        return result
                except Exception as e:
                    _log(f"FRED MYAGM2JPM189N error: {e}", "WARN")

            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)

            return {
                "month": "2026-02",
                "m2_billions_jpy": 1250000,
                "m2_trillion_jpy": 1250.0,
                "fetched_at": datetime.now().isoformat(),
                "is_fallback": True
            }

        return _cached("jp_aiae_m2", TTL_JP_M2, _fetch)

    def _load_jp_margin(self) -> Dict:
        """信用取引残高（手動更新 / 时间衰减デフォルト）
        V1.2: 超过60天的默认值自动向中性衰减, 避免陈旧偏差
        """
        if os.path.exists(JP_MARGIN_FILE):
            try:
                with open(JP_MARGIN_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                _log(f"JP Margin loaded: {data.get('margin_buying_trillion_jpy', 0)}兆円")
                return data
            except Exception:
                pass
        # 时间衰减: 默认值随时间向中性值 (3.5兆円) 衰减
        default = DEFAULT_JP_MARGIN.copy()
        try:
            age_days = (datetime.now() - datetime.strptime(default['date'], '%Y-%m-%d')).days
            if age_days > 60:
                neutral = 3.5  # 历史中位数
                decay = min(age_days / 365, 0.5)  # 最多衰减 50%
                original = default['margin_buying_trillion_jpy']
                default['margin_buying_trillion_jpy'] = round(original + (neutral - original) * decay, 2)
                default['decayed'] = True
        except Exception:
            pass
        _log(f"JP Margin: デフォルト推定値 {default['margin_buying_trillion_jpy']}兆円")
        return default

    def _load_jp_foreign(self) -> Dict:
        """外国人投資家フロー（手動更新 / 时间衰减デフォルト）
        V1.2: 超过60天自动向中性(0)衰减
        """
        if os.path.exists(JP_FOREIGN_FILE):
            try:
                with open(JP_FOREIGN_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                _log(f"JP Foreign loaded: net={data.get('net_buy_billion_jpy', 0)}億円")
                return data
            except Exception:
                pass
        default = DEFAULT_JP_FOREIGN.copy()
        try:
            age_days = (datetime.now() - datetime.strptime(default['date'], '%Y-%m-%d')).days
            if age_days > 60:
                decay = min(age_days / 365, 0.8)  # 外资流向衰减更快
                default['net_buy_billion_jpy'] = round(default['net_buy_billion_jpy'] * (1 - decay))
                default['decayed'] = True
        except Exception:
            pass
        _log(f"JP Foreign: デフォルト推定値 net={default['net_buy_billion_jpy']}億円")
        return default

    def update_jp_margin(self, margin_buying_trillion_jpy: float):
        """手動更新 信用取引残高"""
        data = {
            "margin_buying_trillion_jpy": round(margin_buying_trillion_jpy, 2),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "source": "manual"
        }
        atomic_write_json(data, JP_MARGIN_FILE)
        self._margin_data = data
        _log(f"JP Margin 手動更新: {margin_buying_trillion_jpy}兆円")

    def update_jp_foreign(self, net_buy_billion_jpy: float, cumulative_12m: float = None):
        """手動更新 外国人買い越し"""
        data = {
            "net_buy_billion_jpy": round(net_buy_billion_jpy, 0),
            "cumulative_12m_billion_jpy": round(cumulative_12m, 0) if cumulative_12m else 2500,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "source": "manual"
        }
        atomic_write_json(data, JP_FOREIGN_FILE)
        self._foreign_data = data
        _log(f"JP Foreign 手動更新: net={net_buy_billion_jpy}億円")

    # ========== 核心計算層 ==========

    def compute_aiae_core(self, mktcap_trillion_jpy: float, m2_trillion_jpy: float) -> float:
        """
        JP_AIAE_Core = 日本市場 MktCap / M2 比值 → 歸一化到 AIAE 標度

        歴史アンカー:
          ratio=0.35  (2008リーマン底余裕) → AIAE=8%   (Ⅰ級極度悲観)
          ratio=0.95  (実用30年上限余裕)   → AIAE=32%  (Ⅴ級バブル警報)

        V1.2 優化: 区間 [0.4, 1.2] → [0.35, 0.95]
        旧上限 1.2 は1989年バブル(半世紀の極端事件)がアンカー。
        その後30年間のデータでratioは0.35-0.75の範囲。
        2024-03 N225=41000時 ratio≈0.70。上限 0.95 で十分な余裕あり。

        線形映射: AIAE = 8 + (ratio - 0.35) / (0.95 - 0.35) × 24

        日本特殊性: M2/GDP比率が世界最高(~250%)なので、
        MktCap/(MktCap+M2) だと M2 が過大で常に低値になるか、
        またはMktCapがM2に匹敵すると ~50% に偏る。
        比値法なら正確に歴史データに適合する。
        """
        if m2_trillion_jpy <= 0:
            return 17.0
        ratio = mktcap_trillion_jpy / m2_trillion_jpy
        # 線形歸一化: [0.35, 0.95] → [8%, 32%]
        aiae_core = 8.0 + (ratio - 0.35) / (0.95 - 0.35) * 24.0
        return round(max(5.0, min(40.0, aiae_core)), 2)

    def compute_margin_heat(self, margin_trillion: float, mktcap_trillion: float) -> float:
        """信用取引熱度 = 融資残高 / 時価総額 × 100"""
        if mktcap_trillion <= 0:
            return 0.4
        return round(margin_trillion / mktcap_trillion * 100, 2)

    def normalize_foreign_flow(self, net_buy_billion: float) -> float:
        """
        外資フロー正規化 → AIAE等効値
        周次 net_buy: -5000～+5000 億円 → 6-30% AIAE等効
        """
        normalized = 6 + (net_buy_billion - (-5000)) / (5000 - (-5000)) * (30 - 6)
        return max(6, min(30, round(normalized, 2)))

    def compute_jp_aiae_v1(self, aiae_core: float, margin_heat: float, foreign_flow_norm: float) -> float:
        """
        JP AIAE V1.1 融合
        = 0.5 × AIAE_Core + 0.2 × Margin_正規化 + 0.3 × 外資フロー正規化

        正規化区間与 AIAE_Core 新範囲 (5-40%) 対齐:
        Margin heat: 0.2-0.8% → 6-30% AIAE等效
        Foreign flow: already normalized via normalize_foreign_flow()
        """
        # Margin正規化: 0.2-0.8% → 6-30%
        m_norm = 6 + (margin_heat - 0.2) / (0.8 - 0.2) * (30 - 6)
        m_norm = max(6.0, min(30.0, m_norm))

        return round(0.5 * aiae_core + 0.2 * m_norm + 0.3 * foreign_flow_norm, 2)

    # ========== 五档判定層 ==========

    def classify_regime(self, aiae_value: float) -> int:
        if aiae_value < 10:
            return 1
        elif aiae_value < 14:
            return 2
        elif aiae_value < 20:
            return 3
        elif aiae_value < 28:
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
            signal = {"type": "accel_up", "text": "JP AIAE 加速上行", "level": "warning"}
        elif slope < -2.0:
            signal = {"type": "accel_down", "text": "JP AIAE 加速下行", "level": "opportunity"}
        return {"slope": round(slope, 2), "direction": direction, "signal": signal}

    def _load_prev_aiae(self) -> Optional[float]:
        """磁盤から前月 AIAE 値を読込み (動的斜率計算用)"""
        try:
            if os.path.exists(self._PREV_AIAE_FILE):
                with open(self._PREV_AIAE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get('aiae_v1')
        except Exception:
            pass
        return None

    def _save_current_aiae(self, aiae_v1: float):
        """現在の AIAE 値を磁盤に保存 (次回斜率計算用)"""
        try:
            data = {
                'aiae_v1': aiae_v1,
                'saved_at': datetime.now().isoformat()
            }
            atomic_write_json(data, self._PREV_AIAE_FILE)
        except Exception as e:
            _log(f"前月AIAE保存失敗: {e}", "WARN")

    def classify_erp_level(self, erp_value: float) -> str:
        """日本ERP阈值 (JGB低, 所以ERP阈值整体下移)"""
        if erp_value >= 4.0:
            return "erp_gt4"
        elif erp_value >= 2.0:
            return "erp_2_4"
        elif erp_value >= 0:
            return "erp_0_2"
        else:
            return "erp_lt0"

    def get_position_from_matrix(self, regime: int, erp_level: str) -> int:
        row = POSITION_MATRIX_JP.get(erp_level, POSITION_MATRIX_JP["erp_0_2"])
        idx = min(regime - 1, 4)
        return row[idx]

    def allocate_sub_strategies(self, regime: int, total_position: int) -> Dict:
        alloc = SUB_STRATEGY_ALLOC_JP.get(regime, SUB_STRATEGY_ALLOC_JP[3])
        return {
            "topix":    {"name": "TOPIX ETF (1306)", "pct": alloc["topix"],    "position": round(total_position * alloc["topix"] / 100, 1)},
            "n225":     {"name": "日経225 ETF (1321)", "pct": alloc["n225"],    "position": round(total_position * alloc["n225"] / 100, 1)},
            "dividend": {"name": "高配当50 ETF (1489)", "pct": alloc["dividend"], "position": round(total_position * alloc["dividend"] / 100, 1)},
        }

    # ========== 信号系统 ==========

    def generate_signals(self, aiae_value: float, regime: int, slope_info: Dict, margin_heat: float) -> List[Dict]:
        signals = []
        ri = REGIMES_JP[regime]
        signals.append({
            "type": "main", "level": ri["emoji"],
            "text": f"{ri['cn']}信号 · JP AIAE={aiae_value:.1f}% · {ri['action']}",
            "color": ri["color"]
        })

        if slope_info.get("signal"):
            s = slope_info["signal"]
            signals.append({"type": "slope", "level": s["level"], "text": s["text"],
                          "color": "#f59e0b" if s["level"] == "warning" else "#10b981"})

        if margin_heat > 0.6:
            signals.append({"type": "margin", "level": "warning",
                          "text": f"信用取引残高占比 {margin_heat:.2f}% 偏高", "color": "#f97316"})
        elif margin_heat < 0.2:
            signals.append({"type": "margin", "level": "opportunity",
                          "text": f"信用取引残高占比 {margin_heat:.2f}% 极低", "color": "#10b981"})

        foreign_net = self._foreign_data.get("net_buy_billion_jpy", 0)
        if foreign_net > 3000:
            signals.append({"type": "foreign", "level": "info",
                          "text": f"外资大幅买越 {foreign_net/100:.0f}亿円, 注意追高风险", "color": "#3b82f6"})
        elif foreign_net < -3000:
            signals.append({"type": "foreign", "level": "opportunity",
                          "text": f"外资大幅卖越 {foreign_net/100:.0f}亿円, 逆向机会", "color": "#10b981"})

        return signals

    # ========== 歴史走勢データ ==========

    def get_chart_data(self) -> Dict:
        dates = [s["date"] for s in HISTORICAL_SNAPSHOTS]
        values = [s["aiae"] for s in HISTORICAL_SNAPSHOTS]
        labels = [s["label"] for s in HISTORICAL_SNAPSHOTS]
        bands = [
            {"name": "Ⅰ上限", "value": 10, "color": "#10b981"},
            {"name": "Ⅱ上限", "value": 14, "color": "#3b82f6"},
            {"name": "Ⅲ上限", "value": 20, "color": "#eab308"},
            {"name": "Ⅳ上限", "value": 28, "color": "#f97316"},
        ]
        return {
            "dates": dates, "values": values, "labels": labels,
            "bands": bands,
            "stats": {"mean": 17.0, "min": 7.2, "max": 32.0,
                      "current": values[-1] if values else 17.0}
        }

    # ========== 交叉検証 ==========

    def _get_jp_erp_value(self) -> float:
        try:
            from erp_jp_engine import get_jp_erp_engine
            engine = get_jp_erp_engine()
            signal = engine.compute_signal()
            if signal.get("status") == "success":
                return signal["current_snapshot"].get("erp_value", 2.0)
        except Exception as e:
            _log(f"JP ERP引擎読取失敗, 降級2.0%: {e}", "WARN")
        return 2.0

    def _cross_validate(self, regime: int, erp_value: float) -> Dict:
        erp_level = self.classify_erp_level(erp_value)

        if regime <= 2 and erp_value >= 4.0:
            confidence, verdict, color = 5, "極強買入 · 雙因子共振", "#10b981"
        elif regime <= 2 and erp_value >= 2.0:
            confidence, verdict, color = 5, "強買入", "#10b981"
        elif regime <= 2 and erp_value >= 0:
            confidence, verdict, color = 4, "標準買入", "#34d399"
        elif regime <= 2 and erp_value < 0:
            confidence, verdict, color = 3, "謹慎買入 · ERP為負", "#eab308"
        elif regime == 3 and erp_value >= 2.0:
            confidence, verdict, color = 3, "謹慎樂觀", "#34d399"
        elif regime == 3 and 0 <= erp_value < 2.0:
            confidence, verdict, color = 3, "中性", "#94a3b8"
        elif regime == 3 and erp_value < 0:
            confidence, verdict, color = 3, "中性偏謹慎", "#eab308"
        elif regime == 4 and erp_value >= 2.0:
            confidence, verdict, color = 2, "矛盾信号 · 以AIAE為準", "#f97316"
        elif regime == 4 and erp_value < 2.0:
            confidence, verdict, color = 4, "強減倉", "#ef4444"
        elif regime == 5 and erp_value < 0:
            confidence, verdict, color = 5, "全面撤退", "#ef4444"
        else:
            confidence, verdict, color = 4, "清倉 · ERP未確認底値", "#ef4444"

        return {
            "aiae_regime": regime, "erp_value": erp_value, "erp_level": erp_level,
            "confidence": confidence, "confidence_stars": "⭐" * confidence,
            "verdict": verdict, "color": color,
        }

    # ========== 完整報告 ==========

    def generate_report(self) -> Dict:
        t0 = time.time()
        try:
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix='jp_aiae') as pool:
                f_mkt = pool.submit(self._fetch_topix_market_cap)
                f_m2 = pool.submit(self._fetch_jp_m2)

            mkt_data = f_mkt.result(timeout=30)
            m2_data = f_m2.result(timeout=30)
            _log(f"データ取得完了 ({time.time()-t0:.1f}s)")

            mktcap = mkt_data.get("market_cap_trillion_jpy", 870)
            m2 = m2_data.get("m2_trillion_jpy", 1250)
            margin_t = self._margin_data.get("margin_buying_trillion_jpy", 3.8)
            foreign_net = self._foreign_data.get("net_buy_billion_jpy", 150)

            aiae_core = self.compute_aiae_core(mktcap, m2)
            margin_heat = self.compute_margin_heat(margin_t, mktcap)
            foreign_norm = self.normalize_foreign_flow(foreign_net)
            aiae_v1 = self.compute_jp_aiae_v1(aiae_core, margin_heat, foreign_norm)

            regime = self.classify_regime(aiae_v1)
            regime_info = REGIMES_JP[regime]

            # 斜率計算: 磁盤キャッシュの動的前月値を優先使用
            prev_aiae = self._load_prev_aiae()
            slope_info = self.compute_slope(aiae_v1, prev_aiae)
            # 本次値を保存 (次回斜率計算用)
            self._save_current_aiae(aiae_v1)

            erp_value = self._get_jp_erp_value()
            erp_level = self.classify_erp_level(erp_value)
            matrix_position = self.get_position_from_matrix(regime, erp_level)

            allocations = self.allocate_sub_strategies(regime, matrix_position)
            signals = self.generate_signals(aiae_v1, regime, slope_info, margin_heat)
            chart_data = self.get_chart_data()
            cross_validation = self._cross_validate(regime, erp_value)

            _log(f"報告完成 ({time.time()-t0:.1f}s) | AIAE={aiae_v1}% Regime={regime} Pos={matrix_position}%")

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
                    "market_cap_trillion_jpy": mktcap,
                    "m2_trillion_jpy": m2,
                    "margin_heat": margin_heat,
                    "foreign_flow": self._foreign_data,
                    "slope": slope_info,
                },

                "position": {
                    "matrix_position": matrix_position,
                    "erp_value": erp_value,
                    "erp_level": erp_level,
                    "regime": regime,
                    "matrix": POSITION_MATRIX_JP,
                    "allocations": allocations,
                },

                "signals": signals,
                "cross_validation": cross_validation,
                "chart": chart_data,
                "regimes": REGIMES_JP,

                "raw_data": {
                    "mkt": mkt_data,
                    "m2": m2_data,
                    "margin": self._margin_data,
                    "foreign": self._foreign_data,
                }
            }

        except Exception as e:
            _log(f"generate_report 例外: {e}", "ERROR")
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
                "aiae_core": 17.0, "aiae_v1": 17.5, "regime": 3,
                "regime_info": REGIMES_JP[3],
                "market_cap_trillion_jpy": 870, "m2_trillion_jpy": 1250,
                "margin_heat": 0.44, "foreign_flow": DEFAULT_JP_FOREIGN,
                "slope": {"slope": 0, "direction": "flat", "signal": None},
            },
            "position": {
                "matrix_position": 55, "erp_value": 2.0, "erp_level": "erp_0_2",
                "regime": 3, "matrix": POSITION_MATRIX_JP,
                "allocations": self.allocate_sub_strategies(3, 55),
            },
            "signals": [{"type": "fallback", "level": "warning",
                        "text": f"データ降級: {reason}", "color": "#f59e0b"}],
            "cross_validation": self._cross_validate(3, 2.0),
            "chart": self.get_chart_data(),
            "regimes": REGIMES_JP,
            "raw_data": {},
        }

    def refresh(self):
        """キャッシュクリア: 次回 generate_report 時にデータソースから再取得"""
        with _jp_aiae_lock:
            keys_to_clear = [k for k in _jp_aiae_cache if k.startswith("jp_aiae_")]
            for k in keys_to_clear:
                del _jp_aiae_cache[k]
        self._margin_data = self._load_jp_margin()
        self._foreign_data = self._load_jp_foreign()
        _log(f"キャッシュクリア ({len(keys_to_clear)} keys)")


# ===== 引擎単例 =====
_jp_aiae_instance = None

def get_jp_aiae_engine() -> AIAEJPEngine:
    global _jp_aiae_instance
    if _jp_aiae_instance is None:
        _jp_aiae_instance = AIAEJPEngine()
    return _jp_aiae_instance


# ===== 自検 =====
if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    engine = AIAEJPEngine()
    print("=== JP AIAE Engine V1.0 Self-Test ===")
    report = engine.generate_report()
    if report.get("status") in ("success", "fallback"):
        c = report["current"]
        p = report["position"]
        print(f"AIAE_Core: {c['aiae_core']}% | AIAE_V1: {c['aiae_v1']}%")
        print(f"Regime: {c['regime']} ({c['regime_info']['cn']})")
        print(f"MktCap: {c.get('market_cap_trillion_jpy', '?')}兆円 | M2: {c.get('m2_trillion_jpy', '?')}兆円")
        print(f"Margin Heat: {c['margin_heat']}% | Foreign Net: {c['foreign_flow'].get('net_buy_billion_jpy', 0)}億円")
        print(f"Matrix Position: {p['matrix_position']}% (ERP={p['erp_value']}%)")
        cv = report["cross_validation"]
        print(f"Cross-Validation: {cv['verdict']} [{'*'*cv['confidence']}]")
        for s in report["signals"]:
            print(f"  > {s['text']}")
        print(f"\n--- Latency: {report.get('latency_ms', '?')}ms | Status: {report['status']} ---")
    else:
        print(f"Failed: {report.get('message')}")
