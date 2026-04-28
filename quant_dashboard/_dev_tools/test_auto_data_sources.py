"""
AlphaCore · 自动化数据源可行性测试
===================================
测试三项:
  1. Tushare moneyflow_hsgt (南向资金) — 是否已生效
  2. yfinance ^HSAHP (AH溢价指数) — 可行性测试
  3. JPX 信用取引 + 外資統計 — URL探测 + 下载可行性

运行: python _dev_tools/test_auto_data_sources.py
"""

import sys
import json
import time
from datetime import datetime, timedelta

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

results = {}

print("=" * 60)
print("  AlphaCore · 自动化数据源可行性测试")
print("=" * 60)


# ===== 测试 1: Tushare moneyflow_hsgt =====
print("\n[1/4] 🇭🇰 Tushare 南向资金 (moneyflow_hsgt) ...")

try:
    import tushare as ts
    pro = ts.pro_api()
    today_str = datetime.now().strftime('%Y%m%d')
    start_str = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
    
    df = pro.moneyflow_hsgt(start_date=start_str, end_date=today_str, limit=10)
    
    if df is not None and not df.empty:
        df = df.sort_values('trade_date', ascending=True)
        latest = df.iloc[-1]
        
        # south_money: 南向资金, 单位: 百万元 RMB
        south_money = float(latest.get('south_money', 0))
        south_billion = south_money / 100  # 百万 → 亿
        trade_date = latest.get('trade_date', '?')
        
        # 计算近5日累计
        recent5 = df.tail(5)
        sum5 = recent5['south_money'].sum() / 100  # 亿
        
        results['tushare_southbound'] = {
            'status': 'PASS',
            'latest_date': trade_date,
            'latest_south_money_million': south_money,
            'latest_south_money_billion_rmb': round(south_billion, 2),
            'recent_5d_sum_billion': round(sum5, 2),
            'rows': len(df),
            'columns': list(df.columns),
        }
        print(f"  ✅ PASS | 最新: {trade_date} | 南向净买: {south_billion:.1f}亿RMB")
        print(f"         | 近5日累计: {sum5:.1f}亿RMB | 共{len(df)}行")
        print(f"         | 字段: {list(df.columns)}")
    else:
        results['tushare_southbound'] = {'status': 'FAIL', 'reason': 'DataFrame为空'}
        print(f"  ❌ FAIL | DataFrame为空")
except Exception as e:
    results['tushare_southbound'] = {'status': 'FAIL', 'reason': str(e)}
    print(f"  ❌ FAIL | {e}")


# ===== 测试 2: yfinance ^HSAHP (AH溢价指数) =====
print("\n[2/4] 🇭🇰 yfinance AH溢价指数 (^HSAHP) ...")

try:
    import yfinance as yf
    
    df_ah = yf.download("^HSAHP", period="3mo", progress=False)
    
    if df_ah is not None and not df_ah.empty:
        close_col = df_ah["Close"]
        if hasattr(close_col, "columns"):
            close_col = close_col.iloc[:, 0]
        
        latest_val = float(close_col.dropna().iloc[-1])
        latest_date = df_ah.index[-1].strftime("%Y-%m-%d")
        rows = len(df_ah)
        
        # 数据质量: AH溢价合理范围 100-200
        reasonable = 100 < latest_val < 200
        
        results['yfinance_hsahp'] = {
            'status': 'PASS' if reasonable else 'WARN',
            'latest_date': latest_date,
            'latest_value': round(latest_val, 2),
            'rows': rows,
            'data_range': f"{df_ah.index[0].strftime('%Y-%m-%d')} ~ {latest_date}",
            'reasonable': reasonable,
        }
        
        status = "✅ PASS" if reasonable else "⚠️ WARN (值不在合理范围)"
        print(f"  {status} | 最新: {latest_date} | AH溢价: {latest_val:.2f}")
        print(f"         | {rows}行 | 范围: {df_ah.index[0].strftime('%Y-%m-%d')} ~ {latest_date}")
        
        # 展示近5日数据
        print(f"         | 近5日:")
        for i in range(-min(5, len(df_ah)), 0):
            d = df_ah.index[i].strftime("%Y-%m-%d")
            v = float(close_col.iloc[i])
            print(f"         |   {d}: {v:.2f}")
    else:
        results['yfinance_hsahp'] = {'status': 'FAIL', 'reason': 'DataFrame为空'}
        print(f"  ❌ FAIL | DataFrame为空 (代码可能不存在)")
except Exception as e:
    results['yfinance_hsahp'] = {'status': 'FAIL', 'reason': str(e)}
    print(f"  ❌ FAIL | {e}")

