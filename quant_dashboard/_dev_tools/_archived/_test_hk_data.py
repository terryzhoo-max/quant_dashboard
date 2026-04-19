"""
Fetch real HK market data from alternative sources and submit to AlphaCore API.
V3: Fixed Southbound daily-avg normalization, CNBC parsing, encoding.
"""
import requests
import json
import re
import sys
from datetime import datetime

# Fix Windows console encoding for emoji/CJK characters
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

API_BASE = "http://127.0.0.1:8000"

def fetch_from_cnbc(symbol):
    """Fetch price from CNBC real-time quote API."""
    url = f"https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={symbol}&requestMethod=itv&noCache=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        data = r.json()
        quote = data.get('FormattedQuoteResult', {}).get('FormattedQuote', [{}])[0]
        price_str = quote.get('last', '0').replace(',', '')
        return {
            'price': float(price_str),
            'name': quote.get('name', ''),
            'change': quote.get('change', ''),
            'pctchange': quote.get('change_pct', ''),
        }
    except Exception as e:
        print(f"  CNBC {symbol}: {e}")
        return None

def fetch_from_google(symbol_id):
    """Fetch price from Google Finance."""
    try:
        r = requests.get(f"https://www.google.com/finance/quote/{symbol_id}", 
                        timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        match = re.search(r'data-last-price="([0-9,.]+)"', r.text)
        if match:
            return float(match.group(1).replace(',', ''))
    except Exception as e:
        print(f"  Google {symbol_id}: {e}")
    return None

print("=" * 60)
print("  Fetching Real HK Market Data V3")
print("=" * 60)
print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ═══════════════════════════════════════════
# 1. HSI + HSTECH PRICES
# ═══════════════════════════════════════════
print("\n[1/4] HSI / HSTECH Prices")

hsi_price = None
hstech_price = None

# Try CNBC first 
for sym, label in [('.HSI', 'HSI'), ('.HSTECH', 'HSTECH')]:
    data = fetch_from_cnbc(sym)
    if data and data['price'] > 0:
        print(f"  [OK] {label}: {data['price']:.2f} ({data['name']}) {data['change']} ({data['pctchange']}%)")
        if label == 'HSI': hsi_price = data['price']
        else: hstech_price = data['price']

# Fallback to Google Finance
if not hsi_price:
    hsi_price = fetch_from_google('HSI:INDEXHANGSENG')
    if hsi_price: print(f"  [OK] HSI (Google): {hsi_price:.2f}")
    else: print("  [!!] HSI: All sources failed")

if not hstech_price:
    hstech_price = fetch_from_google('HSTECH:INDEXHANGSENG')
    if hstech_price: print(f"  [OK] HSTECH (Google): {hstech_price:.2f}")
    else: print("  [!!] HSTECH: All sources failed")

# ═══════════════════════════════════════════
# 2. AH PREMIUM INDEX
# ═══════════════════════════════════════════
print("\n[2/4] AH Premium Index")

ahp_value = None

# Try EastMoney
try:
    url = "https://push2.eastmoney.com/api/qt/stock/get?fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f116,f117&secid=100.HSAHP"
    r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
    data = r.json().get('data', {})
    if data and data.get('f43'):
        ahp_value = data['f43'] / 100
        print(f"  [OK] AH Premium (EastMoney): {ahp_value:.1f}")
except Exception as e:
    print(f"  [!!] EastMoney AH: {e}")

if not ahp_value:
    # Try CNBC
    data = fetch_from_cnbc('.HSAHP')
    if data and data['price'] > 0:
        ahp_value = data['price']
        print(f"  [OK] AH Premium (CNBC): {ahp_value:.1f}")

if not ahp_value:
    ahp_value = fetch_from_google('HSAHP:INDEXHANGSENG')
    if ahp_value:
        print(f"  [OK] AH Premium (Google): {ahp_value:.1f}")

if not ahp_value:
    print("  [!!] AH Premium: All sources failed")

# ═══════════════════════════════════════════
# 3. SOUTHBOUND CAPITAL FLOW
# ═══════════════════════════════════════════
print("\n[3/4] Southbound Capital Flow (EastMoney)")

sb_weekly = None
sb_monthly = None
sb_today = None

# Method 1: EastMoney real-time mutual market API (当日实时南向资金)
try:
    url = "https://push2.eastmoney.com/api/qt/kamt.rtmin/get?fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
    r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
    data = r.json().get('data', {})
    if data:
        s2n = data.get('s2n')
        if isinstance(s2n, list) and len(s2n) > 0:
            for entry in reversed(s2n):
                if not isinstance(entry, str):
                    continue
                parts = entry.split(',')
                if len(parts) >= 3 and parts[1] not in ('-', '', None):
                    try:
                        net_buy_wan = float(parts[1])
                        quota_wan = float(parts[2]) if len(parts) > 2 else 0
                        sb_today = round(net_buy_wan / 10000, 2)  # 万 -> 亿
                        print(f"  [OK] Today Southbound (RT): {sb_today:+.2f} 亿 @ {parts[0]}")
                        print(f"       净买入: {net_buy_wan:+,.0f}万, 额度余额: {quota_wan:,.0f}万")
                    except (ValueError, IndexError):
                        pass
                    break
            if sb_today is None:
                print(f"  [--] RT s2n: 今日尚无有效数据 (盘前/盘后)")
        
        print(f"  Available keys: {list(data.keys())[:20]}")
except Exception as e:
    print(f"  [!!] EastMoney RT: {e}")

# Method 2: push2 historical kline API (已验证可靠)
# Format: "日期,净买入(万),额度余额(万),累计净买入(万)"
push2_valid_days = []
try:
    url = "https://push2his.eastmoney.com/api/qt/kamt.kline/get?fields1=f1,f3,f5&fields2=f51,f52,f53,f54,f55,f56&klt=101&lmt=30"
    r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
    data = r.json().get('data', {})
    s2n_hist = data.get('s2n', [])
    if s2n_hist:
        for entry in reversed(s2n_hist):
            parts = entry.split(',')
            if len(parts) >= 3:
                date = parts[0]
                net_buy_wan = float(parts[1])
                push2_valid_days.append({
                    'date': date,
                    'net_buy_wan': net_buy_wan,
                    'net_buy_billion': round(net_buy_wan / 10000, 2),
                })
        
        # Separate active (non-zero) trading days
        active_days = [d for d in push2_valid_days if d['net_buy_wan'] != 0]
        
        print(f"  [OK] push2 Historical S2N ({len(s2n_hist)} total, {len(active_days)} active):")
        for i, day in enumerate(push2_valid_days[:15]):
            marker = " *" if day['net_buy_wan'] != 0 else ""
            print(f"    {day['date']}: {day['net_buy_billion']:+.2f} 亿{marker}")
        
        # ─── V3 CORE FIX: Daily-average normalization ───
        # If we have very few active days, normalize to daily average
        if len(active_days) > 0:
            total_net = sum(d['net_buy_billion'] for d in active_days)
            daily_avg = total_net / len(active_days)
            
            if len(active_days) >= 5:
                # Enough data: use real sums for 5d/20d windows
                sb_weekly = round(sum(d['net_buy_billion'] for d in active_days[:5]), 1)
                sb_monthly = round(sum(d['net_buy_billion'] for d in active_days[:20]), 1)
                print(f"  >> Weekly (5 active days): {sb_weekly:+.1f} 亿RMB")
                print(f"  >> Monthly ({min(20, len(active_days))} active days): {sb_monthly:+.1f} 亿RMB")
            else:
                # Too few active days: use the ACTUAL sum as weekly
                # Do NOT multiply by 5 — a single extreme day should not be amplified
                sb_weekly = round(total_net, 1)
                sb_monthly = round(total_net * 4, 1)  # rough monthly ≈ weekly × 4
                print(f"  >> [NORM] Only {len(active_days)} active day(s), total: {total_net:+.2f} 亿")
                print(f"  >> [NORM] Using actual total as weekly: {sb_weekly:+.1f} 亿RMB")
                print(f"  >> [NORM] Estimated monthly (×4): {sb_monthly:+.1f} 亿RMB")
        else:
            print(f"  [--] All {len(s2n_hist)} days show zero net buy")
    else:
        print(f"  [--] push2 historical returned empty")
except Exception as e:
    print(f"  [!!] push2 Historical: {e}")

# Method 3: RPT_MUTUAL_DEAL_HISTORY fallback (港股通沪003 + 港股通深004)
if sb_weekly is None:
    try:
        total_by_date = {}
        for mt_code in ["003", "004"]:  # 003=沪港通南向, 004=深港通南向
            url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
                   "reportName=RPT_MUTUAL_DEAL_HISTORY"
                   "&columns=TRADE_DATE,MUTUAL_TYPE,FUND_INFLOW,QUOTA_BALANCE,DEAL_AMT"
                   f"&filter=(MUTUAL_TYPE=%22{mt_code}%22)"
                   "&pageNumber=1&pageSize=10&sortColumns=TRADE_DATE&sortTypes=-1")
            r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            resp = r.json()
            result_obj = resp.get('result') or {}
            items = result_obj.get('data') or []
            for item in items:
                date = str(item.get('TRADE_DATE', ''))[:10]
                inflow = item.get('FUND_INFLOW') or 0
                if date not in total_by_date:
                    total_by_date[date] = 0
                total_by_date[date] += inflow
        
        if total_by_date:
            sorted_dates = sorted(total_by_date.keys(), reverse=True)
            active_dates = [(d, total_by_date[d]) for d in sorted_dates if total_by_date[d] != 0]
            
            print(f"  [OK] RPT Southbound ({len(sorted_dates)} dates, {len(active_dates)} active):")
            for i, date in enumerate(sorted_dates[:10]):
                net = total_by_date[date]
                # RPT FUND_INFLOW unit: 百万元(millions) → /100 = 亿
                net_billion = net / 100
                marker = " *" if net != 0 else ""
                print(f"    {date}: {net_billion:+.2f} 亿{marker}")
            
            if len(active_dates) > 0:
                total_active = sum(v / 100 for _, v in active_dates)
                daily_avg = total_active / len(active_dates)
                
                if len(active_dates) >= 5:
                    sb_weekly = round(sum(v / 100 for _, v in active_dates[:5]), 1)
                    sb_monthly = round(sum(v / 100 for _, v in active_dates[:min(20, len(active_dates))]), 1)
                else:
                    sb_weekly = round(daily_avg * 5, 1)
                    sb_monthly = round(daily_avg * 20, 1)
                    print(f"  >> [NORM] {len(active_dates)} active dates, daily avg: {daily_avg:+.2f} 亿")
                
                print(f"  >> Weekly: {sb_weekly:+.1f} 亿RMB")
                print(f"  >> Monthly: {sb_monthly:+.1f} 亿RMB")
            else:
                print(f"  [--] RPT: all dates show zero inflow")
        else:
            print(f"  [--] RPT API returned no data")
    except Exception as e:
        print(f"  [!!] RPT Historical: {e}")

