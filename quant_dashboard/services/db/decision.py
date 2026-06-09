"""决策日志 (V16.0: 科学辅助决策模块)"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict
from .connection import _get_conn, logger


# ══════════════════════════════════════════════════════════
#  决策日志 (V16.0: 科学辅助决策模块)
# ══════════════════════════════════════════════════════════

def upsert_decision_log(data: dict):
    """插入或更新每日决策快照 (按 date UNIQUE 键, 幂等) — V25.3: 含影子模式"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO decision_log
           (date, aiae_regime, aiae_v1, erp_score, erp_val, vix_val, mr_regime,
            hub_composite, jcs_score, jcs_level, suggested_position,
            conflict_count, degraded_modules, recorded_at,
            jcs_v4_score, jcs_v6_score, jcs_shadow_delta, gold_signal, bond_signal,
            jcs_v26_score, delta_v26)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             aiae_regime = excluded.aiae_regime,
             aiae_v1 = excluded.aiae_v1,
             erp_score = excluded.erp_score,
             erp_val = excluded.erp_val,
             vix_val = excluded.vix_val,
             mr_regime = excluded.mr_regime,
             hub_composite = excluded.hub_composite,
             jcs_score = excluded.jcs_score,
             jcs_level = excluded.jcs_level,
             suggested_position = excluded.suggested_position,
             conflict_count = excluded.conflict_count,
             degraded_modules = excluded.degraded_modules,
             recorded_at = excluded.recorded_at,
             jcs_v4_score = excluded.jcs_v4_score,
             jcs_v6_score = excluded.jcs_v6_score,
             jcs_shadow_delta = excluded.jcs_shadow_delta,
             gold_signal = excluded.gold_signal,
             bond_signal = excluded.bond_signal,
             jcs_v26_score = excluded.jcs_v26_score,
             delta_v26 = excluded.delta_v26""",
        (
            data.get("date"),
            data.get("aiae_regime"),
            data.get("aiae_v1"),
            data.get("erp_score"),
            data.get("erp_val"),
            data.get("vix_val"),
            data.get("mr_regime"),
            data.get("hub_composite"),
            data.get("jcs_score"),
            data.get("jcs_level"),
            data.get("suggested_position"),
            data.get("conflict_count", 0),
            data.get("degraded_modules", ""),
            now,
            data.get("jcs_v4_score"),
            data.get("jcs_v6_score"),
            data.get("jcs_shadow_delta"),
            data.get("gold_signal"),
            data.get("bond_signal"),
            data.get("jcs_v26_score"),
            data.get("delta_v26"),
        ),
    )
    conn.commit()


def get_decision_history(days: int = 30) -> List[Dict]:
    """获取最近 N 天的决策日志 (按日期正序)"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM decision_log ORDER BY date DESC LIMIT ?", (days,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def cleanup_old_decisions(keep_days: int = 365):
    """清理超过 keep_days 的旧决策记录"""
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    deleted = conn.execute(
        "DELETE FROM decision_log WHERE date < ?", (cutoff,)
    ).rowcount
    conn.commit()
    if deleted > 0:
        logger.info("清理旧决策记录: 删除 %d 条 (保留 %d 天)", deleted, keep_days)


def backfill_accuracy(date: str, market_return_5d: float):
    """V25.2: 回填 T+5 市场收益率并判断信号正确性
    
    判定基准 (与前端说明一致):
      JCS >= 50 + 市场上涨 → ✅ 正确
      JCS <  50 + 市场下跌 → ✅ 正确
      反向 → ❌ 错误
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT jcs_score FROM decision_log WHERE date = ?", (date,)
    ).fetchone()
    if not row:
        return
    jcs = row[0] if row[0] is not None else 50
    # 信号正确: JCS 方向 与 市场方向 一致
    if jcs >= 50:
        correct = 1 if market_return_5d > 0 else 0
    else:
        correct = 1 if market_return_5d < 0 else 0
    conn.execute(
        "UPDATE decision_log SET market_return_5d = ?, signal_correct = ? WHERE date = ?",
        (round(market_return_5d, 4), correct, date),
    )
    conn.commit()


def get_accuracy_stats() -> Dict:
    """V25.2: 计算信号准确率统计 (含趋势历史 + 连胜/连败)"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT signal_correct, COUNT(*) as cnt FROM decision_log "
        "WHERE signal_correct IS NOT NULL AND signal_correct >= 0 "
        "GROUP BY signal_correct"
    ).fetchall()
    total, correct = 0, 0
    for r in rows:
        total += r[1]
        if r[0] == 1:
            correct = r[1]
    accuracy = round(correct / total * 100, 1) if total > 0 else None
    # 近10次准确率
    recent = conn.execute(
        "SELECT signal_correct FROM decision_log "
        "WHERE signal_correct IS NOT NULL AND signal_correct >= 0 "
        "ORDER BY date DESC LIMIT 10"
    ).fetchall()
    recent_correct = sum(1 for r in recent if r[0] == 1)
    recent_total = len(recent)
    recent_accuracy = round(recent_correct / recent_total * 100, 1) if recent_total > 0 else None
    # V25.2: 连胜/连败计算
    streak, streak_type = 0, "none"
    if recent:
        first_val = recent[0][0]
        streak_type = "win" if first_val == 1 else "lose"
        for r in recent:
            if r[0] == first_val:
                streak += 1
            else:
                break
    # V25.2: 每日准确率历史 (供趋势图)
    history = conn.execute(
        "SELECT date, jcs_score, signal_correct, market_return_5d FROM decision_log "
        "WHERE signal_correct IS NOT NULL AND signal_correct >= 0 "
        "ORDER BY date ASC LIMIT 60"
    ).fetchall()
    history_list = [
        {"date": r[0], "jcs": r[1], "correct": r[2], "ret5d": r[3]}
        for r in history
    ]
    return {
        "total_decisions": total,
        "correct_decisions": correct,
        "accuracy_pct": accuracy,
        "recent_10_accuracy": recent_accuracy,
        "recent_10_total": recent_total,
        "has_data": total >= 1,
        "maturity": "mature" if total >= 15 else ("growing" if total >= 5 else "initial"),
        "current_streak": streak,
        "streak_type": streak_type,
        "history": history_list,
        "recent_signals": [r[0] for r in reversed(recent)] if recent else [],
    }



