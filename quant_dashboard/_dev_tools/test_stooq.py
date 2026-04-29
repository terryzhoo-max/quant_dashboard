import urllib.request, csv, io

# Verify corrected scale factors
for sym, is_etf in [("^spx", False), ("spy.us", True)]:
    try:
        url = f"https://stooq.com/q/l/?s={sym}&f=sd2t2ohlcv&h&e=csv"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(raw))
        for row in reader:
            close = float(row.get("Close", "0"))
            scale = 100.2 if is_etf else 10.0
            wilshire_est = close * scale
            mktcap = wilshire_est / 1000
            print(f"{sym}: Close={close}, Scale={scale}, Wilshire≈{wilshire_est:.0f}, MktCap≈${mktcap:.1f}T")
            break
    except Exception as e:
        print(f"{sym}: ERROR - {e}")

print("\nTarget: Wilshire≈71303, MktCap≈$71.3T")
