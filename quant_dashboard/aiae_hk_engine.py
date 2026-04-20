"""
AlphaCore · 港股 AIAE 宏观仓位管控引擎 V1.0
=============================================
核心思想: HK_AIAE = 港股投资者配置权重的温度计
  - 比例极高 → 市场过热, 减仓
  - 比例极低 → 市场冰点, 加仓

三因子构成 (港股本地化):
  HK_AIAE_Core = HSI总市值 / (HSI总市值 + CN_M2估算)      [50%]  月频
  南向资金热度  = 南向12M累计净买入 / HSI总市值               [20%]  手动/日
  AH溢价指标   = AH溢价指数归一化 (越高=H股越便宜)          [30%]  手动/日

五档状态 (港股校准, 比A股下移4-5%):
  Ⅰ <8%    → 90-95%   极度恐慌    (2022年10月 HSI 14800)
  Ⅱ 8-12%  → 70-85%   低配置区    (2024年1月 HSI 15300)
  Ⅲ 12-18% → 50-65%   中性均衡    (常态区间)
  Ⅳ 18-25% → 25-40%   偏热区域    (2021年2月 HSI 31000)
  Ⅴ >25%   → 0-15%    极度过热    (2018年1月 HSI 33500)

交叉验证: HK_AIAE × HK_ERP 仓位矩阵
子策略配额: 恒生ETF / 恒生科技ETF / 恒生红利低波ETF
"""

import os
import json
import time
import threading
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from config import FRED_API_KEY as CONFIG_FRED_API_KEY

FRED_API_KEY = os.environ.get("FRED_API_KEY", CONFIG_FRED_API_KEY)
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
_hk_aiae_cache = {}
_hk_aiae_lock = threading.Lock()
_bg_executor = ThreadPoolExecutor(max_workers=3)

def _log(msg: str, level: str = "INFO"):
    ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts_str}] [{level}] [HK-AIAE] {msg}")

def _refresh_cache(key: str, fetcher):
    try:
        data = fetcher()
        with _hk_aiae_lock:
            _hk_aiae_cache[key] = (time.time(), data)
        return data
    except Exception as e:
        _log(f"后台缓存刷新失败 ({key}): {e}", "WARN")
        with _hk_aiae_lock:
            if key in _hk_aiae_cache:
                return _hk_aiae_cache[key][1]
        raise

def _cached(key: str, ttl_seconds: int, fetcher):
    """线程安全 TTL 缓存 (支持 SWR - Stale-While-Revalidate)"""
    now = time.time()
    with _hk_aiae_lock:
        if key in _hk_aiae_cache:
            ts_cached, data = _hk_aiae_cache[key]
            if now - ts_cached < ttl_seconds:
                return data
            else:
                _bg_executor.submit(_refresh_cache, key, fetcher)
                return data

    return _refresh_cache(key, fetcher)


# FRED
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


# ===== 历史基准数据 =====
HISTORICAL_SNAPSHOTS = [
    {"date": "2018-01-29", "aiae": 26.5, "hsi_after_1y": -25, "label": "2018年1月 HSI 33500 泡沫"},
    {"date": "2019-08-12", "aiae": 14.0, "hsi_after_1y": -5,  "label": "2019年8月 贸易战+社运"},
    {"date": "2020-03-19", "aiae": 7.5,  "hsi_after_1y": 22,  "label": "2020年3月 COVID底部"},
    {"date": "2021-02-17", "aiae": 24.8, "hsi_after_1y": -35, "label": "2021年2月 HSI 31000顶部"},
    {"date": "2022-03-15", "aiae": 10.5, "hsi_after_1y": -15, "label": "2022年3月 中概退市恐慌"},
    {"date": "2022-10-31", "aiae": 6.2,  "hsi_after_1y": 5,   "label": "2022年10月 HSI 14800 极底"},
    {"date": "2024-01-22", "aiae": 8.8,  "hsi_after_1y": 25,  "label": "2024年1月 HSI 15300"},
    {"date": "2024-09-30", "aiae": 18.5, "hsi_after_1y": None, "label": "2024年9月 国庆牛市"},
    {"date": "2026-04-06", "aiae": 14.0, "hsi_after_1y": None, "label": "当前状态(估)"},
]

