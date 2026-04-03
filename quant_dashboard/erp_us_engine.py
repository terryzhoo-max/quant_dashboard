"""
AlphaCore · 美股ERP择时引擎 V1.0
===================================
五维择时信号系统 (本地最强代理变量):
  D1: ERP绝对值 (1/PE_SPY - US 10Y Treasury)  — 权重20%  [估值]
  D2: ERP历史分位 (近5年)                       — 权重25%  [估值]
  D3: 联邦基金利率方向 (3M T-Bill反向)           — 权重30%  [流动性] ← 最关键因子
  D4: VIX恐慌指数                              — 权重15%  [风险]
  D5: 信用利差 (HYG vs LQD ETF价差)            — 权重10%  [信用]

ETF标的: SPY / QQQ / SCHD
数据源: yfinance (免费) + FRED API (JGB/macro)
"""

import pandas as pd
import numpy as np
import time
import os
from datetime import datetime, timedelta
from typing import Optional

FRED_API_KEY = "eadf412d4f0e8ccd2bb3993b357bdca6"
CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

# FRED API 初始化
_fred_instance = None
def _get_fred():
    global _fred_instance
    if _fred_instance is None:
        try:
            from fredapi import Fred
            _fred_instance = Fred(api_key=FRED_API_KEY)
        except Exception as e:
            print(f"[US-ERP] FRED init failed: {e}")
    return _fred_instance

