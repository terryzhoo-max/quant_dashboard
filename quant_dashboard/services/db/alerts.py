"""V21.0 日报缓存 + V21.2 信号预警 + V22.0 审计日志"""

from datetime import datetime
from typing import Optional, List, Dict
from .connection import _get_conn, logger


# ══════════════════════════════════════════════════════════
#  V21.0: 日报缓存 (投委会报告持久化)
# ══════════════════════════════════════════════════════════

def _ensure_daily_reports_table():
    """幂等建表: daily_reports (V21.0 日报缓存)"""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            markdown TEXT NOT NULL,
            summary_json TEXT,
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(date)")
    conn.commit()


def save_daily_report(date: str, markdown: str, summary: dict = None):
    """保存日报 Markdown (按 date UNIQUE 键, 幂等)"""
    import json as _json
    _ensure_daily_reports_table()
    conn = _get_conn()
    now = datetime.now().isoformat()
    summary_str = _json.dumps(summary, ensure_ascii=False) if summary else None
    conn.execute(
        """INSERT INTO daily_reports (date, markdown, summary_json, generated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             markdown = excluded.markdown,
             summary_json = excluded.summary_json,
             generated_at = excluded.generated_at""",
        (date, markdown, summary_str, now),
    )
    conn.commit()


def get_daily_report(date: str) -> Optional[Dict]:
    """获取指定日期的日报"""
    _ensure_daily_reports_table()
    conn = _get_conn()
    row = conn.execute(
        "SELECT date, markdown, summary_json, generated_at FROM daily_reports WHERE date = ?",
        (date,),
    ).fetchone()
    return dict(row) if row else None


# ═══════════════════════════════════════════════════
#  V21.2: 信号预警持久化
# ═══════════════════════════════════════════════════

def save_alert(rule_id: str, severity: str, title: str, detail: str, value: float):
    """写入预警记录"""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO signal_alerts (rule_id, severity, title, detail, value, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (rule_id, severity, title, detail, value, datetime.now().isoformat()),
    )
    conn.commit()


def get_recent_alerts(limit: int = 20) -> List[Dict]:
    """获取最近预警列表"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, rule_id, severity, title, detail, value, created_at, acknowledged "
        "FROM signal_alerts ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def acknowledge_alert(alert_id: int):
    """标记预警已读"""
    conn = _get_conn()
    conn.execute("UPDATE signal_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
    conn.commit()


def get_last_alert_time(rule_id: str) -> Optional[str]:
    """获取某规则最近一次触发的时间 (用于 cooldown 判断)"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT created_at FROM signal_alerts WHERE rule_id = ? ORDER BY created_at DESC LIMIT 1",
        (rule_id,),
    ).fetchone()
    return row["created_at"] if row else None


def get_unread_alert_count() -> int:
    """未读预警数量 (铃铛 badge)"""
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) as c FROM signal_alerts WHERE acknowledged = 0").fetchone()
    return row["c"] if row else 0


def ack_all_alerts() -> int:
    """P1-2: 一键全部已读 (事务安全版本), 返回受影响行数"""
    conn = _get_conn()
    cur = conn.execute("UPDATE signal_alerts SET acknowledged = 1 WHERE acknowledged = 0")
    conn.commit()
    return cur.rowcount


# ══════════════════════════════════════════════════════════
#  V22.0: 审计日志持久化
# ══════════════════════════════════════════════════════════

def save_audit_log(report: dict):
    """持久化审计报告到 audit_log 表"""
    conn = _get_conn()
    modules = report.get("modules", {})
    dq = modules.get("data_quality", {}).get("score", 0)
    sh = modules.get("strategy_health", {}).get("score", 0)
    rc = modules.get("risk_control", {}).get("score", 0)
    fd = modules.get("factor_decay", {}).get("score", 0)
    ss = modules.get("system_status", {}).get("score", 0)

    conn.execute(
        """INSERT INTO audit_log
           (audit_time, trust_score, trust_grade, total_checks,
            pass_count, warn_count, fail_count, elapsed_seconds,
            data_quality_score, strategy_health_score, risk_control_score,
            factor_decay_score, system_status_score, summary_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            report.get("audit_time", ""),
            report.get("trust_score", 0),
            report.get("trust_grade", "D"),
            report.get("total_checks", 0),
            report.get("pass_count", 0),
            report.get("warn_count", 0),
            report.get("fail_count", 0),
            report.get("elapsed_seconds", 0),
            dq, sh, rc, fd, ss,
            None,  # summary_json placeholder
        )
    )
    conn.commit()

    # 保留最近 90 天
    conn.execute("DELETE FROM audit_log WHERE created_at < datetime('now', '-90 days')")
    conn.commit()


def get_audit_history(limit: int = 10) -> list:
    """获取最近 N 次审计记录"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT audit_time, trust_score, trust_grade, fail_count, warn_count, "
        "pass_count, elapsed_seconds, total_checks "
        "FROM audit_log ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