# ===== 五档状态定义 =====
REGIMES_HK = {
    1: {"name": "Ⅰ · EXTREME FEAR", "cn": "极度恐慌", "range": "<8%",
        "color": "#10b981", "emoji": "🟢", "position": "90-95%", "pos_min": 90, "pos_max": 95,
        "action": "满配进攻", "desc": "2022年10月底部级别 · 分3批建仓"},
    2: {"name": "Ⅱ · LOW ALLOCATION", "cn": "低配置区", "range": "8-12%",
        "color": "#3b82f6", "emoji": "🔵", "position": "70-85%", "pos_min": 70, "pos_max": 85,
        "action": "标准建仓", "desc": "2024年1月底部 · 耐心持有"},
    3: {"name": "Ⅲ · NEUTRAL", "cn": "中性均衡", "range": "12-18%",
        "color": "#eab308", "emoji": "🟡", "position": "50-65%", "pos_min": 50, "pos_max": 65,
        "action": "均衡持有", "desc": "常态运行 · 有纪律地持有"},
    4: {"name": "Ⅳ · GETTING HOT", "cn": "偏热区域", "range": "18-25%",
        "color": "#f97316", "emoji": "🟠", "position": "25-40%", "pos_min": 25, "pos_max": 40,
        "action": "系统减仓", "desc": "2024年9月牛市 · 每周减5%"},
    5: {"name": "Ⅴ · EUPHORIA", "cn": "极度过热", "range": ">25%",
        "color": "#ef4444", "emoji": "🔴", "position": "0-15%", "pos_min": 0, "pos_max": 15,
        "action": "清仓防守", "desc": "2018年1月级别 · 3天清仓"},
}

# ===== HK_AIAE × HK_ERP 仓位矩阵 =====
POSITION_MATRIX_HK = {
    "erp_gt8":  [95, 85, 70, 45, 20],
    "erp_6_8":  [90, 80, 65, 40, 15],
    "erp_4_6":  [85, 70, 55, 30, 10],
    "erp_lt4":  [75, 60, 40, 20,  5],
}

# ===== 子策略配额 =====
SUB_STRATEGY_ALLOC_HK = {
    1: {"hsi": 30, "hstech": 45, "dividend": 25},
    2: {"hsi": 35, "hstech": 35, "dividend": 30},
    3: {"hsi": 30, "hstech": 30, "dividend": 40},
    4: {"hsi": 20, "hstech": 15, "dividend": 65},
    5: {"hsi": 10, "hstech":  0, "dividend": 90},
}

# ===== 手动数据文件 =====
SOUTHBOUND_FILE = os.path.join(CACHE_DIR, "hk_southbound_flow.json")
AH_PREMIUM_FILE = os.path.join(CACHE_DIR, "hk_ah_premium.json")

DEFAULT_SOUTHBOUND = {
    "weekly_net_buy_billion_rmb": 15.0,
    "monthly_net_buy_billion_rmb": 60.0,
    "cumulative_12m_billion_rmb": 350.0,
    "direction": "inflow",
    "date": "2026-04-01",
    "source": "default",
}

DEFAULT_AH_PREMIUM = {
    "index_value": 135.0,
    "date": "2026-04-01",
    "source": "default",
    "interpretation": "A股平均比H股贵35%, H股有折价优势",
}


