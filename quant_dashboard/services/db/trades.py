"""交易记录 CRUD"""

from datetime import datetime
from typing import Optional, List, Dict
from .connection import _get_conn, logger


# ══════════════════════════════════════════════════════════
#  交易记录 CRUD
# ══════════════════════════════════════════════════════════

def add_trade(trade: dict) -> int:
    """插入一条交易记录, 返回 row id"""
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO trades (timestamp, action, ts_code, name, amount, price, total, success, message)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trade.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            trade.get("action", "unknown"),
            trade.get("ts_code", ""),
            trade.get("name", ""),
            trade.get("amount", 0),
            trade.get("price", 0.0),
            trade.get("total", 0.0),
            trade.get("success", True),
            trade.get("message", ""),
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_trades(limit: int = 30, ts_code: Optional[str] = None) -> List[Dict]:
    """查询交易记录 (最新在前)"""
    conn = _get_conn()
    if ts_code:
        rows = conn.execute(
            "SELECT * FROM trades WHERE ts_code = ? ORDER BY id DESC LIMIT ?",
            (ts_code, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_trade_count() -> int:
    """交易记录总数"""
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
