"""
AlphaCore · JPX 数据自动抓取框架 V1.1
======================================
自动下载并解析 JPX (日本取引所) 公开统计数据:
  1. 信用取引残高 (個別銘柄信用取引残高)
  2. 投資部門別売買状況 (外国人投資家フロー)

数据源:
  - 信用取引: https://www.jpx.co.jp/markets/statistics-equities/margin/
  - 外資統計: https://www.jpx.co.jp/markets/statistics-equities/investor-type/

依赖: xlrd (解析 .xls), urllib (下载)
更新频率: 週次 (毎週木曜日更新)

V1.1 更新: 基于实测 XLS 结构修正解析逻辑
  - 信用取引: 数值为字符串格式(含逗号), 需要 parse
  - 外資統計: 固定结构 Row29=海外投資家売り, Row30=買い, col6/col10=差引き
"""

import os
import re
import json
import time
import logging
import urllib.request
from datetime import datetime
from typing import Dict, Optional

CACHE_DIR = "data_lake"
os.makedirs(CACHE_DIR, exist_ok=True)
_logger = logging.getLogger("alphacore.data.jpx")

_JPX_MARGIN_CACHE = os.path.join(CACHE_DIR, "jpx_margin_auto.json")
_JPX_FOREIGN_CACHE = os.path.join(CACHE_DIR, "jpx_foreign_auto.json")

# TTL: 3日 (週次データだが、発表タイミングにバッファ)
_JPX_TTL = 3 * 86400

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _log(msg: str, level: str = "INFO"):
    ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts_str}] [{level}] [JPX] {msg}")


def atomic_write_json(data, filepath):
    """原子性写入 JSON (防中断损坏)"""
    tmp = filepath + ".tmp"
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, filepath)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise e


def _download_url(url: str, timeout: int = 20) -> bytes:
    """下载 URL 内容, 返回 bytes"""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _find_xls_links(page_url: str) -> list:
    """从 JPX 页面 HTML 中提取 XLS/XLSX 下载链接"""
    html = _download_url(page_url).decode("utf-8", errors="replace")
    links = re.findall(r'href="([^"]*\.xls[x]?)"', html, re.IGNORECASE)
    return [("https://www.jpx.co.jp" + l if l.startswith("/") else l) for l in links]


class _SheetAdapter:
    """xlrd 风格的最小接口 (nrows / ncols / cell_value), 统一 .xls 与 .xlsx"""

    def __init__(self, rows):
        self._rows = rows
        self.nrows = len(rows)
        self.ncols = max((len(r) for r in rows), default=0)

    def cell_value(self, r, c):
        row = self._rows[r]
        v = row[c] if c < len(row) else ""
        return "" if v is None else v


def _open_first_sheet(file_bytes: bytes, url: str):
    """2026-10-23: JPX 自 2026-09-29 起改发 .xlsx, xlrd 2.x 不支持 xlsx
    (报错 'Excel xlsx file; not supported'). 这里按扩展名/文件头自动选择解析器."""
    is_xlsx = url.lower().endswith(".xlsx") or file_bytes[:2] == b"PK"
    if is_xlsx:
        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return _SheetAdapter(rows), True
    import xlrd
    wb = xlrd.open_workbook(file_contents=file_bytes)
    return wb.sheet_by_index(0), False


def _dump_raw(file_bytes: bytes, url: str) -> None:
    """解析失败时保存原始文件, 便于按新版版式校准解析规则"""
    try:
        d = os.path.join(CACHE_DIR, "jpx_raw")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, os.path.basename(url)), "wb") as f:
            f.write(file_bytes)
    except Exception:
        pass


