import requests
import re

url = "https://cn.tradingview.com/symbols/CBOE-VIX/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

try:
    r = requests.get(url, headers=headers, timeout=10)
    print("Status code:", r.status_code)
    
    price = None
    change_pct = None
    
    # Method 1: trade price
    m1 = re.search(r'"trade"\s*:\s*\{\s*"price"\s*:\s*([\d.]+)\s*\}', r.text)
    if m1:
        price = float(m1.group(1))
        print("Method 1 (trade price):", price)
        
    # Method 2: daily_bar close
    m2 = re.search(r'"daily_bar"\s*:\s*\{\s*"close"\s*:\s*"([\d.]+)"', r.text)
    if m2:
        price = float(m2.group(1))
        print("Method 2 (daily_bar close):", price)
        
    # Method 3: change percentage
    m3 = re.search(r'"change"\s*:\s*([\d.-]+)', r.text)
    if m3:
        change_pct = float(m3.group(1))
        print("Method 3 (change percent):", change_pct)
        
    if price is not None and change_pct is not None:
        prev_price = price / (1 + change_pct / 100)
        print(f"Calculated prev_price: {prev_price:.4f}")
        
except Exception as e:
    print("Error:", e)
