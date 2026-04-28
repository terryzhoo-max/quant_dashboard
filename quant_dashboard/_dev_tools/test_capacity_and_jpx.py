"""测试 Tushare 南向资金容量 + JPX XLS 依赖"""
import sys, os, re, io
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import tushare as ts
from datetime import datetime, timedelta

pro = ts.pro_api()

print("=" * 60)
print("  Part 1: Tushare moneyflow_hsgt 容量测试")
print("=" * 60)

today = datetime.now().strftime('%Y%m%d')
start_1y = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')

for label, lim in [("无limit", None), ("limit=300", 300), ("limit=500", 500)]:
    try:
        if lim:
            df = pro.moneyflow_hsgt(start_date=start_1y, end_date=today, limit=lim)
        else:
            df = pro.moneyflow_hsgt(start_date=start_1y, end_date=today)
        rng = f"{df['trade_date'].min()} ~ {df['trade_date'].max()}" if len(df) > 0 else "N/A"
        print(f"  [{label}] {len(df)} 行 | {rng}")
    except Exception as e:
        print(f"  [{label}] 失败: {e}")

# 计算12M累计
print("\n--- 12M 累计计算 ---")
try:
    df_full = pro.moneyflow_hsgt(start_date=start_1y, end_date=today, limit=500)
    df_full = df_full.copy()
    df_full['south_money'] = pd.to_numeric(df_full['south_money'], errors='coerce')
    df_full = df_full.sort_values('trade_date').dropna(subset=['south_money'])
    
    total_12m = df_full['south_money'].sum() / 100
    week_sum = df_full.tail(5)['south_money'].sum() / 100
    month_sum = df_full.tail(20)['south_money'].sum() / 100
    
    print(f"  交易日数: {len(df_full)}")
    print(f"  12M 累计南向: {total_12m:.1f} 亿RMB")
    print(f"  近5日合计(周): {week_sum:.1f} 亿")
    print(f"  近20日合计(月): {month_sum:.1f} 亿")
except Exception as e:
    print(f"  失败: {e}")


print("\n" + "=" * 60)
print("  Part 2: JPX XLS 解析依赖检测")
print("=" * 60)

# openpyxl
try:
    import openpyxl
    print(f"  openpyxl: v{openpyxl.__version__} INSTALLED")
except ImportError:
    print("  openpyxl: NOT INSTALLED")

# xlrd
try:
    import xlrd
    print(f"  xlrd: v{xlrd.__version__} INSTALLED")
except ImportError:
    print("  xlrd: NOT INSTALLED")

print(f"  pandas: v{pd.__version__}")


print("\n" + "=" * 60)
print("  Part 3: JPX 信用取引 XLS 下载+解析")
print("=" * 60)

import urllib.request

try:
    url = "https://www.jpx.co.jp/markets/statistics-equities/margin/index.html"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    
    xls_links = re.findall(r'href="([^"]*\.xls[x]?)"', html, re.IGNORECASE)
    if not xls_links:
        print("  未找到 XLS 链接")
    else:
        link = xls_links[0]
        full_url = ("https://www.jpx.co.jp" + link) if link.startswith("/") else link
        print(f"  链接: {full_url}")
        
        req2 = urllib.request.Request(full_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=20) as resp2:
            xls_bytes = resp2.read()
        print(f"  下载: {len(xls_bytes)} bytes ({len(xls_bytes)/1024:.1f} KB)")
        
        ext = ".xlsx" if link.endswith(".xlsx") else ".xls"
        print(f"  格式: {ext}")
        
        parsed = False
        if ext == ".xls":
            try:
                import xlrd
                wb = xlrd.open_workbook(file_contents=xls_bytes)
                sheet = wb.sheet_by_index(0)
                print(f"  xlrd解析: {sheet.nrows}行 x {sheet.ncols}列 | Sheet: {wb.sheet_names()}")
                for i in range(min(8, sheet.nrows)):
                    row = [str(sheet.cell_value(i, j))[:18] for j in range(min(8, sheet.ncols))]
                    print(f"    Row{i}: {row}")
                parsed = True
            except ImportError:
                print("  xlrd 未安装, 尝试 pandas...")
        
        if not parsed:
            tmp_path = os.path.join("data_lake", "_tmp_jpx.xls")
            with open(tmp_path, "wb") as f:
                f.write(xls_bytes)
            try:
                df_jpx = pd.read_excel(tmp_path)
                print(f"  pandas解析: {len(df_jpx)}行 x {len(df_jpx.columns)}列")
                print(f"  列名: {list(df_jpx.columns)[:6]}")
                print(df_jpx.head(3).to_string())
            except Exception as e:
                print(f"  pandas解析失败: {e}")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

except Exception as e:
    print(f"  失败: {e}")


print("\n" + "=" * 60)
print("  Part 4: JPX 外資統計 XLS 下载+解析")
print("=" * 60)

try:
    url2 = "https://www.jpx.co.jp/markets/statistics-equities/investor-type/index.html"
    req = urllib.request.Request(url2, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        html2 = resp.read().decode("utf-8", errors="replace")
    
    xls_links2 = re.findall(r'href="([^"]*\.xls[x]?)"', html2, re.IGNORECASE)
    val_links = [l for l in xls_links2 if "val" in l.lower()]
    
    if val_links:
        link2 = val_links[0]
        full_url2 = ("https://www.jpx.co.jp" + link2) if link2.startswith("/") else link2
        print(f"  链接: {full_url2}")
        
        req3 = urllib.request.Request(full_url2, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req3, timeout=20) as resp3:
            xls_bytes2 = resp3.read()
        print(f"  下载: {len(xls_bytes2)} bytes ({len(xls_bytes2)/1024:.1f} KB)")
        
        ext2 = ".xlsx" if link2.endswith(".xlsx") else ".xls"
        parsed2 = False
        if ext2 == ".xls":
            try:
                import xlrd
                wb2 = xlrd.open_workbook(file_contents=xls_bytes2)
                sheet2 = wb2.sheet_by_index(0)
                print(f"  xlrd解析: {sheet2.nrows}行 x {sheet2.ncols}列 | Sheet: {wb2.sheet_names()}")
                for i in range(min(12, sheet2.nrows)):
                    row = [str(sheet2.cell_value(i, j))[:15] for j in range(min(10, sheet2.ncols))]
                    print(f"    Row{i}: {row}")
                parsed2 = True
            except ImportError:
                pass
        
        if not parsed2:
            tmp2 = os.path.join("data_lake", "_tmp_jpx2.xls")
            with open(tmp2, "wb") as f:
                f.write(xls_bytes2)
            try:
                df_jpx2 = pd.read_excel(tmp2)
                print(f"  pandas解析: {len(df_jpx2)}行")
            except Exception as e:
                print(f"  pandas解析失败: {e}")
            finally:
                if os.path.exists(tmp2):
                    os.remove(tmp2)
    else:
        print("  未找到 val 链接")
except Exception as e:
    print(f"  失败: {e}")

print("\n" + "=" * 60)
print("  测试完成")
print("=" * 60)
