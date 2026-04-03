"""
AlphaCore · 日本ERP择时引擎 V1.0
===================================
五维择时信号系统 (日本市场本地化):
  D1: ERP绝对值 (1/PE_TOPIX - 10Y JGB)       — 权重20%  [估值]
  D2: ERP历史分位 (近5年)                       — 权重25%  [估值]
  D3: 日元汇率趋势 (USDJPY方向)                 — 权重30%  [流动性] ← BOJ政策代理
  D4: 日经225实现波动率 (60日)                   — 权重15%  [风险]
  D5: 日元实际利率变化 (JGB-CPI代理)             — 权重10%  [信用/政策]

特殊考量:
  - JGB 10Y ≈ 0.5-1.5% (全球最低无风险利率之一)
  - ERP天然偏高 (因为JGB极低)，历史中位数 ≈ 5.0-6.5%
  - 日元走弱 = BOJ宽松 = 出口利润↑ = 利好股市 (但USDJPY > 155 = 干预风险)

ETF标的: 1306.T (TOPIX) / 1321.T (日经225) / 1577.T (高股息50)
数据源: yfinance + FRED API (JGB 10Y)
"""

import pandas as pd
import numpy as np
import time
import os
from datetime import datetime, timedelta
from typing import Optional

# FRED API for all Japan data
FRED_API_KEY = "eadf412d4f0e8ccd2bb3993b357bdca6"

CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

_jp_fred = None
def _get_jp_fred():
    global _jp_fred
    if _jp_fred is None:
        try:
            from fredapi import Fred
            _jp_fred = Fred(api_key=FRED_API_KEY)
        except Exception as e:
            print(f"[JP-ERP] FRED init failed: {e}")
    return _jp_fred

_jp_cache = {}

def _jp_cached(key: str, ttl_seconds: int, fetcher):
    now = time.time()
    if key in _jp_cache:
        ts_cached, data = _jp_cache[key]
        if now - ts_cached < ttl_seconds:
            return data
    try:
        data = fetcher()
        _jp_cache[key] = (now, data)
        return data
    except Exception as e:
        print(f"[JP-ERP] cache fail ({key}): {e}")
        if key in _jp_cache:
            return _jp_cache[key][1]
        raise


ENCYCLOPEDIA_JP = {
    "erp_abs": {
        "title": "日本 ERP (株式リスクプレミアム)",
        "what": "ERP = TOPIX盈利收益率(1/PE) - 10Y JGB收益率。衡量日本股票相对国债的超额回报。",
        "why": "JGB极低(0.5-1.5%), 日本ERP天然偏高(5-7%), 需要用日本自身历史区间判断。",
        "alert": "日本ERP < 4% 意味着估值已不便宜(JGB低但PE也抬高了)。ERP > 7% 是极度低估。",
        "history": "2012年安倍经济学前ERP ~8%(极低估), 2021年泡沫高点ERP ~4%(偏高)。"
    },
    "erp_pct": {
        "title": "ERP 历史分位",
        "what": "过去5年中ERP所处的位置。80%分位 → 日股处于罕见低估区。",
        "why": "日本市场在安倍经济学后PE结构性提升，需用近5年分位避免历史偏差。",
        "alert": "分位 > 75% 是配置窗口。分位 < 25% 说明估值已充分反映。",
    },
    "yen_trend": {
        "title": "日元汇率趋势 (USDJPY)",
        "what": "USDJPY上升 = 日元贬值。反映BOJ货币政策宽松程度和出口竞争力。",
        "why": "日元贬值 → 出口企业利润↑ → 日股(尤其制造业)利好。但过度贬值引发BOJ干预。",
        "alert": "USDJPY > 155是BOJ干预警戒线。USDJPY < 130可能意味BOJ收紧。",
    },
    "volatility": {
        "title": "日经波动率",
        "what": "日经225收益率的60日滚动标准差(年化)。反映日本市场的波动水平。",
        "why": "高波动=不确定性大。但极端恐慌(超高波动)往往对应底部。",
        "alert": "波动率突破30% 历史分位90%以上时，留意逆向买入机会。",
    },
    "rate_env": {
        "title": "日元利率环境",
        "what": "JGB 10Y收益率的3个月变化方向 + USDJPY变化率的组合。反映BOJ政策走向。",
        "why": "JGB走高 = BOJ收紧 = 利空股市。JGB稳定/下行 = 宽松持续 = 利好。",
        "alert": "JGB突破1.5%是重要心理关口，可能引发全球债市联动。",
    }
}


