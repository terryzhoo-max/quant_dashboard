"""
AlphaCore · 历史成交导入 (通达信 / 券商客户端导出)
=================================================

职责
----
1. 字节 → 文本: 自动识别 UTF-8(BOM) / GBK / GB18030, 并拦截"已被转码损坏"的文件
   (典型: GBK 文件被当作 UTF-8 打开后另存, 中文变成 � 或 "锟斤拷", 买卖方向不可恢复)。
2. 文本 → 成交记录: 支持三种版式
     - 定宽空格对齐 (通达信 "历史成交" 默认导出, 按 GBK 显示宽度切列, 空列不错位)
     - Tab 分隔 (部分券商 .xls 实为 TSV)
     - 逗号分隔 CSV
   列头按别名映射, 兼容 "历史成交" 与 "交割单" (含手续费/印花税/发生金额)。
3. 业务分类: 买入 / 卖出 / 新股中签 / ETF 申赎 / 逆回购 / 红利 等;
   非持仓类 (逆回购, 红利, 资金划转) 只计数不入持仓。
4. 成交台账 data_lake/trade_ledger.json: 追加去重, 重复导入同一文件幂等。
5. 与券商持仓快照对账 (reconcile_positions): 推出每只持仓的"本轮建仓日"
   (跟踪止盈的高水位锚点), 并标记期初持仓 / 对账不平。

设计原则: 宁可报错, 不可静默算错。方向未知的行一律进入 errors, 不猜。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

from services.logger import get_logger

logger = get_logger("ac.trade_import")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_PATH = os.path.join(_ROOT, "data_lake", "trade_ledger.json")


class TradeImportError(Exception):
    """可直接展示给用户的导入错误 (code 供前端分支处理)."""

    def __init__(self, message: str, code: str = "ERR_TRADE_IMPORT"):
        super().__init__(message)
        self.code = code


# ═══════════════════════════════════════════════════════
#  ① 编码识别 + 损坏拦截
# ═══════════════════════════════════════════════════════

_CORRUPTION_MARKERS = ("�", "锟斤拷")
_CORRUPTION_HELP = (
    "文件在传输/另存时已被转码损坏 (GBK 被当作 UTF-8 处理), 中文字段与买卖方向已不可恢复。"
    "请在通达信中重新导出 (查询 → 历史成交 → 输出 → 保存为文本文件), "
    "直接上传原始 .txt, 不要经过记事本另存、微信/QQ 转发或在线文档复制。"
)


def decode_broker_bytes(raw: bytes) -> tuple[str, str]:
    """券商导出文件字节 → (文本, 编码)。损坏文件抛 TradeImportError。"""
    if not raw:
        raise TradeImportError("文件为空", "ERR_EMPTY_FILE")

    text: Optional[str] = None
    encoding = ""
    if raw.startswith(b"\xef\xbb\xbf"):
        text, encoding = raw[3:].decode("utf-8", errors="strict"), "utf-8-sig"
    else:
        try:
            text, encoding = raw.decode("utf-8", errors="strict"), "utf-8"
        except UnicodeDecodeError:
            for enc in ("gbk", "gb18030"):
                try:
                    text, encoding = raw.decode(enc, errors="strict"), enc
                    break
                except UnicodeDecodeError:
                    continue
    if text is None:
        raise TradeImportError("无法识别文件编码 (非 UTF-8/GBK/GB18030)。" + _CORRUPTION_HELP,
                               "ERR_ENCODING")

    if any(m in text for m in _CORRUPTION_MARKERS):
        raise TradeImportError(_CORRUPTION_HELP, "ERR_ENCODING_CORRUPTED")
    return text, encoding


# ═══════════════════════════════════════════════════════
#  ② 版式解析
# ═══════════════════════════════════════════════════════

# 规范列名 → 别名 (精确匹配优先, 其次包含匹配)
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("成交日期", "日期", "发生日期", "交收日期", "清算日期", "业务日期"),
    "time": ("成交时间", "时间", "委托时间"),
    "code": ("证券代码", "代码", "股票代码"),
    "name": ("证券名称", "名称", "股票名称"),
    "side": ("买卖标志", "买卖方向", "操作", "业务名称", "摘要", "委托类别", "交易类别", "买卖类别"),
    "price": ("成交价格", "成交均价", "成交价", "价格"),
    "qty": ("成交数量", "成交股数", "发生数量", "数量"),
    "amount": ("成交金额", "金额"),
    "net_amount": ("发生金额", "清算金额", "收付金额", "资金发生数"),
    "fee_commission": ("手续费", "佣金", "净佣金"),
    "fee_stamp": ("印花税",),
    "fee_transfer": ("过户费",),
    "fee_other": ("其他杂费", "其他费", "其他费用", "规费", "交易所规费", "经手费", "证管费", "结算费"),
    "trade_id": ("成交编号",),
    "order_id": ("委托编号", "合同编号", "申请编号"),
    "account": ("股东代码", "股东帐户", "股东账户", "股东账号"),
    "order_price": ("委托价格",),
    "order_qty": ("委托数量",),
}
_REQUIRED = ("date", "code", "side", "price", "qty")


def _canon_column(header: str) -> Optional[str]:
    h = header.strip()
    if not h:
        return None
    for key, aliases in COLUMN_ALIASES.items():
        if h in aliases:
            return key
    for key, aliases in COLUMN_ALIASES.items():
        if any(a in h for a in aliases if len(a) >= 2):
            return key
    return None


def _char_width(ch: str) -> int:
    """券商定宽导出按 GBK 字节对齐: 汉字/全角 2, ASCII 1。"""
    if ord(ch) < 128:
        return 1
    try:
        return len(ch.encode("gbk"))
    except UnicodeEncodeError:
        return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _tokens_with_offsets(line: str) -> list[tuple[int, str]]:
    """把一行拆成 (显示列起点, 文本) 的非空白片段。"""
    out: list[tuple[int, str]] = []
    col, start, buf = 0, None, []
    for ch in line:
        if ch.isspace() or ch == "　":
            if buf:
                out.append((start, "".join(buf)))
                buf, start = [], None
        else:
            if start is None:
                start = col
            buf.append(ch)
        col += _char_width(ch)
    if buf:
        out.append((start, "".join(buf)))
    return out


def _find_header(lines: list[str]) -> int:
    for i, line in enumerate(lines[:40]):
        if ("代码" in line) and ("成交" in line or "买卖" in line or "操作" in line or "业务" in line):
            return i
    return -1


def _split_fixed_width(header_line: str, data_lines: list[str]) -> tuple[list[str], list[list[str]]]:
    head = _tokens_with_offsets(header_line)
    names = [t for _, t in head]
    starts = [s for s, _ in head]
    rows: list[list[str]] = []
    for line in data_lines:
        cells = [""] * len(names)
        for pos, tok in _tokens_with_offsets(line):
            # 归属到 "起点 ≤ 片段起点(+1 容差)" 的最后一列: 兼容左对齐与右对齐数值
            j = 0
            for k, s in enumerate(starts):
                if s <= pos + 1:
                    j = k
                else:
                    break
            cells[j] = f"{cells[j]} {tok}".strip() if cells[j] else tok
        rows.append(cells)
    return names, rows


def _split_delimited(header_line: str, data_lines: list[str], delim: str) -> tuple[list[str], list[list[str]]]:
    reader = csv.reader(io.StringIO("\n".join([header_line] + data_lines)), delimiter=delim)
    table = [[c.strip().strip('="').strip('"') for c in row] for row in reader]
    return table[0], table[1:]


def _num(s: str) -> Optional[float]:
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("¥", "")
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _norm_date(s: str) -> Optional[str]:
    s = (s or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── 代码 / 市场 ──

_IPO_CODE_MAP = {"787": "688", "730": "600", "780": "601", "732": "603", "707": "605"}


def ts_code_of(code: str, account: str = "") -> str:
    """6 位代码 → ts_code。股东代码优先判断市场 (A/B 开头=沪, 数字开头=深)。"""
    code = (code or "").strip()
    if "." in code:
        return code.upper()
    acct = (account or "").strip().upper()
    if len(code) == 6:
        if code.startswith(("8", "4", "92")) and not code.startswith(("80",)):
            return code + ".BJ"
        if acct[:1] in ("A", "B"):
            return code + ".SH"
        if acct[:1].isdigit():
            return code + ".SZ"
        if code.startswith(("5", "6", "9", "7")):
            return code + ".SH"
        return code + ".SZ"
    if len(code) == 5:
        return code + ".HK"
    return code


def _is_repo(code: str) -> bool:
    return code.startswith("204") or code.startswith("1318")


# ── 业务分类 ──

@dataclass
class Trade:
    date: str
    time: str
    code: str
    ts_code: str
    name: str
    side: str            # buy / sell
    kind: str            # trade / ipo / etf_creation / etf_redemption
    price: float
    qty: int
    amount: float
    fees: Optional[float] = None
    net_amount: Optional[float] = None
    trade_id: str = ""
    order_id: str = ""
    account: str = ""
    raw_side: str = ""
    source: str = ""

    @property
    def key(self) -> str:
        ident = self.trade_id or self.order_id or self.time
        return f"{self.date}|{ident}|{self.ts_code}|{self.side}|{self.qty}|{self.price:.4f}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return d


def classify_side(raw_side: str, code: str) -> tuple[str, str]:
    """返回 (category, side)。category ∈ trade/ipo/etf_creation/etf_redemption/repo/cash/unknown."""
    s = (raw_side or "").strip()
    if _is_repo(code) or "回购" in s or "融券" in s:
        return "repo", ""
    if any(k in s for k in ("红利", "股息", "利息", "派息", "扣税", "转账", "银证", "存入", "取出", "划转")):
        return "cash", ""
    if any(k in s for k in ("中签", "配售", "配号")) or ("申购" in s and ("新股" in s or code[:3] in _IPO_CODE_MAP)):
        return "ipo", "buy"
    if "申购" in s:
        return "etf_creation", "buy"
    if "赎回" in s:
        return "etf_redemption", "sell"
    has_buy, has_sell = "买" in s, "卖" in s
    if has_buy and not has_sell:
        return "trade", "buy"
    if has_sell and not has_buy:
        return "trade", "sell"
    return "unknown", ""


@dataclass
class ParseResult:
    trades: list[Trade] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    layout: str = ""
    encoding: str = ""

    def summary(self) -> dict:
        dates = sorted(t.date for t in self.trades)
        return {
            "parsed": len(self.trades),
            "buys": sum(1 for t in self.trades if t.side == "buy"),
            "sells": sum(1 for t in self.trades if t.side == "sell"),
            "skipped": dict(self.skipped),
            "errors": self.errors[:50],
            "error_count": len(self.errors),
            "columns": self.columns,
            "layout": self.layout,
            "encoding": self.encoding,
            "date_from": dates[0] if dates else None,
            "date_to": dates[-1] if dates else None,
            "codes": sorted({t.ts_code for t in self.trades}),
        }


def parse_trade_text(text: str, source: str = "") -> ParseResult:
    res = ParseResult()
    if any(m in text for m in _CORRUPTION_MARKERS):
        raise TradeImportError(_CORRUPTION_HELP, "ERR_ENCODING_CORRUPTED")

    lines = [l.rstrip("\r") for l in text.replace("\r\n", "\n").split("\n")]
    hi = _find_header(lines)
    if hi < 0:
        raise TradeImportError("未找到列头 (应包含 '证券代码' 与 '成交日期/买卖标志' 等列)。", "ERR_NO_HEADER")
    header_line = lines[hi]
    data_lines = [l for l in lines[hi + 1:] if l.strip() and not set(l.strip()) <= set("-=_ ")]

    if "\t" in header_line:
        names, rows = _split_delimited(header_line, data_lines, "\t")
        res.layout = "tsv"
    elif header_line.count(",") >= 3:
        names, rows = _split_delimited(header_line, data_lines, ",")
        res.layout = "csv"
    else:
        names, rows = _split_fixed_width(header_line, data_lines)
        res.layout = "fixed_width"

    colmap: dict[str, int] = {}
    for i, n in enumerate(names):
        key = _canon_column(n)
        if key and key not in colmap:
            colmap[key] = i
    res.columns = [n for n in names if n]
    missing = [k for k in _REQUIRED if k not in colmap]
    if missing:
        label = {"date": "成交日期", "code": "证券代码", "side": "买卖标志", "price": "成交价格", "qty": "成交数量"}
        raise TradeImportError("缺少必要列: " + "、".join(label[m] for m in missing), "ERR_MISSING_COLUMNS")

    def cell(row: list[str], key: str) -> str:
        i = colmap.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    fee_keys = [k for k in ("fee_commission", "fee_stamp", "fee_transfer", "fee_other") if k in colmap]
    for ln, row in enumerate(rows, start=hi + 2):
        code = re.sub(r"\D", "", cell(row, "code"))
        date = _norm_date(cell(row, "date"))
        raw_side = cell(row, "side")
        if not code or not date:
            res.errors.append(f"第{ln}行: 日期或代码无法解析")
            continue
        category, side = classify_side(raw_side, code)
        if category in ("repo", "cash"):
            res.skipped[category] = res.skipped.get(category, 0) + 1
            continue
        if category == "unknown":
            res.errors.append(f"第{ln}行: 无法识别买卖方向 '{raw_side}' ({code})")
            continue
        price, qty = _num(cell(row, "price")), _num(cell(row, "qty"))
        if not price or not qty or price <= 0 or qty <= 0:
            res.skipped["zero_qty"] = res.skipped.get("zero_qty", 0) + 1
            continue
        if category == "ipo" and code[:3] in _IPO_CODE_MAP:
            code = _IPO_CODE_MAP[code[:3]] + code[3:]
        amount = _num(cell(row, "amount")) or round(price * qty, 2)
        fees = None
        if fee_keys:
            fees = round(sum(_num(cell(row, k)) or 0.0 for k in fee_keys), 2)
        account = cell(row, "account")
        res.trades.append(Trade(
            date=date,
            time=cell(row, "time") or "",
            code=code,
            ts_code=ts_code_of(code, account),
            name=cell(row, "name"),
            side=side,
            kind=category,
            price=float(price),
            qty=int(round(qty)),
            amount=float(amount),
            fees=fees,
            net_amount=_num(cell(row, "net_amount")),
            trade_id=cell(row, "trade_id"),
            order_id=cell(row, "order_id"),
            account=account,
            raw_side=raw_side,
            source=source,
        ))
    if not res.trades and not res.skipped:
        raise TradeImportError("未解析到任何成交记录", "ERR_NO_ROWS")
    return res


def parse_trade_file(raw: bytes, source: str = "") -> ParseResult:
    text, enc = decode_broker_bytes(raw)
    res = parse_trade_text(text, source=source)
    res.encoding = enc
    return res


# ═══════════════════════════════════════════════════════
#  ③ 成交台账 (追加去重, 原子写)
# ═══════════════════════════════════════════════════════

def load_ledger(path: Optional[str] = None) -> dict:
    path = path or LEDGER_PATH
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("trades"), list):
                return data
        except Exception as e:  # 损坏的台账不覆盖, 交给上层报错
            raise TradeImportError(f"成交台账读取失败: {e}", "ERR_LEDGER_CORRUPT")
    return {"version": 1, "trades": [], "imports": []}


def save_ledger(ledger: dict, path: Optional[str] = None) -> None:
    path = path or LEDGER_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _sort_key(t: Mapping[str, Any]) -> tuple:
    return (t.get("date", ""), t.get("time", ""), t.get("trade_id", ""), t.get("key", ""))


def merge_into_ledger(ledger: dict, trades: Iterable[Trade], meta: Optional[dict] = None) -> dict:
    existing = {t.get("key") for t in ledger.get("trades", [])}
    added = dup = 0
    for t in trades:
        d = t.to_dict()
        if d["key"] in existing:
            dup += 1
            continue
        existing.add(d["key"])
        ledger["trades"].append(d)
        added += 1
    ledger["trades"].sort(key=_sort_key)
    entry = {"at": datetime.now().isoformat(timespec="seconds"), "added": added, "duplicates": dup}
    if meta:
        entry.update(meta)
    ledger.setdefault("imports", []).append(entry)
    ledger["imports"] = ledger["imports"][-50:]
    return {"added": added, "duplicates": dup, "total": len(ledger["trades"])}


def import_trade_file(raw: bytes, file_name: str = "", path: Optional[str] = None) -> dict:
    """解析 + 写入台账, 返回导入摘要。"""
    import hashlib
    res = parse_trade_file(raw, source=file_name)
    ledger = load_ledger(path)
    summary = res.summary()
    ledger["file_hashes"] = sorted(set(ledger.get("file_hashes") or []) | {hashlib.sha256(raw).hexdigest()})[-500:]
    merged = merge_into_ledger(ledger, res.trades, {
        "file": file_name, "date_from": summary["date_from"], "date_to": summary["date_to"],
        "parsed": summary["parsed"],
    })
    save_ledger(ledger, path)
    summary.update(merged)
    logger.info("历史成交导入: %s 解析 %d 条, 新增 %d, 重复 %d",
                file_name, summary["parsed"], merged["added"], merged["duplicates"])
    return summary


# ═══════════════════════════════════════════════════════
#  ③b 导入文件夹: 每月把通达信导出丢进去, 台账自动累积 (突破 60 天导出限制)
# ═══════════════════════════════════════════════════════

IMPORT_DIR = os.path.join(_ROOT, "data_lake", "trade_imports")
_IMPORT_EXT = (".txt", ".csv", ".tsv", ".xls")


def scan_import_folder(folder: Optional[str] = None, path: Optional[str] = None) -> dict:
    """扫描导入文件夹, 按文件内容哈希去重 (同一文件只解析一次), 成交按 key 去重合并。"""
    import hashlib
    folder = folder or IMPORT_DIR
    os.makedirs(folder, exist_ok=True)
    ledger = load_ledger(path)
    seen = set(ledger.get("file_hashes") or [])
    out = {"folder": folder, "files": [], "added": 0}
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith(_IMPORT_EXT):
            continue
        fp = os.path.join(folder, fn)
        try:
            raw = open(fp, "rb").read()
        except OSError as e:
            out["files"].append({"file": fn, "status": "error", "message": str(e)})
            continue
        h = hashlib.sha256(raw).hexdigest()
        if h in seen:
            continue
        try:
            res = parse_trade_file(raw, source=fn)
            sm = res.summary()
            merged = merge_into_ledger(ledger, res.trades, {"file": fn, "date_from": sm["date_from"],
                                                            "date_to": sm["date_to"], "parsed": sm["parsed"],
                                                            "via": "folder"})
            out["added"] += merged["added"]
            out["files"].append({"file": fn, "status": "ok", **merged, "date_from": sm["date_from"],
                                 "date_to": sm["date_to"], "errors": sm["error_count"]})
            seen.add(h)
        except TradeImportError as e:
            out["files"].append({"file": fn, "status": "error", "code": e.code, "message": str(e)})
    ledger["file_hashes"] = sorted(seen)[-500:]
    if out["files"]:
        save_ledger(ledger, path)
        logger.info("导入文件夹扫描: %d 个新文件, 新增 %d 笔", len(out["files"]), out["added"])
    return out


# ═══════════════════════════════════════════════════════
#  ④ 对账 + 本轮建仓日 (跟踪止盈锚点)
# ═══════════════════════════════════════════════════════

def _signed(t: Mapping[str, Any]) -> int:
    q = int(t.get("qty") or 0)
    return q if t.get("side") == "buy" else -q


def reconcile_positions(trades: list[Mapping[str, Any]], holdings: Mapping[str, Mapping[str, Any]],
                        as_of: Optional[str] = None) -> dict[str, dict]:
    """券商持仓 (权威数量/成本) × 成交台账 (时间线) → 每只持仓的锚点与对账状态。

    opening = 持仓数量 − 台账净买入; 期初为 0 才能精确定位本轮建仓日。
      anchor_quality: exact      台账内可见 0→正 的建仓时点
                      pre_window 期初已有持仓, 建仓早于台账起点 (锚点取台账首日, 偏保守)
                      no_history 台账中无该标的
      status:         ok / opening_lot / mismatch (台账买多于持仓 → 漏导卖出或快照过期)
    """
    as_of = as_of or "9999-12-31"
    by_code: dict[str, list[Mapping[str, Any]]] = {}
    for t in trades:
        if t.get("date", "") <= as_of:
            by_code.setdefault(t["ts_code"], []).append(t)
    ledger_start = min((t["date"] for t in trades), default=None)

    out: dict[str, dict] = {}
    for code, pos in holdings.items():
        held = int(round(float(pos.get("amount", 0) or 0)))
        tl = sorted(by_code.get(code, []), key=_sort_key)
        net = sum(_signed(t) for t in tl)
        opening = held - net
        info = {
            "ts_code": code, "held_qty": held, "ledger_net": net, "opening_qty": opening,
            "trades": len(tl), "anchor_date": None, "anchor_quality": "no_history",
            "status": "ok", "ledger_start": ledger_start, "last_buy_date": None,
            "last_sell_date": None,
        }
        if not tl:
            info["status"] = "no_history"
            out[code] = info
            continue
        running = opening
        episode_start = None
        for t in tl:
            before = running
            running += _signed(t)
            if before <= 0 < running:
                episode_start = t["date"]
            if running <= 0:
                episode_start = None
            if t.get("side") == "buy":
                info["last_buy_date"] = t["date"]
            else:
                info["last_sell_date"] = t["date"]
        if opening < 0:
            info["status"] = "mismatch"
            info["anchor_date"] = episode_start or tl[0]["date"]
            info["anchor_quality"] = "approx"
        elif opening > 0 and episode_start is None:
            info["status"] = "opening_lot"
            info["anchor_date"] = ledger_start
            info["anchor_quality"] = "pre_window"
        else:
            info["anchor_date"] = episode_start
            info["anchor_quality"] = "exact" if episode_start else "approx"
        out[code] = info
    return out


def closed_round_trips(trades: list[Mapping[str, Any]], held_codes: Iterable[str] = ()) -> list[dict]:
    """台账内已完成的回合 (持仓 0 → 正 → 0)。仅统计成本完全可见的回合。"""
    held = set(held_codes)
    by_code: dict[str, list[Mapping[str, Any]]] = {}
    for t in trades:
        by_code.setdefault(t["ts_code"], []).append(t)
    trips: list[dict] = []
    for code, tl in by_code.items():
        tl = sorted(tl, key=_sort_key)
        net = sum(_signed(t) for t in tl)
        # 对不再持有的标的, 期初持仓 = −净买入; 对仍持有的标的无法确定 → 只用 0 起点
        opening = max(0, -net) if code not in held else 0
        running = opening
        cur: Optional[dict] = None
        for t in tl:
            before = running
            running += _signed(t)
            if before <= 0 < running:
                cur = {"ts_code": code, "name": t.get("name", ""), "entry_date": t["date"],
                       "buy_qty": 0, "buy_amt": 0.0, "sell_qty": 0, "sell_amt": 0.0, "fills": 0}
            if cur is not None:
                cur["fills"] += 1
                if t.get("side") == "buy":
                    cur["buy_qty"] += int(t["qty"]); cur["buy_amt"] += float(t["amount"])
                else:
                    cur["sell_qty"] += int(t["qty"]); cur["sell_amt"] += float(t["amount"])
                    if not cur["name"] or "申购" in cur["name"]:   # 新股: 用上市后的证券简称
                        cur["name"] = re.sub(r"^[NC](?=\S)", "", t.get("name", "")) or cur["name"]
                if running <= 0 and before > 0:
                    cur["exit_date"] = t["date"]
                    if cur["buy_qty"] == cur["sell_qty"] and cur["buy_qty"] > 0:
                        cur["avg_buy"] = cur["buy_amt"] / cur["buy_qty"]
                        cur["avg_sell"] = cur["sell_amt"] / cur["sell_qty"]
                        cur["pnl"] = round(cur["sell_amt"] - cur["buy_amt"], 2)
                        cur["ret"] = cur["avg_sell"] / cur["avg_buy"] - 1
                        trips.append(cur)
                    cur = None
    trips.sort(key=lambda x: x["exit_date"])
    return trips