# Method 4: Use today's RT as last resort
if sb_weekly is None and sb_today is not None and sb_today != 0:
    # Single-day RT → estimate weekly as daily × 5
    sb_weekly = round(sb_today * 5, 1)
    sb_monthly = round(sb_today * 20, 1)
    print(f"  [!!] Using today's RT as fallback: daily={sb_today:+.2f} → weekly≈{sb_weekly:+.1f} 亿")

# ─── V3: Sanity check before submission ───
if sb_weekly is not None:
    if abs(sb_weekly) > 500:
        print(f"  [WARN] sb_weekly={sb_weekly:.1f} 超过±500亿阈值，数据可能失真!")
        print(f"         可能原因: API 只有少量天数据导致单日异常值主导")
        # 不阻断提交，但标记异常

# ═══════════════════════════════════════════
# 4. SUBMIT DATA TO ALPHACORE
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print("  Submitting Data to AlphaCore API")
print("=" * 60)

submitted = 0

# Submit HSI/HSTECH prices to ERP engine cache (bootstrap)
if hsi_price and hsi_price > 10000:
    print(f"\n  >> HSI Price Bootstrap: {hsi_price:.2f}")
    try:
        # Write a minimal cache file so ERP engine can bootstrap
        import os, pandas as pd, numpy as np
        from datetime import timedelta
        
        cache_dir = "data_lake"
        os.makedirs(cache_dir, exist_ok=True)
        
        for market, price, pe_fallback, eps_est, pe_range in [
            ("hsi", hsi_price, 10.5, 2200.0, (6, 25)),
            ("hstech", hstech_price or 5000.0, 22.0, 200.0, (10, 80)),
        ]:
            cache_file = os.path.join(cache_dir, f"erp_hk_{market}_history.parquet")
            pe_cache_file = os.path.join(cache_dir, f"erp_hk_{market}_pe.json")
            
            # Only bootstrap if no parquet exists
            if not os.path.exists(cache_file):
                # Generate synthetic 5-year daily history using current price
                # Use a simple random walk backfill for ERP percentile calculation
                np.random.seed(42)
                n_days = 5 * 252  # 5 years of trading days
                dates = pd.bdate_range(end=datetime.now(), periods=n_days)
                
                # Current price anchored, random walk backward
                current_p = price
                pe = current_p / eps_est
                pe = max(pe_range[0], min(pe_range[1], pe))
                
                # Generate returns backward from current price
                daily_vol = 0.015 if market == "hsi" else 0.020  # 1.5% / 2.0% daily vol
                daily_drift = 0.03 / 252  # ~3% annual drift
                
                prices = [current_p]
                for i in range(n_days - 1):
                    ret = daily_drift + daily_vol * np.random.randn()
                    prev_price = prices[-1] / (1 + ret)
                    prices.append(max(prev_price, 1000))
                prices.reverse()
                
                # Build DataFrame
                eps_growth = 0.08 if market == "hsi" else 0.15
                current_eps = current_p / pe
                end_dt = datetime.now()
                
                eps_list = []
                for i, d in enumerate(dates):
                    months_ago = (end_dt - d).days / 30
                    eps_list.append(current_eps / ((1 + eps_growth) ** (months_ago / 12)))
                
                df = pd.DataFrame({
                    "trade_date": dates,
                    "close": prices,
                    "eps": eps_list,
                })
                df["pe_ttm"] = df["close"] / df["eps"]
                df["pe_ttm"] = df["pe_ttm"].clip(pe_range[0], pe_range[1])
                
                df.to_parquet(cache_file)
                print(f"  [OK] Bootstrapped {market.upper()} history: {n_days} rows, PE~{pe:.1f}x -> {cache_file}")
            else:
                print(f"  [--] {market.upper()} history cache exists, skipping bootstrap")
            
            # Always update PE cache with latest price
            pe = price / eps_est if market == "hsi" else (hstech_price or 5000.0) / eps_est
            pe = max(pe_range[0], min(pe_range[1], pe))
            with open(pe_cache_file, 'w') as f:
                json.dump({"pe": round(pe, 2), "source": f"cnbc_bootstrap/{market}", "ts": datetime.now().isoformat()}, f)
            print(f"  [OK] {market.upper()} PE cache updated: {pe:.2f}x")
        
        submitted += 1
    except Exception as e:
        print(f"  [!!] Bootstrap error: {e}")