def _parse_foreign_v2(sheet) -> Optional[Dict]:
    """2026-09-29 起新版 stock_1_w_*.xlsx (宽表) 解析.

    实测版式 (stock_1_w_20261013_20261016.xlsx):
      表头第3行: col19「海外投資家 Foreigners」(合并单元格, 下分 法人 / 個人 两组)
      表头第6行: 每组 4 列 = 売 / 買 / 差引 Balance / 合計
      数据行: col1 市場 (東証プライム ...), col2「株数 Shares」/「金額 Value」两行一组
      单位: 千円
    海外投資家 净买入 = 海外法人差引 + 海外個人差引 (东证 Prime, 金額行)
    """
    hdr_r = fc = None
    for r in range(min(10, sheet.nrows)):
        for c in range(sheet.ncols):
            if "海外投資家" in str(sheet.cell_value(r, c)):
                hdr_r, fc = r, c
                break
        if fc is not None:
            break
    if fc is None:
        return None
    # 该大类的右边界 = 同一表头行中下一个非空单元格
    end = sheet.ncols
    for c in range(fc + 1, sheet.ncols):
        if str(sheet.cell_value(hdr_r, c)).strip():
            end = c
            break
    bal_row = None
    for r in range(hdr_r, min(hdr_r + 8, sheet.nrows)):
        if any("差引" in str(sheet.cell_value(r, c)) for c in range(fc, end)):
            bal_row = r
            break
    if bal_row is None:
        return None
    bal_cols = [c for c in range(fc, end) if "差引" in str(sheet.cell_value(bal_row, c))]
    # 二市場 (東京+名古屋) 的「金額」行; 与历史种子同口径. 找不到时退回 东证 Prime
    def _value_row(keys):
        for r in range(bal_row + 1, sheet.nrows):
            if any(k in str(sheet.cell_value(r, 1)) for k in keys):
                for rr in range(r, min(r + 3, sheet.nrows)):
                    if "金額" in str(sheet.cell_value(rr, 2)) or "Value" in str(sheet.cell_value(rr, 2)):
                        return rr
                return None
        return None
    val_row = _value_row(("二市場", "Tokyo & Nagoya", "Tokyo&Nagoya"))
    scope = "二市場"
    if val_row is None:
        val_row = _value_row(("プライム", "Prime"))
        scope = "東証プライム"
    if val_row is None or not bal_cols:
        return None
    total = sum(_parse_number(sheet.cell_value(val_row, c)) for c in bal_cols)
    period = None
    for r in range(bal_row + 1, min(bal_row + 4, sheet.nrows)):
        m = re.match(r"^(\d{4})(\d{2})(\d)$", str(sheet.cell_value(r, 0)).strip())
        if m:
            period = f"{m.group(1)}-{m.group(2)}-W{m.group(3)}"
            break
    return {"raw": total, "row": val_row, "cols": bal_cols, "period": period, "scope": scope}


def _find_header_col(sheet, keywords, max_rows=30):
    """在表头区域按关键字找列, 返回 (row, col) 或 (None, None)"""
    for r in range(min(max_rows, sheet.nrows)):
        for c in range(sheet.ncols):
            v = str(sheet.cell_value(r, c))
            if any(k in v for k in keywords):
                return r, c
    return None, None


def _parse_number(val) -> float:
    """解析 XLS 单元格值为数字 (支持字符串含逗号格式)"""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = val.replace(',', '').replace(' ', '').strip()
        if cleaned and cleaned not in ('-', ''):
            try:
                return float(cleaned)
            except ValueError:
                pass
    return 0.0


# ═══════════════════════════════════════════════════
#  信用取引残高 (Margin Trading Balance)
# ═══════════════════════════════════════════════════

_NUMLIKE = re.compile(r"^[▲△\-−]?[\d,]+(\.\d+)?$")
_MARKET_LABELS = ("二市場", "Tokyo&Nagoya", "Tokyo & Nagoya")


def _num_cells(sheet, r, start_col=0):
    """一行中的数值单元格 (按列序). 「▲84」→ -84, 空/「-」跳过."""
    vals = []
    for c in range(start_col, sheet.ncols):
        v = sheet.cell_value(r, c)
        if isinstance(v, bool) or v in (None, ""):
            continue
        if isinstance(v, (int, float)):
            vals.append(float(v))
            continue
        t = str(v).strip().replace(" ", "")
        if _NUMLIKE.match(t):
            neg = t[0] in "▲△-−"
            x = float(t.lstrip("▲△-−").replace(",", ""))
            vals.append(-x if neg else x)
    return vals