class AIAEHKEngine:
    """港股 AIAE 宏观仓位管控引擎 V1.0"""

    VERSION = "1.0"
    REGION = "HK"

    def __init__(self):
        self._southbound = self._load_json(SOUTHBOUND_FILE, DEFAULT_SOUTHBOUND)
        self._ah_premium = self._load_json(AH_PREMIUM_FILE, DEFAULT_AH_PREMIUM)

    def _load_json(self, filepath: str, default: dict) -> dict:
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return default.copy()

    def refresh(self):
        with _hk_aiae_lock:
            keys_to_clear = [k for k in _hk_aiae_cache if k.startswith("hk_aiae_")]
            for k in keys_to_clear:
                del _hk_aiae_cache[k]
        self._southbound = self._load_json(SOUTHBOUND_FILE, DEFAULT_SOUTHBOUND)
        self._ah_premium = self._load_json(AH_PREMIUM_FILE, DEFAULT_AH_PREMIUM)
        _log(f"缓存已清除")

    # ========== 手动数据更新 ==========

    def update_southbound(self, weekly_net: float, monthly_net: float = None, cumulative_12m: float = None):
        data = self._southbound.copy()
        data["weekly_net_buy_billion_rmb"] = round(weekly_net, 1)
        if monthly_net is not None:
            data["monthly_net_buy_billion_rmb"] = round(monthly_net, 1)
        if cumulative_12m is not None:
            data["cumulative_12m_billion_rmb"] = round(cumulative_12m, 1)
        data["direction"] = "inflow" if weekly_net > 0 else "outflow"
        data["date"] = datetime.now().strftime("%Y-%m-%d")
        data["source"] = "manual"
        atomic_write_json(data, SOUTHBOUND_FILE)
        self._southbound = data
        _log(f"南向资金更新: weekly={weekly_net:.1f}B")

    def update_ah_premium(self, index_value: float):
        data = {
            "index_value": round(index_value, 1),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "source": "manual",
            "interpretation": f"A股平均比H股贵{index_value - 100:.0f}%" if index_value > 100 else f"H股比A股贵{100 - index_value:.0f}%",
        }
        atomic_write_json(data, AH_PREMIUM_FILE)
        self._ah_premium = data
        _log(f"AH溢价指数更新: {index_value:.1f}")

    # ========== 数据获取层 ==========

    def _fetch_hsi_market_cap(self) -> Dict:
        """获取恒生指数近似总市值 (CNBC实时 → 磁盘缓存 → 硬编码)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_hk_mktcap.json")

            # Tier 1: CNBC 实时报价
            try:
                import requests
                cnbc_url = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=.HSI&requestMethod=itv&noCache=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
                @retry_with_backoff(max_retries=3, base_delay=2.0)
                def _call_cnbc():
                    r = requests.get(cnbc_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                    r.raise_for_status()
                    return r.json().get('FormattedQuoteResult', {}).get('FormattedQuote', [{}])[0]
                quote = _call_cnbc()
                price_str = quote.get('last', '0').replace(',', '')
                price = float(price_str)
                if price > 1000:
                    # HSI 近似总市值: 指数点位 × 系数
                    # HSI 20000 ≈ 32万亿HKD ≈ 4.1万亿USD
                    mktcap_hkd_trillion = price / 20000 * 32
                    mktcap_usd_trillion = mktcap_hkd_trillion / 7.8
                    result = {
                        "trade_date": datetime.now().strftime("%Y-%m-%d"),
                        "hsi_close": round(price, 0),
                        "mktcap_hkd_trillion": round(mktcap_hkd_trillion, 1),
                        "mktcap_usd_trillion": round(mktcap_usd_trillion, 2),
                        "fetched_at": datetime.now().isoformat(),
                        "source": "cnbc",
                    }
                    atomic_write_json(result, cache_file)
                    _log(f"HSI MktCap: {mktcap_hkd_trillion:.0f}T HKD (≈${mktcap_usd_trillion:.1f}T USD) [CNBC]")
                    return result
            except Exception as e:
                _log(f"CNBC HSI error: {e}", "WARN")

            # Tier 2: 磁盘缓存
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)

            # Tier 3: 硬编码兜底
            return {
                "trade_date": datetime.now().strftime("%Y-%m-%d"),
                "hsi_close": 21000, "mktcap_hkd_trillion": 33.6,
                "mktcap_usd_trillion": 4.3,
                "fetched_at": datetime.now().isoformat(), "is_fallback": True,
            }
        return _cached("hk_aiae_mktcap", 14400, _fetch)

    def _fetch_cn_m2_proxy(self) -> Dict:
        """获取中国M2 (FRED M2CN — 近似离岸可配置部分)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_hk_cn_m2.json")
            fred = _get_fred()
            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=180)
                    # 使用中国M2 FRED序列
                    @retry_with_backoff(max_retries=3, base_delay=2.0)
                    def _call_fred():
                        return fred.get_series("MYAGM2CNM189N", observation_start=start_dt)
                    series = _call_fred()
                    if series is not None and not series.empty:
                        series = series.dropna()
                        latest = float(series.iloc[-1])
                        # MYAGM2CNM189N 单位: National Currency (亿元人民币)
                        # 中国M2 约 315万亿RMB = 315万亿/7.25 ≈ 43.4万亿USD
                        m2_trillion_rmb = latest / 10000  # 转换为万亿
                        m2_trillion_usd = m2_trillion_rmb / 7.25
                        # V1.1: 使用全量 CN M2 (USD) 作为 AIAE 分母
                        # 概念: HK MktCap / (HK MktCap + CN M2) = 港股占全中国流动性的比例
                        # 与 A 股引擎 A_MktCap / (A_MktCap + CN M2) 逻辑统一
                        effective_m2 = m2_trillion_usd * 1.0
                        result = {
                            "month": series.index[-1].strftime("%Y-%m"),
                            "cn_m2_trillion_rmb": round(m2_trillion_rmb, 1),
                            "cn_m2_trillion_usd": round(m2_trillion_usd, 1),
                            "effective_m2_trillion_usd": round(effective_m2, 2),
                            "fetched_at": datetime.now().isoformat(),
                        }
                        atomic_write_json(result, cache_file)
                        _log(f"CN M2: {m2_trillion_rmb:.0f}T RMB, effective={effective_m2:.1f}T USD")
                        return result
                except Exception as e:
                    _log(f"FRED CN M2 error: {e}", "WARN")

            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)

            return {
                "month": "2026-02", "cn_m2_trillion_rmb": 315.0,
                "cn_m2_trillion_usd": 43.4, "effective_m2_trillion_usd": 43.4,
                "fetched_at": datetime.now().isoformat(), "is_fallback": True,
            }
        return _cached("hk_aiae_cn_m2", 14 * 86400, _fetch)

    # ========== 核心计算层 ==========

    def compute_aiae_core(self, mktcap_usd: float, effective_m2: float) -> float:
        """HK_AIAE_Core = HSI MktCap / Effective_M2 比値 → 歸一化到 AIAE 標度

        V1.1 修正: 从分数法改为 ratio 法 (与美/日统一)
        旧公式 MktCap/(MktCap+M2) 因 CN M2($43T) >> HK MktCap($4T),
        导致 Core 永远≈9%, 五档系统失去区分能力.

        歴史錨点:
          ratio=0.08  (2022-10 HSI 14800 極底) → AIAE=6%  (Ⅰ級恐慌)
          ratio=0.20  (2018-01 HSI 33500 泡沫) → AIAE=28% (Ⅴ級過熱)

        線形映射: AIAE = 6 + (ratio - 0.08) / (0.20 - 0.08) × 22
        """
        if effective_m2 <= 0:
            return 15.0
        ratio = mktcap_usd / effective_m2
        # 線形歸一化: [0.08, 0.20] → [6%, 28%]
        aiae_core = 6.0 + (ratio - 0.08) / (0.20 - 0.08) * 22.0
        return round(max(4.0, min(35.0, aiae_core)), 2)

    def compute_southbound_heat(self, cumulative_12m: float, mktcap_usd: float) -> float:
        """南向热度 = 南向12M累计 / HSI总市值 × 100
        
        V1.1 修正: mktcap_usd 单位=万亿(trillion), cumulative_12m 单位=亿RMB
        旧: *1000 (万亿→十亿) vs 亿 → 放大10倍
        新: *10000 (万亿→亿) 单位统一
        """
        if mktcap_usd <= 0:
            return 1.0
        cumulative_usd = cumulative_12m / 7.25  # 亿RMB→亿USD
        return round(cumulative_usd / (mktcap_usd * 10000) * 100, 2)  # 万亿→亿, 单位统一

    def compute_ah_premium_score(self, ah_index: float) -> float:
        """AH溢价指数归一化 → AIAE等效值
        AH溢价 120-160 → 10-30% AIAE等效
        AH越高 = H股越便宜 = AIAE应该越低(利好加仓)"""
        # 反向: AH越高 = H股越便宜 = 越应该买
        normalized = 30 - (ah_index - 120) / (160 - 120) * (30 - 10)
        return max(5, min(35, normalized))

    def compute_hk_aiae_v1(self, aiae_core: float, sb_heat: float, ah_score: float) -> float:
        """
        HK AIAE V1.0 融合
        = 0.5 × AIAE_Core + 0.2 × SB_归一化 + 0.3 × AH_归一化
        """
        # 南向热度归一化: 0-5% → 10-30% AIAE等效
        sb_norm = 10 + sb_heat / 5 * (30 - 10)
        sb_norm = max(5, min(30, sb_norm))

        return round(0.5 * aiae_core + 0.2 * sb_norm + 0.3 * ah_score, 2)

    # ========== 五档判定 ==========

    def classify_regime(self, aiae_value: float) -> int:
        if aiae_value < 8: return 1
        elif aiae_value < 12: return 2
        elif aiae_value < 18: return 3
        elif aiae_value < 25: return 4
        else: return 5

    def compute_slope(self, current: float, previous: float) -> Dict:
        if previous is None or previous == 0:
            return {"slope": 0, "direction": "flat", "signal": None}
        slope = current - previous
        direction = "rising" if slope > 0 else ("falling" if slope < 0 else "flat")
        signal = None
        if slope > 2.0:
            signal = {"type": "accel_up", "text": "HK AIAE 加速上行", "level": "warning"}
        elif slope < -2.0:
            signal = {"type": "accel_down", "text": "HK AIAE 加速下行", "level": "opportunity"}
        return {"slope": round(slope, 2), "direction": direction, "signal": signal}

    def classify_erp_level(self, erp_value: float) -> str:
        if erp_value >= 8.0: return "erp_gt8"
        elif erp_value >= 6.0: return "erp_6_8"
        elif erp_value >= 4.0: return "erp_4_6"
        else: return "erp_lt4"

    def get_position_from_matrix(self, regime: int, erp_level: str) -> int:
        row = POSITION_MATRIX_HK.get(erp_level, POSITION_MATRIX_HK["erp_4_6"])
        idx = min(regime - 1, 4)
        return row[idx]

    def allocate_sub_strategies(self, regime: int, total_position: int) -> Dict:
        alloc = SUB_STRATEGY_ALLOC_HK.get(regime, SUB_STRATEGY_ALLOC_HK[3])
        return {
            "hsi":      {"name": "恒生ETF (159920)", "pct": alloc["hsi"],      "position": round(total_position * alloc["hsi"] / 100, 1)},
            "hstech":   {"name": "恒生科技ETF (513130)", "pct": alloc["hstech"], "position": round(total_position * alloc["hstech"] / 100, 1)},
            "dividend": {"name": "恒生红利低波ETF (159545)", "pct": alloc["dividend"], "position": round(total_position * alloc["dividend"] / 100, 1)},
        }

    # ========== 信号系统 ==========

    def generate_signals(self, aiae_value: float, regime: int, slope_info: Dict, sb_heat: float) -> List[Dict]:
        signals = []
        ri = REGIMES_HK[regime]
        signals.append({
            "type": "main", "level": ri["emoji"],
            "text": f"{ri['cn']}信号 · HK AIAE={aiae_value:.1f}% · {ri['action']}",
            "color": ri["color"]
        })

        if slope_info.get("signal"):
            s = slope_info["signal"]
            signals.append({"type": "slope", "level": s["level"], "text": s["text"],
                          "color": "#f59e0b" if s["level"] == "warning" else "#10b981"})

        weekly_sb = self._southbound.get("weekly_net_buy_billion_rmb", 0)
        if weekly_sb > 40:
            signals.append({"type": "southbound", "level": "opportunity",
                          "text": f"南向资金强劲流入 {weekly_sb:.0f}亿/周", "color": "#10b981"})
        elif weekly_sb < -20:
            signals.append({"type": "southbound", "level": "warning",
                          "text": f"南向资金大幅流出 {abs(weekly_sb):.0f}亿/周", "color": "#ef4444"})

        ah_index = self._ah_premium.get("index_value", 130)
        if ah_index > 150:
            signals.append({"type": "ah_premium", "level": "opportunity",
                          "text": f"AH溢价{ah_index:.0f} → H股显著折价, 估值修复空间大", "color": "#10b981"})
        elif ah_index < 110:
            signals.append({"type": "ah_premium", "level": "warning",
                          "text": f"AH溢价仅{ah_index:.0f} → H股折价收窄, 吸引力下降", "color": "#f59e0b"})

        return signals

    # ========== 历史走势 ==========

    def get_chart_data(self) -> Dict:
        dates = [s["date"] for s in HISTORICAL_SNAPSHOTS]
        values = [s["aiae"] for s in HISTORICAL_SNAPSHOTS]
        labels = [s["label"] for s in HISTORICAL_SNAPSHOTS]
        bands = [
            {"name": "Ⅰ上限", "value": 8,  "color": "#10b981"},
            {"name": "Ⅱ上限", "value": 12, "color": "#3b82f6"},
            {"name": "Ⅲ上限", "value": 18, "color": "#eab308"},
            {"name": "Ⅳ上限", "value": 25, "color": "#f97316"},
        ]
        return {
            "dates": dates, "values": values, "labels": labels,
            "bands": bands,
            "stats": {"mean": 14.5, "min": 6.2, "max": 26.5,
                      "current": values[-1] if values else 14.0}
        }

    # ========== 交叉验证 ==========

    def _get_hk_erp_value(self) -> float:
        try:
            from erp_hk_engine import get_hk_erp_engine
            engine = get_hk_erp_engine("HSI")
            signal = engine.compute_signal()
            if signal.get("status") == "success":
                return signal["current_snapshot"].get("erp_value", 6.0)
        except Exception as e:
            _log(f"HK ERP引擎读取失败, 降级6.0%: {e}", "WARN")
        return 6.0

    def _cross_validate(self, regime: int, erp_value: float) -> Dict:
        erp_level = self.classify_erp_level(erp_value)

        if regime <= 2 and erp_value >= 8.0:
            confidence, verdict, color = 5, "极强买入 · 双因子共振", "#10b981"
        elif regime <= 2 and erp_value >= 6.0:
            confidence, verdict, color = 5, "强买入", "#10b981"
        elif regime <= 2 and erp_value >= 4.0:
            confidence, verdict, color = 4, "标准买入", "#34d399"
        elif regime <= 2 and erp_value < 4.0:
            confidence, verdict, color = 3, "谨慎买入 · ERP偏低", "#eab308"
        elif regime == 3 and erp_value >= 6.0:
            confidence, verdict, color = 3, "谨慎乐观", "#34d399"
        elif regime == 3 and 4.0 <= erp_value < 6.0:
            confidence, verdict, color = 3, "中性", "#94a3b8"
        elif regime == 3 and erp_value < 4.0:
            confidence, verdict, color = 3, "中性偏谨慎", "#eab308"
        elif regime == 4 and erp_value >= 6.0:
            confidence, verdict, color = 2, "矛盾信号 · 以AIAE为准", "#f97316"
        elif regime == 4 and erp_value < 6.0:
            confidence, verdict, color = 4, "强减仓", "#ef4444"
        elif regime == 5 and erp_value < 4.0:
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
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix='hk_aiae') as pool:
                f_mkt = pool.submit(self._fetch_hsi_market_cap)
                f_m2 = pool.submit(self._fetch_cn_m2_proxy)

            mkt_data = f_mkt.result(timeout=30)
            m2_data = f_m2.result(timeout=30)
            _log(f"数据获取完成 ({time.time()-t0:.1f}s)")

            mktcap_usd = mkt_data.get("mktcap_usd_trillion", 4.3)
            effective_m2 = m2_data.get("effective_m2_trillion_usd", 2.6)

            aiae_core = self.compute_aiae_core(mktcap_usd, effective_m2)

            sb_cumulative = self._southbound.get("cumulative_12m_billion_rmb", 350)
            sb_heat = self.compute_southbound_heat(sb_cumulative, mktcap_usd)

            ah_index = self._ah_premium.get("index_value", 135.0)
            ah_score = self.compute_ah_premium_score(ah_index)

            aiae_v1 = self.compute_hk_aiae_v1(aiae_core, sb_heat, ah_score)
            regime = self.classify_regime(aiae_v1)
            regime_info = REGIMES_HK[regime]

            prev_aiae = HISTORICAL_SNAPSHOTS[-2]["aiae"] if len(HISTORICAL_SNAPSHOTS) >= 2 else None
            slope_info = self.compute_slope(aiae_v1, prev_aiae)

            erp_value = self._get_hk_erp_value()
            erp_level = self.classify_erp_level(erp_value)
            matrix_position = self.get_position_from_matrix(regime, erp_level)

            allocations = self.allocate_sub_strategies(regime, matrix_position)
            signals = self.generate_signals(aiae_v1, regime, slope_info, sb_heat)
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
                    "mktcap_usd_trillion": mktcap_usd,
                    "effective_m2_trillion": effective_m2,
                    "southbound_heat": sb_heat,
                    "ah_premium": float(self._ah_premium.get("index_value", 135.0)),
                    "southbound": self._southbound,
                    "slope": slope_info,
                },

                "position": {
                    "matrix_position": matrix_position,
                    "erp_value": erp_value,
                    "erp_level": erp_level,
                    "regime": regime,
                    "matrix": POSITION_MATRIX_HK,
                    "allocations": allocations,
                },

                "signals": signals,
                "cross_validation": cross_validation,
                "chart": chart_data,
                "regimes": REGIMES_HK,

                "raw_data": {
                    "mkt": mkt_data,
                    "m2": m2_data,
                    "southbound": self._southbound,
                    "ah_premium": self._ah_premium,
                },
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
                "aiae_core": 14.0, "aiae_v1": 14.0, "regime": 3,
                "regime_info": REGIMES_HK[3],
                "mktcap_usd_trillion": 4.3, "effective_m2_trillion": 2.6,
                "southbound_heat": 1.0, "ah_premium": DEFAULT_AH_PREMIUM,
                "southbound": DEFAULT_SOUTHBOUND,
                "slope": {"slope": 0, "direction": "flat", "signal": None},
            },
            "position": {
                "matrix_position": 55, "erp_value": 6.0, "erp_level": "erp_6_8",
                "regime": 3, "matrix": POSITION_MATRIX_HK,
                "allocations": self.allocate_sub_strategies(3, 55),
            },
            "signals": [{"type": "fallback", "level": "warning",
                        "text": f"数据降级: {reason}", "color": "#f59e0b"}],
            "cross_validation": self._cross_validate(3, 6.0),
            "chart": self.get_chart_data(),
            "regimes": REGIMES_HK,
            "raw_data": {},
        }


