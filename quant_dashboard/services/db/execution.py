"""V26.0: OMS 滑点归因 — 执行指令 CRUD"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict
from .connection import _get_conn, logger


# ══════════════════════════════════════════════════════════
#  V26.0: OMS 滑点归因 — 执行指令 CRUD
# ══════════════════════════════════════════════════════════

def create_execution_order(order: dict) -> str:
    """创建执行指令, 返回 order_id (UUID)"""
    import uuid
    order_id = order.get("order_id") or str(uuid.uuid4())[:12]
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO execution_orders
           (order_id, order_date, ts_code, name, side,
            decision_time, decision_price, decision_regime, decision_jcs,
            target_amount, target_position_pct,
            arrival_price, arrival_time,
            exec_price, exec_amount, exec_time, exec_source,
            parent_order_id, fill_seq,
            commission, tax, currency, fx_rate,
            status, notes, created_at, updated_at)
           VALUES (?,?,?,?,?, ?,?,?,?, ?,?, ?,?, ?,?,?,?, ?,?, ?,?,?,?, ?,?,?,?)
           ON CONFLICT(order_id) DO NOTHING""",
        (
            order_id,
            order.get("order_date", datetime.now().strftime("%Y-%m-%d")),
            order.get("ts_code", ""),
            order.get("name", ""),
            order.get("side", "buy"),
            order.get("decision_time"),
            order.get("decision_price"),
            order.get("decision_regime"),
            order.get("decision_jcs"),
            order.get("target_amount"),
            order.get("target_position_pct"),
            order.get("arrival_price"),
            order.get("arrival_time"),
            order.get("exec_price"),
            order.get("exec_amount"),
            order.get("exec_time"),
            order.get("exec_source", "manual"),
            order.get("parent_order_id"),
            order.get("fill_seq", 1),
            order.get("commission", 0),
            order.get("tax", 0),
            order.get("currency", "CNY"),
            order.get("fx_rate", 1.0),
            order.get("status", "pending"),
            order.get("notes"),
            now, now,
        ),
    )
    conn.commit()
    return order_id


def update_execution_fill(order_id: str, fill_data: dict):
    """更新执行指令的成交信息 + IS 归因结果"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    sets = ["updated_at = ?"]
    vals = [now]
    allowed = [
        "arrival_price", "arrival_time", "exec_price", "exec_amount",
        "exec_time", "exec_source", "status", "notes",
        "total_slippage_bps", "total_slippage_cny",
        "overnight_gap_bps", "intraday_drift_bps", "benchmark_close",
        "commission", "tax", "fx_rate", "fx_slippage_bps",
        "parent_order_id", "fill_seq",
    ]
    for key in allowed:
        if key in fill_data:
            sets.append(f"{key} = ?")
            vals.append(fill_data[key])
    vals.append(order_id)
    conn.execute(
        f"UPDATE execution_orders SET {', '.join(sets)} WHERE order_id = ?",
        vals,
    )
    conn.commit()


def get_execution_orders(days: int = 30, ts_code: Optional[str] = None,
                         status: Optional[str] = None) -> List[Dict]:
    """查询执行指令列表 (最新在前)"""
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sql = "SELECT * FROM execution_orders WHERE order_date >= ?"
    params: list = [cutoff]
    if ts_code:
        sql += " AND ts_code = ?"
        params.append(ts_code)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY order_date DESC, id DESC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_execution_order_by_id(order_id: str) -> Optional[Dict]:
    """按 order_id 查询单条指令"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM execution_orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    return dict(row) if row else None


def find_pending_order(ts_code: str, side: str, window_days: int = 3) -> Optional[Dict]:
    """查找指定标的的 pending 指令 (时间窗口内, 用于自动匹配)"""
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    row = conn.execute(
        """SELECT * FROM execution_orders
           WHERE ts_code = ? AND side = ? AND status = 'pending'
             AND order_date >= ?
           ORDER BY order_date DESC LIMIT 1""",
        (ts_code, side, cutoff),
    ).fetchone()
    return dict(row) if row else None


