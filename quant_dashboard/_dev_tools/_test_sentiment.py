"""Test: 东证投資部門別統計 & 信用取引残高 自動取得"""
import urllib.request, json, re, csv, io

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ja,en;q=0.9",
}

# === 1. JPX 信用取引残高 (CSV公開データ) ===
print("=== JPX 信用取引残高 ===")
try:
    # JPX 統計月報 - 信用取引残高 (直近月の CSV)
    url = "https://www.jpx.co.jp/markets/statistics-equities/margin/nlsgeu000005mx48-att/credit_balance.csv"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode('shift_jis', errors='replace')
    print(f"  CSV length: {len(raw)} chars")
    print(f"  First 300: {raw[:300]}")
except Exception as e:
    print(f"  FAILED: {e}")

# === 2. JPX 投資部門別統計 (外国人) ===
print("\n=== JPX 投資部門別統計 ===")
try:
    # 週間の投資部門別売買状況
    url2 = "https://www.jpx.co.jp/markets/statistics-equities/investor-type/nlsgeu000006gevo-att/stock_val_3market_m_202604.csv"
    req2 = urllib.request.Request(url2, headers=headers)
    with urllib.request.urlopen(req2, timeout=15) as resp:
        raw2 = resp.read().decode('shift_jis', errors='replace')
    print(f"  CSV length: {len(raw2)} chars")
    print(f"  First 300: {raw2[:300]}")
except Exception as e:
    print(f"  FAILED (expected - dynamic URL): {e}")

# === 3. yfinance で日経225信用残高代理 ===
print("\n=== yfinance 1357.T (日経レバ) 空売り残高プロキシ ===")
try:
    import yfinance as yf
    # 日経225信用取引のプロキシとして 日経レバETF の出来高/残高
    df = yf.download("1357.T", period="1mo", progress=False)
    if df is not None and not df.empty:
        close = df["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        vol = df["Volume"]
        if hasattr(vol, "columns"):
            vol = vol.iloc[:, 0]
        print(f"  Rows: {len(df)}")
        print(f"  Latest close: {close.iloc[-1]:.0f}")
        print(f"  Avg volume: {vol.mean():.0f}")
except Exception as e:
    print(f"  FAILED: {e}")

# === 4. FRED で日本信用取引のプロキシ ===
print("\n=== FRED 日本 Credit Proxy ===")
try:
    from fredapi import Fred
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import FRED_API_KEY
    f = Fred(api_key=FRED_API_KEY)
    # 日本のcredit to private sector
    s = f.get_series("JPNCLRGDPPR")
    s = s.dropna()
    print(f"  JPNCLRGDPPR: {s.iloc[-1]:.1f} ({s.index[-1].date()}), {len(s)} rows")
except Exception as e:
    print(f"  FAILED: {e}")