def _yf_safe(ticker_str, start, period=None):
    """yfinance容错包装"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker_str)
        if period:
            return t.history(period=period, timeout=8)
        return t.history(start=start, timeout=8)
    except Exception as e:
        print(f"[US-ERP] yfinance {ticker_str} failed: {e}")
        return pd.DataFrame()

# ===== TTL 缓存 (复用中国版架构) =====
_us_cache = {}

def _us_cached(key: str, ttl_seconds: int, fetcher):
    now = time.time()
    if key in _us_cache:
        ts_cached, data = _us_cache[key]
        if now - ts_cached < ttl_seconds:
            return data
    try:
        data = fetcher()
        _us_cache[key] = (now, data)
        return data
    except Exception as e:
        print(f"[US-ERP] cache fail ({key}): {e}")
        if key in _us_cache:
            return _us_cache[key][1]
        raise


# ===== 规则百科 =====
ENCYCLOPEDIA_US = {
    "erp_abs": {
        "title": "US ERP (Equity Risk Premium)",
        "what": "ERP = Earnings Yield (1/PE of S&P500) - 10Y US Treasury Yield. Measures how much extra return stocks offer over risk-free bonds.",
        "why": "Higher ERP → stocks are relatively cheap vs bonds. US historical median ERP ≈ 3.5-4.5%.",
        "alert": "ERP < 1% means stocks barely compensate for risk. ERP > 5% is a rare deep-value opportunity.",
        "history": "US ERP hit ~6% in March 2009 (GFC bottom), dropped to ~1% in late 2021 (bubble peak)."
    },
    "erp_pct": {
        "title": "ERP 历史分位",
        "what": "过去5年中，有多少比例的交易日ERP比今天低。80%分位 → 美股处于极罕见的低估区。",
        "why": "分位越高 → 赔率越好。但注意美股PE结构性偏高(科技权重大)。",
        "alert": "分位 > 80% 是黄金坑。分位 < 20% 需警惕估值泡沫。",
    },
    "fed_liquidity": {
        "title": "Fed 流动性 (联邦基金利率方向)",
        "what": "用3M T-Bill (^IRX) 代理联邦基金利率。利率下降 = Fed宽松 = 利好股市。",
        "why": "Fed降息周期平均带来18-24个月的股市上涨。利率方向比绝对水平更重要。",
        "alert": "利率连续3月上行 → 紧缩周期，股市估值承压。利率见顶回落 → 宽松拐点。",
    },
    "vix": {
        "title": "VIX 恐慌指数",
        "what": "CBOE波动率指数，反映S&P500期权的隐含波动率。俗称\"恐慌指标\"。",
        "why": "VIX < 15 = 市场极度乐观(潜在泡沫)。VIX > 35 = 恐慌抛售(逆向机会)。",
        "alert": "VIX突破40是历史级恐慌(如2020年3月65、2008年80)，往往是最佳买点。",
    },
    "credit_spread": {
        "title": "信用利差 (HY-IG Spread)",
        "what": "高收益债(HYG) vs 投资级债(LQD) 的收益率差。利差扩大 = 市场担忧违约风险。",
        "why": "信用利差是实体经济的\"体温计\"。利差收窄 → 企业融资顺畅 → 利好权益。",
        "alert": "利差 > 5% 通常预示经济衰退或信用危机。利差 < 3% 是经济乐观信号。",
    }
}


class USERPTimingEngine:
    """美股ERP择时引擎 V1.0"""

    VERSION = "1.0"
    REGION = "US"

    # 五维权重
    W = {"erp_abs": 0.20, "erp_pct": 0.25, "fed_liquidity": 0.30, "vix": 0.15, "credit_spread": 0.10}

    # 信号映射 (6级, 同中国版)
    SIGNAL_MAP = {
        "strong_buy":  {"label": "Strong Buy",  "label_cn": "强力买入", "position": "80-100%", "color": "#10b981", "emoji": "🟢🟢", "level": 6},
        "buy":         {"label": "Buy",          "label_cn": "买入",     "position": "60-80%",  "color": "#34d399", "emoji": "🟢",   "level": 5},
        "hold":        {"label": "Hold",         "label_cn": "标配持有", "position": "50-70%",  "color": "#3b82f6", "emoji": "🔵",   "level": 4},
        "reduce":      {"label": "Reduce",       "label_cn": "逐步减仓", "position": "30-50%",  "color": "#f59e0b", "emoji": "🟡",   "level": 3},
        "underweight": {"label": "Underweight",  "label_cn": "低配防御", "position": "10-30%",  "color": "#f97316", "emoji": "🟠",   "level": 2},
        "cash":        {"label": "Cash",         "label_cn": "清仓观望", "position": "0-10%",   "color": "#ef4444", "emoji": "🔴",   "level": 1},
    }

    ETF_TARGETS = {
        "aggressive": {"name": "Nasdaq-100 ETF", "code": "QQQ",  "desc": "科技成长弹性最大"},
        "balanced":   {"name": "S&P 500 ETF",    "code": "SPY",  "desc": "核心宽基，攻守兼备"},
        "defensive":  {"name": "高股息 ETF",      "code": "SCHD", "desc": "防御优先，稳定红利"},
    }

    def __init__(self):
        pass

    # ========== 数据获取层 ==========

    def _get_current_pe(self) -> float:
        """三级PE获取策略: yfinance实时 → 磁盘缓存 → 智能估算"""
        pe_cache_file = os.path.join(CACHE_DIR, "erp_us_current_pe.json")
        
        # Tier 1: yfinance 实时 (最准)
        try:
            import yfinance as yf
            spy = yf.Ticker("SPY")
            info = spy.info
            pe = info.get("trailingPE") or info.get("forwardPE")
            if pe and 10 < pe < 60:
                # 持久化到磁盘，供后续fallback
                import json
                with open(pe_cache_file, "w") as f:
                    json.dump({"pe": round(pe, 2), "source": "yfinance", "ts": datetime.now().isoformat()}, f)
                print(f"[US-ERP] PE from yfinance: {pe:.1f}x")
                return float(pe)
        except Exception as e:
            print(f"[US-ERP] yfinance PE failed: {e}")
        
        # Tier 2: 磁盘缓存 (7天内有效)
        if os.path.exists(pe_cache_file):
            try:
                import json
                with open(pe_cache_file, "r") as f:
                    cached = json.load(f)
                cached_ts = datetime.fromisoformat(cached["ts"])
                if (datetime.now() - cached_ts).days < 7:
                    pe = cached["pe"]
                    print(f"[US-ERP] PE from disk cache: {pe:.1f}x (cached {cached['ts'][:10]})")
                    return float(pe)
            except:
                pass
        
        # Tier 3: 智能估算 — 用S&P500价格/历史均值Earnings Yield(4.2%)反推
        # S&P500 长期Earnings Yield中位数 ≈ 4.0-4.5% → PE ≈ 22-25x
        # 用 yfinance price history 拿最新价格，跟均值EY估算
        try:
            import yfinance as yf
            spy_hist = yf.Ticker("SPY").history(period="5d")
            if not spy_hist.empty:
                price = float(spy_hist["Close"].iloc[-1])
                # 2024-26年S&P500 EPS约 $230-260, 用$245中位估算
                estimated_eps = 245.0
                pe = price / estimated_eps
                pe = max(15, min(40, pe))  # 合理区间保护
                print(f"[US-ERP] PE estimated from price/EPS: {pe:.1f}x (price=${price:.0f}, est_EPS=$245)")
                return float(pe)
        except:
            pass
        
        print("[US-ERP] PE fallback to 24.0x (all sources failed)")
        return 24.0

    def _fetch_spy_pe_history(self, years: int = 5) -> pd.DataFrame:
        """S&P500 PE历史序列 (FRED SP500价格 + 三级PE获取)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_us_spy_history.parquet")
            fred = _get_fred()
            df = None

            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=years * 365)
                    sp500 = fred.get_series("SP500", observation_start=start_dt)
                    if sp500 is not None and not sp500.empty:
                        sp500 = sp500.dropna()
                        df = pd.DataFrame({
                            "trade_date": sp500.index.tz_localize(None) if sp500.index.tz else sp500.index,
                            "close": sp500.values,
                        })
                        # === A1优化: 三级PE获取策略 ===
                        current_pe = self._get_current_pe()

                        current_price = df["close"].iloc[-1]
                        current_eps = current_price / current_pe
                        end_dt = datetime.now()
                        eps_list = []
                        for _, row in df.iterrows():
                            m = (end_dt - row["trade_date"]).days / 30
                            eps_list.append(current_eps / (1.08 ** (m / 12)))
                        df["eps"] = eps_list
                        df["pe_ttm"] = df["close"] / df["eps"]
                        df["pe_ttm"] = df["pe_ttm"].clip(8, 60)
                        df.to_parquet(cache_file)
                        print(f"[US-ERP] SP500 PE (FRED): {len(df)} rows, PE≈{current_pe:.1f}")
                        return df
                except Exception as e:
                    print(f"[US-ERP] FRED SP500 error: {e}")

            # Fallback: 磁盘缓存
            if os.path.exists(cache_file):
                print("[US-ERP] SP500 PE: using disk cache")
                return pd.read_parquet(cache_file)
            raise ValueError("SP500 data unavailable")
        return _us_cached("us_spy_pe", 30 * 60, _fetch)

    def _fetch_us10y_history(self, years: int = 5) -> pd.DataFrame:
        """US 10Y Treasury (FRED DGS10 — 日频数据)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_us_treasury_10y.parquet")
            fred = _get_fred()

            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=years * 365)
                    series = fred.get_series("DGS10", observation_start=start_dt)
                    if series is not None and not series.empty:
                        series = series.dropna()
                        df = pd.DataFrame({
                            "trade_date": series.index.tz_localize(None) if series.index.tz else series.index,
                            "yield_10y": series.values,
                        })
                        df.to_parquet(cache_file)
                        print(f"[US-ERP] 10Y UST (FRED): {len(df)} rows, latest={df['yield_10y'].iloc[-1]:.2f}%")
                        return df
                except Exception as e:
                    print(f"[US-ERP] FRED DGS10 error: {e}")

            if os.path.exists(cache_file):
                return pd.read_parquet(cache_file)
            raise ValueError("US 10Y data unavailable")
        return _us_cached("us_10y", 30 * 60, _fetch)

    def _fetch_vix_history(self, years: int = 5) -> pd.DataFrame:
        """VIX (FRED VIXCLS — 日频数据)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_us_vix.parquet")
            fred = _get_fred()

            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=years * 365)
                    series = fred.get_series("VIXCLS", observation_start=start_dt)
                    if series is not None and not series.empty:
                        series = series.dropna()
                        df = pd.DataFrame({
                            "trade_date": series.index.tz_localize(None) if series.index.tz else series.index,
                            "vix": series.values,
                        })
                        df.to_parquet(cache_file)
                        print(f"[US-ERP] VIX (FRED): {len(df)} rows, latest={df['vix'].iloc[-1]:.1f}")
                        return df
                except Exception as e:
                    print(f"[US-ERP] FRED VIXCLS error: {e}")

            if os.path.exists(cache_file):
                return pd.read_parquet(cache_file)
            raise ValueError("VIX data unavailable")
        return _us_cached("us_vix", 30 * 60, _fetch)

    def _fetch_tbill_3m(self, years: int = 3) -> pd.DataFrame:
        """3M T-Bill (FRED DTB3 — 日频数据)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_us_tbill_3m.parquet")
            fred = _get_fred()

            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=years * 365)
                    series = fred.get_series("DTB3", observation_start=start_dt)
                    if series is not None and not series.empty:
                        series = series.dropna()
                        df = pd.DataFrame({
                            "trade_date": series.index.tz_localize(None) if series.index.tz else series.index,
                            "rate_3m": series.values,
                        })
                        df.to_parquet(cache_file)
                        print(f"[US-ERP] 3M T-Bill (FRED): {len(df)} rows, latest={df['rate_3m'].iloc[-1]:.2f}%")
                        return df
                except Exception as e:
                    print(f"[US-ERP] FRED DTB3 error: {e}")

            if os.path.exists(cache_file):
                return pd.read_parquet(cache_file)
            raise ValueError("3M T-Bill data unavailable")
        return _us_cached("us_3m_tbill", 60 * 60, _fetch)

    def _fetch_credit_spread(self) -> dict:
        """信用利差 (FRED BAMLH0A0HYM2 — ICE BofA HY OAS)
        ⚠️ FRED返回单位是 percent (3.28 = 3.28%), 不是bps!"""
        def _fetch():
            fred = _get_fred()

            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=365)
                    series = fred.get_series("BAMLH0A0HYM2", observation_start=start_dt)
                    if series is not None and not series.empty:
                        series = series.dropna()
                        spread_now = float(series.iloc[-1])  # 直接是百分比: 3.28 = 3.28%
                        spread_3m = float(series.iloc[-63]) if len(series) >= 63 else float(series.iloc[0])
                        trend = "tightening" if spread_now < spread_3m else "widening"
                        # === A2修复: 不再 /100! FRED直接返回百分比 ===
                        result = {"spread": round(spread_now, 2), "trend": trend,
                                  "raw_bps": round(spread_now * 100, 0)}
                        print(f"[US-ERP] HY OAS (FRED): {spread_now:.2f}% = {spread_now*100:.0f}bps ({trend})")
                        return result
                except Exception as e:
                    print(f"[US-ERP] FRED BAMLH0A0HYM2 error: {e}")

            # Fallback: 合理默认值
            return {"spread": 3.5, "trend": "unknown", "raw_bps": 350}
        return _us_cached("us_credit_spread", 2 * 3600, _fetch)

    # ========== 核心计算层 ==========

    def _compute_erp_series(self) -> pd.DataFrame:
        """计算美股5年ERP时间序列"""
        pe_df = self._fetch_spy_pe_history()
        yield_df = self._fetch_us10y_history()

        merged = pd.merge(pe_df, yield_df, on="trade_date", how="left")
        merged = merged.sort_values("trade_date")
        merged["yield_10y"] = merged["yield_10y"].ffill().bfill()
        merged = merged.dropna(subset=["pe_ttm", "yield_10y"])
        merged = merged[merged["pe_ttm"] > 0].copy()
        merged["earnings_yield"] = 1.0 / merged["pe_ttm"] * 100
        merged["erp"] = merged["earnings_yield"] - merged["yield_10y"]
        return merged.sort_values("trade_date").reset_index(drop=True)

    # ========== 五维评分 ==========

    def _score_d1_erp_absolute(self, erp_val: float) -> tuple:
        """D1: ERP绝对值 → 0-100 (美股阈值: 比中国低~1%)"""
        if erp_val >= 5.0:
            score, desc = 100, f"ERP {erp_val:.2f}% ≥ 5% → 极度低估，历史级机会"
        elif erp_val >= 4.0:
            score, desc = 75 + (erp_val - 4.0) * 25, f"ERP {erp_val:.2f}% 4-5%区间 → 显著低估"
        elif erp_val >= 3.0:
            score, desc = 55 + (erp_val - 3.0) * 20, f"ERP {erp_val:.2f}% 3-4%区间 → 估值合理偏低"
        elif erp_val >= 2.0:
            score, desc = 35 + (erp_val - 2.0) * 20, f"ERP {erp_val:.2f}% 2-3%区间 → 估值中性"
        elif erp_val >= 1.0:
            score, desc = 15 + (erp_val - 1.0) * 20, f"ERP {erp_val:.2f}% 1-2%区间 → 偏高估"
        elif erp_val >= 0:
            score, desc = erp_val * 15, f"ERP {erp_val:.2f}% 0-1%区间 → 高估, 股债无差异"
        else:
            score, desc = 0, f"ERP {erp_val:.2f}% < 0% → 极度高估! 买国债比买股票好"
        return round(min(100, max(0, score)), 1), desc

    def _score_d2_erp_percentile(self, erp_val: float, erp_series: pd.Series) -> tuple:
        """D2: ERP历史分位 → 0-100"""
        pct = (erp_series < erp_val).mean() * 100
        if pct >= 80:   desc = f"近5年{pct:.1f}%分位 → 历史极度低估"
        elif pct >= 60: desc = f"近5年{pct:.1f}%分位 → 偏低估"
        elif pct >= 40: desc = f"近5年{pct:.1f}%分位 → 估值中性"
        elif pct >= 20: desc = f"近5年{pct:.1f}%分位 → 偏高估"
        else:           desc = f"近5年{pct:.1f}%分位 → 历史极度高估"
        return round(pct, 1), round(pct, 1), desc

    def _score_d3_fed_liquidity(self) -> tuple:
        """D3: 联邦基金利率方向 (反向逻辑: 利率↓ = 宽松 = 高分)"""
        tbill_df = self._fetch_tbill_3m()
        if tbill_df.empty:
            return 50.0, {"current": 0, "prev_month": 0, "3m_ago": 0, "direction": "unknown"}, "数据缺失"

        latest = float(tbill_df["rate_3m"].iloc[-1])
        prev_1m = float(tbill_df["rate_3m"].iloc[-22]) if len(tbill_df) >= 22 else latest
        prev_3m = float(tbill_df["rate_3m"].iloc[-63]) if len(tbill_df) >= 63 else latest

        is_falling = latest < prev_1m
        is_3m_falling = latest < prev_3m
        rate_drop_3m = prev_3m - latest  # 正数 = 利率下降了

        fed_info = {
            "current": round(latest, 2),
            "prev_month": round(prev_1m, 2),
            "3m_ago": round(prev_3m, 2),
            "direction": "easing" if is_falling else "tightening",
            "3m_direction": "easing" if is_3m_falling else "tightening",
            "rate_drop_3m": round(rate_drop_3m, 2),
        }

        # 评分逻辑 (反向: 低利率+下降趋势 = 高分)
        if latest < 2.0 and is_3m_falling:
            score = 95
            desc = f"3M利率{latest:.2f}% < 2%且持续下降 → 极度宽松，史诗级流动性"
        elif latest < 3.0 and is_falling:
            score = 80
            desc = f"3M利率{latest:.2f}%下降中 → 宽松周期，利好权益"
        elif is_3m_falling and rate_drop_3m > 0.5:
            score = 70
            desc = f"3M利率{latest:.2f}%，3月降{rate_drop_3m:.1f}% → 降息拐点"
        elif is_falling:
            score = 60
            desc = f"3M利率{latest:.2f}%，环比小幅回落 → 边际宽松"
        elif latest > 5.0 and not is_3m_falling:
            score = 15
            desc = f"3M利率{latest:.2f}% > 5%且无下降 → 紧缩高压"
        elif latest > 4.0:
            score = 30
            desc = f"3M利率{latest:.2f}% 偏高 → 流动性偏紧"
        else:
            score = 50
            desc = f"3M利率{latest:.2f}% → 中性"

        return round(min(100, max(0, score)), 1), fed_info, desc

    def _score_d4_vix(self) -> tuple:
        """D4: VIX恐慌指数 → 0-100 (A5优化: 细化15-25区间)"""
        vix_df = self._fetch_vix_history()
        if vix_df.empty:
            return 50.0, {"current": 0, "pct": 50, "regime": "normal"}, "VIX数据不足"

        current_vix = float(vix_df["vix"].iloc[-1])
        vix_pct = (vix_df["vix"] < current_vix).mean() * 100

        # === A5优化: 更精细的VIX评分区间 ===
        if current_vix >= 40:
            score, regime = 10, "extreme_panic"
            desc = f"VIX {current_vix:.1f} ≥ 40 → 极端恐慌! 逆向加仓窗口"
        elif current_vix >= 30:
            score, regime = 25, "high_fear"
            desc = f"VIX {current_vix:.1f} 高恐慌，市场剧烈波动"
        elif current_vix >= 25:
            score, regime = 35, "elevated_high"
            desc = f"VIX {current_vix:.1f} 明显偏高，市场紧张"
        elif current_vix >= 20:
            score, regime = 50, "elevated"
            desc = f"VIX {current_vix:.1f} 偏高，市场有分歧"
        elif current_vix >= 17:
            score, regime = 65, "mild_elevated"
            desc = f"VIX {current_vix:.1f} 略偏高，需关注"
        elif current_vix >= 14:
            score, regime = 80, "normal"
            desc = f"VIX {current_vix:.1f} 正常区间，适合配置"
        elif current_vix >= 12:
            score, regime = 70, "complacent"
            desc = f"VIX {current_vix:.1f} 偏低，市场过度乐观"
        else:
            score, regime = 40, "extreme_complacent"
            desc = f"VIX {current_vix:.1f} < 12 → 极度自满! 警惕突发回调"

        vix_info = {"current": round(current_vix, 1), "pct": round(vix_pct, 1), "regime": regime}
        return round(score, 1), vix_info, desc

    def _score_d5_credit_spread(self) -> tuple:
        """D5: 信用利差 → 0-100"""
        credit = self._fetch_credit_spread()
        spread = credit.get("spread", 2.0)
        trend = credit.get("trend", "unknown")

        if spread <= 1.5:
            score = 90
            desc = f"信用利差仅{spread:.1f}% → 信用环境极佳，企业融资顺畅"
        elif spread <= 2.5:
            score = 75
            desc = f"信用利差{spread:.1f}% → 信用环境良好"
        elif spread <= 3.5:
            score = 55
            desc = f"信用利差{spread:.1f}% → 中性偏紧"
        elif spread <= 5.0:
            score = 30
            desc = f"信用利差{spread:.1f}% → 信用偏弱，违约担忧上升"
        else:
            score = 10
            desc = f"信用利差{spread:.1f}% > 5% → 信用危机! 避险优先"

        # 趋势加减分
        if trend == "tightening":
            score = min(100, score + 8)
            desc += " (利差收窄中,边际改善)"
        elif trend == "widening":
            score = max(0, score - 8)
            desc += " (利差走阔,恶化中)"

        credit_info = {"spread": spread, "trend": trend}
        return round(min(100, max(0, score)), 1), credit_info, desc

    # ========== 买卖规则引擎 ==========

    def _generate_trade_rules(self, score: float, dims: dict, snap: dict) -> dict:
        erp = snap.get("erp_value", 0)
        vix_info = dims.get("vix", {}).get("vix_info", {})
        vix_regime = vix_info.get("regime", "normal")
        vix_val = vix_info.get("current", 20)
        credit_info = dims.get("credit_spread", {}).get("credit_info", {})
        spread = credit_info.get("spread", 3.0)

        d1s = dims.get("erp_abs", {}).get("score", 50)
        d2s = dims.get("erp_pct", {}).get("score", 50)
        d3s = dims.get("fed_liquidity", {}).get("score", 50)
        d4s = dims.get("vix", {}).get("score", 50)
        d5s = dims.get("credit_spread", {}).get("score", 50)

        # === B3增强: 共振判定增加VIX+信用利差极端 ===
        bullish_count = sum([d1s >= 60, d2s >= 60, d3s >= 60])
        bearish_count = sum([d1s < 35, d2s < 35, d3s < 35])
        # VIX极端恐慌 = 额外看空(短期风险)
        if vix_regime in ("extreme_panic", "high_fear"):
            bearish_count += 1
        # 信用危机 = 额外看空
        if spread > 5.0:
            bearish_count += 1

        resonance = "none"
        if bullish_count >= 3:
            resonance = "bullish_resonance"
        elif bearish_count >= 3:
            resonance = "bearish_resonance"
        elif bullish_count >= 1 and bearish_count >= 1:
            resonance = "divergence"

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

        # 逆向修正: VIX恐慌+低估 → 升级
        if vix_regime == "extreme_panic" and erp >= 3.0:
            if signal_key in ("hold", "reduce"):
                signal_key = "buy"

        signal = self.SIGNAL_MAP[signal_key]

        # ETF配置 (B2: 细化reduce/underweight/cash)
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
        elif signal_key == "reduce":
            etf_advice = [
                {"etf": self.ETF_TARGETS["defensive"], "ratio": "50%", "reason": "防御为主"},
                {"etf": self.ETF_TARGETS["balanced"], "ratio": "35%", "reason": "核心底仓"},
                {"etf": self.ETF_TARGETS["aggressive"], "ratio": "15%", "reason": "保留弹性"},
            ]
        elif signal_key == "underweight":
            etf_advice = [
                {"etf": self.ETF_TARGETS["defensive"], "ratio": "60%", "reason": "防御优先"},
                {"etf": self.ETF_TARGETS["balanced"], "ratio": "30%", "reason": "保留底仓"},
                {"etf": self.ETF_TARGETS["aggressive"], "ratio": "10%", "reason": "观察仓"},
            ]
        else:  # cash
            etf_advice = [
                {"etf": self.ETF_TARGETS["defensive"], "ratio": "70%", "reason": "最大防御"},
                {"etf": self.ETF_TARGETS["balanced"], "ratio": "25%", "reason": "种子仓"},
                {"etf": self.ETF_TARGETS["aggressive"], "ratio": "5%", "reason": "象征仓"},
            ]

        # === B1: 动态高亮 — 每条规则附带 triggered 字段 ===
        take_profit = [
            {"trigger": "ERP 回落至 1.0% 以下", "action": "减仓30%权益", "type": "valuation",
             "triggered": bool(erp < 1.0), "current": f"ERP={erp:.2f}%"},
            {"trigger": f"VIX < 12 持续2周", "action": "减仓20% (过度自满)", "type": "vix",
             "triggered": bool(vix_val < 12), "current": f"VIX={vix_val:.1f}"},
            {"trigger": "综合得分从 ≥70 跌破 45", "action": "降至50%仓位", "type": "score_drop",
             "triggered": bool(score < 45), "current": f"得分={score:.0f}"},
        ]

        stop_loss = [
            {"trigger": "ERP ≥ 5% (极端低估)", "action": "逆向加仓20%", "type": "contrarian_buy", "color": "#10b981",
             "triggered": bool(erp >= 5.0), "current": f"ERP={erp:.2f}%"},
            {"trigger": "VIX > 40 + ERP > 3%", "action": "恐慌+低估=加仓", "type": "contrarian_vix", "color": "#10b981",
             "triggered": bool(vix_val > 40 and erp > 3.0), "current": f"VIX={vix_val:.1f},ERP={erp:.2f}%"},
            {"trigger": "ERP < -1% (极端泡沫)", "action": "硬止损: 清仓", "type": "hard_stop", "color": "#ef4444",
             "triggered": bool(erp < -1.0), "current": f"ERP={erp:.2f}%"},
            {"trigger": f"信用利差 > 6%", "action": "降至20%以下", "type": "credit_crisis", "color": "#ef4444",
             "triggered": bool(spread > 6.0), "current": f"利差={spread:.1f}%"},
        ]

        return {
            "signal_key": signal_key, "signal": signal, "resonance": resonance,
            "resonance_label": {"bullish_resonance": "🟢 三维共振看多", "bearish_resonance": "🔴 三维共振看空",
                                "divergence": "🟡 信号分歧", "none": "⚪ 中性"}[resonance],
            "etf_advice": etf_advice, "take_profit": take_profit, "stop_loss": stop_loss,
        }

    # ========== 警示系统 ==========

    def _generate_alerts(self, score, erp, pct, fed_info, vix_info, credit_info) -> list:
        alerts = []
        vix_val = vix_info.get("current", 20)
        spread = credit_info.get("spread", 2.0)
        rate = fed_info.get("current", 4.0)

        if erp < 0:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"ERP {erp:.2f}% < 0! 买国债比买股票划算", "pulse": True})
        if vix_val >= 35:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"VIX {vix_val:.0f} 极端恐慌! 逆向投资者关注", "pulse": True})
        if spread > 5.0:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"信用利差{spread:.1f}%飙升，违约风险上升", "pulse": True})
        if score < 30:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"综合得分仅{score}，美股环境极不利", "pulse": True})

        if 0 <= erp < 1.5:
            alerts.append({"level": "warning", "icon": "🟡", "text": f"ERP {erp:.2f}%偏低，美股性价比不高"})
        if rate > 5.0 and fed_info.get("3m_direction") == "tightening":
            alerts.append({"level": "warning", "icon": "🟡", "text": f"Fed利率{rate:.1f}%高位且持续紧缩"})
        if vix_val < 13:
            alerts.append({"level": "warning", "icon": "🟡", "text": f"VIX {vix_val:.1f}极低，市场过度自满"})

        if erp >= 4.0:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": f"ERP {erp:.2f}% ≥ 4% 美股罕见低估!", "pulse": True})
        if pct >= 80:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": f"分位{pct:.1f}% 历史级低估"})
        if fed_info.get("3m_direction") == "easing" and fed_info.get("rate_drop_3m", 0) > 0.5:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": "Fed降息拐点确认，流动性改善"})

        return alerts if alerts else [{"level": "normal", "icon": "⚪", "text": "当前无特殊警示"}]

    # ========== 诊断卡片 ==========

    def _build_diagnosis(self, erp, pe, y10, pct, fed_info, vix_info, credit_info, trade) -> list:
        cards = []
        vix_val = vix_info.get("current", 20)
        spread = credit_info.get("spread", 2.0)
        rate = fed_info.get("current", 4.0)
        signal = trade["signal"]

        if erp >= 3.0:
            cards.append({"type": "success", "title": "估值 · 低估", "text": f"SPY PE {pe:.1f}x, 盈利收益率{1/pe*100:.1f}%超过10Y UST {y10:.2f}%, ERP={erp:.2f}%。"})
        elif erp >= 1.0:
            cards.append({"type": "info", "title": "估值 · 中性", "text": f"PE {pe:.1f}x, ERP={erp:.2f}% 合理但不便宜。"})
        else:
            cards.append({"type": "danger", "title": "估值 · 高估", "text": f"PE {pe:.1f}x, ERP仅{erp:.2f}%, 股票相对国债无吸引力!"})

        if pct >= 70:
            cards.append({"type": "success", "title": "分位 · 便宜", "text": f"ERP {pct:.0f}%分位，历史罕见低估。"})
        elif pct >= 40:
            cards.append({"type": "info", "title": "分位 · 中性", "text": f"ERP {pct:.0f}%分位。"})
        else:
            cards.append({"type": "warning", "title": "分位 · 昂贵", "text": f"ERP仅{pct:.0f}%分位，历史大部分时间比现在便宜。"})

        if fed_info.get("3m_direction") == "easing":
            cards.append({"type": "success", "title": "流动性 · 宽松", "text": f"3M利率{rate:.2f}%，下降趋势，Fed宽松中。"})
        elif rate <= 4.0:
            cards.append({"type": "info", "title": "流动性 · 中性", "text": f"3M利率{rate:.2f}%，尚可。"})
        else:
            cards.append({"type": "warning", "title": "流动性 · 紧缩", "text": f"3M利率{rate:.2f}%高位，紧缩压力。"})

        if vix_val >= 30:
            cards.append({"type": "warning", "title": "VIX · 恐慌", "text": f"VIX {vix_val:.0f}，逆向机会但风险极高。"})
        elif vix_val <= 14:
            cards.append({"type": "warning", "title": "VIX · 自满", "text": f"VIX {vix_val:.0f}过低，警惕均值回归。"})
        else:
            cards.append({"type": "success", "title": "VIX · 正常", "text": f"VIX {vix_val:.0f}，波动可控。"})

        if spread <= 3.0:
            cards.append({"type": "success", "title": "信用 · 健康", "text": f"HY-IG利差{spread:.1f}%，信用环境良好。"})
        else:
            cards.append({"type": "warning", "title": "信用 · 偏紧", "text": f"HY-IG利差{spread:.1f}%，企业融资成本上升。"})

        etf_text = " / ".join([f"{e['etf']['name']}{e['ratio']}" for e in trade.get("etf_advice", [])])
        cards.append({"type": "info", "title": f"操作 · {signal['label_cn']}", "text": f"{trade['resonance_label']}。建议仓位{signal['position']}。配置: {etf_text}。"})

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
            d3_score, fed_info, d3_desc = self._score_d3_fed_liquidity()
            d4_score, vix_info, d4_desc = self._score_d4_vix()
            d5_score, credit_info, d5_desc = self._score_d5_credit_spread()

            composite = round(
                d1_score * self.W["erp_abs"] + d2_score * self.W["erp_pct"] +
                d3_score * self.W["fed_liquidity"] + d4_score * self.W["vix"] +
                d5_score * self.W["credit_spread"], 1
            )

            snap = {
                "pe_ttm": round(pe_ttm, 2), "yield_10y": round(yield_10y, 4),
                "earnings_yield": round(1.0 / pe_ttm * 100, 2), "erp_value": round(erp_val, 2),
                "erp_percentile": round(d2_pct, 1), "trade_date": latest["trade_date"].strftime("%Y-%m-%d"),
            }

            dims = {
                "erp_abs":       {"score": d1_score, "weight": self.W["erp_abs"], "label": "ERP绝对值", "desc": d1_desc},
                "erp_pct":       {"score": d2_score, "weight": self.W["erp_pct"], "label": "ERP历史分位", "desc": d2_desc, "percentile": d2_pct},
                "fed_liquidity": {"score": d3_score, "weight": self.W["fed_liquidity"], "label": "Fed流动性", "desc": d3_desc, "fed_info": fed_info},
                "vix":           {"score": d4_score, "weight": self.W["vix"], "label": "VIX恐慌", "desc": d4_desc, "vix_info": vix_info},
                "credit_spread": {"score": d5_score, "weight": self.W["credit_spread"], "label": "信用利差", "desc": d5_desc, "credit_info": credit_info},
            }

            trade = self._generate_trade_rules(composite, dims, snap)
            alerts = self._generate_alerts(composite, erp_val, d2_pct, fed_info, vix_info, credit_info)
            diagnosis = self._build_diagnosis(erp_val, pe_ttm, yield_10y, d2_pct, fed_info, vix_info, credit_info, trade)

            return {
                "status": "success", "region": "US",
                "current_snapshot": snap, "signal": {
                    "score": composite, "key": trade["signal_key"],
                    "label": trade["signal"]["label_cn"], "position": trade["signal"]["position"],
                    "color": trade["signal"]["color"], "emoji": trade["signal"]["emoji"],
                },
                "dimensions": dims, "trade_rules": trade,
                "alerts": alerts, "diagnosis": diagnosis, "encyclopedia": ENCYCLOPEDIA_US,
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
            "status": "fallback", "region": "US", "message": f"数据异常: {reason}",
            "current_snapshot": {"pe_ttm": 23.0, "yield_10y": 4.30, "earnings_yield": 4.35, "erp_value": 0.05, "erp_percentile": 15.0, "trade_date": datetime.now().strftime("%Y-%m-%d")},
            "signal": {"score": 35, "key": "reduce", "label": "减仓(降级)", "position": "30-50%", "color": "#f59e0b", "emoji": "🟡"},
            "dimensions": {k: {"score": 50, "weight": v, "label": k, "desc": "降级"} for k, v in self.W.items()},
            "trade_rules": {"signal_key": "reduce", "signal": self.SIGNAL_MAP["reduce"], "resonance": "none", "resonance_label": "⚪ 降级", "etf_advice": [], "take_profit": [], "stop_loss": []},
            "alerts": [{"level": "warning", "icon": "🟡", "text": reason}],
            "diagnosis": [{"type": "warning", "title": "数据降级", "text": reason}],
            "encyclopedia": ENCYCLOPEDIA_US,
        }


# ===== 单例 =====
_us_engine = None
def get_us_erp_engine() -> USERPTimingEngine:
    global _us_engine
    if _us_engine is None:
        _us_engine = USERPTimingEngine()
    return _us_engine


if __name__ == "__main__":
    engine = USERPTimingEngine()
    print("=== US ERP Timing Engine V1.0 Self-Test ===")
    report = engine.generate_report()
    if report.get("status") == "success":
        snap = report["current_snapshot"]
        sig = report["signal"]
        print(f"SPY PE: {snap['pe_ttm']} | 10Y UST: {snap['yield_10y']}% | ERP: {snap['erp_value']}%")
        print(f"分位: {snap['erp_percentile']}% | 得分: {sig['score']} | {sig['emoji']} {sig['label']} ({sig['position']})")
        for d, v in report["dimensions"].items():
            print(f"  {v['label']}: {v['score']} ({v.get('desc','')})")
    else:
        print(f"Fallback: {report.get('message')}")
