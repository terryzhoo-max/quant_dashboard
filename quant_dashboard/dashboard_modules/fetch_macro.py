"""
Dashboard Module: 宏观数据抓取 (VIX / CNY)
=========================================
从 main.py 提取，提供 VIX 恐慌指数 + 离岸人民币汇率的抓取。
"""

import requests
import re
from datetime import datetime, timedelta


def fetch_vix_for_dashboard():
    """FRED VIXCLS → CNBC → 默认值 (返回 (latest, prev) 元组)"""
    try:
        from fredapi import Fred
        _fred_key = getattr(__import__('config'), 'FRED_API_KEY', 'eadf412d4f0e8ccd2bb3993b357bdca6')
        fred = Fred(api_key=_fred_key)
        s = fred.get_series("VIXCLS", observation_start=(datetime.now() - timedelta(days=10)))
        if s is not None and not s.empty:
            s = s.dropna()
            if len(s) >= 2:
                return float(s.iloc[-1]), float(s.iloc[-2])
            return float(s.iloc[-1]), float(s.iloc[-1])
    except Exception:
        pass
    # CNBC fallback
    rt = _fetch_vix_cnbc()
    return (rt, rt) if rt else (18.25, 18.25)


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
        print(f"SCRAPER ERROR: {e}")
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
    loop = asyncio.get_event_loop()
    vix_result, cny_result = await asyncio.gather(
        loop.run_in_executor(executor, fetch_vix_for_dashboard),
        loop.run_in_executor(executor, fetch_cny_for_dashboard)
    )
    latest_vix, prev_vix = vix_result
    return latest_vix, prev_vix, cny_result