def get_accuracy_by_jcs_level() -> Dict:
    """P3-C: 按 JCS 置信度级别分组的准确率"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT jcs_level, signal_correct, COUNT(*) as cnt "
        "FROM decision_log "
        "WHERE signal_correct IS NOT NULL AND signal_correct >= 0 "
        "AND jcs_level IS NOT NULL "
        "GROUP BY jcs_level, signal_correct"
    ).fetchall()

    levels = {}
    for level, correct, cnt in rows:
        if level not in levels:
            levels[level] = {"total": 0, "correct": 0}
        levels[level]["total"] += cnt
        if correct == 1:
            levels[level]["correct"] += cnt

    result = {}
    for level in ["high", "medium", "low"]:
        data = levels.get(level, {"total": 0, "correct": 0})
        result[level] = {
            "total": data["total"],
            "correct": data["correct"],
            "accuracy": round(data["correct"] / data["total"] * 100, 1) if data["total"] > 0 else None,
        }
    return result


def get_accuracy_by_regime() -> Dict:
    """P3-C: 按 AIAE Regime 分组的准确率"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT aiae_regime, signal_correct, COUNT(*) as cnt "
        "FROM decision_log "
        "WHERE signal_correct IS NOT NULL AND signal_correct >= 0 "
        "AND aiae_regime IS NOT NULL "
        "GROUP BY aiae_regime, signal_correct"
    ).fetchall()

    regimes = {}
    regime_labels = {1: "Ⅰ 极冷", 2: "Ⅱ 偏冷", 3: "Ⅲ 中性", 4: "Ⅳ 偏热", 5: "Ⅴ 极热"}
    for regime, correct, cnt in rows:
        if regime not in regimes:
            regimes[regime] = {"total": 0, "correct": 0}
        regimes[regime]["total"] += cnt
        if correct == 1:
            regimes[regime]["correct"] += cnt

    result = {}
    for r in range(1, 6):
        data = regimes.get(r, {"total": 0, "correct": 0})
        result[str(r)] = {
            "regime": r,
            "label": regime_labels.get(r, f"R{r}"),
            "total": data["total"],
            "correct": data["correct"],
            "accuracy": round(data["correct"] / data["total"] * 100, 1) if data["total"] > 0 else None,
        }
    return result


