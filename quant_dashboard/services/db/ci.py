"""P1-3: CI/CD 管道 CRUD"""

import json
from typing import Optional, List, Dict
from .connection import _get_conn, logger


# ══════════════════════════════════════════════════════════
#  P1-3: CI/CD 管道 CRUD
# ══════════════════════════════════════════════════════════

def save_ci_run(run: dict) -> int:
    """保存一条 CI 运行记录"""
    conn = _get_conn()
    cur = conn.execute(
        """INSERT OR REPLACE INTO ci_runs
           (run_id, strategy, regime, status, old_params, new_params,
            old_metrics, new_metrics, quality_gate, diff_summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run["run_id"], run["strategy"], run.get("regime"),
            run["status"],
            json.dumps(run.get("old_params", {}), ensure_ascii=False),
            json.dumps(run.get("new_params", {}), ensure_ascii=False),
            json.dumps(run.get("old_metrics", {}), ensure_ascii=False),
            json.dumps(run.get("new_metrics", {}), ensure_ascii=False),
            json.dumps(run.get("quality_gate", []), ensure_ascii=False),
            run.get("diff_summary", ""),
        )
    )
    conn.commit()
    return cur.lastrowid


def get_ci_history(strategy: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """查询 CI 运行历史"""
    conn = _get_conn()
    if strategy:
        rows = conn.execute(
            "SELECT * FROM ci_runs WHERE strategy = ? ORDER BY created_at DESC LIMIT ?",
            (strategy, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ci_runs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        for k in ("old_params", "new_params", "old_metrics", "new_metrics", "quality_gate"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (json.JSONDecodeError, TypeError):
                    pass
        results.append(d)
    return results


def get_ci_latest(strategy: str) -> Optional[Dict]:
    """获取某策略最近一次 CI 结果"""
    results = get_ci_history(strategy=strategy, limit=1)
    return results[0] if results else None


def update_ci_status(run_id: str, new_status: str) -> bool:
    """更新 CI 运行状态 (REVIEW → ACCEPT/REJECT)"""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE ci_runs SET status = ? WHERE run_id = ?",
        (new_status, run_id)
    )
    conn.commit()
    return cur.rowcount > 0