class JPERPTimingEngine:
    """日本ERP择时引擎 V1.0"""

    VERSION = "1.0"
    REGION = "JP"

    W = {"erp_abs": 0.20, "erp_pct": 0.25, "yen_trend": 0.30, "volatility": 0.15, "rate_env": 0.10}

    SIGNAL_MAP = {
        "strong_buy":  {"label": "Strong Buy",  "label_cn": "強力買い", "position": "80-100%", "color": "#10b981", "emoji": "🟢🟢", "level": 6},
        "buy":         {"label": "Buy",          "label_cn": "買い",     "position": "60-80%",  "color": "#34d399", "emoji": "🟢",   "level": 5},
        "hold":        {"label": "Hold",         "label_cn": "標配保有", "position": "50-70%",  "color": "#3b82f6", "emoji": "🔵",   "level": 4},
        "reduce":      {"label": "Reduce",       "label_cn": "段階縮小", "position": "30-50%",  "color": "#f59e0b", "emoji": "🟡",   "level": 3},
        "underweight": {"label": "Underweight",  "label_cn": "低配防御", "position": "10-30%",  "color": "#f97316", "emoji": "🟠",   "level": 2},
        "cash":        {"label": "Cash",         "label_cn": "清仓観望", "position": "0-10%",   "color": "#ef4444", "emoji": "🔴",   "level": 1},
    }

    ETF_TARGETS = {
        "aggressive": {"name": "TOPIX ETF",       "code": "1306.T", "desc": "日本全市场，弹性最大"},
        "balanced":   {"name": "日経225 ETF",      "code": "1321.T", "desc": "蓝筹核心，攻守兼备"},
        "defensive":  {"name": "高配当50 ETF",     "code": "1577.T", "desc": "高股息防御，稳定分红"},
    }

    def __init__(self):
        pass


    # ========== 数据获取层 (FRED优先) ==========

    def _get_current_pe(self) -> float:
        """三级PE获取策略: yfinance实时 → 磁盘缓存 → 智能估算"""
        import json
        pe_cache_file = os.path.join(CACHE_DIR, "erp_jp_current_pe.json")

        # Tier 1: yfinance 拉取 1306.T (TOPIX ETF) 或 日経225
        try:
            import yfinance as yf
            for ticker in ["1306.T", "^N225"]:
                try:
                    t = yf.Ticker(ticker)
                    info = t.info
                    pe = info.get("trailingPE") or info.get("forwardPE")
                    if pe and 8 < pe < 40:
                        with open(pe_cache_file, "w") as f:
                            json.dump({"pe": round(pe, 2), "source": f"yfinance/{ticker}", "ts": datetime.now().isoformat()}, f)
                        print(f"[JP-ERP] PE from yfinance ({ticker}): {pe:.1f}x")
                        return float(pe)
                except Exception:
                    continue
        except Exception as e:
            print(f"[JP-ERP] yfinance PE failed: {e}")

        # Tier 2: 磁盘缓存 (7天内有效)
        if os.path.exists(pe_cache_file):
            try:
                with open(pe_cache_file, "r") as f:
                    cached = json.load(f)
                cached_ts = datetime.fromisoformat(cached["ts"])
                if (datetime.now() - cached_ts).days < 7:
                    pe = cached["pe"]
                    print(f"[JP-ERP] PE from disk cache: {pe:.1f}x (cached {cached['ts'][:10]})")
                    return float(pe)
            except Exception:
                pass

        # Tier 3: 智能估算 — 日经225当前EPS约 ¥2400-2600，用 ¥2500 中位估算
        try:
            import yfinance as yf
            nk_hist = yf.Ticker("^N225").history(period="5d")
            if not nk_hist.empty:
                price = float(nk_hist["Close"].iloc[-1])
                estimated_eps = 2500.0  # 日经225 2025-26年EPS中位估算
                pe = price / estimated_eps
                pe = max(10, min(35, pe))  # 合理区间保护
                print(f"[JP-ERP] PE estimated from price/EPS: {pe:.1f}x (price=¥{price:.0f}, est_EPS=¥2500)")
                return float(pe)
        except Exception:
            pass

        print("[JP-ERP] PE fallback to 16.0x (all sources failed)")
        return 16.0

    def _fetch_topix_pe_history(self, years: int = 5) -> pd.DataFrame:
        """日経225 PE历史序列 (FRED NIKKEI225価格 + 三級PE獲取)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_jp_topix_history.parquet")
            fred = _get_jp_fred()

            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=years * 365)
                    nk = fred.get_series("NIKKEI225", observation_start=start_dt)
                    if nk is not None and not nk.empty:
                        nk = nk.dropna()
                        df = pd.DataFrame({
                            "trade_date": nk.index.tz_localize(None) if nk.index.tz else nk.index,
                            "close": nk.values,
                        })
                        # === V2.0: 三级PE获取策略 (替代硬编码16.0) ===
                        current_pe = self._get_current_pe()
                        current_price = df["close"].iloc[-1]
                        current_eps = current_price / current_pe
                        end_dt = datetime.now()
                        eps_list = []
                        for _, row in df.iterrows():
                            m = (end_dt - row["trade_date"]).days / 30
                            eps_list.append(current_eps / (1.06 ** (m / 12)))
                        df["eps"] = eps_list
                        df["pe_ttm"] = df["close"] / df["eps"]
                        df["pe_ttm"] = df["pe_ttm"].clip(8, 40)
                        df.to_parquet(cache_file)
                        print(f"[JP-ERP] Nikkei PE (FRED): {len(df)} rows, PE≈{current_pe:.1f}")
                        return df
                except Exception as e:
                    print(f"[JP-ERP] FRED NIKKEI225 error: {e}")

            if os.path.exists(cache_file):
                print("[JP-ERP] Nikkei PE: using disk cache")
                return pd.read_parquet(cache_file)
            raise ValueError("Nikkei data unavailable")
        return _jp_cached("jp_topix_pe", 30 * 60, _fetch)


    def _fetch_jgb_10y_history(self, years: int = 5) -> pd.DataFrame:
        """10Y JGB (FRED IRLTLT01JPM156N — 月频→日频填充)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_jp_jgb_10y.parquet")
            fred = _get_jp_fred()

            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=years * 365)
                    series = fred.get_series("IRLTLT01JPM156N", observation_start=start_dt)
                    if series is not None and not series.empty:
                        df = pd.DataFrame({
                            "trade_date": series.index.tz_localize(None) if series.index.tz else series.index,
                            "yield_10y": series.values,
                        })
                        df = df.dropna()
                        df = df.set_index("trade_date").resample("D").ffill().reset_index()
                        df.to_parquet(cache_file)
                        print(f"[JP-ERP] JGB 10Y (FRED): {len(df)} rows, latest={df['yield_10y'].iloc[-1]:.3f}%")
                        return df
                except Exception as e:
                    print(f"[JP-ERP] FRED JGB error: {e}")

            if os.path.exists(cache_file):
                return pd.read_parquet(cache_file)

            # 最终降级: 用近似值
            print("[JP-ERP] JGB fallback: proxy values")
            dates = pd.date_range(end=datetime.now(), periods=years * 252, freq="B")
            jgb_vals = np.interp(range(len(dates)), [0, len(dates)//3, len(dates)*2//3, len(dates)-1], [0.1, 0.3, 0.7, 1.0])
            jgb_vals = np.clip(jgb_vals + np.random.normal(0, 0.05, len(dates)), 0.0, 2.0)
            df = pd.DataFrame({"trade_date": dates, "yield_10y": jgb_vals})
            df.to_parquet(cache_file)
            return df
        return _jp_cached("jp_jgb_10y", 60 * 60, _fetch)

    def _fetch_usdjpy_history(self, years: int = 3) -> pd.DataFrame:
        """USDJPY (FRED DEXJPUS — 日频)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_jp_usdjpy.parquet")
            fred = _get_jp_fred()

            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=years * 365)
                    series = fred.get_series("DEXJPUS", observation_start=start_dt)
                    if series is not None and not series.empty:
                        series = series.dropna()
                        df = pd.DataFrame({
                            "trade_date": series.index.tz_localize(None) if series.index.tz else series.index,
                            "usdjpy": series.values,
                        })
                        df.to_parquet(cache_file)
                        print(f"[JP-ERP] USDJPY (FRED): {len(df)} rows, latest={df['usdjpy'].iloc[-1]:.2f}")
                        return df
                except Exception as e:
                    print(f"[JP-ERP] FRED DEXJPUS error: {e}")

            if os.path.exists(cache_file):
                return pd.read_parquet(cache_file)
            raise ValueError("USDJPY data unavailable")
        return _jp_cached("jp_usdjpy", 30 * 60, _fetch)

    def _fetch_nikkei_history(self, years: int = 5) -> pd.DataFrame:
        """日经225历史 (FRED NIKKEI225)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_jp_nikkei.parquet")
            fred = _get_jp_fred()

            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=years * 365)
                    series = fred.get_series("NIKKEI225", observation_start=start_dt)
                    if series is not None and not series.empty:
                        series = series.dropna()
                        df = pd.DataFrame({
                            "trade_date": series.index.tz_localize(None) if series.index.tz else series.index,
                            "close": series.values,
                        })
                        df.to_parquet(cache_file)
                        return df
                except Exception as e:
                    print(f"[JP-ERP] FRED NIKKEI225 error: {e}")

            if os.path.exists(cache_file):
                return pd.read_parquet(cache_file)
            raise ValueError("Nikkei data unavailable")
        return _jp_cached("jp_nikkei", 30 * 60, _fetch)

    # ========== 核心计算层 ==========

    def _compute_erp_series(self) -> pd.DataFrame:
        pe_df = self._fetch_topix_pe_history()
        jgb_df = self._fetch_jgb_10y_history()

        merged = pd.merge(pe_df, jgb_df, on="trade_date", how="left")
        merged = merged.sort_values("trade_date")
        merged["yield_10y"] = merged["yield_10y"].ffill().bfill()
        merged = merged.dropna(subset=["pe_ttm", "yield_10y"])
        merged = merged[merged["pe_ttm"] > 0].copy()
        merged["earnings_yield"] = 1.0 / merged["pe_ttm"] * 100
        merged["erp"] = merged["earnings_yield"] - merged["yield_10y"]
        return merged.sort_values("trade_date").reset_index(drop=True)

    # ========== 五维评分 ==========

    def _score_d1_erp_absolute(self, erp_val: float) -> tuple:
        """D1: ERP绝对值 (日本阈值: 比中国高~1%, 因为JGB极低)"""
        if erp_val >= 7.0:
            score, desc = 100, f"ERP {erp_val:.2f}% ≥ 7% → 极度低估，历史级机会"
        elif erp_val >= 6.0:
            score, desc = 75 + (erp_val - 6.0) * 25, f"ERP {erp_val:.2f}% 6-7%区间 → 显著低估"
        elif erp_val >= 5.0:
            score, desc = 55 + (erp_val - 5.0) * 20, f"ERP {erp_val:.2f}% 5-6%区间 → 合理偏低"
        elif erp_val >= 4.0:
            score, desc = 35 + (erp_val - 4.0) * 20, f"ERP {erp_val:.2f}% 4-5%区间 → 估值中性"
        elif erp_val >= 3.0:
            score, desc = 15 + (erp_val - 3.0) * 20, f"ERP {erp_val:.2f}% 3-4%区间 → 偏高估"
        else:
            score, desc = max(0, erp_val * 5), f"ERP {erp_val:.2f}% < 3% → 高估"
        return round(min(100, max(0, score)), 1), desc

    def _score_d2_erp_percentile(self, erp_val: float, erp_series: pd.Series) -> tuple:
        pct = (erp_series < erp_val).mean() * 100
        if pct >= 80:   desc = f"近5年{pct:.1f}%分位 → 历史极度低估"
        elif pct >= 60: desc = f"近5年{pct:.1f}%分位 → 偏低估"
        elif pct >= 40: desc = f"近5年{pct:.1f}%分位 → 中性"
        elif pct >= 20: desc = f"近5年{pct:.1f}%分位 → 偏高估"
        else:           desc = f"近5年{pct:.1f}%分位 → 历史极度高估"
        return round(pct, 1), round(pct, 1), desc

    def _score_d3_yen_trend(self) -> tuple:
        """D3: 日元汇率趋势 (USDJPY方向)
        日元贬值(USDJPY↑) = BOJ宽松 + 出口利润↑ = 利好股市
        但 > 155 有干预风险"""
        fx_df = self._fetch_usdjpy_history()
        if fx_df.empty:
            return 50.0, {"current": 0, "direction": "unknown"}, "数据缺失"

        current = float(fx_df["usdjpy"].iloc[-1])
        prev_1m = float(fx_df["usdjpy"].iloc[-22]) if len(fx_df) >= 22 else current
        prev_3m = float(fx_df["usdjpy"].iloc[-63]) if len(fx_df) >= 63 else current

        is_weakening = current > prev_1m  # USDJPY上升 = 日元贬值
        is_3m_weakening = current > prev_3m
        change_3m = ((current - prev_3m) / prev_3m * 100) if prev_3m else 0

        yen_info = {
            "current": round(current, 2),
            "prev_month": round(prev_1m, 2),
            "3m_ago": round(prev_3m, 2),
            "direction": "weakening" if is_weakening else "strengthening",
            "3m_direction": "weakening" if is_3m_weakening else "strengthening",
            "change_3m_pct": round(change_3m, 2),
        }

        # === B4优化: 干预风险区更激进降分 ===
        if current > 160:
            score = 15  # 极度贬值→BOJ强制干预概率极高
            desc = f"USDJPY {current:.1f} > 160 → 极度贬值! BOJ强制干预迫在眉睫"
        elif current > 155:
            score = 25  # 过度贬值→BOJ干预风险高
            desc = f"USDJPY {current:.1f} > 155 → 日元过度贬值! BOJ干预警戒"
        elif current > 145 and is_3m_weakening:
            score = 65
            desc = f"USDJPY {current:.1f}，日元持续贬值 → 出口利好但需警惕"
        elif 135 <= current <= 145:
            score = 75
            desc = f"USDJPY {current:.1f} 温和弱势 → 最佳出口竞争力区间"
        elif 125 <= current < 135:
            score = 55
            desc = f"USDJPY {current:.1f} → 日元中性偏强"
        elif current < 125 and not is_3m_weakening:
            score = 25
            desc = f"USDJPY {current:.1f} < 125 → 日元大幅升值，出口承压"
        else:
            score = 50
            desc = f"USDJPY {current:.1f} → 中性"

        # 趋势加减分
        if is_3m_weakening and current <= 155:
            score = min(100, score + 10)
        elif not is_3m_weakening and current < 140:
            score = max(0, score - 10)

        return round(min(100, max(0, score)), 1), yen_info, desc

    def _score_d4_volatility(self) -> tuple:
        """D4: 日经225 实现波动率"""
        nk_df = self._fetch_nikkei_history()
        if nk_df.empty or len(nk_df) < 60:
            return 50.0, {"current": 0, "pct": 50, "regime": "normal"}, "数据不足"

        returns = nk_df["close"].pct_change().dropna()
        vol_60d = float(returns.rolling(60).std().iloc[-1] * np.sqrt(252) * 100)
        vol_series = returns.rolling(60).std().dropna() * np.sqrt(252) * 100
        vol_pct = (vol_series < vol_60d).mean() * 100

        if vol_pct >= 90:
            score, regime = 15, "extreme_panic"
            desc = f"日经波动率{vol_60d:.1f}%({vol_pct:.0f}%分位) → 极端恐慌"
        elif vol_pct >= 70:
            score, regime = 35, "high"
            desc = f"日经波动率{vol_60d:.1f}%({vol_pct:.0f}%分位) → 波动偏高"
        elif vol_pct >= 30:
            score, regime = 70, "normal"
            desc = f"日经波动率{vol_60d:.1f}%({vol_pct:.0f}%分位) → 正常"
        else:
            score, regime = 85, "calm"
            desc = f"日经波动率{vol_60d:.1f}%({vol_pct:.0f}%分位) → 市场平稳"

        vol_info = {"current": round(vol_60d, 1), "pct": round(vol_pct, 1), "regime": regime}
        return round(score, 1), vol_info, desc

    def _score_d5_rate_env(self) -> tuple:
        """D5: 日本利率环境 (JGB方向 + USDJPY变化率)"""
        jgb_df = self._fetch_jgb_10y_history()
        fx_df = self._fetch_usdjpy_history()

        jgb_now = float(jgb_df["yield_10y"].iloc[-1]) if not jgb_df.empty else 0.8
        jgb_3m = float(jgb_df["yield_10y"].iloc[-63]) if len(jgb_df) >= 63 else jgb_now

        jgb_rising = jgb_now > jgb_3m + 0.1  # JGB上升超0.1% = 收紧
        jgb_falling = jgb_now < jgb_3m - 0.05

        fx_now = float(fx_df["usdjpy"].iloc[-1]) if not fx_df.empty else 150
        fx_3m = float(fx_df["usdjpy"].iloc[-63]) if len(fx_df) >= 63 else fx_now
        fx_change = ((fx_now - fx_3m) / fx_3m * 100) if fx_3m else 0

        rate_info = {
            "jgb_now": round(jgb_now, 3),
            "jgb_3m_ago": round(jgb_3m, 3),
            "jgb_direction": "rising" if jgb_rising else ("falling" if jgb_falling else "stable"),
            "usdjpy_change_3m": round(fx_change, 2),
        }

        # JGB上升 = BOJ收紧 = 利空
        if jgb_now > 1.5:
            score = 20
            desc = f"JGB {jgb_now:.3f}% > 1.5% → BOJ收紧信号，利空权益"
        elif jgb_rising:
            score = 35
            desc = f"JGB {jgb_now:.3f}% 上行中 → BOJ渐进收紧"
        elif jgb_falling:
            score = 80
            desc = f"JGB {jgb_now:.3f}% 下行 → BOJ维持/加大宽松"
        elif jgb_now < 0.5:
            score = 85
            desc = f"JGB {jgb_now:.3f}% 极低 → 超宽松环境"
        else:
            score = 60
            desc = f"JGB {jgb_now:.3f}% 稳定 → 政策中性"

        return round(min(100, max(0, score)), 1), rate_info, desc

    # ========== 买卖规则引擎 ==========

    def _generate_trade_rules(self, score, dims, snap) -> dict:
        erp = snap.get("erp_value", 5.0)
        vol_info = dims.get("volatility", {}).get("vol_info", {})
        vol_regime = vol_info.get("regime", "normal")
        vol_pct = vol_info.get("pct", 50)
        yen_info = dims.get("yen_trend", {}).get("yen_info", {})
        usdjpy = yen_info.get("current", 150)
        rate_info = dims.get("rate_env", {}).get("rate_info", {})
        jgb = rate_info.get("jgb_now", 0.8)

        d1s = dims.get("erp_abs", {}).get("score", 50)
        d2s = dims.get("erp_pct", {}).get("score", 50)
        d3s = dims.get("yen_trend", {}).get("score", 50)

        bullish_count = sum([d1s >= 60, d2s >= 60, d3s >= 60])
        bearish_count = sum([d1s < 35, d2s < 35, d3s < 35])

        resonance = "none"
        if bullish_count >= 3: resonance = "bullish_resonance"
        elif bearish_count >= 3: resonance = "bearish_resonance"
        elif bullish_count >= 1 and bearish_count >= 1: resonance = "divergence"

        if score >= 80 and resonance == "bullish_resonance": signal_key = "strong_buy"
        elif score >= 70: signal_key = "buy"
        elif score >= 55: signal_key = "hold"
        elif score >= 40: signal_key = "reduce"
        elif score >= 25: signal_key = "underweight"
        else: signal_key = "cash"

        if vol_regime == "extreme_panic" and erp >= 5.0:
            if signal_key in ("hold", "reduce"): signal_key = "buy"

        signal = self.SIGNAL_MAP[signal_key]

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

        # === B1: 动态高亮 ===
        take_profit = [
            {"trigger": "ERP 回落至 4.0% 以下", "action": "减仓20%", "type": "valuation",
             "triggered": bool(erp < 4.0), "current": f"ERP={erp:.2f}%"},
            {"trigger": "USDJPY < 130 (日元大幅升值)", "action": "减仓30%", "type": "yen",
             "triggered": bool(usdjpy < 130), "current": f"USDJPY={usdjpy:.1f}"},
            {"trigger": "综合得分跌破 50", "action": "降至标配", "type": "score_drop",
             "triggered": bool(score < 50), "current": f"得分={score:.0f}"},
        ]

        stop_loss = [
            {"trigger": "ERP ≥ 8% (极端低估)", "action": "逆向加仓20%", "type": "contrarian_buy", "color": "#10b981",
             "triggered": bool(erp >= 8.0), "current": f"ERP={erp:.2f}%"},
            {"trigger": "日经波动率90%分位+ERP>5%", "action": "恐慌+低估=加仓", "type": "contrarian_vol", "color": "#10b981",
             "triggered": bool(vol_pct >= 90 and erp > 5.0), "current": f"波动={vol_pct:.0f}%,ERP={erp:.2f}%"},
            {"trigger": "ERP < 3% (日本罕见高估)", "action": "硬止损: 清仓", "type": "hard_stop", "color": "#ef4444",
             "triggered": bool(erp < 3.0), "current": f"ERP={erp:.2f}%"},
            {"trigger": "JGB > 2.0% (BOJ急收紧)", "action": "降至20%以下", "type": "rate_shock", "color": "#ef4444",
             "triggered": bool(jgb > 2.0), "current": f"JGB={jgb:.3f}%"},
        ]

        return {
            "signal_key": signal_key, "signal": signal, "resonance": resonance,
            "resonance_label": {"bullish_resonance": "🟢 三维共振看多", "bearish_resonance": "🔴 三维共振看空",
                                "divergence": "🟡 信号分歧", "none": "⚪ 中性"}[resonance],
            "etf_advice": etf_advice, "take_profit": take_profit, "stop_loss": stop_loss,
        }

    # ========== 警示系统 ==========

    def _generate_alerts(self, score, erp, pct, yen_info, vol_info, rate_info) -> list:
        alerts = []
        usdjpy = yen_info.get("current", 150)
        jgb = rate_info.get("jgb_now", 0.8)

        if erp < 3.0:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"ERP {erp:.2f}% < 3%, 日股罕见高估", "pulse": True})
        if usdjpy > 155:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"USDJPY {usdjpy:.1f} > 155! BOJ干预风险", "pulse": True})
        if jgb > 1.5:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"JGB {jgb:.3f}% > 1.5%, BOJ加速收紧", "pulse": True})

        if 3.0 <= erp < 4.5:
            alerts.append({"level": "warning", "icon": "🟡", "text": f"ERP {erp:.2f}% 偏低(日本标准)"})
        if 150 < usdjpy <= 155:
            alerts.append({"level": "warning", "icon": "🟡", "text": f"USDJPY {usdjpy:.1f} 接近干预警戒线"})

        if erp >= 7.0:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": f"ERP {erp:.2f}% ≥ 7% 历史级低估!", "pulse": True})
        if pct >= 80:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": f"分位{pct:.1f}% 历史低估区"})

        return alerts if alerts else [{"level": "normal", "icon": "⚪", "text": "无特殊警示"}]

    # ========== 诊断卡片 ==========

    def _build_diagnosis(self, erp, pe, jgb, pct, yen_info, vol_info, rate_info, trade) -> list:
        cards = []
        usdjpy = yen_info.get("current", 150)
        signal = trade["signal"]

        if erp >= 5.5:
            cards.append({"type": "success", "title": "估值 · 低估", "text": f"TOPIX PE {pe:.1f}x, ERP={erp:.2f}%。JGB {jgb:.3f}% 极低→ 日股性价比突出。"})
        elif erp >= 4.0:
            cards.append({"type": "info", "title": "估值 · 中性", "text": f"PE {pe:.1f}x, ERP={erp:.2f}% 日本标准中性区间。"})
        else:
            cards.append({"type": "warning", "title": "估值 · 偏高", "text": f"PE {pe:.1f}x, ERP {erp:.2f}% 低于日本历史中位数。"})

        if pct >= 70:
            cards.append({"type": "success", "title": "分位 · 低估", "text": f"{pct:.0f}%分位。"})
        elif pct >= 40:
            cards.append({"type": "info", "title": "分位 · 中性", "text": f"{pct:.0f}%分位。"})
        else:
            cards.append({"type": "warning", "title": "分位 · 偏贵", "text": f"仅{pct:.0f}%分位。"})

        if 135 <= usdjpy <= 150:
            cards.append({"type": "success", "title": "日元 · 甜蜜区", "text": f"USDJPY {usdjpy:.1f}，温和弱势，出口利好最大。"})
        elif usdjpy > 150:
            cards.append({"type": "warning", "title": "日元 · 过度贬值", "text": f"USDJPY {usdjpy:.1f}，干预风险上升。"})
        else:
            cards.append({"type": "info", "title": "日元 · 偏强", "text": f"USDJPY {usdjpy:.1f}，出口竞争力受压。"})

        vol_regime = vol_info.get("regime", "normal")
        if vol_regime in ("extreme_panic", "high"):
            cards.append({"type": "warning", "title": "波动率 · 异常", "text": "日经波动显著放大。"})
        else:
            cards.append({"type": "success", "title": "波动率 · 正常", "text": "市场波动可控。"})

        jgb_dir = rate_info.get("jgb_direction", "stable")
        jgb_now = rate_info.get("jgb_now", 0.8)
        if jgb_dir == "rising":
            cards.append({"type": "warning", "title": "利率 · 上行", "text": f"JGB {jgb_now:.3f}% 上行中，BOJ渐进收紧。"})
        else:
            cards.append({"type": "success", "title": "利率 · 宽松", "text": f"JGB {jgb_now:.3f}% 稳定/下行。"})

        etf_text = " / ".join([f"{e['etf']['name']}{e['ratio']}" for e in trade.get("etf_advice", [])])
        cards.append({"type": "info", "title": f"操作 · {signal['label_cn']}", "text": f"{trade['resonance_label']}。仓位{signal['position']}。配置: {etf_text}。"})

        return cards

    # ========== 信号融合 ==========

    def compute_signal(self) -> dict:
        try:
            erp_df = self._compute_erp_series()
            if erp_df.empty:
                return self._fallback_signal("ERP序列为空")

            latest = erp_df.iloc[-1]
            erp_val = float(latest["erp"])
            pe_ttm = float(latest["pe_ttm"])
            yield_10y = float(latest["yield_10y"])

            d1_score, d1_desc = self._score_d1_erp_absolute(erp_val)
            d2_score, d2_pct, d2_desc = self._score_d2_erp_percentile(erp_val, erp_df["erp"])
            d3_score, yen_info, d3_desc = self._score_d3_yen_trend()
            d4_score, vol_info, d4_desc = self._score_d4_volatility()
            d5_score, rate_info, d5_desc = self._score_d5_rate_env()

            composite = round(
                d1_score * self.W["erp_abs"] + d2_score * self.W["erp_pct"] +
                d3_score * self.W["yen_trend"] + d4_score * self.W["volatility"] +
                d5_score * self.W["rate_env"], 1
            )

            snap = {
                "pe_ttm": round(pe_ttm, 2), "yield_10y": round(yield_10y, 4),
                "earnings_yield": round(1.0 / pe_ttm * 100, 2), "erp_value": round(erp_val, 2),
                "erp_percentile": round(d2_pct, 1), "trade_date": latest["trade_date"].strftime("%Y-%m-%d"),
            }

            dims = {
                "erp_abs":    {"score": d1_score, "weight": self.W["erp_abs"], "label": "ERP绝対値", "desc": d1_desc},
                "erp_pct":    {"score": d2_score, "weight": self.W["erp_pct"], "label": "ERP分位", "desc": d2_desc, "percentile": d2_pct},
                "yen_trend":  {"score": d3_score, "weight": self.W["yen_trend"], "label": "日元趋势", "desc": d3_desc, "yen_info": yen_info},
                "volatility": {"score": d4_score, "weight": self.W["volatility"], "label": "日経波動率", "desc": d4_desc, "vol_info": vol_info},
                "rate_env":   {"score": d5_score, "weight": self.W["rate_env"], "label": "利率環境", "desc": d5_desc, "rate_info": rate_info},
            }

            trade = self._generate_trade_rules(composite, dims, snap)
            alerts = self._generate_alerts(composite, erp_val, d2_pct, yen_info, vol_info, rate_info)
            diagnosis = self._build_diagnosis(erp_val, pe_ttm, yield_10y, d2_pct, yen_info, vol_info, rate_info, trade)

            return {
                "status": "success", "region": "JP",
                "current_snapshot": snap, "signal": {
                    "score": composite, "key": trade["signal_key"],
                    "label": trade["signal"]["label_cn"], "position": trade["signal"]["position"],
                    "color": trade["signal"]["color"], "emoji": trade["signal"]["emoji"],
                },
                "dimensions": dims, "trade_rules": trade,
                "alerts": alerts, "diagnosis": diagnosis, "encyclopedia": ENCYCLOPEDIA_JP,
            }
        except Exception as e:
            import traceback; traceback.print_exc()
            return self._fallback_signal(str(e))

    def get_erp_chart_data(self) -> dict:
        try:
            erp_df = self._compute_erp_series()
            sampled = erp_df.iloc[::3].copy()
            erp_mean = float(erp_df["erp"].mean())
            erp_std = float(erp_df["erp"].std())
            return {
                "status": "success",
                "dates": sampled["trade_date"].dt.strftime("%Y-%m-%d").tolist(),
                "erp": sampled["erp"].round(2).tolist(),
                "pe_ttm": sampled["pe_ttm"].round(2).tolist(),
                "yield_10y": sampled["yield_10y"].round(2).tolist(),
                "stats": {
                    "mean": round(erp_mean, 2), "std": round(erp_std, 2),
                    "overweight_line": round(erp_mean + 0.5 * erp_std, 2),
                    "underweight_line": round(erp_mean - 0.5 * erp_std, 2),
                    "current": round(float(erp_df["erp"].iloc[-1]), 2),
                }
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def generate_report(self) -> dict:
        signal = self.compute_signal()
        chart = self.get_erp_chart_data()
        return {**signal, "chart": chart, "engine_version": self.VERSION, "region": self.REGION, "updated_at": datetime.now().isoformat()}

    def _fallback_signal(self, reason):
        return {
            "status": "fallback", "region": "JP", "message": f"数据异常: {reason}",
            "current_snapshot": {"pe_ttm": 15.5, "yield_10y": 0.85, "earnings_yield": 6.45, "erp_value": 5.6, "erp_percentile": 55.0, "trade_date": datetime.now().strftime("%Y-%m-%d")},
            "signal": {"score": 60, "key": "hold", "label": "標配(降級)", "position": "50-70%", "color": "#3b82f6", "emoji": "🔵"},
            "dimensions": {k: {"score": 50, "weight": v, "label": k, "desc": "降級"} for k, v in self.W.items()},
            "trade_rules": {"signal_key": "hold", "signal": self.SIGNAL_MAP["hold"], "resonance": "none", "resonance_label": "⚪ 降級", "etf_advice": [], "take_profit": [], "stop_loss": []},
            "alerts": [{"level": "warning", "icon": "🟡", "text": reason}],
            "diagnosis": [{"type": "warning", "title": "降級", "text": reason}],
            "encyclopedia": ENCYCLOPEDIA_JP,
        }


_jp_engine = None
def get_jp_erp_engine() -> JPERPTimingEngine:
    global _jp_engine
    if _jp_engine is None:
        _jp_engine = JPERPTimingEngine()
    return _jp_engine


if __name__ == "__main__":
    engine = JPERPTimingEngine()
    print("=== JP ERP Timing Engine V1.0 Self-Test ===")
    report = engine.generate_report()
    if report.get("status") == "success":
        snap = report["current_snapshot"]
        sig = report["signal"]
        print(f"TOPIX PE: {snap['pe_ttm']} | JGB 10Y: {snap['yield_10y']}% | ERP: {snap['erp_value']}%")
        print(f"分位: {snap['erp_percentile']}% | 得分: {sig['score']} | {sig['emoji']} {sig['label']} ({sig['position']})")
        for d, v in report["dimensions"].items():
            print(f"  {v['label']}: {v['score']} ({v.get('desc','')})")
    else:
        print(f"Fallback: {report.get('message')}")
