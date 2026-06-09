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
    _signal_direction, _signal_conviction, compute_conflict_matrix,
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

# P2 安全校验: 权重总和必须为 1.0 (防止未来修改时漂移)
assert abs(sum(_JCS_WEIGHTS.values()) - 1.0) < 0.01, \
    f"JCS 权重总和偏离 1.0: {sum(_JCS_WEIGHTS.values()):.4f}"

# V25.3 影子模式: 旧4维权重 (用于并行对比)
_JCS_WEIGHTS_V4 = {
    "aiae": 0.35,
    "erp": 0.25,
    "vix": 0.20,
    "mr": 0.20,
}

# AIAE Regime → Cap 映射
try:
    import aiae_params as AP
    _is_v5 = getattr(AP, 'V5_ENABLED', False)
    _PM = AP.V5_POSITION_MATRIX if _is_v5 else AP.POSITION_MATRIX
    _REGIME_CAP_MAP = {i+1: _PM["erp_2_4"][i] for i in range(5)}
except Exception:
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
    # V25.3-fix: 只看核心 4 引擎的一致性, gold/bond 为软信号不阻塞共识奖励
    _CORE_ENGINES = ["aiae", "erp", "vix", "mr"]
    core_active = [directions.get(k, 0) for k in _CORE_ENGINES if directions.get(k, 0) != 0]
    core_active_count = len(core_active)

    if core_active_count == 4 and all(d == core_active[0] for d in core_active):
        consensus_bonus = 20.0
    elif core_active_count >= 2 and all(d == core_active[0] for d in core_active):
        # 按比例: 2/4=10, 3/4=15
        consensus_bonus = core_active_count * 5.0
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


def _compute_jcs_v26(snapshot: dict, weights: dict) -> dict:
    """
    V26 Signal Conviction Model — 连续信念度 + 矛盾衰减

    JCS = conviction_score × conflict_decay + data_health

    conviction_score (0-80):
      基准 40 分 (全中性时) + 40 × magnitude^0.7
      magnitude = |加权信念度向量和| / 权重总和
      + direction_bonus: ≥3 核心引擎同向时额外 +2/引擎 (max +8)

    conflict_decay (0.0-1.0):
      = 1 / (1 + severe×3 + medium×1)  Sigmoid 式衰减

    data_health (0-20): 与 V25.3 一致
    """
    convictions = _signal_conviction(snapshot)
    directions = _signal_direction(snapshot)  # 兼容旧 API

    # ── 1. Conviction Score (0-80) ──
    weighted_sum = sum(convictions.get(k, 0) * weights.get(k, 0) for k in weights)
    total_weight = sum(weights.values())
    magnitude = abs(weighted_sum) / total_weight if total_weight > 0 else 0

    # 非线性映射: ^0.7 让弱信号区更敏感, 强信号区适度压缩
    conviction_score = 40.0 + 40.0 * (magnitude ** 0.7)

    # 方向奖励: 核心引擎同向且信念度>0.2 时加分 (替代旧 consensus_bonus)
    _CORE_ENGINES = ["aiae", "erp", "vix", "mr"]
    same_sign_count = sum(
        1 for k in _CORE_ENGINES
        if convictions.get(k, 0) * weighted_sum > 0
        and abs(convictions.get(k, 0)) > 0.2
    )
    if same_sign_count >= 3:
        conviction_score += same_sign_count * 2.0  # max +8

    conviction_score = min(80.0, conviction_score)

    # ── 2. Data Health (0-20) ── 保持不变
    stale_count = 0
    for key in ["aiae_regime", "erp_score", "vix_val", "mr_regime"]:
        if snapshot.get(key) is None:
            stale_count += 1
    for key in ["gold_signal", "bond_signal"]:
        if key in weights and snapshot.get(key) is None:
            stale_count += 0.25
    degraded = snapshot.get("degraded_modules", [])
    if isinstance(degraded, str):
        degraded = [d.strip() for d in degraded.split(",") if d.strip()]
    data_health = max(0.0, 20.0 - stale_count * 4.0 - len(degraded) * 2.0)

    # ── 3. Conflict Decay (0-1) ──
    conflicts = compute_conflict_matrix(snapshot)
    severe = 1 if conflicts["has_severe"] else 0
    medium = max(0, conflicts["conflict_count"] - severe)
    decay = 1.0 / (1.0 + severe * 3.0 + medium * 1.0)

    # ── 合成 ──
    raw_jcs = conviction_score * decay + data_health
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
        "convictions": convictions,
        "conviction_score": round(conviction_score, 1),
        "data_health": round(data_health, 1),
        "conflict_decay": round(decay, 3),
        "conflict_count": conflicts["conflict_count"],
        "agreement_pct": round(magnitude * 100, 1),
        "consensus_bonus": 0.0,  # V26 废弃, 保持 API 兼容
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
    # V25.3: 6 维正式计算 (当前生产)
    result = _compute_jcs_with_weights(snapshot, _JCS_WEIGHTS, n_core=6)

    # P3-C 影子模式: 并行计算旧4维版本
    v4_result = _compute_jcs_with_weights(snapshot, _JCS_WEIGHTS_V4, n_core=4)

    # V26 影子模式: Signal Conviction Model (30天验证期)
    v26_result = _compute_jcs_v26(snapshot, _JCS_WEIGHTS)

    result["shadow"] = {
        "v4_score": v4_result["score"],
        "v6_score": result["score"],
        "delta": round(result["score"] - v4_result["score"], 1),
        "v4_level": v4_result["level"],
        "v26_score": v26_result["score"],
        "v26_level": v26_result["level"],
        "v26_convictions": v26_result.get("convictions", {}),
        "v26_conviction_score": v26_result.get("conviction_score", 0),
        "v26_decay": v26_result.get("conflict_decay", 1.0),
        "delta_v26": round(v26_result["score"] - result["score"], 1),
    }

    return result