# ===== 引擎单例 =====
_hk_aiae_instance = None

def get_hk_aiae_engine() -> AIAEHKEngine:
    global _hk_aiae_instance
    if _hk_aiae_instance is None:
        _hk_aiae_instance = AIAEHKEngine()
    return _hk_aiae_instance


# ===== 自检 =====
if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    engine = AIAEHKEngine()
    print("=== HK AIAE Engine V1.0 Self-Test ===")
    report = engine.generate_report()
    if report.get("status") in ("success", "fallback"):
        c = report["current"]
        p = report["position"]
        print(f"AIAE_Core: {c['aiae_core']}% | AIAE_V1: {c['aiae_v1']}%")
        print(f"Regime: {c['regime']} ({c['regime_info']['cn']})")
        print(f"MktCap: ${c['mktcap_usd_trillion']}T | Eff.M2: ${c['effective_m2_trillion']}T")
        print(f"SB Heat: {c['southbound_heat']}% | AH Premium: {c['ah_premium']}")
        print(f"Matrix Position: {p['matrix_position']}% (ERP={p['erp_value']}%)")
        cv = report["cross_validation"]
        print(f"Cross-Validation: {cv['verdict']} [{'*'*cv['confidence']}]")
        for s in report["signals"]:
            print(f"  > {s['text']}")
        print(f"\n--- Latency: {report.get('latency_ms', '?')}ms | Status: {report['status']} ---")
    else:
        print(f"Failed: {report.get('message')}")
