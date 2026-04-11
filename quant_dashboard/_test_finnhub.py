"""Test Finnhub API coverage for all tickers used in the overseas strategy framework."""
import requests, json

TOKEN = "d7c76p9r01qsv375ifbgd7c76p9r01qsv375ifc0"
BASE = "https://finnhub.io/api/v1"

def test_quote(sym):
    r = requests.get(f"{BASE}/quote?symbol={sym}&token={TOKEN}", timeout=5)
    d = r.json()
    c = d.get("c", 0)
    return f"  quote: c={c}, pc={d.get('pc',0)}, h={d.get('h',0)}, l={d.get('l',0)}" if c else f"  quote: NO DATA"

def test_metric(sym):
    r = requests.get(f"{BASE}/stock/metric?symbol={sym}&metric=all&token={TOKEN}", timeout=5)
    d = r.json()
    m = d.get("metric", {})
    pe = m.get("peNormalizedAnnual") or m.get("peBasicExclExtraTTM") or m.get("peTTM")
    keys = [k for k in m.keys() if "pe" in k.lower() or "PE" in k]
    return f"  metric: PE={pe}, PE-keys={keys}"

def test_candle(sym, count=5):
    import time
    to_ts = int(time.time())
    from_ts = to_ts - 7 * 86400
    r = requests.get(f"{BASE}/stock/candle?symbol={sym}&resolution=D&from={from_ts}&to={to_ts}&token={TOKEN}", timeout=5)
    d = r.json()
    status = d.get("s", "no_data")
    if status == "ok":
        closes = d.get("c", [])
        return f"  candle: {len(closes)} bars, latest={closes[-1] if closes else 'N/A'}"
    return f"  candle: status={status}"

# === Test all tickers used in the overseas strategy framework ===
tickers = {
    # US
    "SPY":     "S&P500 ETF (erp_us PE/price)",
    "QQQ":     "Nasdaq ETF",
    "SCHD":    "Dividend ETF",
    # Indices
    "^GSPC":   "S&P 500 index",
    # VIX
    "^VIX":    "VIX index (main.py)",
    # FX
    "USDCNY":  "USD/CNY forex",
    "USD/JPY": "USD/JPY forex",
    # Japan
    "^N225":   "Nikkei 225",
    "^TPX":    "TOPIX",
    "1306.T":  "TOPIX ETF (Tokyo)",
    # Hong Kong
    "^HSI":    "Hang Seng Index",
    "2800.HK": "HSI ETF",
    # AAPL for comparison
    "AAPL":    "Apple (control test)",
}

print("=" * 60)
print("Finnhub API Coverage Test")
print("=" * 60)
for sym, desc in tickers.items():
    print(f"\n--- {sym} ({desc}) ---")
    try:
        print(test_quote(sym))
    except Exception as e:
        print(f"  quote: ERROR {e}")
    try:
        print(test_candle(sym))
    except Exception as e:
        print(f"  candle: ERROR {e}")
    if sym in ("SPY", "AAPL", "1306.T"):
        try:
            print(test_metric(sym))
        except Exception as e:
            print(f"  metric: ERROR {e}")
