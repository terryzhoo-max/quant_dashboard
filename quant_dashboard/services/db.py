"""
AlphaCore SQLite 持久化层 — Batch 10 数据治理
==============================================
统一管理 3 张表:
  - trades:        交易记录 (从 trade_history.json 迁移)
  - aiae_monthly:  AIAE 月度历史 (从 aiae_monthly_history.json 迁移)
  - erp_daily:     ERP 日度历史 (从 erp_daily_history.json 迁移)

设计原则:
  - 线程安全 (check_same_thread=False + 连接池)
  - 零风险迁移 (双写 JSON + SQLite)
  - 启动自动迁移旧 JSON 数据
"""

import sqlite3
import json
import os
import threading
from datetime import datetime
from typing import Optional, List, Dict
from services.logger import get_logger

logger = get_logger("ac.db")

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_lake")
DB_PATH = os.path.join(DB_DIR, "alphacore.db")

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """线程本地连接 (每线程独立, 避免 SQLite 跨线程锁)"""
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(DB_DIR, exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


def init_db():
    """建表 (幂等, 启动时调用)"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            amount INTEGER,
            price REAL,
            total REAL,
            success BOOLEAN,
            message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_trades_code ON trades(ts_code);

        CREATE TABLE IF NOT EXISTS aiae_monthly (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL UNIQUE,
            aiae_v1 REAL,
            regime INTEGER,
            recorded_at TEXT,
            updated_at TEXT,
            source TEXT
        );

        CREATE TABLE IF NOT EXISTS erp_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            score REAL,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            total_asset REAL,
            cash REAL,
            market_value REAL,
            total_pnl REAL,
            position_count INTEGER,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    logger.info("SQLite 数据库初始化完成 · %s", DB_PATH)


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


# ══════════════════════════════════════════════════════════
#  AIAE 月度历史
# ══════════════════════════════════════════════════════════

def upsert_aiae_monthly(month: str, aiae_v1: float, regime: int,
                         recorded_at: Optional[str] = None,
                         source: Optional[str] = None):
    """插入或更新月度 AIAE 记录 (按 month UNIQUE 键)"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO aiae_monthly (month, aiae_v1, regime, recorded_at, updated_at, source)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(month) DO UPDATE SET
             aiae_v1 = excluded.aiae_v1,
             regime = excluded.regime,
             updated_at = ?,
             source = COALESCE(excluded.source, aiae_monthly.source)""",
        (month, aiae_v1, regime, recorded_at or now, now, source, now),
    )
    conn.commit()


def get_aiae_history() -> List[Dict]:
    """获取所有 AIAE 月度历史 (按月排序)"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM aiae_monthly ORDER BY month ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_prev_month_aiae(current_month: str) -> Optional[float]:
    """获取上个月的 AIAE 值 (排除当月)"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT aiae_v1 FROM aiae_monthly WHERE month < ? ORDER BY month DESC LIMIT 1",
        (current_month,),
    ).fetchone()
    return row["aiae_v1"] if row else None


# ══════════════════════════════════════════════════════════
#  ERP 日度历史
# ══════════════════════════════════════════════════════════

def upsert_erp_daily(date: str, score: float):
    """插入或更新 ERP 日度记录"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO erp_daily (date, score, recorded_at)
           VALUES (?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             score = excluded.score,
             recorded_at = excluded.recorded_at""",
        (date, score, now),
    )
    conn.commit()


def get_erp_history(days: int = 30) -> List[Dict]:
    """获取最近 N 天的 ERP 历史"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM erp_daily ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]  # 按日期正序


def get_erp_latest() -> Optional[Dict]:
    """获取最新一条 ERP 记录"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM erp_daily ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


# ══════════════════════════════════════════════════════════
#  JSON → SQLite 迁移 (启动时一次性调用)
# ══════════════════════════════════════════════════════════

def migrate_from_json() -> dict:
    """从旧 JSON 文件导入数据到 SQLite (幂等, 重复数据跳过)"""
    result = {"trades": 0, "aiae": 0, "erp": 0, "errors": []}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. 交易历史
    trade_file = os.path.join(root, "trade_history.json")
    if os.path.exists(trade_file):
        try:
            with open(trade_file, "r", encoding="utf-8") as f:
                trades = json.load(f)
            existing_count = get_trade_count()
            if existing_count == 0 and trades:
                conn = _get_conn()
                for t in trades:
                    conn.execute(
                        """INSERT INTO trades (timestamp, action, ts_code, name, amount, price, total, success, message)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (t.get("timestamp"), t.get("action"), t.get("ts_code"),
                         t.get("name"), t.get("amount", 0), t.get("price", 0),
                         t.get("total", 0), t.get("success", True), t.get("message", "")),
                    )
                conn.commit()
                result["trades"] = len(trades)
                logger.info("迁移 trade_history.json → SQLite: %d 条", len(trades))
            elif existing_count > 0:
                logger.info("trades 表已有 %d 条记录, 跳过迁移", existing_count)
        except Exception as e:
            result["errors"].append(f"trade_history: {e}")
            logger.warning("迁移 trade_history 失败: %s", e)

    # 2. AIAE 月度历史
    aiae_file = os.path.join(root, "data_lake", "aiae_monthly_history.json")
    if os.path.exists(aiae_file):
        try:
            with open(aiae_file, "r", encoding="utf-8") as f:
                records = json.load(f)
            for r in records:
                upsert_aiae_monthly(
                    month=r["month"],
                    aiae_v1=r.get("aiae_v1", 0),
                    regime=r.get("regime", 3),
                    recorded_at=r.get("recorded_at"),
                    source=r.get("source"),
                )
            result["aiae"] = len(records)
            logger.info("迁移 aiae_monthly_history.json → SQLite: %d 条", len(records))
        except Exception as e:
            result["errors"].append(f"aiae_monthly: {e}")
            logger.warning("迁移 aiae_monthly 失败: %s", e)

    # 3. ERP 日度历史
    erp_file = os.path.join(root, "data_lake", "erp_daily_history.json")
    if os.path.exists(erp_file):
        try:
            with open(erp_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            history = data.get("score_history", [])
            for entry in history:
                upsert_erp_daily(
                    date=entry["date"],
                    score=entry["score"],
                )
            result["erp"] = len(history)
            logger.info("迁移 erp_daily_history.json → SQLite: %d 条", len(history))
        except Exception as e:
            result["errors"].append(f"erp_daily: {e}")
            logger.warning("迁移 erp_daily 失败: %s", e)

    return result


# ══════════════════════════════════════════════════════════
#  组合净值快照 (Batch 11: 每日收盘自动存档)
# ══════════════════════════════════════════════════════════

def save_portfolio_snapshot(date: str, total_asset: float, cash: float,
                            market_value: float, total_pnl: float,
                            position_count: int):
    """保存每日组合快照 (按 date UNIQUE 键, 幂等)"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO portfolio_snapshots (date, total_asset, cash, market_value, total_pnl, position_count, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             total_asset = excluded.total_asset,
             cash = excluded.cash,
             market_value = excluded.market_value,
             total_pnl = excluded.total_pnl,
             position_count = excluded.position_count,
             recorded_at = excluded.recorded_at""",
        (date, total_asset, cash, market_value, total_pnl, position_count, now),
    )
    conn.commit()


def get_portfolio_snapshots(days: int = 90) -> List[Dict]:
    """获取最近 N 天的组合快照 (按日期正序)"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM portfolio_snapshots ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_portfolio_snapshot_count() -> int:
    """快照总数"""
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]
