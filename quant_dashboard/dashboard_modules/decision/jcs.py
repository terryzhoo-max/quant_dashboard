"""
AlphaCore · 联合置信度引擎 (JCS) — V17.0 加法模型
=====================================================
从 decision_engine.py 拆分 (P2-A)

公开 API:
  - compute_jcs(snapshot) → {score, level, label, directions, ...}
  - _JCS_WEIGHTS: dict
  - _recalc_vix_score(vix_val) → float
  - _recalc_hub_composite(snapshot) → float
  - _REGIME_CN_MAP: dict
  - _REGIME_CAP_MAP: dict
"""

from dashboard_modules.decision.conflicts import (
    _signal_direction, compute_conflict_matrix,
)

# 引擎权重 (用于方向一致性加权)
_JCS_WEIGHTS = {
    "aiae": 0.35,   # V19.1: 主锚降权 (0.45→0.35), 月频滞后指标不应过半
    "erp": 0.25,    # 估值锚不变
    "vix": 0.20,    # V19.1: 提权 (0.15→0.20), 唯一实时情绪指标
    "mr": 0.20,     # V19.1: 提权 (0.15→0.20), 唯一价格结构指标
}

# AIAE Regime → Cap 映射 (从 aiae_params.POSITION_MATRIX 动态读取, 取 erp_2_4 行)
try:
    from aiae_params import POSITION_MATRIX as _PM
    _REGIME_CAP_MAP = {i+1: _PM["erp_2_4"][i] for i in range(5)}
except ImportError:
    _REGIME_CAP_MAP = {1: 85, 2: 70, 3: 50, 4: 25, 5: 5}  # fallback

_REGIME_CN_MAP = {1: "极度恐慌", 2: "低配置区", 3: "中性均衡", 4: "偏热区域", 5: "极度过热"}


def _recalc_vix_score(vix_val: float) -> float:
    """VIX → 归一化分数 (0-100, 越低越好)"""
    return max(0, min(100, (40 - vix_val) / 40 * 100))


def _recalc_hub_composite(snapshot: dict) -> float:
    """根据 snapshot 各读数重新计算 Hub 复合分"""
    aiae_r = snapshot.get("aiae_regime", 3)
    erp_s = snapshot.get("erp_score", 50)
    vix_v = snapshot.get("vix_val", 20)
    vix_s = _recalc_vix_score(vix_v)

    # 简化复合: AIAE(反) 40% + ERP 30% + VIX(正) 30%
    aiae_score = max(0, min(100, (5 - aiae_r) / 4 * 100))
    return round(aiae_score * 0.4 + erp_s * 0.3 + vix_s * 0.3, 1)


