import requests
import re
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_vix")

def _fetch_vix_tradingview():
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

def fetch_vix_for_dashboard_test():
    # 1. TradingView
    logger.info("Trying TradingView...")
    tv_res = _fetch_vix_tradingview()
    if tv_res:
        logger.info(f"TradingView success: {tv_res}")
        return tv_res
        
    # 2. yfinance
    logger.info("Trying yfinance...")
    yf_res = _fetch_vix_yfinance()
    if yf_res:
        logger.info(f"yfinance success: {yf_res}")
        return yf_res
        
    # 3. FRED
    logger.info("FRED fallback...")
    # (omitted for test, we know it works)
    return None

if __name__ == "__main__":
    print("Testing new VIX fetchers:")
    res = fetch_vix_for_dashboard_test()
    print("Final result:", res)