def parse_margin_current(sheet) -> Optional[Dict]:
    """解析 JPX「信用取引現在高」(全市场周度汇总) YYYYMMDD_mtcurrent.xlsx.

    实测版式 (20261016_mtcurrent.xlsx, 单位: 千株 / 百万円):
      row5 : col4「二市場 Tokyo&Nagoya」, col8「東京 Tokyo」      ← 市场是"列"分组
      row6 : col4 売残高 / col5 前週比 / col6 買残高 / col7 前週比 (二市場)
      区块: 每项两行「株数Shs.」「金額Val.」, 顺序为
            制度信用(自己) / 制度信用(委託) / 一般信用(委託) / 信用取引残高合計 / 社内対当 / 貸借取引 / 自己貸株・自己融資
    合計区块由恒等式自检定位: 合計 = 前三个区块之和 (株数、金額 两项误差 <0.5%),
    不依赖行号和标签文字.
    """
    # 1) 定位「二市場」列组与 売/買 列
    hdr_r = c0 = None
    for r in range(min(15, sheet.nrows)):
        for c in range(sheet.ncols):
            if any(k in str(sheet.cell_value(r, c)) for k in _MARKET_LABELS):
                hdr_r, c0 = r, c
                break
        if c0 is not None:
            break
    if c0 is None:
        return None
    sell_c = buy_c = None
    for r in range(hdr_r, min(hdr_r + 3, sheet.nrows)):
        for c in range(c0, min(c0 + 4, sheet.ncols)):
            t = str(sheet.cell_value(r, c))
            if sell_c is None and ("売残" in t or "Sales" in t):
                sell_c = c
            if buy_c is None and ("買残" in t or "Purchases" in t):
                buy_c = c
    if sell_c is None or buy_c is None:
        return None

    def _n(r, c):
        v = sheet.cell_value(r, c)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        t = str(v).strip().replace(" ", "")
        if _NUMLIKE.match(t):
            x = float(t.lstrip("▲△-−").replace(",", ""))
            return -x if t[0] in "▲△-−" else x
        return None

    # 2) 收集区块 (株数行 + 紧随的 金額行)
    blocks = []
    r = hdr_r + 1
    while r < sheet.nrows:
        lab = "".join(str(sheet.cell_value(r, c)) for c in range(min(c0, sheet.ncols)))
        if ("株数" in lab or "Shs" in lab) and _n(r, buy_c) is not None:
            val_r = None
            if r + 1 < sheet.nrows:
                lab2 = "".join(str(sheet.cell_value(r + 1, c)) for c in range(min(c0, sheet.ncols)))
                if ("金額" in lab2 or "Val" in lab2) and _n(r + 1, buy_c) is not None:
                    val_r = r + 1
            blocks.append((r, val_r))
            r = (val_r or r) + 1
            continue
        r += 1

    # 3) 恒等式自检定位合計
    for i in range(3, len(blocks)):
        sr, vr = blocks[i]
        prev = blocks[i - 3:i]
        if vr is None or any(p[1] is None for p in prev):
            continue
        ok = True
        for rows_idx in (0, 1):  # 0=株数, 1=金額
            tot = _n(blocks[i][rows_idx], buy_c)
            s = sum(_n(p[rows_idx], buy_c) for p in prev)
            if not tot or abs(s - tot) / abs(tot) > 0.005:
                ok = False
                break
        if ok:
            report_date = None
            for rr in range(min(4, sheet.nrows)):
                for cc in range(min(4, sheet.ncols)):
                    v = sheet.cell_value(rr, cc)
                    if hasattr(v, "strftime"):
                        report_date = v.strftime("%Y%m%d")
                        break
                if report_date:
                    break
            return {
                "row": vr,
                "buy_shares_k": _n(sr, buy_c), "buy_value_mn": _n(vr, buy_c),
                "sell_shares_k": _n(sr, sell_c), "sell_value_mn": _n(vr, sell_c),
                "buy_value_wow_mn": _n(vr, buy_c + 1) or 0.0,
                "report_date": report_date,
            }
    return None