def get_accuracy_rolling(window: int = 30) -> Dict:
    """P3-C: 滚动窗口准确率 (30/60/90日)"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT date, jcs_score, jcs_level, signal_correct, market_return_5d, "
        "aiae_regime, jcs_v4_score, jcs_v6_score, jcs_shadow_delta "
        "FROM decision_log "
        "WHERE signal_correct IS NOT NULL AND signal_correct >= 0 "
        "ORDER BY date DESC LIMIT ?", (window,)
    ).fetchall()

    if not rows:
        return {"window": window, "total": 0, "accuracy": None, "data": []}

    total = len(rows)
    correct = sum(1 for r in rows if r[3] == 1)
    accuracy = round(correct / total * 100, 1) if total > 0 else None

    data = [{
        "date": r[0], "jcs": r[1], "level": r[2], "correct": r[3],
        "ret5d": r[4], "regime": r[5],
        "v4_score": r[6], "v6_score": r[7], "shadow_delta": r[8],
    } for r in rows]

    return {
        "window": window,
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "data": data,
    }


def get_shadow_comparison() -> Dict:
    """P3-C: V4 vs V6 影子模式对比分析"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT jcs_v4_score, jcs_v6_score, jcs_shadow_delta, signal_correct "
        "FROM decision_log "
        "WHERE jcs_v4_score IS NOT NULL AND jcs_v6_score IS NOT NULL "
        "AND signal_correct IS NOT NULL AND signal_correct >= 0 "
        "ORDER BY date DESC LIMIT 60"
    ).fetchall()

    if not rows:
        return {"has_data": False, "total": 0}

    total = len(rows)
    # V4 准确率
    v4_correct = sum(1 for r in rows if (r[0] >= 50 and r[3] == 1) or (r[0] < 50 and r[3] == 0))
    # V6 准确率
    v6_correct = sum(1 for r in rows if (r[1] >= 50 and r[3] == 1) or (r[1] < 50 and r[3] == 0))

    avg_delta = round(sum(r[2] for r in rows if r[2]) / total, 2) if total > 0 else 0

    return {
        "has_data": True,
        "total": total,
        "v4_accuracy": round(v4_correct / total * 100, 1) if total > 0 else None,
        "v6_accuracy": round(v6_correct / total * 100, 1) if total > 0 else None,
        "avg_delta": avg_delta,
        "v6_better": v6_correct > v4_correct,
        "recommendation": (
            "V6 表现优于 V4，建议正式切换" if v6_correct > v4_correct + 2
            else "V4/V6 表现接近，继续观察" if abs(v6_correct - v4_correct) <= 2
            else "V4 表现优于 V6，维持现有权重"
        ),
    }


def get_calendar_data(year: int = None, month: int = None) -> List[Dict]:
    """获取月历数据 (每日 JCS + 仓位 + 矛盾数)"""
    conn = _get_conn()
    if year and month:
        prefix = f"{year:04d}-{month:02d}"
        rows = conn.execute(
            "SELECT date, jcs_score, jcs_level, suggested_position, conflict_count, "
            "aiae_regime, market_return_5d, signal_correct "
            "FROM decision_log WHERE date LIKE ? ORDER BY date",
            (prefix + "%",)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT date, jcs_score, jcs_level, suggested_position, conflict_count, "
            "aiae_regime, market_return_5d, signal_correct "
            "FROM decision_log ORDER BY date DESC LIMIT 62"
        ).fetchall()
    return [dict(r) for r in rows]
