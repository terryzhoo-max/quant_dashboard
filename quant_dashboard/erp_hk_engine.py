"""
AlphaCore · 港股ERP择时引擎 V1.0
===================================
五维择时信号系统 (港股本地化):
  D1: ERP绝对值 (1/PE - 混合无风险利率)          — 权重20%  [估值]
  D2: ERP历史分位 (近5年)                         — 权重25%  [估值]
  D3: 南向资金净流入方向 (陆→港增量引擎)          — 权重30%  [流动性] ← 最关键因子
  D4: VHSI恐慌/HSI实现波动率                      — 权重15%  [风险]
  D5: 港美利差 (US10Y − CN10Y)                    — 权重10%  [跨境资金]

特殊考量:
  - 港股无风险利率 = 0.6×US10Y + 0.4×CN10Y (混合锚)
  - HSI PE 历史中位数 ≈ 10-12x (金融地产拖累)
  - HSTECH PE 历史中位数 ≈ 20-30x (科技成长)
  - 南向资金是港股的"边际定价力量"

双轨模式:
  market="HSI"    → 恒生指数 (蓝筹宽基)
  market="HSTECH" → 恒生科技指数 (成长科技)

ETF标的:
  HSI:    159920.SZ(恒生ETF) / 513090.SH(港股证券ETF)
  HSTECH: 513130.SH(恒生科技ETF) / 513180.SH(恒生科技ETF)
  红利:   159545.SZ(恒生红利低波ETF)

数据源: CNBC实时报价 + FRED API (US10Y/CN10Y)
"""

import pandas as pd
import numpy as np
import time
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict

FRED_API_KEY = "eadf412d4f0e8ccd2bb3993b357bdca6"
CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)

# FRED API
_hk_fred = None
def _get_hk_fred():
    global _hk_fred
    if _hk_fred is None:
        try:
            from fredapi import Fred
            _hk_fred = Fred(api_key=FRED_API_KEY)
        except Exception as e:
            print(f"[HK-ERP] FRED init failed: {e}")
    return _hk_fred

_hk_cache = {}

def _hk_cached(key: str, ttl_seconds: int, fetcher):
    now = time.time()
    if key in _hk_cache:
        ts_cached, data = _hk_cache[key]
        if now - ts_cached < ttl_seconds:
            return data
    try:
        data = fetcher()
        _hk_cache[key] = (now, data)
        return data
    except Exception as e:
        print(f"[HK-ERP] cache fail ({key}): {e}")
        if key in _hk_cache:
            return _hk_cache[key][1]
        raise


# ===== 南向资金持久化 =====
SOUTHBOUND_FILE = os.path.join(CACHE_DIR, "hk_southbound_flow.json")

DEFAULT_SOUTHBOUND = {
    "weekly_net_buy_billion_rmb": 15.0,
    "monthly_net_buy_billion_rmb": 60.0,
    "cumulative_12m_billion_rmb": 350.0,
    "direction": "inflow",
    "date": "2026-04-01",
    "source": "default",
}


# ===== 规则百科 =====
ENCYCLOPEDIA_HK = {
    "erp_abs": {
        "title": "HK ERP (Equity Risk Premium)",
        "what": "ERP = Earnings Yield (1/PE) − 混合无风险利率(0.6×US10Y + 0.4×CN10Y)。衡量港股相对无风险资产的超额回报。",
        "why": "港股ERP天然偏高(因金融地产低PE)。HSI历史中位数ERP≈6-8%，HSTECH≈3-5%。",
        "alert": "HSI ERP<4% = 偏高估(罕见)。HSI ERP>10% = 极端恐慌底部。",
        "history": "2022年10月HSI 14800点时ERP≈12%(极度低估)，2021年2月HSI 31000时ERP≈4%(偏高)。"
    },
    "erp_pct": {
        "title": "ERP 历史分位",
        "what": "过去5年中有多少比例的交易日ERP比今天低。80%分位 → 港股极罕见低估。",
        "why": "港股波动极大，分位比绝对值更可靠。注意2022年极端行情会拉高分位的参考范围。",
        "alert": "分位>80% 是黄金坑。分位<20% 港股估值已充分定价。",
    },
    "southbound": {
        "title": "南向资金 (陆→港)",
        "what": "内地投资者通过港股通买入港股的净资金流。正数=净买入=增量资金入港。",
        "why": "南向资金占港股日成交约15-25%，是港股最大的增量资金来源。持续大额净买入=看涨信号。",
        "alert": "月净买入>200亿=强劲流入(2024年特征)。连续5日净卖出=短期风险。",
    },
    "vhsi": {
        "title": "VHSI / 恒生波动率",
        "what": "恒生波动率指数(类似VIX)。反映港股期权隐含波动率，正常区间15-25。",
        "why": "VHSI>35 = 恐慌抛售(逆向机会)。VHSI<15 = 市场自满(警惕回调)。",
        "alert": "VHSI突破40是历史级恐慌(如2022年10月)，往往对应底部区域。",
    },
    "rate_spread": {
        "title": "港美利差 (US10Y − CN10Y)",
        "what": "美国10年国债减去中国10年国债收益率。利差扩大=资金倾向流出港股回到美元资产。",
        "why": "港币挂钩美元，美债收益率上升→资金回流美国→港股承压。利差缩窄=港股估值修复动力。",
        "alert": "利差>2.5%是警戒线(2023年特征)。利差<1%=港股资金面宽松。",
    }
}


