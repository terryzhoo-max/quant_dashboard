"""JPX XLS 内部结构调査"""
import sys, os, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import urllib.request
import xlrd

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# ===== 信用取引 =====
print("===== 信用取引 XLS 全列走査 =====\n")
url1 = "https://www.jpx.co.jp/markets/statistics-equities/margin/index.html"
req = urllib.request.Request(url1, headers={"User-Agent": UA})
with urllib.request.urlopen(req, timeout=15) as resp:
    html = resp.read().decode("utf-8", errors="replace")
links = re.findall(r'href="([^"]*\.xls[x]?)"', html, re.IGNORECASE)
xls_url = "https://www.jpx.co.jp" + links[0]
print(f"URL: {xls_url}")

req2 = urllib.request.Request(xls_url, headers={"User-Agent": UA})
with urllib.request.urlopen(req2, timeout=20) as resp2:
    xls_bytes = resp2.read()

wb = xlrd.open_workbook(file_contents=xls_bytes)
sheet = wb.sheet_by_index(0)
print(f"Sheet: {sheet.name} | {sheet.nrows}行 x {sheet.ncols}列\n")

# 打印前15行的全部内容
print("--- 前15行 ---")
for r in range(min(15, sheet.nrows)):
    row_vals = []
    for c in range(sheet.ncols):
        v = sheet.cell_value(r, c)
        if v == '' or v is None:
            continue
        row_vals.append(f"[c{c}]{str(v)[:25]}")
    if row_vals:
        print(f"  Row{r}: {' | '.join(row_vals)}")

# 统计每列的数据特征
print("\n--- 各列统计 (数据行 Row7+) ---")
for c in range(sheet.ncols):
    col_sum = 0
    count = 0
    for r in range(7, sheet.nrows):
        v = sheet.cell_value(r, c)
        if isinstance(v, (int, float)) and v > 0:
            col_sum += v
            count += 1
    if count > 0:
        print(f"  Col{c}: {count}行 sum={col_sum:.0f} avg={col_sum/count:.0f}")


# ===== 外資統計 =====
print("\n\n===== 外資統計 XLS 全列走査 =====\n")
url2 = "https://www.jpx.co.jp/markets/statistics-equities/investor-type/index.html"
req = urllib.request.Request(url2, headers={"User-Agent": UA})
with urllib.request.urlopen(req, timeout=15) as resp:
    html2 = resp.read().decode("utf-8", errors="replace")
links2 = re.findall(r'href="([^"]*\.xls[x]?)"', html2, re.IGNORECASE)
val_links = [l for l in links2 if "val" in l.lower()]
xls_url2 = "https://www.jpx.co.jp" + val_links[0]
print(f"URL: {xls_url2}")

req3 = urllib.request.Request(xls_url2, headers={"User-Agent": UA})
with urllib.request.urlopen(req3, timeout=20) as resp3:
    xls_bytes2 = resp3.read()

wb2 = xlrd.open_workbook(file_contents=xls_bytes2)
sheet2 = wb2.sheet_by_index(0)
print(f"Sheet: {sheet2.name} | {sheet2.nrows}行 x {sheet2.ncols}列\n")

# 打印全部行
print("--- 全行内容 ---")
for r in range(sheet2.nrows):
    row_vals = []
    for c in range(sheet2.ncols):
        v = sheet2.cell_value(r, c)
        if v == '' or v is None:
            continue
        s = str(v)[:20]
        row_vals.append(f"[c{c}]{s}")
    if row_vals:
        print(f"  Row{r}: {' | '.join(row_vals)}")
