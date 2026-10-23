"""历史成交导入: 编码识别 / 损坏拦截 / 定宽解析 / 分类 / 台账去重 / 对账锚点"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.trade_import import (  # noqa: E402
    TradeImportError, closed_round_trips, decode_broker_bytes, import_trade_file,
    load_ledger, parse_trade_file, parse_trade_text, reconcile_positions, ts_code_of,
)

# 通达信 "历史成交" 默认版式: 列宽按 GBK 字节, 空格补齐
HEADER = ["成交日期", "成交时间", "证券代码", "证券名称", "买卖标志", "成交价格", "成交数量",
          "成交金额", "成交编号", "委托价格", "委托数量", "委托编号", "股东代码"]
WIDTHS = [16, 16, 16, 16, 16, 16, 16, 16, 24, 16, 16, 16, 18]


def _pad(cells):
    out = b""
    for c, w in zip(cells, WIDTHS):
        b = str(c).encode("gbk")
        out += b + b" " * max(1, w - len(b))
    return out


def tdx_bytes(rows):
    lines = [b"-" * 100, b"", _pad(HEADER)] + [_pad(r) for r in rows]
    return b"\r\n".join(lines) + b"\r\n"


ROWS = [
    ["20260901", "00:00:00", "204001", "GC001", "融券", "1.3500", "20", "2000.07", "1200801006021215", "1.3500", "20", "1768255", "A468056267"],
    ["20260902", "10:39:18", "002156", "通富微电", "证券买入", "59.9100", "300", "17973.00", "0103000035061491", "59.9100", "300", "960567", "0900069159"],
    ["20260904", "10:14:07", "002156", "通富微电", "证券买入", "58.7500", "100", "5875.00", "0104000030939089", "58.7600", "100", "842009", "0900069159"],
    ["20260904", "10:33:46", "510500", "500ETF", "证券买入", "7.7900", "2400", "18696.00", "30617256", "7.7900", "2400", "895235", "A468056267"],
    ["20260907", "19:22:12", "787837", "诺诺申购", "新股申购", "27.6000", "500", "13800.00", "", "27.6000", "0", "0", "A468056267"],
    ["20260909", "10:46:48", "510500", "500ETF", "证券卖出", "7.8160", "2400", "18758.40", "33175815", "7.8150", "2400", "961629", "A468056267"],
    ["20260917", "09:50:27", "688837", "C诺维", "证券卖出", "44.8700", "500", "22435.00", "15888360", "44.8700", "500", "509529", "A468056267"],
    ["20261013", "09:48:48", "159516", "半导设备", "证券买入", ".5890", "31900", "18789.10", "0105000012461235", ".5890", "31900", "373309", "0900069159"],
]


def test_decode_gbk_and_parse_fixed_width():
    res = parse_trade_file(tdx_bytes(ROWS), source="t.txt")
    assert res.encoding == "gbk" and res.layout == "fixed_width"
    assert res.skipped == {"repo": 1}
    assert len(res.trades) == 7
    t = res.trades[0]
    assert (t.ts_code, t.side, t.qty, t.price, t.name) == ("002156.SZ", "buy", 300, 59.91, "通富微电")
    etf = [x for x in res.trades if x.code == "159516"][0]
    assert etf.price == 0.589 and etf.ts_code == "159516.SZ"


def test_ipo_code_mapped_and_empty_column_not_shifted():
    res = parse_trade_file(tdx_bytes(ROWS))
    ipo = [t for t in res.trades if t.kind == "ipo"][0]
    assert ipo.ts_code == "688837.SH" and ipo.side == "buy" and ipo.qty == 500
    assert ipo.trade_id == ""                      # 空列不导致后续列错位
    assert ipo.price == 27.6 and ipo.account == "A468056267"


def test_corrupted_utf8_mojibake_is_rejected():
    # GBK 字节被当 UTF-8 打开另存 → 中文变 U+FFFD, 方向不可恢复
    broken = tdx_bytes(ROWS).decode("utf-8", errors="replace").encode("utf-8")
    with pytest.raises(TradeImportError) as e:
        parse_trade_file(broken)
    assert e.value.code == "ERR_ENCODING_CORRUPTED"
    # 再被 GBK 误读一次的 "锟斤拷" 形态同样拦截
    with pytest.raises(TradeImportError):
        parse_trade_text(broken.decode("gb18030", errors="replace"))


def test_utf8_and_tab_layout():
    text = "\t".join(HEADER) + "\n" + "\n".join("\t".join(r) for r in ROWS[1:3])
    res = parse_trade_file(text.encode("utf-8-sig"))
    assert res.layout == "tsv" and len(res.trades) == 2 and res.encoding == "utf-8-sig"


def test_unknown_side_goes_to_errors_not_guessed():
    rows = [ROWS[1][:4] + ["撤单"] + ROWS[1][5:]]
    with pytest.raises(TradeImportError):
        parse_trade_file(tdx_bytes(rows))   # 唯一一行无法识别 → 无成交
    res = parse_trade_file(tdx_bytes(rows + [ROWS[2]]))
    assert len(res.trades) == 1 and res.errors and "撤单" in res.errors[0]


def test_missing_columns():
    with pytest.raises(TradeImportError) as e:
        parse_trade_text("证券代码 成交日期 成交价格\n002156 20260901 1.0\n")
    assert e.value.code == "ERR_MISSING_COLUMNS"


def test_ledger_import_is_idempotent(tmp_path):
    p = str(tmp_path / "ledger.json")
    s1 = import_trade_file(tdx_bytes(ROWS), "a.txt", path=p)
    s2 = import_trade_file(tdx_bytes(ROWS), "a.txt", path=p)
    assert s1["added"] == 7 and s2["added"] == 0 and s2["duplicates"] == 7
    assert len(load_ledger(p)["trades"]) == 7


def test_reconcile_anchor_and_round_trips():
    trades = [t.to_dict() for t in parse_trade_file(tdx_bytes(ROWS)).trades]
    holdings = {
        "002156.SZ": {"amount": 400, "cost": 59.6},     # 全部在台账内建仓 → exact
        "159516.SZ": {"amount": 150500, "cost": 0.672},  # 期初已有 → pre_window
        "300476.SZ": {"amount": 600, "cost": 262.0},     # 台账无记录
    }
    rec = reconcile_positions(trades, holdings)
    assert rec["002156.SZ"]["anchor_date"] == "2026-09-02"
    assert rec["002156.SZ"]["anchor_quality"] == "exact" and rec["002156.SZ"]["status"] == "ok"
    assert rec["159516.SZ"]["status"] == "opening_lot"
    assert rec["159516.SZ"]["anchor_date"] == "2026-09-02"   # 台账首个持仓类成交日
    assert rec["300476.SZ"]["status"] == "no_history"

    trips = closed_round_trips(trades, held_codes=holdings.keys())
    codes = {t["ts_code"]: t for t in trips}
    assert codes["510500.SH"]["pnl"] == pytest.approx(62.4)
    assert codes["688837.SH"]["entry_date"] == "2026-09-07"
    assert codes["688837.SH"]["ret"] == pytest.approx(44.87 / 27.6 - 1)


def test_reconcile_mismatch_when_ledger_exceeds_holding():
    trades = [t.to_dict() for t in parse_trade_file(tdx_bytes(ROWS)).trades]
    rec = reconcile_positions(trades, {"002156.SZ": {"amount": 100}})
    assert rec["002156.SZ"]["status"] == "mismatch"


def test_ts_code_market_from_account():
    assert ts_code_of("510500", "A468056267") == "510500.SH"
    assert ts_code_of("159995", "0900069159") == "159995.SZ"
    assert ts_code_of("688981") == "688981.SH"
    assert ts_code_of("002156") == "002156.SZ"


def test_decode_rejects_empty():
    with pytest.raises(TradeImportError):
        decode_broker_bytes(b"")


def test_scan_import_folder_accumulates_and_dedupes(tmp_path):
    from services.trade_import import scan_import_folder
    folder, ledger = tmp_path / "imports", str(tmp_path / "ledger.json")
    folder.mkdir()
    (folder / "2026-09.txt").write_bytes(tdx_bytes(ROWS[:4]))
    r1 = scan_import_folder(str(folder), ledger)
    assert r1["added"] == 3 and r1["files"][0]["status"] == "ok"
    (folder / "2026-10.txt").write_bytes(tdx_bytes(ROWS[2:]))       # 与上月重叠
    (folder / "bad.txt").write_bytes(tdx_bytes(ROWS).decode("utf-8", "replace").encode())
    r2 = scan_import_folder(str(folder), ledger)
    st = {f["file"]: f for f in r2["files"]}
    assert st["2026-10.txt"]["added"] == 4 and st["2026-10.txt"]["duplicates"] == 2
    assert st["bad.txt"]["code"] == "ERR_ENCODING_CORRUPTED"
    assert scan_import_folder(str(folder), ledger)["files"][0]["file"] == "bad.txt"   # 好文件不再重复解析
    assert len(load_ledger(ledger)["trades"]) == 7