def compute_jcs(snapshot: dict) -> dict:
    """
    V17.0 联合置信度引擎 (加法模型, 替代旧版乘法连乘):

    JCS = base_agreement (60%) + data_health (20%) + consensus_bonus (20%)

    旧版问题: agreement × freshness × health 三乘数连乘导致分值被压缩到 30-50 区间,
              "中置信" 成为常态, 丧失信号区分价值.

    返回:
    {
        "score": 0-100,
        "level": "high" / "medium" / "low",
        "label": str,
        "directions": {engine: direction},
        "agreement_pct": float,
        "data_health": float,
        "consensus_bonus": float,
        "conflict_count": int,
    }
    """
    directions = _signal_direction(snapshot)
    dir_vals = list(directions.values())  # [+1, 0, -1, ...]

    # ── 1. Base Agreement (占 60 分) ──
    # 有明确方向的引擎数量 (非中性)
    active_count = sum(1 for d in dir_vals if d != 0)
    # 所有有方向引擎的方向是否一致 (全+1 或全-1)
    active_dirs = [d for d in dir_vals if d != 0]
    if active_count == 0:
        # 全部中性 → 无信号, 基础分 30 (不应高也不应低)
        base_agreement = 30.0
    elif all(d == active_dirs[0] for d in active_dirs):
        # 所有有方向的引擎一致
        # 4引擎全一致=60, 3一致1中性=52, 2一致2中性=42
        base_agreement = 30.0 + active_count * 7.5
    else:
        # 存在方向对冲: 按加权方向计算衰减
        weighted_sum = sum(
            directions[k] * _JCS_WEIGHTS[k] for k in _JCS_WEIGHTS
        )
        max_weight = sum(_JCS_WEIGHTS.values())
        agreement_ratio = abs(weighted_sum) / max_weight if max_weight > 0 else 0
        # 对冲越严重分越低: 完全对冲→10, 弱对冲→25
        base_agreement = 10.0 + agreement_ratio * 20.0

    # V19.1: 中性距离加分 — 中性引擎的读数仍含信息量
    # VIX=16 (安全) vs VIX=24 (临界) 不应得分相同
    distance_bonus = 0.0
    if directions["vix"] == 0:
        vix_v = snapshot.get("vix_val", 20)
        # VIX 离恐慌线 (25) 越远越安全, 最多+2.5
        distance_bonus += max(0, (25 - vix_v) / 25) * 2.5
    if directions["erp"] == 0:
        erp_s = snapshot.get("erp_score", 50)
        # ERP 偏离中位 50 越远, 方向性越明确, 最多+2.5
        distance_bonus += abs(erp_s - 50) / 50 * 2.5
    base_agreement += min(distance_bonus, 5.0)  # 总距离分上限 5

    # ── 2. Data Health (占 20 分) ──
    stale_count = 0
    if snapshot.get("aiae_regime") is None:
        stale_count += 1
    if snapshot.get("erp_score") is None:
        stale_count += 1
    if snapshot.get("vix_val") is None:
        stale_count += 1
    if snapshot.get("mr_regime") is None:
        stale_count += 1

    degraded = snapshot.get("degraded_modules", [])
    if isinstance(degraded, str):
        degraded = [d.strip() for d in degraded.split(",") if d.strip()]
    degraded_count = len(degraded)

    # 每个缺失引擎扣 4 分, 每个降级模块扣 2 分
    data_health = max(0.0, 20.0 - stale_count * 4.0 - degraded_count * 2.0)

    # ── 3. Consensus Bonus (占 20 分) ──
    # 全方向一致且无中性 → +20; 有中性但无矛盾 → +10; 其他 → 0
    if active_count == 4 and all(d == active_dirs[0] for d in active_dirs):
        consensus_bonus = 20.0
    elif active_count >= 2 and all(d == active_dirs[0] for d in active_dirs):
        consensus_bonus = 10.0
    else:
        consensus_bonus = 0.0

    # ── 合成 JCS ──
    raw_jcs = base_agreement + data_health + consensus_bonus

    # ── 矛盾惩罚 (减法, 不再用乘法) ──
    # V22.0 O1: 直接复用 compute_conflict_matrix 已计算好的
    #          conflict_count/has_severe, 避免重复过滤
    conflicts = compute_conflict_matrix(snapshot)
    penalty_count = conflicts["conflict_count"]
    has_severe = conflicts["has_severe"]

    if has_severe:
        raw_jcs -= 25.0  # 严重矛盾扣 25 分
    elif penalty_count > 0:
        raw_jcs -= penalty_count * 10.0  # 每个中度矛盾扣 10 分

    jcs = round(min(100, max(0, raw_jcs)), 1)

    # ── 分级 ──
    if jcs >= 70:
        level, label = "high", "🟢 高置信 — 多引擎方向一致"
    elif jcs >= 40:
        level, label = "medium", "🟡 中置信 — 存在分歧或部分降级"
    else:
        level, label = "low", "🔴 低置信 — 严重矛盾或数据缺失，建议观望"

    return {
        "score": jcs,
        "level": level,
        "label": label,
        "directions": directions,
        "agreement_pct": min(100.0, round(base_agreement / 60.0 * 100, 1)),
        "data_health": round(data_health, 1),
        "consensus_bonus": round(consensus_bonus, 1),
        "conflict_count": conflicts["conflict_count"],
    }
