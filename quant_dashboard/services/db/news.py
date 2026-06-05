"""P2-C: NLP 情报层 CRUD"""

import json
from typing import Optional, List, Dict
from .connection import _get_conn, logger


# ══════════════════════════════════════════════════════════
#  P2-C: NLP 情报层 CRUD
# ══════════════════════════════════════════════════════════

def save_news_event(event: dict) -> int:
    """保存一条 NLP 提取的事件"""
    conn = _get_conn()
    cur = conn.execute(
        """INSERT OR IGNORE INTO news_events
           (event_id, title, category, impact_score, summary,
            affected_assets, scenario_id, source, raw_text)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event["event_id"], event["title"], event["category"],
            event.get("impact_score", 0),
            event.get("summary", ""),
            json.dumps(event.get("affected_assets", []), ensure_ascii=False),
            event.get("scenario_id"),
            event.get("source", ""),
            event.get("raw_text", ""),
        )
    )
    conn.commit()
    return cur.lastrowid


def get_news_events(category: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """查询事件历史"""
    conn = _get_conn()
    if category:
        rows = conn.execute(
            "SELECT * FROM news_events WHERE category = ? ORDER BY created_at DESC LIMIT ?",
            (category, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM news_events ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        if d.get("affected_assets"):
            try:
                d["affected_assets"] = json.loads(d["affected_assets"])
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(d)
    return results