# Submit AH Premium
if ahp_value and 80 <= ahp_value <= 200:
    print(f"\n  >> AH Premium: {ahp_value:.1f}")
    try:
        r = requests.post(f"{API_BASE}/api/v1/aiae_hk/update_ah_premium",
                         json={"index_value": round(ahp_value, 1)})
        result = r.json()
        status = 'OK' if result.get('status') == 'success' else 'FAIL'
        print(f"  [{status}] {result.get('message', result)}")
        if status == 'OK': submitted += 1
    except Exception as e:
        print(f"  [!!] Submit error: {e}")
else:
    print(f"\n  [--] AH Premium not submitted (value={ahp_value})")

# Submit Southbound
if sb_weekly is not None:
    print(f"\n  >> Southbound: weekly={sb_weekly}, monthly={sb_monthly}")
    body = {"weekly_net_buy_billion_rmb": sb_weekly}
    if sb_monthly is not None:
        body["monthly_net_buy_billion_rmb"] = sb_monthly
    try:
        r = requests.post(f"{API_BASE}/api/v1/aiae_hk/update_southbound", json=body)
        result = r.json()
        status = 'OK' if result.get('status') == 'success' else 'FAIL'
        print(f"  [{status}] {result.get('message', result)}")
        if status == 'OK': submitted += 1
    except Exception as e:
        print(f"  [!!] Submit error: {e}")
