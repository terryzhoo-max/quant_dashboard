"""
AlphaCore V22.0 · 策略漂移监控 (Strategy Drift Monitor)
==========================================================
检测策略信号是否在持续退化, 预防"无声失效"。

检测维度:
  1. 准确率漂移: 最近 20 次 vs 历史基准
  2. 市场环境偏移: 当前 AIAE regime 在训练集的覆盖度
  3. JCS 趋势: JCS 是否在系统性下降
  4. 矛盾趋势: 矛盾计数是否在上升

数据源: decision_log (SQLite) + 当前快照
"""

from datetime import datetime, timedelta
from typing import Optional
from services.logger import get_logger

logger = get_logger("ac.drift")


def _get_decision_history(days: int = 90):
    """从 SQLite 获取历史决策记录"""
    from services import db as ac_db
    return ac_db.get_decision_history(days)


def check_accuracy_drift() -> dict:
    """
    检测信号准确率漂移。

    比较最近 20 次信号的准确率 vs 全部历史基准。
    漂移 > 5%  → warning
    漂移 > 10% → critical
    """
    from services import db as ac_db
    stats = ac_db.get_accuracy_stats()

    total_acc = stats.get("accuracy_pct")
    recent_acc = stats.get("recent_10_accuracy")
    total_decisions = stats.get("total_decisions", 0)

    if total_decisions < 15:
        return {
            "status": "insufficient_data",
            "label": "数据积累中",
            "detail": f"仅 {total_decisions} 次决策记录, 需 ≥ 15 次方可评估漂移",
            "total_accuracy": total_acc,
            "recent_accuracy": recent_acc,
            "drift_pct": None,
        }

    drift = round((total_acc - recent_acc), 1) if total_acc is not None and recent_acc is not None else None

    if drift is None:
        return {"status": "ok", "label": "无数据", "detail": "准确率数据不完整", "drift_pct": None}

    if drift > 10:
        return {
            "status": "critical",
            "label": f"严重退化 ({drift:.0f}%)",
            "detail": f"近10次准确率 {recent_acc}% vs 历史 {total_acc}%, 信号可靠性显著下降。建议检查市场环境是否发生结构性变化。",
            "total_accuracy": total_acc,
            "recent_accuracy": recent_acc,
            "drift_pct": drift,
        }
    elif drift > 5:
        return {
            "status": "warning",
            "label": f"轻度退化 ({drift:.0f}%)",
            "detail": f"近10次准确率 {recent_acc}% vs 历史 {total_acc}%。继续观察, 如持续恶化需审查策略参数。",
            "total_accuracy": total_acc,
            "recent_accuracy": recent_acc,
            "drift_pct": drift,
        }
    else:
        return {
            "status": "ok",
            "label": f"稳定 (±{abs(drift):.0f}%)",
            "detail": f"近10次准确率 {recent_acc}% 与历史 {total_acc}% 一致, 信号质量稳定。",
            "total_accuracy": total_acc,
            "recent_accuracy": recent_acc,
            "drift_pct": drift,
        }


def check_regime_shift() -> dict:
    """
    检测当前市场环境是否偏离历史训练分布。

    比较当前 AIAE regime 在历史决策记录中的频率。
    如果当前 regime 在历史中出现 < 10%, 说明系统在"陌生环境"中运行。
    """
    history = _get_decision_history(180)

    if len(history) < 30:
        return {"status": "insufficient_data", "label": "数据积累中"}

    # 统计各 regime 的历史频率
    regime_counts = {}
    for h in history:
        r = h.get("aiae_regime")
        if r is not None:
            regime_counts[int(r)] = regime_counts.get(int(r), 0) + 1
    total = sum(regime_counts.values())

    # 获取当前 regime
    from dashboard_modules.decision_engine import _build_snapshot_from_cache
    snapshot = _build_snapshot_from_cache()
    current_regime = snapshot.get("aiae_regime", 3)

    current_freq = regime_counts.get(current_regime, 0) / max(total, 1) * 100

    if current_freq < 5:
        return {
            "status": "warning",
            "label": f"陌生环境 (R{current_regime}, 历史{current_freq:.0f}%)",
            "detail": f"当前 AIAE R{current_regime} 在过去 180 天仅出现 {current_freq:.0f}% 的时间。系统在此环境中缺乏足够训练样本, 信号可靠性可能降低。",
            "current_regime": current_regime,
            "coverage_pct": round(current_freq, 1),
            "regime_distribution": {str(k): round(v / total * 100, 1) for k, v in sorted(regime_counts.items())},
        }
    elif current_freq < 15:
        return {
            "status": "info",
            "label": f"低覆盖环境 (R{current_regime}, {current_freq:.0f}%)",
            "detail": f"当前 regime 在历史中覆盖度偏低 ({current_freq:.0f}%), 对策略信号保持审慎。",
            "current_regime": current_regime,
            "coverage_pct": round(current_freq, 1),
            "regime_distribution": {str(k): round(v / total * 100, 1) for k, v in sorted(regime_counts.items())},
        }
    else:
        return {
            "status": "ok",
            "label": f"熟悉环境 (R{current_regime}, {current_freq:.0f}%)",
            "detail": f"当前 AIAE regime 在历史中覆盖充分, 策略在熟悉区间运行。",
            "current_regime": current_regime,
            "coverage_pct": round(current_freq, 1),
            "regime_distribution": {str(k): round(v / total * 100, 1) for k, v in sorted(regime_counts.items())},
        }


