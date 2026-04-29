"""
AlphaCore · 海外AIAE 数据源全链路诊断
======================================
逐一测试每个数据源的可达性、返回值合理性和缓存状态
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.chdir(os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timedelta

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
INFO = "\033[94mINFO\033[0m"

results = []

def check(name, condition, detail="", warn_only=False):
    tag = PASS if condition else (WARN if warn_only else FAIL)
    status = "PASS" if condition else ("WARN" if warn_only else "FAIL")
    results.append({"name": name, "status": status, "detail": detail})
    print(f"  [{tag}] {name}")
    if detail:
        print(f"         {detail}")
    return condition


print("=" * 70)
print("  AlphaCore 海外AIAE 数据源全链路诊断")
print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

# ================================================================
# 1. FRED API
# ================================================================
print(f"\n{'─'*60}")
print("  [1/7] FRED API 连接")
print(f"{'─'*60}")

try:
    from config import FRED_API_KEY
    fred_key = os.environ.get("FRED_API_KEY", FRED_API_KEY)
    check("FRED API Key 存在", bool(fred_key), f"长度={len(fred_key) if fred_key else 0}")
except Exception as e:
    check("FRED API Key 存在", False, str(e))
    fred_key = None

if fred_key:
    try:
        from fredapi import Fred
        fred = Fred(api_key=fred_key)

        # M2SL
        t0 = time.time()
        m2 = fred.get_series("M2SL", observation_start=datetime.now() - timedelta(days=180))
        m2_val = float(m2.dropna().iloc[-1])
        m2_t = round(m2_val / 1000, 2)
        elapsed = round(time.time() - t0, 2)
        check("FRED M2SL (美国M2)", 15 < m2_t < 30, f"${m2_t}T | {elapsed}s")

        # Margin Debt
        t0 = time.time()
        margin = fred.get_series("BOGZ1FL663067003Q", observation_start=datetime.now() - timedelta(days=400))
        margin_val = float(margin.dropna().iloc[-1])
        margin_t = round(margin_val / 1000000, 4)
        elapsed = round(time.time() - t0, 2)
        check("FRED Margin Debt (季频)", 0.3 < margin_t < 2.0, f"${margin_t}T | date={margin.dropna().index[-1].strftime('%Y-%m-%d')} | {elapsed}s")

        # UMich Sentiment (AAII fallback)
        t0 = time.time()
        umich = fred.get_series("UMCSENT", observation_start=datetime.now() - timedelta(days=90))
        umich_val = float(umich.dropna().iloc[-1])
        elapsed = round(time.time() - t0, 2)
        check("FRED UMCSENT (UMich情绪)", 40 < umich_val < 120, f"UMich={umich_val:.1f} | {elapsed}s")

        # Japan M2 (for JP engine)
        t0 = time.time()
        try:
            jp_m2 = fred.get_series("MABMM201JPM189S", observation_start=datetime.now() - timedelta(days=180))
            jp_m2_val = float(jp_m2.dropna().iloc[-1])
            elapsed = round(time.time() - t0, 2)
            check("FRED JP M2 (日本M2)", jp_m2_val > 0, f"¥{jp_m2_val:,.0f}B | {elapsed}s")
        except Exception as e:
            check("FRED JP M2 (日本M2)", False, str(e)[:80], warn_only=True)

    except Exception as e:
        check("FRED API 整体", False, str(e)[:100])

# ================================================================
# 2. yfinance
# ================================================================
print(f"\n{'─'*60}")
print("  [2/7] yfinance 数据源")
print(f"{'─'*60}")

try:
    import yfinance as yf
    check("yfinance 已安装", True, f"版本: {yf.__version__}")

    # ^W5000
    t0 = time.time()
    df = yf.download("^W5000", period="5d", progress=False)
    elapsed = round(time.time() - t0, 2)
    if df is not None and not df.empty:
        close_col = df["Close"]
        if hasattr(close_col, "columns"):
            close_col = close_col.iloc[:, 0]
        w5000 = float(close_col.dropna().iloc[-1])
        check("yfinance ^W5000 (Wilshire)", 10000 < w5000 < 200000, f"idx={w5000:.0f} | ≈${w5000/1000:.1f}T | {elapsed}s")
    else:
        check("yfinance ^W5000 (Wilshire)", False, f"空DataFrame | {elapsed}s")

    # VTI (fallback)
    t0 = time.time()
    df = yf.download("VTI", period="5d", progress=False)
    elapsed = round(time.time() - t0, 2)
    if df is not None and not df.empty:
        close_col = df["Close"]
        if hasattr(close_col, "columns"):
            close_col = close_col.iloc[:, 0]
        vti = float(close_col.dropna().iloc[-1])
        vti_wilshire = vti * 203.4
        check("yfinance VTI (Wilshire fallback)", 100 < vti < 500, f"VTI=${vti:.2f} | ×203.4→{vti_wilshire:.0f} | {elapsed}s")
    else:
        check("yfinance VTI (Wilshire fallback)", False, f"空DataFrame | {elapsed}s")

    # TOPIX proxy (^N225 or 1306.T)
    for sym, label in [("^N225", "日经225"), ("1306.T", "TOPIX ETF")]:
        t0 = time.time()
        df = yf.download(sym, period="5d", progress=False)
        elapsed = round(time.time() - t0, 2)
        if df is not None and not df.empty:
            close_col = df["Close"]
            if hasattr(close_col, "columns"):
                close_col = close_col.iloc[:, 0]
            val = float(close_col.dropna().iloc[-1])
            check(f"yfinance {sym} ({label})", val > 0, f"¥{val:,.0f} | {elapsed}s")
        else:
            check(f"yfinance {sym} ({label})", False, f"空DataFrame | {elapsed}s")

    # HSI
    t0 = time.time()
    df = yf.download("^HSI", period="5d", progress=False)
    elapsed = round(time.time() - t0, 2)
    if df is not None and not df.empty:
        close_col = df["Close"]
        if hasattr(close_col, "columns"):
            close_col = close_col.iloc[:, 0]
        hsi = float(close_col.dropna().iloc[-1])
        check("yfinance ^HSI (恒生指数)", 10000 < hsi < 50000, f"HK${hsi:,.0f} | {elapsed}s")
    else:
        check("yfinance ^HSI (恒生指数)", False, f"空DataFrame | {elapsed}s")

    # AH Premium basket test (sample: 0939.HK / 601939.SS)
    t0 = time.time()
    df_h = yf.download("0939.HK", period="5d", progress=False)
    df_a = yf.download("601939.SS", period="5d", progress=False)
    elapsed = round(time.time() - t0, 2)
    if df_h is not None and not df_h.empty and df_a is not None and not df_a.empty:
        h_close = df_h["Close"]
        a_close = df_a["Close"]
        if hasattr(h_close, "columns"): h_close = h_close.iloc[:, 0]
        if hasattr(a_close, "columns"): a_close = a_close.iloc[:, 0]
        h_val = float(h_close.dropna().iloc[-1])
        a_val = float(a_close.dropna().iloc[-1])
        check("yfinance AH篮子 (建设银行)", h_val > 0 and a_val > 0,
              f"H={h_val:.2f}HKD A={a_val:.2f}CNY | {elapsed}s")
    else:
        check("yfinance AH篮子 (建设银行)", False, f"数据缺失 | {elapsed}s", warn_only=True)

except ImportError:
    check("yfinance 已安装", False, "pip install yfinance")
except Exception as e:
    check("yfinance 整体", False, str(e)[:100])

# ================================================================
# 3. AAII Sentiment
# ================================================================
print(f"\n{'─'*60}")
print("  [3/7] AAII 散户情绪")
print(f"{'─'*60}")

# Check cached file
aaii_file = os.path.join("data_lake", "aaii_sentiment.json")
if os.path.exists(aaii_file):
    with open(aaii_file, 'r', encoding='utf-8') as f:
        aaii = json.load(f)
    age_days = (time.time() - os.path.getmtime(aaii_file)) / 86400
    spread = aaii.get("spread", 0)
    source = aaii.get("source", "unknown")
    check("AAII 缓存文件", True, f"spread={spread:+.1f}% | source={source} | age={age_days:.1f}天")
    check("AAII 数据新鲜度", age_days < 7, f"{age_days:.1f}天 (阈值7天)", warn_only=True)
else:
    check("AAII 缓存文件", False, "不存在, 将使用默认值", warn_only=True)

# Try direct crawl
try:
    import urllib.request
    req = urllib.request.Request("https://www.aaii.com/sentimentsurvey", headers={
        "User-Agent": "Mozilla/5.0", "Accept": "text/html"
    })
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=8) as resp:
        status = resp.status
    elapsed = round(time.time() - t0, 2)
    check("AAII 网站直连", status == 200, f"HTTP {status} | {elapsed}s")
except Exception as e:
    err = str(e)[:60]
    check("AAII 网站直连", False, f"{err} (预期: 403反爬)", warn_only=True)

# ================================================================
# 4. Tushare (南向资金)
# ================================================================
print(f"\n{'─'*60}")
print("  [4/7] Tushare (南向资金)")
print(f"{'─'*60}")

try:
    import tushare as ts
    check("Tushare 已安装", True, f"版本: {ts.__version__}")

    ts_token = os.environ.get("TUSHARE_TOKEN", "")
    if not ts_token:
        try:
            from config import TUSHARE_TOKEN
            ts_token = TUSHARE_TOKEN
        except:
            pass

    if ts_token:
        check("Tushare Token 存在", True, f"长度={len(ts_token)}")
        t0 = time.time()
        try:
            pro = ts.pro_api(ts_token)
            today = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
            df = pro.moneyflow_hsgt(start_date=start, end_date=today)
            elapsed = round(time.time() - t0, 2)
            if df is not None and not df.empty:
                latest = df.iloc[0]
                south = latest.get("south_money", 0)
                check("Tushare 南向资金", True,
                      f"latest={latest.get('trade_date','')} | 南向={south}万 | {elapsed}s")
            else:
                check("Tushare 南向资金", False, f"空DataFrame | {elapsed}s", warn_only=True)
        except Exception as e:
            check("Tushare 南向资金", False, str(e)[:80], warn_only=True)
    else:
        check("Tushare Token 存在", False, "未配置", warn_only=True)
except ImportError:
    check("Tushare 已安装", False, "pip install tushare", warn_only=True)

# ================================================================
# 5. JPX (信用取引 / 外資流向)
# ================================================================
print(f"\n{'─'*60}")
print("  [5/7] JPX 数据 (信用取引/外資)")
print(f"{'─'*60}")

# Check cached files
jpx_files = {
    "jpx_margin_trading.json": "信用取引残高",
    "jpx_investor_type.json": "外国人投資家",
}
for fname, label in jpx_files.items():
    path = os.path.join("data_lake", fname)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        age = (time.time() - os.path.getmtime(path)) / 86400
        check(f"JPX {label} 缓存", True, f"age={age:.1f}天 | keys={list(data.keys())[:3]}")
    else:
        check(f"JPX {label} 缓存", False, "不存在", warn_only=True)

# Test JPX URL accessibility
try:
    import urllib.request
    jpx_url = "https://www.jpx.co.jp/markets/statistics-equities/margin/index.html"
    req = urllib.request.Request(jpx_url, headers={"User-Agent": "Mozilla/5.0"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=10) as resp:
        status = resp.status
    elapsed = round(time.time() - t0, 2)
    check("JPX 网站可达", status == 200, f"HTTP {status} | {elapsed}s")
except Exception as e:
    check("JPX 网站可达", False, str(e)[:60], warn_only=True)

# ================================================================
# 6. 磁盘缓存完整性
# ================================================================
print(f"\n{'─'*60}")
print("  [6/7] 磁盘缓存文件完整性 (data_lake/)")
print(f"{'─'*60}")

critical_caches = {
    "aiae_us_wilshire.json": {"key": "market_cap_trillion_usd", "min": 10, "max": 200, "label": "Wilshire MktCap"},
    "aiae_us_m2.json": {"key": "m2_trillion_usd", "min": 15, "max": 30, "label": "US M2"},
    "aiae_us_margin.json": {"key": "margin_trillion_usd", "min": 0.3, "max": 2.0, "label": "US Margin"},
    "aiae_jp_topix.json": {"key": "topix_market_cap_trillion_jpy", "min": 0, "max": 99999, "label": "JP TOPIX MktCap"},
    "aiae_hk_mktcap.json": {"key": "market_cap_trillion_hkd", "min": 0, "max": 99999, "label": "HK MktCap"},
}

for fname, spec in critical_caches.items():
    path = os.path.join("data_lake", fname)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            val = data.get(spec["key"], 0)
            source = data.get("source", "?")
            age = (time.time() - os.path.getmtime(path)) / 86400
            in_range = spec["min"] <= val <= spec["max"] if spec["max"] < 99999 else val > 0
            check(f"{fname}", in_range,
                  f"{spec['label']}={val} | source={source} | age={age:.1f}天")
        except Exception as e:
            check(f"{fname}", False, str(e)[:60])
    else:
        check(f"{fname}", False, "不存在 (首次启动会自动创建)", warn_only=True)

# ================================================================
# 7. 引擎端到端测试
# ================================================================
print(f"\n{'─'*60}")
print("  [7/7] 引擎端到端计算测试")
print(f"{'─'*60}")

# US Engine
try:
    from aiae_us_engine import AIAEUSEngine
    t0 = time.time()
    eng = AIAEUSEngine()
    report = eng.generate_report()
    elapsed = round(time.time() - t0, 2)
    if report.get("status") in ("success", "fallback"):
        c = report.get("current", {})
        aiae = c.get("aiae_v1", 0)
        regime = c.get("regime", 0)
        core = c.get("aiae_core", 0)
        mh = c.get("margin_heat", 0)
        check("US引擎 generate_report()", 5 < aiae < 50,
              f"AIAE={aiae:.1f}% R{regime} | Core={core:.1f}% MH={mh:.2f}% | {elapsed}s")
        # Sanity: core不应该是5.0%(地板值)
        check("US Core 非地板值", core > 5.0,
              f"Core={core:.1f}% (5.0%=数据异常)", warn_only=core <= 5.0)
    else:
        check("US引擎 generate_report()", False, f"status={report.get('status')}")
except Exception as e:
    check("US引擎 generate_report()", False, str(e)[:80])

# JP Engine
try:
    from aiae_jp_engine import AIAEJPEngine
    t0 = time.time()
    eng = AIAEJPEngine()
    report = eng.generate_report()
    elapsed = round(time.time() - t0, 2)
    if report.get("status") in ("success", "fallback"):
        c = report.get("current", {})
        aiae = c.get("aiae_v1", 0)
        regime = c.get("regime", 0)
        check("JP引擎 generate_report()", 3 < aiae < 45,
              f"AIAE={aiae:.1f}% R{regime} | {elapsed}s")
    else:
        check("JP引擎 generate_report()", False, f"status={report.get('status')}")
except Exception as e:
    check("JP引擎 generate_report()", False, str(e)[:80])

# HK Engine
try:
    from aiae_hk_engine import AIAEHKEngine
    t0 = time.time()
    eng = AIAEHKEngine()
    report = eng.generate_report()
    elapsed = round(time.time() - t0, 2)
    if report.get("status") in ("success", "fallback"):
        c = report.get("current", {})
        aiae = c.get("aiae_v1", 0)
        regime = c.get("regime", 0)
        check("HK引擎 generate_report()", 3 < aiae < 40,
              f"AIAE={aiae:.1f}% R{regime} | {elapsed}s")
    else:
        check("HK引擎 generate_report()", False, f"status={report.get('status')}")
except Exception as e:
    check("HK引擎 generate_report()", False, str(e)[:80])


# ================================================================
# SUMMARY
# ================================================================
print(f"\n{'='*70}")
print("  诊断总结")
print(f"{'='*70}")

passes = sum(1 for r in results if r["status"] == "PASS")
warns = sum(1 for r in results if r["status"] == "WARN")
fails = sum(1 for r in results if r["status"] == "FAIL")
total = len(results)

print(f"  PASS: {passes}/{total} | WARN: {warns}/{total} | FAIL: {fails}/{total}")
print()

if fails > 0:
    print(f"  \033[91m[FAIL 项目]\033[0m")
    for r in results:
        if r["status"] == "FAIL":
            print(f"    - {r['name']}: {r['detail']}")
    print()

if warns > 0:
    print(f"  \033[93m[WARN 项目]\033[0m")
    for r in results:
        if r["status"] == "WARN":
            print(f"    - {r['name']}: {r['detail']}")

print(f"\n{'='*70}")