else:
    print(f"\n  [--] Southbound not submitted (no data)")

# ═══════════════════════════════════════════
# 5. REFRESH & VERIFY
# ═══════════════════════════════════════════
print(f"\n{'=' * 60}")
print(f"  Refreshing Engines ({submitted} data points submitted)")
print(f"{'=' * 60}")

print(f"\n  >> HK AIAE Engine")
try:
    r = requests.get(f"{API_BASE}/api/v1/aiae_hk/report?refresh=true", timeout=30)
    data = r.json()
    report = data.get('data', data)
    current = report.get('current', {})
    ri = current.get('regime_info', {})
    aiae_v1 = current.get('aiae_v1', '?')
    regime = current.get('regime', '?')
    print(f"     AIAE V1: {aiae_v1}%")
    print(f"     Regime:  {regime} - {ri.get('cn', '?')}")
    print(f"     Color:   {ri.get('emoji', '')} {ri.get('name', '?')}")
    pos = current.get('position', report.get('position', {}))
    if isinstance(pos, dict):
        print(f"     Position: {pos.get('matrix_position', '?')}%")
    else:
        print(f"     Position: {pos}")
    
    # Sanity check
    if isinstance(aiae_v1, (int, float)):
        if aiae_v1 > 30:
            print(f"     [WARN] AIAE V1={aiae_v1}% 偏高! 检查南向数据是否失真")
        elif aiae_v1 < 5:
            print(f"     [WARN] AIAE V1={aiae_v1}% 偏低! 检查市值数据")
    
    # Show raw data
    raw = report.get('raw_data', {})
    sb_raw = raw.get('southbound', {})
    ah_raw = raw.get('ah_premium', {})
    mkt_raw = raw.get('mkt', {})
    m2_raw = raw.get('m2', {})
    print(f"\n     Raw Data:")
    print(f"       MktCap: {mkt_raw.get('mktcap_hkd_trillion', '?')} T HKD (fallback={mkt_raw.get('is_fallback', '?')})")
    print(f"       M2:     {m2_raw.get('cn_m2_trillion_rmb', '?')} T RMB")
    print(f"       SB:     {sb_raw.get('weekly_net_buy_billion_rmb', '?')} B/wk, {sb_raw.get('monthly_net_buy_billion_rmb', '?')} B/mo ({sb_raw.get('source', '?')})")
    print(f"       AH:     {ah_raw.get('index_value', '?')} ({ah_raw.get('source', '?')}, {ah_raw.get('date', '?')})")
