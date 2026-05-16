"""
AlphaCore · 联合置信度引擎 (JCS) — V25.3 六维加法模型
=====================================================
从 decision_engine.py 拆分 (P2-A), V25.3 扩展至6维

公开 API:
  - compute_jcs(snapshot) → {score, level, label, directions, ...}
  - _JCS_WEIGHTS: dict  (6维权重)
  - _recalc_vix_score(vix_val) → float
  - _recalc_hub_composite(snapshot) → float
  - _REGIME_CN_MAP: dict
  - _REGIME_CAP_MAP: dict

V25.3 变更:
  - 权重从 4 维扩展至 6 维 (gold 5% + bond 5%)
  - consensus_bonus 判定从 ==4 升级为 ==6
  - 新增 shadow mode: 并行计算新旧权重分数供对比
"""

from dashboard_modules.decision.conflicts import (
    _signal_direction, compute_conflict_matrix,
)

# ── V25.3: 6 维权重 (原4维各降 2.5pp, 给 gold + bond 各 5%) ──
_JCS_WEIGHTS = {
    "aiae": 0.325,  # V25.3: 0.35 → 0.325
    "erp": 0.225,   # V25.3: 0.25 → 0.225
    "vix": 0.175,   # V25.3: 0.20 → 0.175
    "mr": 0.175,    # V25.3: 0.20 → 0.175
    "gold": 0.05,   # V25.3 NEW: 黄金对冲信号
    "bond": 0.05,   # V25.3 NEW: 国债利率信号
}

# V25.3 影子模式: 旧4维权重 (用于并行对比)
_JCS_WEIGHTS_V4 = {
    "aiae": 0.35,
    "erp": 0.25,
    "vix": 0.20,
    "mr": 0.20,
}

# AIAE Regime → Cap 映射
try:
    from aiae_params import POSITION_MATRIX as _PM
    _REGIME_CAP_MAP = {i+1: _PM["erp_2_4"][i] for i in range(5)}
except ImportError:
    _REGIME_CAP_MAP = {1: 85, 2: 70, 3: 50, 4: 25, 5: 5}

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

    aiae_score = max(0, min(100, (5 - aiae_r) / 4 * 100))
    return round(aiae_score * 0.4 + erp_s * 0.3 + vix_s * 0.3, 1)


def _compute_jcs_with_weights(snapshot: dict, weights: dict, n_core: int = 4) -> dict:
    """
    JCS 计算核心 (可配权重版本, 供正式/影子模式复用)
    
    Args:
        snapshot: 系统快照
        weights: 引擎权重字典
        n_core: 核心引擎数量 (4=旧版, 6=新版), 影响 consensus_bonus
    
    Returns:
        JCS 结果字典
    """
    directions = _signal_direction(snapshot)
    
    # 只取当前权重中存在的引擎方向
    active_engines = list(weights.keys())
    dir_vals = [directions.get(k, 0) for k in active_engines]

    # ── 1. Base Agreement (占 60 分) ──
    active_count = sum(1 for d in dir_vals if d != 0)
    active_dirs = [d for d in dir_vals if d != 0]
    
    if active_count == 0:
        base_agreement = 30.0
    elif all(d == active_dirs[0] for d in active_dirs):
        # V25.3: 按比例缩放, 6引擎全一致 = 60, 4/6 = 50, etc.
        base_agreement = 30.0 + active_count * (30.0 / n_core)
    else:
        weighted_sum = sum(
            directions.get(k, 0) * weights[k] for k in weights
        )
        max_weight = sum(weights.values())
        agreement_ratio = abs(weighted_sum) / max_weight if max_weight > 0 else 0
        base_agreement = 10.0 + agreement_ratio * 20.0

    # V19.1: 中性距离加分
    distance_bonus = 0.0
    if directions.get("vix", 0) == 0:
        vix_v = snapshot.get("vix_val") or 20  # 审计修复: None 安全降级
        distance_bonus += max(0, (25 - vix_v) / 25) * 2.5
    if directions.get("erp", 0) == 0:
        erp_s = snapshot.get("erp_score") or 50  # 审计修复: None 安全降级
        distance_bonus += abs(erp_s - 50) / 50 * 2.5
    base_agreement += min(distance_bonus, 5.0)

    # ── 2. Data Health (占 20 分) ──
    stale_count = 0
    for key in ["aiae_regime", "erp_score", "vix_val", "mr_regime"]:
        if snapshot.get(key) is None:
            stale_count += 1
    # V25.3: 新维度缺失只扣 1 分 (软信号)
    for key in ["gold_signal", "bond_signal"]:
        if key in weights and snapshot.get(key) is None:
            stale_count += 0.25

    degraded = snapshot.get("degraded_modules", [])
    if isinstance(degraded, str):
        degraded = [d.strip() for d in degraded.split(",") if d.strip()]
    degraded_count = len(degraded)

    data_health = max(0.0, 20.0 - stale_count * 4.0 - degraded_count * 2.0)

    # ── 3. Consensus Bonus (占 20 分) ──
    if active_count == n_core and all(d == active_dirs[0] for d in active_dirs):
        consensus_bonus = 20.0
    elif active_count >= max(2, n_core // 2) and all(d == active_dirs[0] for d in active_dirs):
        consensus_bonus = 10.0
    else:
        consensus_bonus = 0.0

    # ── 合成 ──
    raw_jcs = base_agreement + data_health + consensus_bonus

    # 矛盾惩罚
    conflicts = compute_conflict_matrix(snapshot)
    penalty_count = conflicts["conflict_count"]
    has_severe = conflicts["has_severe"]

    if has_severe:
        raw_jcs -= 25.0
    elif penalty_count > 0:
        raw_jcs -= penalty_count * 10.0

    jcs = round(min(100, max(0, raw_jcs)), 1)

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


def compute_jcs(snapshot: dict) -> dict:
    """
    V25.3 联合置信度引擎 (6维 + 影子模式):

    JCS = base_agreement (60%) + data_health (20%) + consensus_bonus (20%)

    返回:
    {
        "score": 0-100,
        "level": "high" / "medium" / "low",
        "label": str,
        "directions": {engine: direction},  // 6维
        "shadow": {                         // P3-C 影子模式对比
            "v4_score": float,
            "v6_score": float,
            "delta": float,
        },
        ...
    }
    """
    # V25.3: 6 维正式计算
    result = _compute_jcs_with_weights(snapshot, _JCS_WEIGHTS, n_core=6)

    # P3-C 影子模式: 并行计算旧4维版本, 供30天验证对比
    v4_result = _compute_jcs_with_weights(snapshot, _JCS_WEIGHTS_V4, n_core=4)

    result["shadow"] = {
        "v4_score": v4_result["score"],
        "v6_score": result["score"],
        "delta": round(result["score"] - v4_result["score"], 1),
        "v4_level": v4_result["level"],
    }

    return result
