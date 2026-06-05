"""AIAE 月度、ERP 日度、组合净值快照"""

from datetime import datetime
from typing import Optional, List, Dict
from .connection import _get_conn, logger


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