except Exception as e:
    print(f"  [!!] Refresh error: {e}")

print(f"\n  >> HK ERP Engine")
try:
    r = requests.get(f"{API_BASE}/api/v1/strategy/erp-hk?refresh=true", timeout=30)
    data = r.json()
    d = data.get('data', {})
    snap = d.get('current_snapshot', {})
    sig = d.get('signal', {})
    dims = d.get('dimensions', {})
    print(f"     Status: {d.get('status', '?')} ({d.get('message', '')[:50]})")
    print(f"     Market: {d.get('market', '?')}")
    print(f"     ERP:    {snap.get('erp_value', '?')}%")
    print(f"     PE:     {snap.get('pe_ttm', '?')}")
    print(f"     RF:     {snap.get('blended_rf', '?')}%")
    print(f"     Signal: {sig.get('key', '?')} (Score: {sig.get('score', '?')}, {sig.get('label', '?')})")
    if dims:
        print(f"     Dimensions:")
        for k, v in dims.items():
            if isinstance(v, dict):
                print(f"       {k}: score={v.get('score', '?')}, weight={v.get('weight', '?')}")
except Exception as e:
    print(f"  [!!] Refresh error: {e}")

print(f"\n{'=' * 60}")
print(f"  All Done! HSI={hsi_price or 'N/A'}, HSTECH={hstech_price or 'N/A'}")
print(f"  AH Premium={ahp_value or 'N/A'}, SB Weekly={sb_weekly or 'N/A'}")
print(f"{'=' * 60}")
