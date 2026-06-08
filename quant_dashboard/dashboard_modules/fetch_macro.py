"""
Dashboard Module: 宏观数据抓取 (VIX / CNY)
=========================================
从 main.py 提取，提供 VIX 恐慌指数 + 离岸人民币汇率的抓取。
"""

import requests
import re
import logging
from datetime import datetime, timedelta
from services.fred_guard import fred_get_series

logger = logging.getLogger("alphacore.fetch_macro")


def fetch_vix_for_dashboard():
    """VIX 数据源优先级: TradingView -> yfinance -> FRED -> CNBC -> 默认值"""
    # 1. 优先尝试 TradingView (符合用户指定的 CBOE-VIX 页面)
    tv_res = _fetch_vix_tradingview()
    if tv_res:
        logger.info(f"VIX 数据抓取成功: TradingView -> {tv_res}")
        return tv_res

    # 2. 备用尝试 yfinance (^VIX)
    yf_res = _fetch_vix_yfinance()
    if yf_res:
        logger.info(f"VIX 数据抓取成功: yfinance -> {yf_res}")
        return yf_res

    # 3. 备用尝试 FRED API
    try:
        from fredapi import Fred
        from config import FRED_API_KEY
        fred = Fred(api_key=FRED_API_KEY)
        s = fred_get_series(
            "VIXCLS",
            lambda: fred.get_series("VIXCLS", observation_start=(datetime.now() - timedelta(days=10))),
        )
        if s is not None and not s.empty:
            s = s.dropna()
            if len(s) >= 2:
                logger.info(f"VIX 数据抓取成功: FRED -> ({s.iloc[-1]}, {s.iloc[-2]})")
                return float(s.iloc[-1]), float(s.iloc[-2])
            logger.info(f"VIX 数据抓取成功: FRED -> ({s.iloc[-1]}, {s.iloc[-1]})")
            return float(s.iloc[-1]), float(s.iloc[-1])
    except Exception as e:
        logger.warning(f"FRED VIX fetch failure: {e}")

    # 4. 备用尝试 CNBC
    rt = _fetch_vix_cnbc()
    if rt is not None:
        logger.info(f"VIX 数据抓取成功: CNBC Scraper -> ({rt}, {rt})")
        return rt, rt

    logger.warning("VIX 数据所有渠道抓取失败，使用默认值 (18.25, 18.25)")
    return 18.25, 18.25


def _fetch_vix_tradingview():
    """从 TradingView 抓取 CBOE-VIX 的实时价格和涨跌幅，计算出前一日收盘价。
    返回 (latest_vix, prev_vix) 或者 None。
    """
    url = "https://cn.tradingview.com/symbols/CBOE-VIX/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code == 200:
            html = response.text
            price = None
            m_trade = re.search(r'"trade"\s*:\s*\{\s*"price"\s*:\s*([\d.]+)\s*\}', html)
            if m_trade:
                price = float(m_trade.group(1))
            else:
                m_daily = re.search(r'"daily_bar"\s*:\s*\{\s*"close"\s*:\s*"([\d.]+)"', html)
                if m_daily:
                    price = float(m_daily.group(1))
            
            change_pct = None
            m_change = re.search(r'"change"\s*:\s*([\d.-]+)', html)
            if m_change:
                change_pct = float(m_change.group(1))
                
            if price is not None:
                if change_pct is not None and change_pct != -100:
                    prev_price = price / (1 + change_pct / 100)
                    return price, prev_price
                else:
                    return price, price
    except Exception as e:
        logger.warning(f"TradingView fetch failure: {e}")
    return None


def _fetch_vix_yfinance():
    """从 yfinance 获取 ^VIX 的最新价格 and 前一日收盘价。
    返回 (latest_vix, prev_vix) 或者 None。
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker("^VIX")
        df = ticker.history(period="5d")
        if df is not None and not df.empty:
            df = df.dropna(subset=["Close"])
            if len(df) >= 2:
                return float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
            elif len(df) == 1:
                val = float(df["Close"].iloc[-1])
                return val, val
    except Exception as e:
        logger.warning(f"yfinance fetch failure: {e}")
    return None


def _fetch_vix_cnbc():
    """CNBC VIX scraper"""
    url = "https://www.cnbc.com/quotes/.VIX"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            match = re.search(r'"last":"([\d.]+)"', response.text)
            if match:
                return float(match.group(1))
    except Exception as e:
        logger.warning(f"SCRAPER ERROR: {e}")
    return None


def fetch_cny_for_dashboard():
    """CNBC USD/CNY → 默认值"""
    try:
        url = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=USD/CNY&requestMethod=itv&noCache=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
        r = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        quote = r.json().get('FormattedQuoteResult', {}).get('FormattedQuote', [{}])[0]
        return float(quote.get('last', '7.23').replace(',', ''))
    except Exception:
        return 7.23


async def fetch_macro_data(executor):
    """异步并行抓取 VIX + CNY → 返回 (latest_vix, prev_vix, latest_cny)"""
    import asyncio
    loop = asyncio.get_running_loop()
    vix_result, cny_result = await asyncio.gather(
        loop.run_in_executor(executor, fetch_vix_for_dashboard),
        loop.run_in_executor(executor, fetch_cny_for_dashboard)
    )
    latest_vix, prev_vix = vix_result
    return latest_vix, prev_vix, cny_result