def fetch_jpx_margin() -> Optional[Dict]:
    """
    JPX「信用取引現在高」(毎週第2営業日 16:00 公表) → 二市場 信用取引残高合計 買残金額

    2026-10-23: 数据源由「日々公表銘柄」(仅数百只个股, 以 株数×推定均价2000円 推算,
    结果长期被下限钳制在 2.0兆円) 更换为全市场周度汇总. 2026-10-16 实测 = 6.66兆円.
    页面: https://www.jpx.co.jp/markets/statistics-equities/margin/04.html
    新版: YYYYMMDD_mtcurrent.xlsx (2026-09-25 起); 旧版: mtseisanYYYYMMDD00.xls
    """
    if os.path.exists(_JPX_MARGIN_CACHE):
        try:
            with open(_JPX_MARGIN_CACHE, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            age = time.time() - cached.get("fetched_ts", 0)
            if cached.get("source") == "jpx_weekly_total" and age < _JPX_TTL:
                _log(f"JPX Margin キャッシュHit ({age/3600:.0f}h ago, {cached.get('report_date')})")
                return cached
        except Exception:
            pass

    try:
        page_url = "https://www.jpx.co.jp/markets/statistics-equities/margin/04.html"
        links = _find_xls_links(page_url)

        def _date_of(u):
            m = re.search(r'(\d{8})_mtcurrent\.xlsx$', u) or re.search(r'mtseisan(\d{8})\d*\.xls$', u)
            return m.group(1) if m else ""

        cands = sorted([l for l in links if _date_of(l)], key=_date_of, reverse=True)
        if not cands:
            _log("JPX Margin: 信用取引現在高ファイルが見つかりません", "WARN")
            return _load_margin_cache()

        xls_url = cands[0]
        report_date = _date_of(xls_url)
        _log(f"JPX Margin ダウンロード: {xls_url}")
        xls_bytes = _download_url(xls_url)
        sheet, is_xlsx = _open_first_sheet(xls_bytes, xls_url)

        parsed = parse_margin_current(sheet)
        if parsed and parsed.get("report_date"):
            report_date = parsed["report_date"]  # 表内「申込現在」日期优先于文件名
        if parsed is None:
            _dump_raw(xls_bytes, xls_url)
            _log("JPX Margin: 合計行の自己検証に失敗 (版式変更?), 原文件已存 data_lake/jpx_raw/", "ERROR")
            return _load_margin_cache()

        margin_trillion = round(parsed["buy_value_mn"] / 1e6, 3)   # 百万円 → 兆円
        if not (1.0 <= margin_trillion <= 20.0):
            _dump_raw(xls_bytes, xls_url)
            _log(f"JPX Margin: 買残金額 {margin_trillion}兆円 超出合理区间 [1, 20], 拒绝", "ERROR")
            return _load_margin_cache()

        credit_ratio = round(parsed["buy_shares_k"] / parsed["sell_shares_k"], 2) if parsed["sell_shares_k"] > 0 else 0
        result = {
            "margin_buying_trillion_jpy": margin_trillion,
            "margin_selling_trillion_jpy": round(parsed["sell_value_mn"] / 1e6, 3),
            "buy_value_wow_trillion_jpy": round(parsed["buy_value_wow_mn"] / 1e6, 3),
            "total_buy_shares_k": parsed["buy_shares_k"],
            "total_sell_shares_k": parsed["sell_shares_k"],
            "credit_ratio": credit_ratio,
            "scope": "二市場 信用取引残高合計 (制度+一般)",
            "report_date": f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:]}",
            "source": "jpx_weekly_total",
            "confidence": "high",
            "xls_url": xls_url,
            "detected_row": parsed["row"],
            "fetched_at": datetime.now().isoformat(),
            "fetched_ts": time.time(),
        }
        atomic_write_json(result, _JPX_MARGIN_CACHE)
        _log(f"JPX Margin 解析完了: 買残 {margin_trillion}兆円 (前週比 {result['buy_value_wow_trillion_jpy']:+}兆) "
             f"貸借倍率={credit_ratio} [{result['report_date']}] (全市場週次合計, 恒等式検証済)")
        return result

    except ImportError as e:
        _log(f"Excel 解析库未安装 ({e}); 请 pip install xlrd openpyxl", "ERROR")
        return _load_margin_cache()
    except Exception as e:
        _log(f"JPX Margin 取得失敗: {e}", "ERROR")
        _logger.debug("Traceback", exc_info=True)
        return _load_margin_cache()


