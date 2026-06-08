"""
Dashboard Module: 宏观数据抓取 (VIX / CNY)
=========================================
从 main.py 提取，提供 VIX 恐慌指数 + 离岸人民币汇率的抓取。
"""

import requests
import re
import logging
import json
import yfinance as yf
from datetime import datetime, timedelta
from typing import Tuple, Optional
from services.fred_guard import fred_get_series

logger = logging.getLogger("alphacore.fetch_macro")


def fetch_vix_for_dashboard() -> Tuple[float, float]:
    """Production-grade VIX fetch: TradingView -> yfinance -> FRED -> CNBC -> Default"""
    # 1. TradingView
    try:
        latest, prev = _fetch_vix_tradingview()
        if latest is not None and prev is not None:
            logger.info(f"VIX successfully fetched from TradingView: latest={latest}, prev={prev}")
            return latest, prev
    except Exception as e:
        logger.warning(f"TradingView VIX fetch failed: {e}")

    # 2. yfinance fallback
    try:
        latest, prev = _fetch_vix_yfinance()
        if latest is not None and prev is not None:
            logger.info(f"VIX successfully fetched from yfinance: latest={latest}, prev={prev}")
            return latest, prev
    except Exception as e:
        logger.warning(f"yfinance VIX fetch failed: {e}")

    # 3. FRED fallback
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
                logger.info(f"VIX successfully fetched from FRED: latest={float(s.iloc[-1])}, prev={float(s.iloc[-2])}")
                return float(s.iloc[-1]), float(s.iloc[-2])
            logger.info(f"VIX successfully fetched from FRED (single): latest={float(s.iloc[-1])}")
            return float(s.iloc[-1]), float(s.iloc[-1])
    except Exception as e:
        logger.warning(f"FRED VIX fetch failed: {e}")

    # 4. CNBC fallback
    try:
        rt = _fetch_vix_cnbc()
        if rt is not None:
            logger.info(f"VIX successfully fetched from CNBC: latest={rt}")
            return rt, rt
    except Exception as e:
        logger.warning(f"CNBC VIX fetch failed: {e}")

    # 5. Ultimate default fallback
    logger.warning("All VIX data sources failed. Using default values.")
    return 18.25, 18.25


def _fetch_vix_tradingview() -> Tuple[Optional[float], Optional[float]]:
    """Scrape cn.tradingview.com for VIX price and change percent"""
    url = "https://cn.tradingview.com/symbols/CBOE-VIX/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code != 200:
            logger.warning(f"TradingView responded with status code {response.status_code}")
            return None, None
            
        for m in re.finditer(r'<script[^>]*>(.*?)</script>', response.text, re.DOTALL):
            content = m.group(1).strip()
            if not content or '"pro_symbol":"CBOE:VIX"' not in content:
                continue
            try:
                data = json.loads(content)
                for k, v in data.items():
                    if isinstance(v, dict) and "data" in v:
                        data_dict = v["data"]
                        sym_data = data_dict.get("symbol", {})
                        
                        price = None
                        trade = sym_data.get("trade")
                        if trade and isinstance(trade, dict) and "price" in trade:
                            price = float(trade["price"])
                        else:
                            daily_bar = sym_data.get("daily_bar")
                            if daily_bar and isinstance(daily_bar, dict) and "close" in daily_bar:
                                price = float(daily_bar["close"])
                                
                        change = None
                        screener_data = data_dict.get("symbol_screener_data")
                        if screener_data and isinstance(screener_data, dict) and "change" in screener_data:
                            change = float(screener_data["change"])
                        else:
                            faq_data = data_dict.get("symbol_faq_data", [])
                            if faq_data and isinstance(faq_data, list):
                                vars_dict = faq_data[0].get("variables", {})
                                change_obj = vars_dict.get("daily_bar_change", {})
                                fields = change_obj.get("fields", [{}])
                                if fields and isinstance(fields, list) and "value" in fields[0]:
                                    change = float(fields[0]["value"])
                                    
                        if price is not None:
                            if change is not None:
                                factor = 1.0 + change / 100.0
                                prev = price / factor if factor != 0 else price
                                return price, prev
                            else:
                                return price, price
            except Exception as e:
                logger.debug(f"Failed to parse script tag JSON in TradingView scraper: {e}")
    except Exception as e:
        logger.warning(f"TradingView fetch HTTP error: {e}")
    return None, None


def _fetch_vix_yfinance() -> Tuple[Optional[float], Optional[float]]:
    """Fetch VIX data from Yahoo Finance"""
    ticker = yf.Ticker("^VIX")
    hist = ticker.history(period="5d", timeout=5)
    if hist is not None and not hist.empty and len(hist) >= 1:
        latest = float(hist.iloc[-1]['Close'])
        prev = float(hist.iloc[-2]['Close']) if len(hist) >= 2 else latest
        return latest, prev
    return None, None


def _fetch_vix_cnbc() -> Optional[float]:
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


def fetch_cny_for_dashboard() -> float:
    """CNBC USD/CNY → 默认值"""
    try:
        url = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=USD/CNY&requestMethod=itv&noCache=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
        r = requests.get(url, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
        quote = r.json().get('FormattedQuoteResult', {}).get('FormattedQuote', [{}])[0]
        return float(quote.get('last', '7.23').replace(',', ''))
    except Exception:
        return 7.23


async def fetch_macro_data(executor) -> Tuple[float, float, float]:
    """异步并行抓取 VIX + CNY → 返回 (latest_vix, prev_vix, latest_cny)"""
    import asyncio
    loop = asyncio.get_running_loop()
    vix_result, cny_result = await asyncio.gather(
        loop.run_in_executor(executor, fetch_vix_for_dashboard),
        loop.run_in_executor(executor, fetch_cny_for_dashboard)
    )
    latest_vix, prev_vix = vix_result
    return latest_vix, prev_vix, cny_result