def check_jcs_trend() -> dict:
    """
    检测 JCS 是否在系统性下降 (30 日线性趋势)。
    """
    history = _get_decision_history(30)

    if len(history) < 10:
        return {"status": "insufficient_data", "label": "数据积累中"}

    # 取最近 30 天的 JCS 值
    jcs_values = []
    for h in history[-30:]:
        j = h.get("jcs_score")
        if j is not None:
            jcs_values.append(float(j))

    if len(jcs_values) < 10:
        return {"status": "insufficient_data", "label": "JCS 数据不足"}

    # P2-3: 用中位数替代均值, 增强噪声鲁棒性 (单日异常不会触发 critical)
    n = len(jcs_values)
    first_half = sorted(jcs_values[:n // 2])
    second_half = sorted(jcs_values[n // 2:])
    median_first = first_half[len(first_half) // 2]
    median_second = second_half[len(second_half) // 2]
    trend = round(median_second - median_first, 1)
    current = jcs_values[-1]

    if trend < -10:
        return {
            "status": "critical",
            "label": f"JCS 急降 ({trend:+.0f})",
            "detail": f"JCS 30日中位数从 {median_first:.0f} 降至 {median_second:.0f}, 当前 {current:.0f}。信号方向在持续恶化, 建议全面防御。",
            "current_jcs": current,
            "trend_30d": trend,
        }
    elif trend < -5:
        return {
            "status": "warning",
            "label": f"JCS 下降 ({trend:+.0f})",
            "detail": f"JCS 呈下降趋势 (30日中位数 {median_first:.0f}→{median_second:.0f})。关注信号是否持续弱化。",
            "current_jcs": current,
            "trend_30d": trend,
        }
    else:
        direction = "上升" if trend > 0 else "平稳"
        return {
            "status": "ok",
            "label": f"JCS {direction} ({trend:+.0f})",
            "detail": f"JCS 30日趋势稳定, 当前 {current:.0f}。",
            "current_jcs": current,
            "trend_30d": trend,
        }


def check_conflict_trend() -> dict:
    """
    检测矛盾信号是否在增多。
    """
    history = _get_decision_history(30)

    if len(history) < 10:
        return {"status": "insufficient_data", "label": "数据积累中"}

    conflicts = [h.get("conflict_count", 0) or 0 for h in history[-30:]]
    n = len(conflicts)
    first_half = sum(conflicts[:n // 2]) / (n // 2)
    second_half = sum(conflicts[n // 2:]) / (n - n // 2)
    trend = round(second_half - first_half, 1)
    current = conflicts[-1]

    if trend > 1.0:
        return {
            "status": "warning",
            "label": f"矛盾增多 ({trend:+.1f})",
            "detail": f"30日平均矛盾从 {first_half:.1f} 增至 {second_half:.1f}, 引擎分歧加大。可能需要重新审视各引擎权重。",
            "current_conflicts": current,
            "trend_30d": trend,
        }
    else:
        return {
            "status": "ok",
            "label": "矛盾稳定",
            "detail": f"30日平均矛盾 {second_half:.1f}, 无显著上升趋势。",
            "current_conflicts": current,
            "trend_30d": trend,
        }


def get_drift_status() -> dict:
    """
    一站式漂移状态检查。

    返回:
    {
        "status": "ok" / "warning" / "critical",
        "summary": str,
        "checks": {
            "accuracy": {...},
            "regime_shift": {...},
            "jcs_trend": {...},
            "conflict_trend": {...},
        }
    }
    """
    checks = {
        "accuracy": check_accuracy_drift(),
        "regime_shift": check_regime_shift(),
        "jcs_trend": check_jcs_trend(),
        "conflict_trend": check_conflict_trend(),
    }

    # 综合判定
    statuses = [c.get("status", "ok") for c in checks.values()]
    if "critical" in statuses:
        overall = "critical"
        summary = "🔴 检测到严重漂移, 建议审查策略参数并降低仓位"
    elif "warning" in statuses:
        overall = "warning"
        warning_checks = [k for k, v in checks.items() if v.get("status") == "warning"]
        summary = f"🟡 {len(warning_checks)} 项警告 ({', '.join(warning_checks[:2])}), 持续监控"
    else:
        overall = "ok"
        summary = "🟢 策略运行稳定, 未检测到显著漂移"

    return {
        "status": overall,
        "summary": summary,
        "checks": checks,
        "checked_at": datetime.now().isoformat(),
    }