def get_today_decision_snapshot(date: str, ts_code: str = None) -> Optional[Dict]:
    """查询今日是否已有决策快照 (用于去重)"""
    conn = _get_conn()
    if ts_code:
        row = conn.execute(
            """SELECT * FROM execution_orders
               WHERE order_date = ? AND ts_code = ? AND status = 'pending'
               ORDER BY id DESC LIMIT 1""",
            (date, ts_code),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT * FROM execution_orders
               WHERE order_date = ? AND status = 'pending'
               ORDER BY id DESC LIMIT 1""",
            (date,),
        ).fetchone()
    return dict(row) if row else None


# ── 滑点日度汇总 ──

def upsert_slippage_daily(date: str, summary: dict):
    """写入/更新日度滑点汇总"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO slippage_daily
           (date, order_count, total_turnover, avg_slippage_bps,
            total_slippage_cny, overnight_gap_pct, intraday_drift_pct,
            worst_order_id, worst_slippage_bps, eqs_score, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(date) DO UPDATE SET
             order_count = excluded.order_count,
             total_turnover = excluded.total_turnover,
             avg_slippage_bps = excluded.avg_slippage_bps,
             total_slippage_cny = excluded.total_slippage_cny,
             overnight_gap_pct = excluded.overnight_gap_pct,
             intraday_drift_pct = excluded.intraday_drift_pct,
             worst_order_id = excluded.worst_order_id,
             worst_slippage_bps = excluded.worst_slippage_bps,
             eqs_score = excluded.eqs_score""",
        (
            date,
            summary.get("order_count", 0),
            summary.get("total_turnover", 0),
            summary.get("avg_slippage_bps", 0),
            summary.get("total_slippage_cny", 0),
            summary.get("overnight_gap_pct", 0),
            summary.get("intraday_drift_pct", 0),
            summary.get("worst_order_id"),
            summary.get("worst_slippage_bps"),
            summary.get("eqs_score"),
            now,
        ),
    )
    conn.commit()


def get_slippage_history(days: int = 30) -> List[Dict]:
    """获取滑点日度历史 (日期正序)"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM slippage_daily ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_slippage_stats() -> Dict:
    """滑点统计摘要 (供面板总览卡片)"""
    conn = _get_conn()
    # 近30日汇总
    cutoff_30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    r30 = conn.execute(
        """SELECT COUNT(*) as days, SUM(order_count) as orders,
              SUM(total_turnover) as turnover,
              SUM(total_slippage_cny) as total_cost,
              AVG(avg_slippage_bps) as avg_bps
           FROM slippage_daily WHERE date >= ?""",
        (cutoff_30,),
    ).fetchone()
    # 近7日汇总 (用于趋势)
    cutoff_7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    r7 = conn.execute(
        """SELECT AVG(avg_slippage_bps) as avg_bps_7d,
              AVG(eqs_score) as avg_eqs_7d
           FROM slippage_daily WHERE date >= ?""",
        (cutoff_7,),
    ).fetchone()
    # 历史总计
    total = conn.execute(
        "SELECT SUM(total_slippage_cny) as lifetime_cost, COUNT(*) as total_days "
        "FROM slippage_daily"
    ).fetchone()
    return {
        "period_30d": {
            "days": r30["days"] or 0,
            "orders": r30["orders"] or 0,
            "turnover": round(r30["turnover"] or 0, 2),
            "total_cost": round(r30["total_cost"] or 0, 2),
            "avg_bps": round(r30["avg_bps"] or 0, 2),
        },
        "period_7d": {
            "avg_bps": round(r7["avg_bps_7d"] or 0, 2),
            "avg_eqs": round(r7["avg_eqs_7d"] or 0, 1),
        },
        "lifetime": {
            "total_cost": round(total["lifetime_cost"] or 0, 2),
            "total_days": total["total_days"] or 0,
        },
    }


def get_execution_order_count() -> int:
    """执行指令总数"""
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0]