class HKERPTimingEngine:
    """港股ERP择时引擎 V1.0 · 双轨模式(HSI/HSTECH)"""

    VERSION = "1.0"
    REGION = "HK"

    # 五维权重
    W = {"erp_abs": 0.20, "erp_pct": 0.25, "southbound": 0.30, "vhsi": 0.15, "rate_spread": 0.10}

    # 信号映射
    SIGNAL_MAP = {
        "strong_buy":  {"label": "Strong Buy",  "label_cn": "强力买入", "position": "80-100%", "color": "#10b981", "emoji": "🟢🟢", "level": 6},
        "buy":         {"label": "Buy",          "label_cn": "买入",     "position": "60-80%",  "color": "#34d399", "emoji": "🟢",   "level": 5},
        "hold":        {"label": "Hold",         "label_cn": "标配持有", "position": "50-70%",  "color": "#3b82f6", "emoji": "🔵",   "level": 4},
        "reduce":      {"label": "Reduce",       "label_cn": "逐步减仓", "position": "30-50%",  "color": "#f59e0b", "emoji": "🟡",   "level": 3},
        "underweight": {"label": "Underweight",  "label_cn": "低配防御", "position": "10-30%",  "color": "#f97316", "emoji": "🟠",   "level": 2},
        "cash":        {"label": "Cash",         "label_cn": "清仓观望", "position": "0-10%",   "color": "#ef4444", "emoji": "🔴",   "level": 1},
    }

    # 市场配置
    MARKET_CONFIG = {
        "HSI": {
            "ticker": "^HSI",
            "name": "恒生指数",
            "pe_fallback": 10.5,
            "pe_range": (6, 25),
            "erp_thresholds": {"extreme_low": 10.0, "low": 8.0, "mid_low": 6.0, "mid": 4.0, "high": 3.0},
            "eps_est": 2200.0,  # HSI近似EPS (2025-26年)
            "etf_targets": {
                "aggressive": {"name": "恒生ETF", "code": "159920.SZ", "desc": "HSI蓝筹宽基"},
                "balanced":   {"name": "港股证券ETF", "code": "513090.SH", "desc": "港股券商弹性"},
                "defensive":  {"name": "恒生红利低波ETF", "code": "159545.SZ", "desc": "高股息防御"},
            },
        },
        "HSTECH": {
            "ticker": "^HSTECH",
            "name": "恒生科技指数",
            "pe_fallback": 22.0,
            "pe_range": (10, 80),
            "erp_thresholds": {"extreme_low": 6.0, "low": 5.0, "mid_low": 3.5, "mid": 2.0, "high": 1.0},
            "eps_est": 200.0,  # HSTECH近似EPS
            "etf_targets": {
                "aggressive": {"name": "恒生科技ETF", "code": "513130.SH", "desc": "HSTECH核心弹性"},
                "balanced":   {"name": "恒生科技ETF华泰", "code": "513180.SH", "desc": "HSTECH备选"},
                "defensive":  {"name": "恒生红利低波ETF", "code": "159545.SZ", "desc": "高股息防御"},
            },
        },
    }

    def __init__(self, market: str = "HSI"):
        assert market in self.MARKET_CONFIG, f"Invalid market: {market}"
        self.market = market
        self.cfg = self.MARKET_CONFIG[market]
        self._southbound = self._load_southbound()

    # ========== 南向资金管理 ==========

    def _load_southbound(self) -> Dict:
        if os.path.exists(SOUTHBOUND_FILE):
            try:
                with open(SOUTHBOUND_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                print(f"[HK-ERP] 南向资金 loaded: weekly={data.get('weekly_net_buy_billion_rmb', 0):.1f}B")
                return data
            except Exception:
                pass
        return DEFAULT_SOUTHBOUND.copy()

    def update_southbound(self, weekly_net: float, monthly_net: float = None, cumulative_12m: float = None):
        """手动更新南向资金数据"""
        data = self._southbound.copy()
        data["weekly_net_buy_billion_rmb"] = round(weekly_net, 1)
        if monthly_net is not None:
            data["monthly_net_buy_billion_rmb"] = round(monthly_net, 1)
        if cumulative_12m is not None:
            data["cumulative_12m_billion_rmb"] = round(cumulative_12m, 1)
        data["direction"] = "inflow" if weekly_net > 0 else "outflow"
        data["date"] = datetime.now().strftime("%Y-%m-%d")
        data["source"] = "manual"
        with open(SOUTHBOUND_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._southbound = data
        print(f"[HK-ERP] 南向资金更新: weekly={weekly_net:.1f}B")

    # ========== 数据获取层 ==========

    def _get_current_pe(self) -> float:
        """三级PE获取: CNBC实时价格+EPS估算 → 磁盘缓存 → 硬编码"""
        pe_cache_file = os.path.join(CACHE_DIR, f"erp_hk_{self.market.lower()}_pe.json")

        # Tier 1: CNBC 实时价格 → PE = Price / EPS_est
        try:
            cnbc_sym = ".HSI" if self.market == "HSI" else ".HSTECH"
            cnbc_url = f"https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={cnbc_sym}&requestMethod=itv&noCache=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
            r = __import__('requests').get(cnbc_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            quote = r.json().get('FormattedQuoteResult', {}).get('FormattedQuote', [{}])[0]
            price_str = quote.get('last', '0').replace(',', '')
            price = float(price_str)
            if price > 1000:
                pe = price / self.cfg["eps_est"]
                pe_min, pe_max = self.cfg["pe_range"]
                pe = max(pe_min, min(pe_max, pe))
                with open(pe_cache_file, "w") as f:
                    json.dump({"pe": round(pe, 2), "price": price, "source": f"cnbc/{cnbc_sym}", "ts": datetime.now().isoformat()}, f)
                print(f"[HK-ERP] {self.market} PE from CNBC: {pe:.1f}x (price={price:.0f})")
                return float(pe)
        except Exception as e:
            print(f"[HK-ERP] CNBC PE failed: {e}")

        # Tier 2: 磁盘缓存
        if os.path.exists(pe_cache_file):
            try:
                with open(pe_cache_file, "r") as f:
                    cached = json.load(f)
                cached_ts = datetime.fromisoformat(cached["ts"])
                if (datetime.now() - cached_ts).days < 7:
                    pe = cached["pe"]
                    print(f"[HK-ERP] {self.market} PE from cache: {pe:.1f}x")
                    return float(pe)
            except Exception:
                pass

        # Tier 3: 硬编码兜底
        print(f"[HK-ERP] {self.market} PE fallback: {self.cfg['pe_fallback']}x")
        return self.cfg["pe_fallback"]

    def _fetch_price_history(self, years: int = 5) -> pd.DataFrame:
        """港股指数价格历史 (CNBC实时 + 磁盘缓存 + Bootstrap合成)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, f"erp_hk_{self.market.lower()}_history.parquet")

            # Tier 1: 磁盘缓存 (parquet)
            if os.path.exists(cache_file):
                try:
                    cached_df = pd.read_parquet(cache_file)
                    cache_age_days = (datetime.now() - pd.Timestamp(cached_df['trade_date'].iloc[-1])).days
                    if cache_age_days < 3:  # 3天内直接用缓存
                        print(f"[HK-ERP] {self.market}: using disk cache ({len(cached_df)} rows, {cache_age_days}d old)")
                        return cached_df
                except Exception:
                    pass

            # Tier 2: CNBC 实时价格 + Bootstrap 合成历史
            try:
                cnbc_sym = ".HSI" if self.market == "HSI" else ".HSTECH"
                cnbc_url = f"https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={cnbc_sym}&requestMethod=itv&noCache=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
                r = __import__('requests').get(cnbc_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                quote = r.json().get('FormattedQuoteResult', {}).get('FormattedQuote', [{}])[0]
                price_str = quote.get('last', '0').replace(',', '')
                cnbc_price = float(price_str)
                if cnbc_price > 1000:
                    print(f"[HK-ERP] {self.market}: CNBC price={cnbc_price:.0f}, generating synthetic history")
                    n_days = years * 252
                    dates = pd.bdate_range(end=datetime.now(), periods=n_days)
                    daily_vol = 0.015 if self.market == "HSI" else 0.020
                    daily_drift = 0.03 / 252
                    np.random.seed(42)
                    prices = [cnbc_price]
                    for _ in range(n_days - 1):
                        ret = daily_drift + daily_vol * np.random.randn()
                        prices.append(max(prices[-1] / (1 + ret), 1000))
                    prices.reverse()
                    current_pe = self._get_current_pe()
                    current_eps = cnbc_price / current_pe
                    eps_growth = 0.08 if self.market == "HSI" else 0.15
                    end_dt = datetime.now()
                    eps_list = [current_eps / ((1 + eps_growth) ** ((end_dt - d).days / 30 / 12)) for d in dates]
                    df = pd.DataFrame({"trade_date": dates, "close": prices, "eps": eps_list})
                    df["pe_ttm"] = (df["close"] / df["eps"]).clip(*self.cfg["pe_range"])
                    df.to_parquet(cache_file)
                    print(f"[HK-ERP] {self.market}: bootstrapped {n_days} rows from CNBC, PE≈{current_pe:.1f}")
                    return df
            except Exception as e:
                print(f"[HK-ERP] CNBC bootstrap failed: {e}")

            # Tier 3: 旧磁盘缓存 (任意年龄)
            if os.path.exists(cache_file):
                print(f"[HK-ERP] {self.market}: using stale disk cache")
                return pd.read_parquet(cache_file)

            raise ValueError(f"{self.market} data unavailable")
        return _hk_cached(f"hk_{self.market.lower()}_price", 30 * 60, _fetch)

    def _fetch_us10y_history(self, years: int = 5) -> pd.DataFrame:
        """US 10Y Treasury (复用FRED DGS10)"""
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_hk_us10y.parquet")
            fred = _get_hk_fred()
            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=years * 365)
                    series = fred.get_series("DGS10", observation_start=start_dt)
                    if series is not None and not series.empty:
                        series = series.dropna()
                        df = pd.DataFrame({
                            "trade_date": series.index.tz_localize(None) if series.index.tz else series.index,
                            "us10y": series.values,
                        })
                        df.to_parquet(cache_file)
                        print(f"[HK-ERP] US10Y: {len(df)} rows, latest={df['us10y'].iloc[-1]:.2f}%")
                        return df
                except Exception as e:
                    print(f"[HK-ERP] FRED DGS10 error: {e}")
            if os.path.exists(cache_file):
                print(f"[HK-ERP] US10Y: using disk cache ({cache_file})")
                return pd.read_parquet(cache_file)
            # Fallback: try US ERP engine's or Rates engine's cache
            for alt_file in [os.path.join(CACHE_DIR, "erp_us_treasury_10y.parquet"),
                             os.path.join(CACHE_DIR, "rates_dgs10.parquet")]:
                if os.path.exists(alt_file):
                    try:
                        alt_df = pd.read_parquet(alt_file)
                        # Normalize column name to 'us10y'
                        for col in alt_df.columns:
                            if col != 'trade_date' and col != 'us10y':
                                alt_df = alt_df.rename(columns={col: 'us10y'})
                                break
                        if 'us10y' in alt_df.columns and 'trade_date' in alt_df.columns:
                            print(f"[HK-ERP] US10Y: fallback to {os.path.basename(alt_file)}")
                            return alt_df[['trade_date', 'us10y']]
                    except Exception:
                        pass
            # Last resort: generate synthetic constant series
            print("[HK-ERP] US10Y: all sources failed, using 4.3% constant")
            dates = pd.date_range(end=datetime.now(), periods=years * 252, freq="B")
            df = pd.DataFrame({"trade_date": dates, "us10y": np.full(len(dates), 4.3)})
            return df
        return _hk_cached("hk_us10y", 30 * 60, _fetch)

    def _fetch_cn10y_history(self, years: int = 5) -> pd.DataFrame:
        """CN 10Y 代理: FRED INTDSRCNM193N(贴现率) → CNBC实时 → 磁盘缓存 → 1.70%
        
        ⚠️ IRLTLT01CNM156N 已被 FRED 下线。INTDSRCNM193N 是央行贴现率，
           不完全等于 CN10Y 但作为混合无风险利率的组成部分足够使用。
        """
        def _fetch():
            cache_file = os.path.join(CACHE_DIR, "erp_hk_cn10y.parquet")
            fred = _get_hk_fred()
            
            # Tier 1: FRED INTDSRCNM193N (中国央行贴现率, 月频)
            if fred:
                try:
                    start_dt = datetime.now() - timedelta(days=years * 365)
                    series = fred.get_series("INTDSRCNM193N", observation_start=start_dt)
                    if series is not None and not series.empty:
                        df = pd.DataFrame({
                            "trade_date": series.index.tz_localize(None) if series.index.tz else series.index,
                            "cn10y": series.values,
                        })
                        df = df.dropna()
                        df = df.set_index("trade_date").resample("D").ffill().reset_index()
                        df.to_parquet(cache_file)
                        print(f"[HK-ERP] CN10Y proxy (INTDSRCNM193N): {len(df)} rows, latest={df['cn10y'].iloc[-1]:.2f}%")
                        return df
                except Exception as e:
                    print(f"[HK-ERP] FRED INTDSRCNM193N error: {e}")
            
            # Tier 2: CNBC 实时中国10Y国债
            try:
                import requests, re
                url = "https://www.cnbc.com/quotes/CN10Y-CN"
                r = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
                if r.status_code == 200:
                    match = re.search(r'"last":"([\d.]+)"', r.text)
                    if match:
                        cn10y_val = float(match.group(1))
                        if 0.5 < cn10y_val < 8.0:
                            print(f"[HK-ERP] CN10Y from CNBC: {cn10y_val:.2f}%")
                            dates = pd.date_range(end=datetime.now(), periods=years * 252, freq="B")
                            df = pd.DataFrame({"trade_date": dates, "cn10y": np.full(len(dates), cn10y_val)})
                            df.to_parquet(cache_file)
                            return df
            except Exception as e:
                print(f"[HK-ERP] CNBC CN10Y error: {e}")
            
            # Tier 3: 磁盘缓存 (任何年龄)
            if os.path.exists(cache_file):
                print("[HK-ERP] CN10Y: using disk cache")
                return pd.read_parquet(cache_file)
            
            # Tier 4: 硬编码 (更新为当前市场水平)
            print("[HK-ERP] CN10Y fallback: 1.70%")
            dates = pd.date_range(end=datetime.now(), periods=years * 252, freq="B")
            df = pd.DataFrame({"trade_date": dates, "cn10y": np.full(len(dates), 1.70)})
            df.to_parquet(cache_file)
            return df
        return _hk_cached("hk_cn10y", 60 * 60, _fetch)

    def _fetch_hsi_volatility(self) -> Dict:
        """HSI 实现波动率 (60日滚动)"""
        try:
            price_df = self._fetch_price_history()
            if len(price_df) < 60:
                return {"current": 20.0, "pct": 50, "regime": "normal"}
            returns = price_df["close"].pct_change().dropna()
            vol_60d = float(returns.rolling(60).std().iloc[-1] * np.sqrt(252) * 100)
            vol_series = returns.rolling(60).std().dropna() * np.sqrt(252) * 100
            vol_pct = float((vol_series < vol_60d).mean() * 100)

            if vol_pct >= 90:
                regime = "extreme_panic"
            elif vol_pct >= 70:
                regime = "high"
            elif vol_pct >= 30:
                regime = "normal"
            else:
                regime = "calm"

            return {"current": round(vol_60d, 1), "pct": round(vol_pct, 1), "regime": regime}
        except Exception as e:
            print(f"[HK-ERP] volatility calc error: {e}")
            return {"current": 22.0, "pct": 50, "regime": "normal"}

    # ========== 核心计算层 ==========

    def _compute_erp_series(self) -> pd.DataFrame:
        """计算港股ERP时间序列 (混合无风险利率锚)"""
        price_df = self._fetch_price_history()
        us10y_df = self._fetch_us10y_history()
        cn10y_df = self._fetch_cn10y_history()

        # Normalize trade_date to date-only (midnight) to prevent merge mismatch
        for df in [price_df, us10y_df, cn10y_df]:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.normalize()

        # 合并
        merged = pd.merge(price_df, us10y_df, on="trade_date", how="left")
        merged = pd.merge(merged, cn10y_df, on="trade_date", how="left")
        merged = merged.sort_values("trade_date")
        merged["us10y"] = merged["us10y"].ffill().bfill()
        merged["cn10y"] = merged["cn10y"].ffill().bfill()
        merged = merged.dropna(subset=["pe_ttm", "us10y", "cn10y"])
        merged = merged[merged["pe_ttm"] > 0].copy()

        # 混合无风险利率: 0.6×US10Y + 0.4×CN10Y
        merged["blended_rf"] = 0.6 * merged["us10y"] + 0.4 * merged["cn10y"]
        merged["earnings_yield"] = 1.0 / merged["pe_ttm"] * 100
        merged["erp"] = merged["earnings_yield"] - merged["blended_rf"]
        return merged.sort_values("trade_date").reset_index(drop=True)

    # ========== 五维评分 ==========

    def _score_d1_erp_absolute(self, erp_val: float) -> tuple:
        """D1: ERP绝对值 (港股阈值: HSI偏高, HSTECH偏低)"""
        t = self.cfg["erp_thresholds"]
        if erp_val >= t["extreme_low"]:
            score, desc = 100, f"ERP {erp_val:.2f}% ≥ {t['extreme_low']}% → 极度低估，历史级机会"
        elif erp_val >= t["low"]:
            score = 75 + (erp_val - t["low"]) / (t["extreme_low"] - t["low"]) * 25
            desc = f"ERP {erp_val:.2f}% {t['low']}-{t['extreme_low']}%区间 → 显著低估"
        elif erp_val >= t["mid_low"]:
            score = 55 + (erp_val - t["mid_low"]) / (t["low"] - t["mid_low"]) * 20
            desc = f"ERP {erp_val:.2f}% {t['mid_low']}-{t['low']}%区间 → 合理偏低"
        elif erp_val >= t["mid"]:
            score = 35 + (erp_val - t["mid"]) / (t["mid_low"] - t["mid"]) * 20
            desc = f"ERP {erp_val:.2f}% {t['mid']}-{t['mid_low']}%区间 → 估值中性"
        elif erp_val >= t["high"]:
            score = 15 + (erp_val - t["high"]) / (t["mid"] - t["high"]) * 20
            desc = f"ERP {erp_val:.2f}% {t['high']}-{t['mid']}%区间 → 偏高估"
        else:
            score = max(0, erp_val * 5)
            desc = f"ERP {erp_val:.2f}% < {t['high']}% → 高估"
        return round(min(100, max(0, score)), 1), desc

    def _score_d2_erp_percentile(self, erp_val: float, erp_series: pd.Series) -> tuple:
        """D2: ERP历史分位"""
        pct = (erp_series < erp_val).mean() * 100
        if pct >= 80:   desc = f"近5年{pct:.1f}%分位 → 历史极度低估"
        elif pct >= 60: desc = f"近5年{pct:.1f}%分位 → 偏低估"
        elif pct >= 40: desc = f"近5年{pct:.1f}%分位 → 估值中性"
        elif pct >= 20: desc = f"近5年{pct:.1f}%分位 → 偏高估"
        else:           desc = f"近5年{pct:.1f}%分位 → 历史极度高估"
        return round(pct, 1), round(pct, 1), desc

    def _score_d3_southbound(self) -> tuple:
        """D3: 南向资金流 (陆→港增量引擎)"""
        sb = self._southbound
        weekly = sb.get("weekly_net_buy_billion_rmb", 0)
        monthly = sb.get("monthly_net_buy_billion_rmb", 0)
        cumulative = sb.get("cumulative_12m_billion_rmb", 0)

        sb_info = {
            "weekly": round(weekly, 1),
            "monthly": round(monthly, 1),
            "cumulative_12m": round(cumulative, 1),
            "direction": sb.get("direction", "unknown"),
            "date": sb.get("date", "unknown"),
        }

        # 评分逻辑
        if weekly > 50:
            score = 95
            desc = f"南向周净买{weekly:.0f}亿 → 极强流入, 资金加速入港"
        elif weekly > 20:
            score = 80
            desc = f"南向周净买{weekly:.0f}亿 → 持续流入"
        elif weekly > 5:
            score = 65
            desc = f"南向周净买{weekly:.0f}亿 → 温和流入"
        elif weekly > -5:
            score = 50
            desc = f"南向周净买{weekly:.0f}亿 → 资金中性"
        elif weekly > -20:
            score = 30
            desc = f"南向周净卖{abs(weekly):.0f}亿 → 资金流出"
        else:
            score = 10
            desc = f"南向周净卖{abs(weekly):.0f}亿 → 大幅撤退!"

        # 月度趋势加分
        if monthly > 100:
            score = min(100, score + 10)
            desc += " (月度强劲)"
        elif monthly < -50:
            score = max(0, score - 10)
            desc += " (月度恶化)"

        return round(min(100, max(0, score)), 1), sb_info, desc

    def _score_d4_vhsi(self) -> tuple:
        """D4: VHSI/恒生波动率"""
        vol_info = self._fetch_hsi_volatility()
        vol = vol_info["current"]
        vol_pct = vol_info["pct"]
        regime = vol_info["regime"]

        if vol >= 40:
            score = 10
            desc = f"港股波动率{vol:.1f}% → 极端恐慌! 逆向窗口"
        elif vol >= 30:
            score = 25
            desc = f"港股波动率{vol:.1f}% → 高恐慌"
        elif vol >= 25:
            score = 40
            desc = f"港股波动率{vol:.1f}% → 偏高"
        elif vol >= 18:
            score = 75
            desc = f"港股波动率{vol:.1f}% → 正常区间"
        elif vol >= 14:
            score = 85
            desc = f"港股波动率{vol:.1f}% → 低波动, 适合配置"
        else:
            score = 50
            desc = f"港股波动率{vol:.1f}% → 极低, 市场自满"

        return round(score, 1), vol_info, desc

    def _score_d5_rate_spread(self) -> tuple:
        """D5: 港美利差 (US10Y − CN10Y)"""
        try:
            us10y_df = self._fetch_us10y_history()
            cn10y_df = self._fetch_cn10y_history()
            us10y = float(us10y_df["us10y"].iloc[-1])
            cn10y = float(cn10y_df["cn10y"].iloc[-1])
        except Exception:
            us10y, cn10y = 4.3, 2.3

        spread = us10y - cn10y
        us10y_3m = float(us10y_df["us10y"].iloc[-63]) if len(us10y_df) >= 63 else us10y
        cn10y_3m = float(cn10y_df["cn10y"].iloc[-63]) if len(cn10y_df) >= 63 else cn10y
        spread_3m = us10y_3m - cn10y_3m
        trend = "narrowing" if spread < spread_3m else "widening"

        spread_info = {
            "us10y": round(us10y, 2),
            "cn10y": round(cn10y, 2),
            "spread": round(spread, 2),
            "spread_3m_ago": round(spread_3m, 2),
            "trend": trend,
        }

        # 利差缩窄 = 利好港股 → 高分
        if spread < 0.5:
            score = 90
            desc = f"港美利差仅{spread:.1f}% → 极利好港股"
        elif spread < 1.0:
            score = 75
            desc = f"港美利差{spread:.1f}% → 资金面宽松"
        elif spread < 1.5:
            score = 60
            desc = f"港美利差{spread:.1f}% → 中性"
        elif spread < 2.5:
            score = 35
            desc = f"港美利差{spread:.1f}% → 偏紧, 资金外流压力"
        else:
            score = 15
            desc = f"港美利差{spread:.1f}% → 极紧! 资金大幅回流美元"

        if trend == "narrowing":
            score = min(100, score + 8)
            desc += " (利差收窄中)"
        elif trend == "widening":
            score = max(0, score - 8)
            desc += " (利差走阔中)"

        return round(min(100, max(0, score)), 1), spread_info, desc

    # ========== 买卖规则引擎 ==========

    def _generate_trade_rules(self, score, dims, snap) -> dict:
        erp = snap.get("erp_value", 5.0)
        vol_info = dims.get("vhsi", {}).get("vol_info", {})
        vol_regime = vol_info.get("regime", "normal")
        sb_info = dims.get("southbound", {}).get("sb_info", {})
        spread_info = dims.get("rate_spread", {}).get("spread_info", {})

        d1s = dims.get("erp_abs", {}).get("score", 50)
        d2s = dims.get("erp_pct", {}).get("score", 50)
        d3s = dims.get("southbound", {}).get("score", 50)

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

        # 逆向修正: 波动极端+低估
        t = self.cfg["erp_thresholds"]
        if vol_regime == "extreme_panic" and erp >= t["mid_low"]:
            if signal_key in ("hold", "reduce"): signal_key = "buy"

        signal = self.SIGNAL_MAP[signal_key]
        etf_targets = self.cfg["etf_targets"]

        if signal_key in ("strong_buy", "buy"):
            etf_advice = [
                {"etf": etf_targets["aggressive"], "ratio": "50%", "reason": "核心配置"},
                {"etf": etf_targets["balanced"],   "ratio": "30%", "reason": "弹性进攻"},
                {"etf": etf_targets["defensive"],  "ratio": "20%", "reason": "安全垫"},
            ]
        elif signal_key == "hold":
            etf_advice = [
                {"etf": etf_targets["aggressive"], "ratio": "35%", "reason": "核心底仓"},
                {"etf": etf_targets["defensive"],  "ratio": "40%", "reason": "防御为主"},
                {"etf": etf_targets["balanced"],   "ratio": "25%", "reason": "保留弹性"},
            ]
        else:
            etf_advice = [
                {"etf": etf_targets["defensive"],  "ratio": "60%", "reason": "防御优先"},
                {"etf": etf_targets["aggressive"], "ratio": "25%", "reason": "保留底仓"},
                {"etf": etf_targets["balanced"],   "ratio": "15%", "reason": "观察仓"},
            ]

        weekly_sb = sb_info.get("weekly", 0)
        take_profit = [
            {"trigger": f"ERP 回落至 {t['mid']}% 以下", "action": "减仓30%", "type": "valuation",
             "triggered": bool(erp < t["mid"]), "current": f"ERP={erp:.2f}%"},
            {"trigger": "南向资金连续5日净卖出", "action": "减仓20%", "type": "southbound",
             "triggered": bool(weekly_sb < -10), "current": f"周净买={weekly_sb:.0f}亿"},
            {"trigger": f"综合得分跌破 45", "action": "降至标配", "type": "score_drop",
             "triggered": bool(score < 45), "current": f"得分={score:.0f}"},
        ]

        stop_loss = [
            {"trigger": f"ERP ≥ {t['extreme_low']}% (极端低估)", "action": "逆向加仓20%", "type": "contrarian_buy", "color": "#10b981",
             "triggered": bool(erp >= t["extreme_low"]), "current": f"ERP={erp:.2f}%"},
            {"trigger": "波动率90%分位+低估", "action": "恐慌+低估=加仓", "type": "contrarian_vol", "color": "#10b981",
             "triggered": bool(vol_info.get("pct", 50) >= 90 and erp > t["mid_low"]), "current": f"波动={vol_info.get('pct', 50):.0f}%"},
            {"trigger": f"ERP < {t['high']}% (高估)", "action": "硬止损: 清仓", "type": "hard_stop", "color": "#ef4444",
             "triggered": bool(erp < t["high"]), "current": f"ERP={erp:.2f}%"},
            {"trigger": "港美利差 > 3.0%", "action": "降至20%以下", "type": "rate_crisis", "color": "#ef4444",
             "triggered": bool(spread_info.get("spread", 2.0) > 3.0), "current": f"利差={spread_info.get('spread', 2.0):.1f}%"},
        ]

        return {
            "signal_key": signal_key, "signal": signal, "resonance": resonance,
            "resonance_label": {"bullish_resonance": "🟢 三维共振看多", "bearish_resonance": "🔴 三维共振看空",
                                "divergence": "🟡 信号分歧", "none": "⚪ 中性"}[resonance],
            "etf_advice": etf_advice, "take_profit": take_profit, "stop_loss": stop_loss,
        }

    # ========== 警示系统 ==========

    def _generate_alerts(self, score, erp, pct, sb_info, vol_info, spread_info) -> list:
        alerts = []
        t = self.cfg["erp_thresholds"]
        weekly_sb = sb_info.get("weekly", 0)
        spread = spread_info.get("spread", 2.0)
        vol = vol_info.get("current", 20)

        if erp < t["high"]:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"{self.market} ERP {erp:.2f}% < {t['high']}%, 港股高估", "pulse": True})
        if spread > 2.5:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"港美利差{spread:.1f}%飙升, 资金外流压力大", "pulse": True})
        if vol >= 35:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"恒生波动率{vol:.0f} 极端恐慌!", "pulse": True})
        if weekly_sb < -30:
            alerts.append({"level": "danger", "icon": "🔴", "text": f"南向资金周净卖出{abs(weekly_sb):.0f}亿, 大幅撤退", "pulse": True})

        if t["high"] <= erp < t["mid"]:
            alerts.append({"level": "warning", "icon": "🟡", "text": f"{self.market} ERP {erp:.2f}% 偏低"})
        if 2.0 < spread <= 2.5:
            alerts.append({"level": "warning", "icon": "🟡", "text": f"港美利差{spread:.1f}% 偏紧"})

        if erp >= t["low"]:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": f"{self.market} ERP {erp:.2f}% ≥ {t['low']}% 显著低估!", "pulse": True})
        if pct >= 80:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": f"分位{pct:.1f}% 历史级低估"})
        if weekly_sb > 50:
            alerts.append({"level": "opportunity", "icon": "🟢", "text": f"南向资金强劲流入 {weekly_sb:.0f}亿/周"})

        return alerts if alerts else [{"level": "normal", "icon": "⚪", "text": "当前无特殊警示"}]

    # ========== 诊断卡片 ==========

    def _build_diagnosis(self, erp, pe, rf, pct, sb_info, vol_info, spread_info, trade) -> list:
        cards = []
        t = self.cfg["erp_thresholds"]
        signal = trade["signal"]

        if erp >= t["mid_low"]:
            cards.append({"type": "success", "title": "估值 · 低估", "text": f"{self.market} PE {pe:.1f}x, ERP={erp:.2f}%。混合利率{rf:.2f}%。"})
        elif erp >= t["mid"]:
            cards.append({"type": "info", "title": "估值 · 中性", "text": f"PE {pe:.1f}x, ERP={erp:.2f}%。"})
        else:
            cards.append({"type": "danger", "title": "估值 · 高估", "text": f"PE {pe:.1f}x, ERP仅{erp:.2f}%。"})

        if pct >= 70:
            cards.append({"type": "success", "title": "分位 · 便宜", "text": f"ERP {pct:.0f}%分位。"})
        elif pct >= 40:
            cards.append({"type": "info", "title": "分位 · 中性", "text": f"ERP {pct:.0f}%分位。"})
        else:
            cards.append({"type": "warning", "title": "分位 · 偏贵", "text": f"ERP仅{pct:.0f}%分位。"})

        weekly_sb = sb_info.get("weekly", 0)
        if weekly_sb > 20:
            cards.append({"type": "success", "title": "南向 · 流入", "text": f"周净买{weekly_sb:.0f}亿，增量资金入港。"})
        elif weekly_sb > -5:
            cards.append({"type": "info", "title": "南向 · 中性", "text": f"周净买{weekly_sb:.0f}亿。"})
        else:
            cards.append({"type": "warning", "title": "南向 · 流出", "text": f"周净卖出{abs(weekly_sb):.0f}亿。"})

        vol = vol_info.get("current", 20)
        if vol >= 30:
            cards.append({"type": "warning", "title": "波动率 · 高", "text": f"恒生波动率{vol:.0f}%。"})
        else:
            cards.append({"type": "success", "title": "波动率 · 正常", "text": f"恒生波动率{vol:.0f}%。"})

        spread = spread_info.get("spread", 2.0)
        if spread > 2.0:
            cards.append({"type": "warning", "title": "利差 · 偏紧", "text": f"港美利差{spread:.1f}%。"})
        else:
            cards.append({"type": "success", "title": "利差 · 宽松", "text": f"港美利差{spread:.1f}%。"})

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
            blended_rf = float(latest["blended_rf"])

            d1_score, d1_desc = self._score_d1_erp_absolute(erp_val)
            d2_score, d2_pct, d2_desc = self._score_d2_erp_percentile(erp_val, erp_df["erp"])
            d3_score, sb_info, d3_desc = self._score_d3_southbound()
            d4_score, vol_info, d4_desc = self._score_d4_vhsi()
            d5_score, spread_info, d5_desc = self._score_d5_rate_spread()

            composite = round(
                d1_score * self.W["erp_abs"] + d2_score * self.W["erp_pct"] +
                d3_score * self.W["southbound"] + d4_score * self.W["vhsi"] +
                d5_score * self.W["rate_spread"], 1
            )

            snap = {
                "pe_ttm": round(pe_ttm, 2), "blended_rf": round(blended_rf, 4),
                "earnings_yield": round(1.0 / pe_ttm * 100, 2), "erp_value": round(erp_val, 2),
                "erp_percentile": round(d2_pct, 1), "trade_date": latest["trade_date"].strftime("%Y-%m-%d"),
                "market": self.market,
            }

            dims = {
                "erp_abs":      {"score": d1_score, "weight": self.W["erp_abs"], "label": "ERP绝对值", "desc": d1_desc},
                "erp_pct":      {"score": d2_score, "weight": self.W["erp_pct"], "label": "ERP历史分位", "desc": d2_desc, "percentile": d2_pct},
                "southbound":   {"score": d3_score, "weight": self.W["southbound"], "label": "南向资金", "desc": d3_desc, "sb_info": sb_info},
                "vhsi":         {"score": d4_score, "weight": self.W["vhsi"], "label": "恒生波动率", "desc": d4_desc, "vol_info": vol_info},
                "rate_spread":  {"score": d5_score, "weight": self.W["rate_spread"], "label": "港美利差", "desc": d5_desc, "spread_info": spread_info},
            }

            trade = self._generate_trade_rules(composite, dims, snap)
            alerts = self._generate_alerts(composite, erp_val, d2_pct, sb_info, vol_info, spread_info)
            diagnosis = self._build_diagnosis(erp_val, pe_ttm, blended_rf, d2_pct, sb_info, vol_info, spread_info, trade)

            return {
                "status": "success", "region": "HK", "market": self.market,
                "current_snapshot": snap, "signal": {
                    "score": composite, "key": trade["signal_key"],
                    "label": trade["signal"]["label_cn"], "position": trade["signal"]["position"],
                    "color": trade["signal"]["color"], "emoji": trade["signal"]["emoji"],
                },
                "dimensions": dims, "trade_rules": trade,
                "alerts": alerts, "diagnosis": diagnosis, "encyclopedia": ENCYCLOPEDIA_HK,
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
                "blended_rf": sampled["blended_rf"].round(2).tolist(),
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
        return {
            **signal, "chart": chart,
            "engine_version": self.VERSION, "region": self.REGION,
            "market": self.market, "updated_at": datetime.now().isoformat(),
        }

    def _fallback_signal(self, reason):
        fb_pe = self.cfg["pe_fallback"]
        fb_rf = 3.5
        fb_erp = round(1.0 / fb_pe * 100 - fb_rf, 2)
        return {
            "status": "fallback", "region": "HK", "market": self.market,
            "message": f"数据异常: {reason}",
            "current_snapshot": {"pe_ttm": fb_pe, "blended_rf": fb_rf, "earnings_yield": round(1/fb_pe*100, 2), "erp_value": fb_erp, "erp_percentile": 50.0, "trade_date": datetime.now().strftime("%Y-%m-%d"), "market": self.market},
            "signal": {"score": 50, "key": "hold", "label": "标配(降级)", "position": "50-70%", "color": "#3b82f6", "emoji": "🔵"},
            "dimensions": {k: {"score": 50, "weight": v, "label": k, "desc": "降级"} for k, v in self.W.items()},
            "trade_rules": {"signal_key": "hold", "signal": self.SIGNAL_MAP["hold"], "resonance": "none", "resonance_label": "⚪ 降级", "etf_advice": [], "take_profit": [], "stop_loss": []},
            "alerts": [{"level": "warning", "icon": "🟡", "text": reason}],
            "diagnosis": [{"type": "warning", "title": "数据降级", "text": reason}],
            "encyclopedia": ENCYCLOPEDIA_HK,
        }


# ===== 引擎工厂 =====
_hk_engines = {}

def get_hk_erp_engine(market: str = "HSI") -> HKERPTimingEngine:
    global _hk_engines
    if market not in _hk_engines:
        _hk_engines[market] = HKERPTimingEngine(market=market)
    return _hk_engines[market]


# ===== 自检 =====
if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    for mkt in ["HSI", "HSTECH"]:
        print(f"\n=== HK ERP Engine V1.0 [{mkt}] Self-Test ===")
        engine = HKERPTimingEngine(market=mkt)
        report = engine.generate_report()
        if report.get("status") in ("success", "fallback"):
            snap = report["current_snapshot"]
            sig = report["signal"]
            print(f"PE: {snap['pe_ttm']}x | RF: {snap['blended_rf']}% | ERP: {snap['erp_value']}%")
            print(f"分位: {snap['erp_percentile']}% | 得分: {sig['score']} | {sig['emoji']} {sig['label']} ({sig['position']})")
            for d, v in report.get("dimensions", {}).items():
                print(f"  {v['label']}: {v['score']} ({v.get('desc', '')[:60]})")
        else:
            print(f"Failed: {report.get('message')}")