# 如果 ^HSAHP 失败, 尝试备用代码
if results.get('yfinance_hsahp', {}).get('status') == 'FAIL':
    print("\n[2b/4] 尝试备用代码: HSAHP.HK / HSAHPI.HK ...")
    for alt_sym in ["HSAHP.HK", "HSAHPI.HK", "2800.HK"]:
        try:
            df_alt = yf.download(alt_sym, period="1mo", progress=False)
            if df_alt is not None and not df_alt.empty:
                print(f"  ℹ️ {alt_sym} 有数据: {len(df_alt)}行")
        except:
            pass


# ===== 测试 3: JPX 信用取引残高 CSV 探测 =====
print("\n[3/4] 🇯🇵 JPX 信用取引残高 CSV URL探测 ...")

try:
    import urllib.request
    
    # JPX 信用取引统计页面
    jpx_margin_url = "https://www.jpx.co.jp/markets/statistics-equities/margin/index.html"
    req = urllib.request.Request(jpx_margin_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode('utf-8', errors='replace')
    
    # 寻找 CSV/Excel 下载链接
    import re
    csv_links = re.findall(r'href="([^"]*\.(?:csv|xls|xlsx))"', html, re.IGNORECASE)
    
    results['jpx_margin'] = {
        'status': 'PASS' if csv_links else 'WARN',
        'page_accessible': True,
        'page_size_kb': round(len(html) / 1024, 1),
        'csv_links_found': len(csv_links),
        'sample_links': csv_links[:5],
    }
    
    if csv_links:
        print(f"  ✅ PASS | 页面可访问 ({len(html)/1024:.0f}KB) | 发现 {len(csv_links)} 个下载链接")
        for link in csv_links[:3]:
            print(f"         | → {link}")
    else:
        # 尝试找更多模式的链接
        all_links = re.findall(r'href="([^"]*(?:margin|shinyo)[^"]*)"', html, re.IGNORECASE)
        print(f"  ⚠️ WARN | 页面可访问但未找到CSV链接 | 相关链接: {len(all_links)}")
        for link in all_links[:3]:
            print(f"         | → {link}")
        results['jpx_margin']['related_links'] = all_links[:5]

except Exception as e:
    results['jpx_margin'] = {'status': 'FAIL', 'reason': str(e)}
    print(f"  ❌ FAIL | {e}")


# ===== 测试 4: JPX 投資部門別売買状況 (外資) =====
print("\n[4/4] 🇯🇵 JPX 投資部門別売買状況 (外資流向) ...")

try:
    jpx_investor_url = "https://www.jpx.co.jp/markets/statistics-equities/investor-type/index.html"
    req = urllib.request.Request(jpx_investor_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode('utf-8', errors='replace')
    
    csv_links = re.findall(r'href="([^"]*\.(?:csv|xls|xlsx))"', html, re.IGNORECASE)
    
    results['jpx_investor'] = {
        'status': 'PASS' if csv_links else 'WARN',
        'page_accessible': True,
        'page_size_kb': round(len(html) / 1024, 1),
        'csv_links_found': len(csv_links),
        'sample_links': csv_links[:5],
    }
    
    if csv_links:
        print(f"  ✅ PASS | 页面可访问 ({len(html)/1024:.0f}KB) | 发现 {len(csv_links)} 个下载链接")
        for link in csv_links[:3]:
            print(f"         | → {link}")
    else:
        all_links = re.findall(r'href="([^"]*(?:investor|tobun)[^"]*)"', html, re.IGNORECASE)
        print(f"  ⚠️ WARN | 页面可访问但未找到CSV链接 | 相关链接: {len(all_links)}")
        results['jpx_investor']['related_links'] = all_links[:5]

except Exception as e:
    results['jpx_investor'] = {'status': 'FAIL', 'reason': str(e)}
    print(f"  ❌ FAIL | {e}")


# ===== 汇总 =====
print(f"\n{'=' * 60}")
print(f"  测试汇总")
print(f"{'=' * 60}")

pass_count = sum(1 for r in results.values() if r.get('status') == 'PASS')
total = len(results)

for name, r in results.items():
    icon = '✅' if r['status'] == 'PASS' else ('⚠️' if r['status'] == 'WARN' else '❌')
    print(f"  {icon} {name}: {r['status']}")

print(f"\n  通过: {pass_count}/{total}")
print(f"{'=' * 60}")

# 保存报告
from pathlib import Path
report_path = Path(__file__).parent / "auto_data_source_test_report.json"
with open(report_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print(f"\n报告已保存: {report_path}")
