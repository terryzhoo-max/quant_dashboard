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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional, Dict, List

FRED_API_KEY = "eadf412d4f0e8ccd2bb3993b357bdca6"
CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

_jp_aiae_cache = {}
_jp_aiae_lock = threading.Lock()

def _log(msg: str, level: str = "INFO"):
    ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts_str}] [{level}] [JP-AIAE] {msg}")

def _cached(key: str, ttl_seconds: int, fetcher):
    now = time.time()
    with _jp_aiae_lock:
        if key in _jp_aiae_cache:
            ts_cached, data = _jp_aiae_cache[key]
            if now - ts_cached < ttl_seconds:
                return data
    try:
        data = fetcher()
        with _jp_aiae_lock:
            _jp_aiae_cache[key] = (now, data)
        return data
    except Exception as e:
        _log(f"缓存获取失敗 ({key}): {e}", "WARN")
        with _jp_aiae_lock:
            if key in _jp_aiae_cache:
                return _jp_aiae_cache[key][1]
        raise

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
HISTORICAL_SNAPSHOTS = [
    {"date": "1989-12-29", "aiae": 32.0, "nk_after_1y": -38, "label": "バブル崩壊直前"},
    {"date": "2003-04-28", "aiae":  8.5, "nk_after_1y": 47,  "label": "りそな危機底値"},
    {"date": "2006-01-16", "aiae": 21.5, "nk_after_1y":  2,  "label": "ライブドアショック前"},
    {"date": "2008-10-28", "aiae":  7.2, "nk_after_1y": 29,  "label": "リーマン底値"},
    {"date": "2012-11-14", "aiae":  8.0, "nk_after_1y": 56,  "label": "アベノミクス前夜"},
    {"date": "2018-01-23", "aiae": 19.5, "nk_after_1y": -12, "label": "日経24,000天井"},
    {"date": "2020-03-19", "aiae":  9.5, "nk_after_1y": 55,  "label": "COVID底値"},
    {"date": "2024-03-22", "aiae": 24.0, "nk_after_1y":  5,  "label": "日経41,000突破"},
    {"date": "2024-07-11", "aiae": 26.5, "nk_after_1y": -8,  "label": "バブル前兆"},
    {"date": "2026-04-06", "aiae": 17.5, "nk_after_1y": None,"label": "現在状態(推定)"},
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
    """日本 AIAE 宏観仓位管控引擎 V1.0"""

    VERSION = "1.0"
    REGION = "JP"

    def __init__(self):
        self._margin_data = self._load_jp_margin()
        self._foreign_data = self._load_jp_foreign()

    # ========== データ取得層 ==========

    def _fetch_topix_market_cap(self) -> Dict:
        """TOPIX/日経225 から推估時価総額 (FRED + yfinance フォールバック)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_jp_topix.json")

            # 1. yfinance で TOPIX ETF (1306.T) を取得
            try:
                import yfinance as yf
                topix = yf.Ticker("^TPX")
                hist = topix.history(period="5d")
                if hist is not None and not hist.empty:
                    latest = float(hist['Close'].iloc[-1])
                    # TOPIX 1点 ≈ 時価総額の比例; TOPIX 2800 ≈ 全市場900兆円
                    mktcap_trillion_jpy = round(latest / 2800 * 900, 1)
                    result = {
                        "trade_date": hist.index[-1].strftime("%Y-%m-%d"),
                        "topix_index": round(latest, 2),
                        "market_cap_trillion_jpy": mktcap_trillion_jpy,
                        "fetched_at": datetime.now().isoformat()
                    }
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    _log(f"TOPIX: {latest:.0f} (≈{mktcap_trillion_jpy}兆円)")
                    return result
            except Exception as e:
                _log(f"yfinance TOPIX error: {e}", "WARN")

            # 2. FRED Nikkei225 フォールバック
            fred = _get_fred()
            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=30)
                    series = fred.get_series("NIKKEI225", observation_start=start_dt)
                    if series is not None and not series.empty:
                        series = series.dropna()
                        latest = float(series.iloc[-1])
                        # N225 40000 ≈ TOPIX 2800 ≈ 900兆円
                        mktcap = round(latest / 40000 * 900, 1)
                        result = {
                            "trade_date": series.index[-1].strftime("%Y-%m-%d"),
                            "topix_index": round(latest / 14.3, 2),
                            "nikkei225": round(latest, 2),
                            "market_cap_trillion_jpy": mktcap,
                            "fetched_at": datetime.now().isoformat()
                        }
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            json.dump(result, f, ensure_ascii=False, indent=2)
                        _log(f"N225→TOPIX推估: {mktcap}兆円")
                        return result
                except Exception as e:
                    _log(f"FRED NIKKEI225 error: {e}", "WARN")

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

        return _cached("jp_aiae_topix", 86400, _fetch)

    def _fetch_jp_m2(self) -> Dict:
        """日本M2 (FRED MYAGM2JPM189N, 月頻)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "aiae_jp_m2.json")
            fred = _get_fred()
            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=180)
                    series = fred.get_series("MYAGM2JPM189N", observation_start=start_dt)
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
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            json.dump(result, f, ensure_ascii=False, indent=2)
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

        return _cached("jp_aiae_m2", 7 * 86400, _fetch)

    def _load_jp_margin(self) -> Dict:
        """信用取引残高（固定推定値 / 手動更新）"""
        if os.path.exists(JP_MARGIN_FILE):
            try:
                with open(JP_MARGIN_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                _log(f"JP Margin loaded: {data.get('margin_buying_trillion_jpy', 0)}兆円")
                return data
            except Exception:
                pass
        _log("JP Margin: 使用デフォルト推定値", "WARN")
        return DEFAULT_JP_MARGIN.copy()

    def _load_jp_foreign(self) -> Dict:
        """外国人投資家フロー（固定推定値 / 手動更新）"""
        if os.path.exists(JP_FOREIGN_FILE):
            try:
                with open(JP_FOREIGN_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                _log(f"JP Foreign loaded: net={data.get('net_buy_billion_jpy', 0)}億円")
                return data
            except Exception:
                pass
        _log("JP Foreign: 使用デフォルト推定値", "WARN")
        return DEFAULT_JP_FOREIGN.copy()

    def update_jp_margin(self, margin_buying_trillion_jpy: float):
        """手動更新 信用取引残高"""
        data = {
            "margin_buying_trillion_jpy": round(margin_buying_trillion_jpy, 2),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "source": "manual"
        }
        with open(JP_MARGIN_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
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
        with open(JP_FOREIGN_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._foreign_data = data
        _log(f"JP Foreign 手動更新: net={net_buy_billion_jpy}億円")

    # ========== 核心計算層 ==========

    def compute_aiae_core(self, mktcap_trillion_jpy: float, m2_trillion_jpy: float) -> float:
        """JP_AIAE_Core = TOPIX市值 / (TOPIX市値 + 日本M2)"""
        if m2_trillion_jpy <= 0:
            return 17.0
        return round(mktcap_trillion_jpy / (mktcap_trillion_jpy + m2_trillion_jpy) * 100, 2)

    def compute_margin_heat(self, margin_trillion: float, mktcap_trillion: float) -> float:
        """信用取引熱度 = 融資残高 / 時価総額 × 100"""
        if mktcap_trillion <= 0:
            return 0.4
        return round(margin_trillion / mktcap_trillion * 100, 2)

    def normalize_foreign_flow(self, net_buy_billion: float) -> float:
        """
        外資フロー正規化 → AIAE等効値
        年間累計 -1兆円~+3兆円 → 10-40% AIAE等効
        """
        # 周次 net_buy: -5000～+5000 億円が典型
        normalized = 10 + (net_buy_billion - (-5000)) / (5000 - (-5000)) * (40 - 10)
        return max(10, min(40, round(normalized, 2)))

    def compute_jp_aiae_v1(self, aiae_core: float, margin_heat: float, foreign_flow_norm: float) -> float:
        """
        JP AIAE V1.0 融合
        = 0.5 × AIAE_Core + 0.2 × Margin_正規化 + 0.3 × 外資フロー正規化
        """
        # Margin正規化: 0.2-0.8% → 10-40%
        m_norm = 10 + (margin_heat - 0.2) / (0.8 - 0.2) * (40 - 10)
        m_norm = max(10, min(40, m_norm))

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

            prev_aiae = HISTORICAL_SNAPSHOTS[-2]["aiae"] if len(HISTORICAL_SNAPSHOTS) >= 2 else None
            slope_info = self.compute_slope(aiae_v1, prev_aiae)

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