def _load_margin_cache() -> Optional[Dict]:
    """磁盤キャッシュ (TTL無視). 旧版「日々公表銘柄」推算値 (2.0兆円钳制) は不採用."""
    if os.path.exists(_JPX_MARGIN_CACHE):
        try:
            with open(_JPX_MARGIN_CACHE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get("source") != "jpx_weekly_total":
                _log("JPX Margin: 旧版推算缓存(日々公表銘柄, 不可信)已忽略", "WARN")
                return None
            age_d = (time.time() - data.get("fetched_ts", 0)) / 86400
            data["stale"] = age_d > 10
            data["cache_age_days"] = round(age_d, 1)
            _log(f"JPX Margin: 磁盤キャッシュ使用 (取得から{age_d:.0f}日, 報告日={data.get('report_date')})", "WARN")
            return data
        except Exception:
            pass
    return None


# ═══════════════════════════════════════════════════
#  投資部門別売買状況 (Foreign Investor Flow)
# ═══════════════════════════════════════════════════

def _fetch_jpx_foreign_flow_impl() -> Optional[Dict]:
    """
    自動下載 JPX 投資部門別売買状況 XLS → 解析外国人フロー

    実測 XLS 結構 (2026-04-03, TSE Prime):
      Row10: ヘッダー [col3]04/06～04/10  [col7]04/13～04/17
      Row11: ヘッダー [col3]金額 Value [col5]比率 [col6]差引き Balance [col7]金額... [col10]差引き
      Row29: [col0]海外投資家 [col1]売り → col4=売り額, col6=差引き(W1)
      Row30: [col0]Foreigners [col1]買い → col4=買い額, col6=差引き(W1), col10=差引き(W2)

    差引き(Balance) = 買い - 売り = 週次純買越
    単位: 千円
    col6 = 前週 Balance, col10 = 最新週 Balance
    ※ Balance は「買い」行にのみ記載される
    """

    if os.path.exists(_JPX_FOREIGN_CACHE):
        try:
            with open(_JPX_FOREIGN_CACHE, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            age = time.time() - cached.get("fetched_ts", 0)
            if age < _JPX_TTL:
                _log(f"JPX Foreign キャッシュHit ({age/3600:.0f}h ago)")
                return cached
        except Exception:
            pass

    try:
        page_url = "https://www.jpx.co.jp/markets/statistics-equities/investor-type/index.html"
        links = _find_xls_links(page_url)
        # 2026-09-29 起文件名改为 stock_1_w_YYYYMMDD_YYYYMMDD.xlsx (旧: stock_val_*.xls)
        val_links = [l for l in links
                     if ("stock_val" in l.lower() or "stock_1_w_" in l.lower()) and "yyyy" not in l.lower()]
        if not val_links:
            _log("JPX Foreign: stock_val XLSリンクが見つかりません", "WARN")
            return _load_foreign_cache()

        xls_url = val_links[0]
        _log(f"JPX Foreign ダウンロード: {xls_url}")
        xls_bytes = _download_url(xls_url)
        sheet, _ = _open_first_sheet(xls_bytes, xls_url)  # TSE Prime
        _v2 = _parse_foreign_v2(sheet)
        if _v2 is not None:
            net = round(_v2["raw"] / 1e5, 1)  # 千円 → 億円
            result = {
                "net_buy_billion_jpy": net,
                "prev_week_billion_jpy": None,
                "raw_value_thousand_jpy": _v2["raw"],
                "report_period": _v2["period"] or "unknown",
                "source": "jpx_auto_v2",
                "xls_url": xls_url,
                "detected_row": _v2["row"],
                "detected_col": _v2["cols"],
                "fetched_at": datetime.now().isoformat(),
                "fetched_ts": time.time(),
            }
            atomic_write_json(result, _JPX_FOREIGN_CACHE)
            _log(f"JPX Foreign 解析完了(新版): net={net}億円 (海外法人+個人, {_v2['scope']}, Row{_v2['row']} Col{_v2['cols']}) [{_v2['period']}]")
            return result
        if report_period_from_name := re.search(r'stock_1_w_(\d{8})_(\d{8})', xls_url):
            _fname_period = f"{report_period_from_name.group(1)}~{report_period_from_name.group(2)}"
        else:
            _fname_period = None

        # 週次期間を抽出
        report_period = None
        for r in range(min(5, sheet.nrows)):
            cell = str(sheet.cell_value(r, 0))
            m = re.search(r'(\d{4})年(\d{1,2})月第(\d)週', cell)
            if m:
                report_period = f"{m.group(1)}-{int(m.group(2)):02d}-W{m.group(3)}"
                break

        # 差引き(Balance)列を探す: Row11 ヘッダーから
        balance_cols = []
        for r in range(0, min(30, sheet.nrows)):
            for c in range(sheet.ncols):
                val = str(sheet.cell_value(r, c))
                if ("差引" in val or "Balance" in val) and c not in balance_cols:
                    balance_cols.append(c)

        _log(f"JPX Foreign: Balance列検出 = {balance_cols}")

        # 海外投資家の「買い」行を探す (Balance は買い行に記載)
        foreign_buy_row = -1
        for r in range(sheet.nrows):
            row_text = ""
            for c in range(min(6, sheet.ncols)):
                row_text += str(sheet.cell_value(r, c))
            if ("Foreigners" in row_text or "外国人" in row_text or "海外投資家" in row_text) and ("買" in row_text or "Purchase" in row_text):
                foreign_buy_row = r
                break

        if foreign_buy_row < 0:
            # フォールバック: 「海外投資家」行の次の行を買い行と推定
            for r in range(sheet.nrows):
                for c in range(min(6, sheet.ncols)):
                    val = str(sheet.cell_value(r, c))
                    if "海外投資家" in val or "外国人" in val:
                        foreign_buy_row = r + 1  # 次の行が買い行
                        break
                if foreign_buy_row >= 0:
                    break

        if foreign_buy_row < 0:
            _dump_raw(xls_bytes, xls_url)
            _log("JPX Foreign: 外国人買い行が見つかりません (原文件已存 data_lake/jpx_raw/)", "ERROR")
            return _load_foreign_cache()

        _log(f"JPX Foreign: 外国人買い行 = Row{foreign_buy_row}")

        # 最新週の差引きを取得 (最後のBalance列)
        foreign_balance = None
        used_col = -1

        # Balance列のうち、最新(最右)のものから試す
        for bc in reversed(balance_cols):
            val = _parse_number(sheet.cell_value(foreign_buy_row, bc))
            if val != 0:
                foreign_balance = val
                used_col = bc
                break

        # Balance列が空の場合、買い行の全数値から推定
        if foreign_balance is None:
            _log("JPX Foreign: Balance列から値取得失敗, 全列走査", "WARN")
            for c in reversed(range(sheet.ncols)):
                val = _parse_number(sheet.cell_value(foreign_buy_row, c))
                if val != 0 and abs(val) < 1e12:  # Balanceは売買額より小さい
                    foreign_balance = val
                    used_col = c
                    break

        if foreign_balance is None:
            _log("JPX Foreign: 外国人Balance値の取得に失敗", "ERROR")
            return _load_foreign_cache()

        # 単位: 千円 → 億円  (1億 = 1e8円 = 1e5千円)
        net_buy_billion_jpy = round(foreign_balance / 1e5, 1)

        # 前週のBalanceも取得 (あれば)
        prev_balance = None
        if len(balance_cols) >= 2:
            prev_col = balance_cols[0] if used_col != balance_cols[0] else (balance_cols[1] if len(balance_cols) > 1 else None)
            if prev_col is not None:
                pv = _parse_number(sheet.cell_value(foreign_buy_row, prev_col))
                if pv != 0:
                    prev_balance = round(pv / 1e5, 1)

        result = {
            "net_buy_billion_jpy": net_buy_billion_jpy,
            "prev_week_billion_jpy": prev_balance,
            "raw_value_thousand_jpy": foreign_balance,
            "report_period": report_period or _fname_period or "unknown",
            "source": "jpx_auto",
            "xls_url": xls_url,
            "detected_row": foreign_buy_row,
            "detected_col": used_col,
            "fetched_at": datetime.now().isoformat(),
            "fetched_ts": time.time(),
        }
        atomic_write_json(result, _JPX_FOREIGN_CACHE)
        _log(f"JPX Foreign 解析完了: net={net_buy_billion_jpy}億円 (Row{foreign_buy_row},Col{used_col}) [{report_period}]")
        return result

    except ImportError as e:
        _log(f"Excel 解析库未安装 ({e}); 请 pip install xlrd openpyxl", "ERROR")
        return _load_foreign_cache()
    except Exception as e:
        _log(f"JPX Foreign 取得失敗: {e}", "ERROR")
        _logger.debug("Traceback", exc_info=True)
        return _load_foreign_cache()


# ═══════════════════════════════════════════════════
#  外資フロー 週次履歴 (2026-10-23: 正規化を履歴ベースで自己校準するため)
# ═══════════════════════════════════════════════════

_JPX_FOREIGN_HIST = os.path.join(CACHE_DIR, "jpx_foreign_history.json")
_ARCHIVE_URL = "https://www.jpx.co.jp/markets/statistics-equities/investor-type/00-00-archives-00.html"
_backfill_lock = __import__("threading").Lock()
_backfill_state = {"last_try": 0.0}


def _week_key_from_url(url: str) -> Optional[str]:
    """週末日 (YYYY-MM-DD). 新版 stock_1_w_起_止.xlsx → 止; 旧版 stock_val_1_YYMMDD.xls → 该日."""
    m = re.search(r'stock_1_w_\d{8}_(\d{8})', url)
    if m:
        d = m.group(1)
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    m = re.search(r'stock_val_1_(\d{2})(\d{2})(\d{2})\.xls', url)
    if m:
        return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


_JPX_FOREIGN_SEED = os.path.join(CACHE_DIR, "jpx_foreign_history_seed.json")


def load_foreign_history() -> Dict[str, float]:
    """{週末日: 海外投資家 二市場 週次差引 (億円)} 旧→新 排序.
    种子 (2023-01 ~ 2026-10, 164 周, 已与年度合计及 JPX 原表交叉验证) + 实时记录 (覆盖种子)."""
    weeks = {}
    for fp in (_JPX_FOREIGN_SEED, _JPX_FOREIGN_HIST):
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                weeks.update(json.load(f).get("weeks", {}))
        except Exception:
            pass
    out = {}
    for k, v in sorted(weeks.items()):
        try:
            out[k] = float(v["net_oku"])
        except Exception:
            pass
    return out


def _record_foreign_weeks(items: Dict[str, float], urls=()) -> None:
    try:
        try:
            with open(_JPX_FOREIGN_HIST, 'r', encoding='utf-8') as f:
                h = json.load(f)
        except Exception:
            h = {"weeks": {}, "urls": []}
        for k, v in items.items():
            h["weeks"][k] = {"net_oku": round(float(v), 1)}
        h["urls"] = sorted(set(h.get("urls", [])) | set(urls))
        atomic_write_json(h, _JPX_FOREIGN_HIST)
    except Exception as e:
        _log(f"外資履歴保存失敗: {e}", "WARN")


def _parse_foreign_v1(sheet):
    """旧版 stock_val_1_*.xls: 返回 (最新週差引, 前週差引) 千円, 失败 None"""
    bal_cols = []
    for r in range(0, min(30, sheet.nrows)):
        for c in range(sheet.ncols):
            v = str(sheet.cell_value(r, c))
            if ("差引" in v or "Balance" in v) and c not in bal_cols:
                bal_cols.append(c)
    row = -1
    for r in range(sheet.nrows):
        t = "".join(str(sheet.cell_value(r, c)) for c in range(min(6, sheet.ncols)))
        if ("Foreigners" in t or "外国人" in t or "海外投資家" in t) and ("買" in t or "Purchase" in t):
            row = r
            break
    if row < 0 or not bal_cols:
        return None
    vals = [_parse_number(sheet.cell_value(row, c)) for c in sorted(bal_cols)]
    vals = [v for v in vals if v != 0]
    if not vals:
        return None
    return vals[-1], (vals[0] if len(vals) >= 2 else None)


def backfill_foreign_history(max_files: int = 170) -> int:
    """从 JPX 归档页回填周度外资流向 (在服务所在机器上运行). 返回新增周数."""
    try:
        links = _find_xls_links(_ARCHIVE_URL)
    except Exception as e:
        _log(f"外資履歴回填: 归档页获取失败 {e}", "WARN")
        return 0
    try:
        with open(_JPX_FOREIGN_HIST, 'r', encoding='utf-8') as f:
            done = set(json.load(f).get("urls", []))
    except Exception:
        done = set()
    weekly = [l for l in dict.fromkeys(links)
              if _week_key_from_url(l) and l not in done and "yyyy" not in l.lower()
              and l.lower().endswith(".xlsx")]  # 仅新版 (二市場口径); 旧版 xls 为 Prime 口径, 不混入
    weekly = sorted(weekly, key=_week_key_from_url, reverse=True)[:max_files]
    added = 0
    for url in weekly:
        key = _week_key_from_url(url)
        try:
            sheet, _ = _open_first_sheet(_download_url(url), url)
            v2 = _parse_foreign_v2(sheet)
            items = {}
            if v2 is not None:
                items[key] = v2["raw"] / 1e5
            else:
                v1 = _parse_foreign_v1(sheet)
                if v1 is None:
                    continue
                items[key] = v1[0] / 1e5
                if v1[1] is not None:
                    prev = (datetime.strptime(key, "%Y-%m-%d") - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d")
                    items.setdefault(prev, v1[1] / 1e5)
            _record_foreign_weeks(items, urls=[url])
            added += len(items)
        except Exception as e:
            _log(f"外資履歴回填: {os.path.basename(url)} 失败 {e}", "WARN")
        time.sleep(0.3)
    _log(f"外資履歴回填完了: 新增 {added} 周, 累计 {len(load_foreign_history())} 周")
    return added


def _maybe_backfill_async(min_weeks: int = 104) -> None:
    if len(load_foreign_history()) >= min_weeks:
        return
    with _backfill_lock:
        if time.time() - _backfill_state["last_try"] < 86400:
            return
        _backfill_state["last_try"] = time.time()
    t = __import__("threading").Thread(target=backfill_foreign_history, name="jpx-foreign-backfill", daemon=True)
    t.start()


def fetch_jpx_foreign_flow() -> Optional[Dict]:
    """外資フロー取得 + 周度历史记录 (供自校准正规化) + 历史不足时后台回填"""
    result = _fetch_jpx_foreign_flow_impl()
    try:
        url = (result or {}).get("xls_url")
        key = _week_key_from_url(url) if url else None
        if key and result.get("net_buy_billion_jpy") is not None and not result.get("stale"):
            _record_foreign_weeks({key: result["net_buy_billion_jpy"]}, urls=[url])
            _maybe_backfill_async()
    except Exception:
        pass
    return result


def _load_foreign_cache() -> Optional[Dict]:
    """磁盤キャッシュから外資フローデータを読込"""
    if os.path.exists(_JPX_FOREIGN_CACHE):
        try:
            with open(_JPX_FOREIGN_CACHE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            age_d = (time.time() - data.get("fetched_ts", 0)) / 86400
            data["stale"] = age_d > 10
            data["cache_age_days"] = round(age_d, 1)
            _log(f"JPX Foreign: 磁盤キャッシュ使用 (取得から{age_d:.0f}日, 期間={data.get('report_period')})", "WARN")
            return data
        except Exception:
            pass
    return None


# ═══════════════════════════════════════════════════
#  自検 (Self-Test)
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    print("=" * 60)
    print("  JPX Data Fetcher V1.1 Self-Test")
    print("=" * 60)

    print("\n[1/2] 信用取引残高...")
    margin = fetch_jpx_margin()
    if margin:
        print(f"  ✅ 買残合計: {margin['margin_buying_trillion_jpy']}兆円")
        print(f"     銘柄数: {margin.get('stock_count', '?')}")
        print(f"     基準日: {margin.get('report_date', '?')}")
        print(f"     検出列: Col{margin.get('detected_col', '?')} ({margin.get('detected_unit', '?')})")
    else:
        print("  ❌ FAILED")

    print("\n[2/2] 外国人投資家フロー...")
    foreign = fetch_jpx_foreign_flow()
    if foreign:
        print(f"  ✅ 最新週ネット: {foreign['net_buy_billion_jpy']}億円")
        if foreign.get('prev_week_billion_jpy') is not None:
            print(f"     前週ネット: {foreign['prev_week_billion_jpy']}億円")
        print(f"     期間: {foreign.get('report_period', '?')}")
        print(f"     検出: Row{foreign.get('detected_row', '?')}, Col{foreign.get('detected_col', '?')}")
    else:
        print("  ❌ FAILED")

    print("\n" + "=" * 60)
